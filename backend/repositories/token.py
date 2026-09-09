"""Refresh-token (session) queries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from backend.models.identity.token import Token
from backend.repositories.base import BaseRepository
from backend.utils.enums import TokenType


class TokenRepository(BaseRepository[Token]):
    model = Token

    async def get_active_by_hash(self, token_hash: str) -> Token | None:
        """Find a live refresh-token session by its hash.

        Expiry is filtered in SQL rather than checked in Python afterwards so
        an expired token is indistinguishable from a nonexistent one to the
        caller -- both simply return None.
        """
        stmt = select(Token).where(
            Token.token_hash == token_hash,
            Token.token_type == TokenType.REFRESH,
            Token.revoked.is_(False),
            Token.expires_at > datetime.now(UTC),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_hash_any_state(self, token_hash: str) -> Token | None:
        """Find a session by hash regardless of revoked/expired state.

        Used for reuse detection: a token that exists but is already revoked
        is a materially different (and more alarming) event than one that
        never existed, and the two need telling apart even though the caller
        is refused either way.
        """
        stmt = select(Token).where(Token.token_hash == token_hash)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_active_for_user(self, user_id: int) -> list[Token]:
        stmt = (
            select(Token)
            .where(
                Token.user_id == user_id,
                Token.token_type == TokenType.REFRESH,
                Token.revoked.is_(False),
                Token.expires_at > datetime.now(UTC),
            )
            .order_by(Token.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_active_for_user_by_public_id(
        self, user_id: int, public_id: uuid.UUID
    ) -> Token | None:
        """Scoped to ``user_id`` on purpose: a caller may only address their
        own sessions, so a valid id belonging to someone else resolves to
        None and answers 404 rather than revealing that it exists."""
        stmt = select(Token).where(
            Token.public_id == public_id,
            Token.user_id == user_id,
            Token.token_type == TokenType.REFRESH,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def revoke(self, token: Token) -> None:
        token.revoked = True
        token.revoked_at = datetime.now(UTC)

    async def revoke_all_for_user(self, user_id: int) -> int:
        """Revoke every live session for a user, in one statement.

        A bulk UPDATE rather than load-then-loop: this runs on password
        change, account suspension and "sign out everywhere", where the user
        may have many sessions and loading them all to mutate each one is
        both slower and a wider race window.
        """
        stmt = (
            update(Token)
            .where(
                Token.user_id == user_id,
                Token.token_type == TokenType.REFRESH,
                Token.revoked.is_(False),
            )
            .values(revoked=True, revoked_at=datetime.now(UTC))
        )
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)
