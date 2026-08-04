"""Google OAuth only — no password path. A signed-in user is linked to a
`members` row by email; without that link they can read but not submit."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi.responses import RedirectResponse
from httpx_oauth.clients.google import GoogleOAuth2
from sqlalchemy import func, select

from core.config import settings
from core.database import get_session
from core.orm import Member, OAuthAccount, User

IS_PROD = settings.ENVIRONMENT == "production"


class OAuthNotAllowedError(Exception):
    """Authenticated with Google, but not on ALLOWED_EMAILS."""


def _is_allowed(email: str) -> bool:
    allowed = {e.strip().lower() for e in settings.ALLOWED_EMAILS.split(",") if e.strip()}
    return not allowed or email.strip().lower() in allowed


google_oauth_client = GoogleOAuth2(settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET)


class UserManager(BaseUserManager[User, str]):
    reset_password_token_secret = settings.USER_SECRET
    verification_token_secret = settings.USER_SECRET

    def parse_id(self, value: Any) -> str:
        return str(value)

    async def oauth_callback(self, oauth_name: str, access_token: str, account_id: str,
                             account_email: str, *args, **kwargs) -> User:
        if not _is_allowed(account_email):
            raise OAuthNotAllowedError(account_email)

        user = await super().oauth_callback(
            oauth_name, access_token, account_id, account_email, *args, **kwargs
        )
        if not user.name:
            user = await self.user_db.update(user, {"name": account_email.split("@")[0]})

        # Claim the members row with this email, if one is waiting. Matching on
        # email, not display_name — the Django app compared name to username,
        # which broke the moment someone's name had a space in it.
        session = self.user_db.session
        member = await session.scalar(
            select(Member).where(func.lower(Member.email) == account_email.lower())
        )
        if member and member.user_id != user.id:
            member.user_id = user.id
            await session.commit()
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
    name="oauth-cookie", transport=RedirectCookieTransport(**_cookie_kwargs), get_strategy=_jwt
)

fastapi_users = FastAPIUsers[User, str](get_user_manager, [auth_backend])

current_user = fastapi_users.current_user(active=True)
current_user_optional = fastapi_users.current_user(active=True, optional=True)
