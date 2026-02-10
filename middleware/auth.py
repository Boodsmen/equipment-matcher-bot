from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from config import settings
from database.crud import create_user, get_user
from utils.logger import logger


class AuthMiddleware(BaseMiddleware):
    """
    Whitelist middleware (5 steps):
    1. Check telegram_id in users table
    2. If found and is_admin=True -> allow
    3. If not found -> check ADMIN_IDS from .env
    4. If in .env -> create user record with is_admin=True, allow
    5. Otherwise -> deny access
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        user = event.from_user
        if user is None:
            return

        telegram_id = user.id

        # Step 1: check DB
        db_user = await get_user(telegram_id)

        # Step 2: found and admin
        if db_user and db_user.is_admin:
            return await handler(event, data)

        # Step 3: not in DB — check .env ADMIN_IDS
        if db_user is None and telegram_id in settings.admin_ids_list:
            # Step 4: create user record
            full_name = user.full_name or ""
            await create_user(
                telegram_id=telegram_id,
                username=user.username,
                full_name=full_name,
                is_admin=True,
            )
            logger.info(f"Auto-registered admin {telegram_id} ({user.username})")
            return await handler(event, data)

        # Step 5: deny access
        logger.warning(f"Access denied for {telegram_id} ({user.username})")
        await event.answer(
            f"Доступ запрещён. Ваш ID: {telegram_id}\n"
            "Обратитесь к администратору для получения доступа."
        )
        return None
