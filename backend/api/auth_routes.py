from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from fastapi_users.router.oauth import (
    CSRF_TOKEN_KEY,
    generate_csrf_token,
    generate_state_token,
)
from pydantic import BaseModel

from core.config import settings
from core.deps import get_member
from core.orm import Member, User
from core.users import (
    auth_backend,
    current_user,
    fastapi_users,
    google_oauth_client,
    oauth_backend,
)

router = APIRouter(prefix="/api", tags=["auth"])

CALLBACK_URL = f"{settings.API_BASE_URL}/api/auth/google/callback"


class MemberOut(BaseModel):
    id: int
    display_name: str
    role: str

    model_config = {"from_attributes": True}


class MeOut(BaseModel):
    id: str
    email: str
    name: str | None
    member: MemberOut | None


@router.get("/users/me", response_model=MeOut)
async def me(
    user: User = Depends(current_user), member: Member | None = Depends(get_member)
):
    """The SPA reads `member` to decide what's writable — a signed-in user with
    no linked member row gets read-only."""
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        member=MemberOut.model_validate(member) if member else None,
    )


@router.get("/auth/google/login")
async def google_login():
    """The browser navigates here directly rather than fetching it, so the CSRF
    cookie is set first-party."""
    csrf = generate_csrf_token()
    state = generate_state_token({CSRF_TOKEN_KEY: csrf}, settings.USER_SECRET)
    response = RedirectResponse(
        await google_oauth_client.get_authorization_url(CALLBACK_URL, state)
    )
    response.set_cookie(
        "fastapiusersoauthcsrf",
        csrf,
        max_age=3600,
        path="/",
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
    )
    return response


@router.post("/auth/logout")
async def logout(
    user_token=Depends(fastapi_users.authenticator.current_user_token(active=True)),
    strategy=Depends(auth_backend.get_strategy),
):
    user, token = user_token
    return await auth_backend.logout(strategy, user, token)


router.include_router(
    fastapi_users.get_oauth_router(
        google_oauth_client,
        oauth_backend,
        settings.USER_SECRET,
        redirect_url=CALLBACK_URL,
        associate_by_email=True,
        is_verified_by_default=True,
        csrf_token_cookie_secure=settings.ENVIRONMENT == "production",
        csrf_token_cookie_samesite="lax",
    ),
    prefix="/auth/google",
)
