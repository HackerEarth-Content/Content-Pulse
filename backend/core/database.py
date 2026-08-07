from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings

engine = create_async_engine(
    settings.sqlalchemy_url,
    # Supabase's transaction pooler rotates server connections between
    # statements, so server-side prepared statements never match.
    connect_args={"prepare_threshold": None},
    pool_pre_ping=True,
    # Request traffic shares this pool with the scheduler jobs; the SQLAlchemy
    # default of 5+10 is the first thing to run out under both at once.
    pool_size=20,
    max_overflow=20,
)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with Session() as session:
        yield session
