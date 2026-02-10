from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import async_session_maker
from database.models import Model, SearchHistory, User
from utils.logger import logger


# ──────────────────────────── Users ────────────────────────────


async def get_user(telegram_id: int) -> Optional[User]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def create_user(
    telegram_id: int,
    username: Optional[str] = None,
    full_name: Optional[str] = None,
    is_admin: bool = True,
) -> User:
    async with async_session_maker() as session:
        async with session.begin():
            user = User(
                telegram_id=telegram_id,
                username=username,
                full_name=full_name,
                is_admin=is_admin,
            )
            session.add(user)
        await session.refresh(user)
        logger.info(f"Created user {telegram_id} ({username})")
        return user


# ──────────────────────────── Models ───────────────────────────


async def get_all_models() -> Sequence[Model]:
    async with async_session_maker() as session:
        result = await session.execute(select(Model))
        return result.scalars().all()


async def get_models_by_category(category: str) -> Sequence[Model]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Model).where(Model.category == category)
        )
        return result.scalars().all()


async def get_model_by_name(model_name: str) -> Sequence[Model]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Model).where(Model.model_name.ilike(f"%{model_name}%"))
        )
        return result.scalars().all()


async def get_models_count() -> int:
    async with async_session_maker() as session:
        result = await session.execute(select(func.count(Model.id)))
        return result.scalar_one()


async def search_models_by_specs(
    specifications: Dict[str, Any],
    category: Optional[str] = None,
    limit: int = 100,
) -> Sequence[Model]:
    """Search models whose specifications contain the given key-value pairs."""
    async with async_session_maker() as session:
        query = select(Model)
        if category:
            query = query.where(Model.category == category)
        # JSONB containment: model specs must contain all requested specs
        query = query.where(Model.specifications.op("@>")(specifications))
        query = query.limit(limit)
        result = await session.execute(query)
        return result.scalars().all()


async def bulk_create_models(models_data: List[Dict[str, Any]]) -> int:
    """Bulk insert models into the database. Returns number of inserted rows."""
    if not models_data:
        return 0
    async with async_session_maker() as session:
        async with session.begin():
            session.add_all([Model(**data) for data in models_data])
        logger.info(f"Bulk inserted {len(models_data)} models")
        return len(models_data)


async def delete_all_models() -> int:
    """Delete all models from the database. Returns number of deleted rows."""
    async with async_session_maker() as session:
        async with session.begin():
            result = await session.execute(text("DELETE FROM models"))
            count = result.rowcount
        logger.info(f"Deleted {count} models")
        return count


# ──────────────────────────── Search History ───────────────────


async def save_search_history(
    user_id: int,
    docx_filename: str,
    requirements: Optional[Dict] = None,
    results_summary: Optional[Dict] = None,
) -> SearchHistory:
    async with async_session_maker() as session:
        async with session.begin():
            record = SearchHistory(
                user_id=user_id,
                docx_filename=docx_filename,
                requirements=requirements,
                results_summary=results_summary,
            )
            session.add(record)
        await session.refresh(record)
        logger.info(f"Saved search history for user {user_id}: {docx_filename}")
        return record
