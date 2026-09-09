"""System settings (spec §23).

**The one table in this codebase whose primary key is deliberately exposed.**
Everywhere else an integer PK is sequential, enumerable and meaningless, so
`public_id` exists to keep it internal. A setting's key is the opposite on
every count: `grading.pass_mark` is the name of the thing, it is what a
caller already knows before making the request, and generating a UUID for it
would mean looking up an identifier in order to ask for a value by name.

**Writing settings is Super Admin only, and that is spec §2, not an
oversight.** The Administrator role holds `setting.read` and not
`setting.update` — it can run the institution's daily operations and cannot
change the rules those operations run under.

There is no create endpoint distinct from update. A setting either exists or
it does not, and "PUT this key to this value" answers both — a separate
create would only add a 409 nobody benefits from.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import NotFoundError
from backend.models.administration import SystemSetting
from backend.models.identity.user import User
from backend.repositories.administration import SystemSettingRepository
from backend.schemas.administration import SettingWriteRequest
from backend.schemas.base import PageParams
from backend.services import audit_service
from backend.services.audit_service import AuditAction


class SettingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = SystemSettingRepository(session)

    async def list(
        self, params: PageParams, *, prefix: str | None = None
    ) -> tuple[Sequence[SystemSetting], int]:
        return await self.settings.search(params, prefix=prefix)

    async def get(self, key: str) -> SystemSetting:
        setting = await self.settings.get_key(key)
        if setting is None:
            raise NotFoundError("Setting not found.")
        return setting

    async def put(self, key: str, payload: SettingWriteRequest, *, actor: User) -> SystemSetting:
        setting = await self.settings.get_key(key)
        created = setting is None

        if setting is None:
            setting = SystemSetting(key=key, value=payload.value, description=payload.description)
            self.session.add(setting)
        else:
            changes = payload.model_dump(exclude_unset=True)
            for field, value in changes.items():
                setattr(setting, field, value)

        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.CREATE if created else AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="system_setting",
            # `entity_id` is an integer column and this table's key is text,
            # so the key travels in `details` instead of being forced into a
            # numeric field it does not fit.
            entity_id=None,
            details={"key": key, "value": payload.value},
        )
        return setting

    async def delete(self, key: str, *, actor: User) -> None:
        setting = await self.get(key)
        previous = setting.value
        await self.session.delete(setting)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="system_setting",
            entity_id=None,
            # The removed value is recorded: a setting reverting to its code
            # default changes behaviour, and "what was it before?" is the
            # first question asked afterwards.
            details={"key": key, "previous_value": previous},
        )
