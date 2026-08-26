"""Google OAuth only — no password path. A signed-in user is linked to a
`members` row by email; without that link they can read but not submit."""

from __future__ import annotations

from typing import Any

from fastapi import Depends
from fastapi_users import BaseUserManager, FastAPIUsers
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi.responses import RedirectResponse
from httpx_oauth.clients.google import GoogleOAuth2
from sqlalchemy import case, func, or_, select, update

from core.config import settings
from core.database import get_session
from core.orm import Member, OAuthAccount, User

IS_PROD = settings.ENVIRONMENT == "production"


class OAuthNotAllowedError(Exception):
    """Authenticated with Google, but nobody here recognises the address."""


async def _claim_member(session, user, email: str) -> None:
    """Link this account to its members row, and make super-admins admins.

    Super-admins come from env, so they resolve even with no row — a bad edit to
    the members table can never lock every administrator out.
    """
    lowered = email.strip().lower()
    member = await session.scalar(
        select(Member)
        .where(or_(Member.user_id == user.id, func.lower(Member.email) == lowered))
        # Both halves can match, on different rows: one already linked to this
        # account, another carrying the address being signed in with. Without an
        # explicit order Postgres returns whichever it likes, and if it returned
        # the already-linked row the correct one was never claimed at all. The
        # address is the identity being asserted, so it wins.
        .order_by(case((func.lower(Member.email) == lowered, 0), else_=1), Member.id)
    )
    if member is None and lowered in settings.superadmins:
        member = Member(display_name=email.split("@")[0], email=lowered, role="admin")
        session.add(member)

    if member is None:
        return

    # `user_id` is not unique, and get_viewer resolves a member from it — two
    # rows pointing at one account would hand out whichever role came first.
    await session.execute(
        update(Member)
        .where(Member.user_id == user.id, Member.id != member.id)
        .values(user_id=None)
    )
    member.user_id = user.id
    if lowered in settings.superadmins:
        member.role = "admin"
        member.is_active = True
    await session.commit()


async def _may_sign_in(session, email: str) -> bool:
    """The members table is the allowlist. Adding a person is a row, not a deploy."""
    lowered = email.strip().lower()
    if lowered in settings.superadmins:
        return True
    return bool(
        await session.scalar(
            select(Member.id).where(
                func.lower(Member.email) == lowered, Member.is_active.is_(True)
            )
        )
    )


google_oauth_client = GoogleOAuth2(
    settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
)


class UserManager(BaseUserManager[User, str]):
    reset_password_token_secret = settings.USER_SECRET
    verification_token_secret = settings.USER_SECRET

    def parse_id(self, value: Any) -> str:
        return str(value)

    async def oauth_callback(
        self,
        oauth_name: str,
        access_token: str,
        account_id: str,
        account_email: str,
        *args,
        **kwargs,
    ) -> User:
        session = self.user_db.session
        if not await _may_sign_in(session, account_email):
            raise OAuthNotAllowedError(account_email)

        user = await super().oauth_callback(
            oauth_name, access_token, account_id, account_email, *args, **kwargs
        )
        if not user.name:
            user = await self.user_db.update(
                user, {"name": account_email.split("@")[0]}
            )

        # Match on email, not display_name — the Django app compared name to
        # username, which broke the moment someone's name had a space in it.
        await _claim_member(session, user, account_email)
        return user


async def get_user_db(session=Depends(get_session)):
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


_cookie_kwargs = dict(
    cookie_name="contentops_auth",
    cookie_max_age=60 * 60 * 12,
    cookie_secure=IS_PROD,
    cookie_samesite="none" if IS_PROD else "lax",
)


class RedirectCookieTransport(CookieTransport):
    """Sets the cookie, then bounces to the SPA — the OAuth callback lands in
    the browser's address bar, so it can't return JSON."""

    async def get_login_response(self, token: str) -> RedirectResponse:
        return self._set_login_cookie(
            RedirectResponse(settings.FRONTEND_URL, status_code=302), token
        )


def _jwt() -> JWTStrategy:
    return JWTStrategy(secret=settings.USER_SECRET, lifetime_seconds=60 * 60 * 12)


auth_backend = AuthenticationBackend(
    name="cookie", transport=CookieTransport(**_cookie_kwargs), get_strategy=_jwt
)
oauth_backend = AuthenticationBackend(
    name="oauth-cookie",
    transport=RedirectCookieTransport(**_cookie_kwargs),
    get_strategy=_jwt,
)

fastapi_users = FastAPIUsers[User, str](get_user_manager, [auth_backend])

current_user = fastapi_users.current_user(active=True)
current_user_optional = fastapi_users.current_user(active=True, optional=True)
