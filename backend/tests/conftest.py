import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from core.database import Session
from core.orm import AEDailyUpdate, DailyEntry, Member, TaskType, User
from core.users import current_user
from main import app

TEST_MEMBER = "PyTest Member"
AE_MEMBER = "PyTest AE"
ADMIN_MEMBER = "PyTest Admin"


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
            await db.commit()
        await db.execute(delete(DailyEntry).where(DailyEntry.member_id == m.id))
        await db.commit()
        return m.id


@pytest_asyncio.fixture
async def ae_member() -> int:
    """An AE-role member with no AE rows, so the upsert path starts clean."""
    async with Session() as db:
        m = await db.scalar(select(Member).where(Member.display_name == AE_MEMBER))
        if m is None:
            m = Member(display_name=AE_MEMBER, role="ae")
            db.add(m)
            await db.commit()
        await db.execute(delete(AEDailyUpdate).where(AEDailyUpdate.member_id == m.id))
        await db.commit()
        return m.id


@pytest_asyncio.fixture
async def task_type() -> int:
    async with Session() as db:
        return await db.scalar(select(TaskType.id).order_by(TaskType.sort_order).limit(1))
