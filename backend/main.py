from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from api.analytics_routes import router as analytics_router
from api.auth_routes import router as auth_router
from api.integrations_routes import router as integrations_router
from api.intake_routes import router as intake_router
from api.entries_routes import router as entries_router
from api.export_routes import router as export_router
from api.members_routes import router as members_router
from core.config import settings
from core.database import engine
from core.scheduler import start as start_scheduler
from core.users import OAuthNotAllowedError

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)
    await engine.dispose()


app = FastAPI(title="ContentOps API", lifespan=lifespan)

# Cookie auth needs credentialed CORS, which browsers only allow with an
# explicit origin — "*" is rejected once allow_credentials is on.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OAuthNotAllowedError)
async def oauth_not_allowed(request: Request, exc: OAuthNotAllowedError):
    """This fires mid-redirect, in the address bar — send them back to the SPA
    with a flag rather than a bare JSON error."""
    return RedirectResponse(f"{settings.FRONTEND_URL}?authError=not_allowed", status_code=302)


@app.get("/api/health")
async def health():
    return {"ok": True, "environment": settings.ENVIRONMENT}


app.include_router(auth_router)
app.include_router(members_router)
app.include_router(entries_router)
app.include_router(analytics_router)
app.include_router(integrations_router)
app.include_router(intake_router)
app.include_router(export_router)
