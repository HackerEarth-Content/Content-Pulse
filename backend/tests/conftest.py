import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from core.config import settings
from core.database import Session
from core.orm import DailyEntry, Member, TaskType, User
from core.users import current_user
from main import app

@pytest.fixture(autouse=True)
def no_outbound(monkeypatch):
    """Nothing leaves the process during a test.

    A test run once created a real Jira ticket (TCE-9202) because a background
    task fired against a live token. Every outbound integration is forced off
    here; the few tests that exercise a write path opt back in explicitly and
    do it against a mock transport.
    """
    for flag in ("JIRA_WRITES_ENABLED", "SLACK_WRITES_ENABLED", "EMAIL_ENABLED"):
        monkeypatch.setattr(settings, flag, False)


TEST_MEMBER = "PyTest Member"
AE_MEMBER = "PyTest AE"
ADMIN_MEMBER = "PyTest Admin"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def deactivate_test_members():
    """Tests run against the live database, so whatever they file has to be
    removed again on the way out.

    Deactivating the members is not enough: analytics aggregates by entry, not
    by member status, so a leftover fixture ticket still lands in the real
    totals. A reconciliation against Jira caught exactly that — `TCE-42` on
    `PyTest Member`, 90 minutes of effort that no Jira issue backs. The entries
    go, the members stay (deactivated) because real rows reference them.

    A separate test database is still the real fix."""
    yield
    names = [TEST_MEMBER, AE_MEMBER, ADMIN_MEMBER, "RBAC Ada", "RBAC Grace"]
    async with Session() as db:
        ids = (await db.execute(
            select(Member.id).where(Member.display_name.in_(names))
        )).scalars().all()
        if ids:
            # Items cascade from the entry.
            await db.execute(delete(DailyEntry).where(DailyEntry.member_id.in_(ids)))
            await db.execute(
                update(Member).where(Member.id.in_(ids)).values(is_active=False)
            )
        await db.commit()


@pytest_asyncio.fixture(scope="session")
async def fake_user():
    """A real row — created_by_user_id is a FK, so a detached object won't do.

    Linked to an admin member: most tests file work on behalf of other members,
    which RBAC only permits for leads. Authorization itself is covered in
    tests/test_rbac.py with deliberately unprivileged users.
    """
    async with Session() as db:
        user = await db.get(User, "test-user")
        if user is None:
            user = User(id="test-user", email="pytest@example.com", name="PyTest",
                        hashed_password="", is_verified=True)
            db.add(user)
            await db.commit()

        admin = await db.scalar(select(Member).where(Member.display_name == ADMIN_MEMBER))
        if admin is None:
            admin = Member(display_name=ADMIN_MEMBER, email="pytest@example.com",
                           role="admin")
            db.add(admin)
        admin.role, admin.user_id, admin.is_active = "admin", user.id, True
        await db.commit()
        return user


@pytest_asyncio.fixture
async def client(fake_user):
    app.dependency_overrides[current_user] = lambda: fake_user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def member() -> int:
    """A throwaway member, wiped before each test so plan-per-day is clean."""
    async with Session() as db:
        m = await db.scalar(select(Member).where(Member.display_name == TEST_MEMBER))
        if m is None:
            m = Member(display_name=TEST_MEMBER)
            db.add(m)
        # Reactivate: the session fixture deactivates this row on the way out,
        # so from the second run onwards it existed but was invisible to every
        # team-facing query, and the today-strip test failed on its absence.
        m.is_active = True
        await db.commit()
        await db.execute(delete(DailyEntry).where(DailyEntry.member_id == m.id))
        await db.commit()
        return m.id


@pytest_asyncio.fixture
async def task_type() -> int:
    async with Session() as db:
        return await db.scalar(select(TaskType.id).order_by(TaskType.sort_order).limit(1))
