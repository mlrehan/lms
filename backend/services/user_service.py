"""User administration (spec §4)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Sequence

from fastapi import UploadFile

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.identity.user import User
from backend.repositories.geo import CityRepository, CountryRepository
from backend.repositories.token import TokenRepository
from backend.repositories.user import UserRepository
from backend.schemas.base import PageParams
from backend.schemas.user import UserCreateRequest, UserUpdateRequest
from backend.security import password as pwd
from backend.services import audit_service
from backend.services.avatar import CONTENT_TYPE as AVATAR_CONTENT_TYPE, process_avatar
from backend.storage import get_storage
from backend.storage.base import build_key
from backend.services.audit_service import AuditAction
from backend.services.scope import ScopeResolver
from backend.utils.enums import UserStatus

# Distinguishes "the client never mentioned this field" from "the client sent
# it as null" when threading `changes` (already filtered by `exclude_unset`)
# into `_apply_location`. `None` is itself a meaningful value here (clear the
# country/city), so it cannot double as the "untouched" marker.
_UNSET = object()


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.tokens = TokenRepository(session)
        self.geo_countries = CountryRepository(session)
        self.geo_cities = CityRepository(session)

    # -- reads ---------------------------------------------------------------

    async def list_users(
        self,
        params: PageParams,
        *,
        actor: User,
        query: str | None = None,
        status: UserStatus | None = None,
        role: str | None = None,
    ) -> tuple[Sequence[User], int]:
        """`actor` is required, not optional.

        Making the caller a mandatory argument is the point: an endpoint that
        forgets to scope cannot compile-by-accident into one that returns the
        whole directory. A Tutor, Guardian or Corporate Manager all hold
        `user.read`, so without this filter each of them would list every
        person in the institution.
        """
        scope = await ScopeResolver(self.session).visible_student_ids(actor)
        return await self.users.search(
            params, query=query, status=status, role=role, scope=scope
        )

    async def get(self, public_id: uuid.UUID, *, actor: User) -> User:
        user = await self.users.get_by_public_id_with_roles(public_id)
        if user is None or user.status is UserStatus.DELETED:
            # A soft-deleted account is treated as absent rather than
            # returned with a "deleted" flag: it is not a member of the
            # institution any more, and the row survives only because
            # audit_logs and enrollments still reference it.
            raise NotFoundError("User not found.")

        scope = await ScopeResolver(self.session).visible_student_ids(actor)
        if not scope.allows(user.id):
            # 404, never 403. A guardian probing ids must not be able to tell
            # "no such person" from "someone else's child" -- the second
            # answer confirms the account exists and is enrolled here.
            raise NotFoundError("User not found.")
        return user

    # -- writes --------------------------------------------------------------

    async def create(self, payload: UserCreateRequest, *, actor: User) -> User:
        await self._assert_username_free(payload.username)
        await self._assert_email_free(payload.email)

        roles = await self.users.get_roles_by_names(payload.roles)
        self._assert_all_roles_resolved(payload.roles, roles)

        user = User(
            username=payload.username,
            email=str(payload.email).lower(),
            slug=await User.generate_slug(payload.username, self.session),
            hashed_password=pwd.hash_password(payload.password),
            can_login=payload.can_login,
            first_name=payload.first_name,
            last_name=payload.last_name,
            title=payload.title,
            gender=payload.gender,
            date_of_birth=payload.date_of_birth,
            phone_number=payload.phone_number,
            mobile=payload.mobile,
            # Administrator-provisioned accounts are active immediately: the
            # administrator creating it *is* the vouching step that email
            # verification would otherwise provide.
            status=UserStatus.ACTIVE,
            created_by=actor.id,
        )
        user.roles = roles

        await self.users.add_and_flush(user)
        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="user",
            entity_id=user.id,
            details={"username": user.username, "roles": sorted(r.name for r in roles)},
        )
        return user

    async def update(
        self, public_id: uuid.UUID, payload: UserUpdateRequest, *, actor: User
    ) -> User:
        user = await self.get(public_id, actor=actor)
        await self._apply_update(user, payload, actor=actor)
        return user

    async def update_self(self, payload: UserUpdateRequest, *, actor: User) -> User:
        """Edit your own profile. Deliberately narrower than `update`.

        Identity is not self-service: changing the email changes the sign-in
        identifier, and this deployment cannot verify a new address, so it is
        an administrator's decision. Everything else about *you* is yours.
        """
        if "email" in payload.model_fields_set:
            raise ValidationError("Ask an administrator to change your email address.")
        user = await self.users.get_by_public_id_with_roles(actor.public_id)
        assert user is not None
        await self._apply_update(user, payload, actor=actor)
        return user

    async def _apply_update(self, user: User, payload: UserUpdateRequest, *, actor: User) -> None:
        # `exclude_unset` is what makes this a real PATCH: a field the client
        # never mentioned is left alone, while one explicitly sent as null is
        # cleared. Without it, every omitted field would be overwritten with
        # its default and a partial update would quietly wipe the profile.
        changes = payload.model_dump(exclude_unset=True)

        if "email" in changes and changes["email"]:
            new_email = str(changes["email"]).lower()
            if new_email != (user.email or "").lower():
                await self._assert_email_free(new_email)
            changes["email"] = new_email

        # country_id/city_id arrive as public_ids and must resolve to
        # internal ids before `setattr`; handled separately rather than in
        # the generic loop below, the same way `email` already is.
        country_given = "country_id" in changes
        city_given = "city_id" in changes
        if country_given or city_given:
            await self._apply_location(
                user,
                country_public_id=changes.pop("country_id", None) if country_given else _UNSET,
                city_public_id=changes.pop("city_id", None) if city_given else _UNSET,
            )

        for field, value in changes.items():
            setattr(user, field, value)
        if "timezone" in changes:
            # Whoever types a zone owns it: an address change must not quietly replace it (services/locale_service.py).
            user.timezone_is_auto = False

        user.updated_by = actor.id

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="user",
            entity_id=user.id,
            details={"fields": sorted(changes), "self": user.id == actor.id},
        )

    # -- profile picture -------------------------------------------------------

    async def set_picture(self, user: User, upload: UploadFile, *, actor: User) -> User:
        """Replace `user`'s picture. The caller has already authorised access to `user`."""
        raw = await upload.read(5 * 1024 * 1024 + 1)  # bounded: never buffer an unbounded body
        data = await asyncio.to_thread(process_avatar, raw)  # CPU-bound; keep the loop free

        storage = get_storage()
        key = build_key(prefix=f"avatars/{user.public_id}", filename="picture.webp")
        await storage.save(key, data, content_type=AVATAR_CONTENT_TYPE)

        previous = user.profile_picture
        user.profile_picture = key
        user.updated_by = actor.id
        audit_service.record(
            self.session, action=AuditAction.UPDATE, actor_user_id=actor.id, actor_email=actor.email,
            entity_type="user", entity_id=user.id, details={"fields": ["profile_picture"], "self": user.id == actor.id},
        )
        await self.session.flush()
        await self._discard(previous)
        return user

    async def remove_picture(self, user: User, *, actor: User) -> User:
        previous = user.profile_picture
        user.profile_picture = None
        user.updated_by = actor.id
        audit_service.record(
            self.session, action=AuditAction.UPDATE, actor_user_id=actor.id, actor_email=actor.email,
            entity_type="user", entity_id=user.id, details={"fields": ["profile_picture"], "removed": True},
        )
        await self.session.flush()
        await self._discard(previous)
        return user

    @staticmethod
    async def _discard(key: str | None) -> None:
        """Best effort: an orphaned file is dead weight; failing the request over it is worse."""
        if not key:
            return
        try:
            await get_storage().delete(key)
        except Exception:  # noqa: BLE001
            pass

    async def load_own(self, actor: User) -> User:
        user = await self.users.get_by_public_id_with_roles(actor.public_id)
        assert user is not None
        return user

    async def set_login_access(self, public_id: uuid.UUID, can_login: bool, *, actor: User) -> tuple[User, bool]:
        """Switch sign-in on or off. Returns the user and whether the account
        still carries the shared default password."""
        user = await self.get(public_id, actor=actor)
        if user.id == actor.id:
            raise ConflictError("You cannot change your own sign-in access.")

        default_in_use = await asyncio.to_thread(
            pwd.verify_password, user.hashed_password, self._default_password()
        )
        user.can_login = can_login
        user.updated_by = actor.id
        if not can_login:
            # Same reasoning as suspension: a switch that leaves existing
            # sessions working has not switched anything off.
            await self.tokens.revoke_all_for_user(user.id)
        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            entity_type="user",
            entity_id=user.id,
            details={"can_login": can_login, "default_password_in_use": default_in_use},
        )
        return user, default_in_use

    @staticmethod
    def _default_password() -> str:
        from backend.core.config import get_settings

        return get_settings().lait.default_password.get_secret_value()

    async def set_status(
        self, public_id: uuid.UUID, new_status: UserStatus, *, actor: User
    ) -> User:
        user = await self.get(public_id, actor=actor)

        if user.id == actor.id:
            # Recovering from self-suspension needs direct database access,
            # so it is refused outright rather than left as a foot-gun.
            # 409 rather than 422: the request body is perfectly valid, it is
            # the *target* that makes it impossible, and a client needs to
            # tell that apart from "you sent a malformed field".
            raise ConflictError("You cannot change your own account status.")

        user.status = new_status
        user.updated_by = actor.id

        if new_status is not UserStatus.ACTIVE:
            # Suspending an account that keeps working until its tokens
            # expire is not a suspension. Ending the sessions is what makes
            # the status change take effect now.
            await self.tokens.revoke_all_for_user(user.id)

        if new_status is UserStatus.ACTIVE:
            user.is_locked = False
            user.locked_until = None
            user.failed_login_attempts = 0

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="user",
            entity_id=user.id,
            details={"status": new_status.value},
        )
        return user

    async def soft_delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        user = await self.get(public_id, actor=actor)

        if user.id == actor.id:
            raise ConflictError("You cannot delete your own account.")

        user.status = UserStatus.DELETED
        user.deleted_at = datetime.now(UTC)
        user.deleted_by = actor.id
        await self.tokens.revoke_all_for_user(user.id)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="user",
            entity_id=user.id,
        )

    async def set_roles(
        self, public_id: uuid.UUID, role_names: Sequence[str], *, actor: User
    ) -> User:
        user = await self.get(public_id, actor=actor)
        roles = await self.users.get_roles_by_names(role_names)
        self._assert_all_roles_resolved(role_names, roles)

        if user.id == actor.id:
            # Otherwise the last Super Admin can demote themselves and lock
            # everyone out of role management with no way back through the API.
            raise ConflictError("You cannot change your own roles.")

        user.roles = roles
        user.updated_by = actor.id

        # A role change alters what the holder may do; existing sessions must
        # not keep the old authority. (Permissions are resolved per-request,
        # so this is belt-and-braces rather than strictly required -- but it
        # makes the guarantee independent of that implementation detail.)
        await self.tokens.revoke_all_for_user(user.id)

        audit_service.record(
            self.session,
            action=AuditAction.PERMISSION_CHANGE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="user",
            entity_id=user.id,
            details={"roles": sorted(r.name for r in roles)},
        )
        return user

    async def set_password(self, public_id: uuid.UUID, new_password: str, *, actor: User) -> None:
        user = await self.get(public_id, actor=actor)
        user.hashed_password = pwd.hash_password(new_password)
        user.updated_by = actor.id
        await self.tokens.revoke_all_for_user(user.id)

        audit_service.record(
            self.session,
            action=AuditAction.PASSWORD_RESET_BY_ADMIN,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="user",
            entity_id=user.id,
        )

    # -- location --------------------------------------------------------------

    async def _apply_location(
        self,
        user: User,
        *,
        country_public_id: object,
        city_public_id: object,
    ) -> None:
        """Resolve and reconcile `country_id`/`city_id`.

        A city implies its country unambiguously, so setting one resolves or
        checks the other rather than letting them silently disagree -- a
        profile recording country="Japan" and city="Paris" is a bug, not a
        valid state. Each parameter is `_UNSET` (the client never mentioned
        it), `None` (explicitly clearing it), or a real public_id.
        """
        city_touched = city_public_id is not _UNSET
        country_touched = country_public_id is not _UNSET

        if city_touched and city_public_id is not None:
            city = await self.geo_cities.get_by_public_id_full(city_public_id)  # type: ignore[arg-type]
            if city is None:
                raise NotFoundError("City not found.")

            if country_touched:
                if country_public_id is None:
                    raise ValidationError("Cannot clear country while setting a city.")
                country = await self.geo_countries.get_by_public_id(country_public_id)  # type: ignore[arg-type]
                if country is None:
                    raise NotFoundError("Country not found.")
                if country.id != city.country_id:
                    raise ValidationError(
                        "This city does not belong to the given country.",
                        details={"city": city.name, "country": country.name},
                    )
                resolved_country_id = country.id
            else:
                # Country wasn't mentioned -- derive it from the city, the
                # only way "set a city" can be an unambiguous instruction.
                resolved_country_id = city.country_id

            resolved_city_id = city.id

        elif city_touched:  # city explicitly cleared
            resolved_city_id = None
            if country_touched:
                if country_public_id is None:
                    resolved_country_id = None
                else:
                    country = await self.geo_countries.get_by_public_id(country_public_id)  # type: ignore[arg-type]
                    if country is None:
                        raise NotFoundError("Country not found.")
                    resolved_country_id = country.id
            else:
                resolved_country_id = user.country_id  # untouched

        else:  # country touched, city not mentioned
            if country_public_id is None:
                resolved_country_id = None
                resolved_city_id = None  # a city can't outlive its country
            else:
                country = await self.geo_countries.get_by_public_id(country_public_id)  # type: ignore[arg-type]
                if country is None:
                    raise NotFoundError("Country not found.")
                resolved_country_id = country.id
                # Keep the existing city only if it still belongs to the new
                # country -- otherwise the profile would show a city from a
                # country other than the one just selected.
                resolved_city_id = (
                    user.city_id
                    if user.current_city and user.current_city.country_id == country.id
                    else None
                )

        user.country_id = resolved_country_id
        user.city_id = resolved_city_id

        # Assigning the FK columns directly does not tell SQLAlchemy that
        # `user.country`/`user.current_city` -- eagerly loaded by `self.get`
        # moments ago -- are now stale; the relationship objects keep
        # whatever they resolved to when first loaded. Without this, the
        # response echoed pre-update country/city (verified live: setting a
        # city returned `city: null, country: null`, and changing country
        # away from one echoed the *previous* country back). `refresh`
        # rather than a bare `expire` because this is async: touching an
        # expired attribute outside an explicit, awaited reload raises
        # MissingGreenlet, the same class of bug already hit twice in this
        # codebase (the role seeder, `set_tutors`).
        await self.session.flush()
        await self.session.refresh(user, attribute_names=["country", "current_city"])

    # -- guards --------------------------------------------------------------

    async def _assert_username_free(self, username: str) -> None:
        if await self.users.get_by_username(username):
            raise ConflictError("That username is already taken.")

    async def _assert_email_free(self, email: str) -> None:
        if await self.users.get_by_email(str(email)):
            raise ConflictError("That email address is already registered.")

    @staticmethod
    def _assert_all_roles_resolved(requested: Sequence[str], resolved: Sequence) -> None:
        """Refuse the whole request if any named role does not exist.

        Silently dropping an unknown name would create a user with fewer
        privileges than the caller asked for and report success -- the kind
        of failure discovered later by someone who cannot do their job.
        """
        found = {r.name for r in resolved}
        missing = [name for name in requested if name not in found]
        if missing:
            raise ValidationError(
                "Unknown role(s).",
                details={"unknown_roles": missing},
            )
