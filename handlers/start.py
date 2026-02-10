from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from database.crud import get_models_count
from utils.logger import logger

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    logger.info(f"/start from {user.id} ({user.username})")

    try:
        count = await get_models_count()
        db_info = f"В базе данных: {count} моделей оборудования."
    except Exception:
        db_info = "База данных недоступна."

    await message.answer(
        f"Здравствуйте, {user.full_name}!\n\n"
        "Я бот для подбора оборудования Eltex по техническим заданиям тендеров.\n\n"
        f"{db_info}\n\n"
        "Отправьте DOCX файл с ТЗ тендера для анализа."
    )
