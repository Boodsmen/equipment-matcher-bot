"""Handler for uploaded documents (DOCX, future PDF)."""

import os

from aiogram import Bot, Router
from aiogram.types import FSInputFile, Message

from config import settings
from database.crud import save_search_history
from services.docx_parser import extract_text_from_docx
from services.excel_generator import generate_report
from services.matcher import find_matching_models
from services.openai_service import process_document
from services.table_parser import parse_requirements_from_tables
from utils.logger import logger

router = Router()

TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp_files")


@router.message(lambda m: m.document is not None)
async def handle_document(message: Message, bot: Bot) -> None:
    """Download and process an uploaded document."""
    doc = message.document
    file_name = doc.file_name or "unknown"
    user_id = message.from_user.id
    logger.info(f"Document received from {user_id}: {file_name} ({doc.file_size} bytes)")

    # PDF — future support
    if file_name.lower().endswith(".pdf"):
        await message.answer(
            "Поддержка PDF находится в разработке.\n"
            "Пожалуйста, отправьте файл в формате DOCX."
        )
        return

    # Only DOCX allowed
    if not file_name.lower().endswith(".docx"):
        await message.answer(
            "Неподдерживаемый формат файла.\n"
            "Пожалуйста, отправьте файл в формате DOCX."
        )
        return

    # Check file size (20 MB limit)
    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await message.answer("Файл слишком большой (макс. 20 МБ).")
        return

    status_msg = await message.answer("Файл получен. Начинаю анализ...")

    os.makedirs(TEMP_DIR, exist_ok=True)
    file_path = os.path.join(TEMP_DIR, f"{user_id}_{file_name}")

    try:
        # Download file
        file = await bot.get_file(doc.file_id)
        await bot.download_file(file.file_path, file_path)
        logger.info(f"File downloaded to {file_path}")

        # HYBRID APPROACH: Try table parser first, then AI fallback
        await status_msg.edit_text("Анализирую структуру документа...")

        # Strategy 1: Direct table parsing (fast, reliable for structured docs)
        logger.info("Attempting table-based parsing...")
        requirements = parse_requirements_from_tables(file_path)

        if requirements:
            items = requirements.get("items", [])
            logger.info(f"✓ Table parser succeeded: {len(items)} items extracted")
            await status_msg.edit_text(
                f"✓ Обнаружена структурированная таблица\n"
                f"Извлечено позиций: {len(items)}"
            )
        else:
            # Strategy 2: AI-based parsing (flexible for unstructured docs)
            logger.info("Table parser returned None, falling back to AI...")
            await status_msg.edit_text("Извлекаю текст из документа...")
            text = extract_text_from_docx(file_path)

            if not text.strip():
                await status_msg.edit_text("Документ пуст или не содержит текста.")
                return

            # Process with OpenAI (Router -> Parser)
            await status_msg.edit_text(
                f"Анализирую техническое задание с помощью AI ({len(text)} символов)...\n"
                "Этап 1/2: Поиск технических требований..."
            )

            requirements = await process_document(text, "docx")
            items = requirements.get("items", [])

        if not items:
            await status_msg.edit_text(
                "Не удалось извлечь требования к оборудованию из документа.\n"
                "Убедитесь, что файл содержит техническое задание с характеристиками."
            )
            return

        # Format results summary
        summary_lines = [f"Извлечено позиций оборудования: {len(items)}\n"]
        for i, item in enumerate(items, 1):
            name = item.get("item_name") or item.get("model_name") or "Без названия"
            category = item.get("category") or "—"
            specs_count = len(item.get("required_specs", {}))
            model = item.get("model_name")
            model_str = f" (модель: {model})" if model else ""
            summary_lines.append(f"{i}. {name}{model_str}\n   Категория: {category}, характеристик: {specs_count}")

        summary_text = "\n".join(summary_lines)

        # Stage 3: Match models with database
        await status_msg.edit_text(
            f"{summary_text}\n\n"
            "Этап 2/3: Сопоставление с базой данных..."
        )

        match_results = await find_matching_models(requirements)
        match_summary = match_results.get("summary", {})

        # Format match results
        result_lines = [
            f"\nРезультаты сопоставления:",
            f"Найдено моделей: {match_summary.get('total_models_found', 0)}",
            f"Идеальные совпадения: {match_summary.get('ideal_matches', 0)}",
            f"Частичные совпадения: {match_summary.get('partial_matches', 0)}",
        ]

        # Show top matches for each requirement
        for idx, result in enumerate(match_results.get("results", []), 1):
            req = result["requirement"]
            matches = result["matches"]
            ideal = matches.get("ideal", [])
            partial = matches.get("partial", [])

            req_name = req.get("item_name") or req.get("model_name") or f"Позиция {idx}"

            if ideal:
                top = ideal[0]
                result_lines.append(
                    f"\n{idx}. {req_name}:\n"
                    f"   ✅ {top['model_name']} ({top['source_file']}) — 100%"
                )
            elif partial:
                top = partial[0]
                result_lines.append(
                    f"\n{idx}. {req_name}:\n"
                    f"   ⚠️ {top['model_name']} ({top['source_file']}) — {top['match_percentage']}%"
                )
            else:
                result_lines.append(f"\n{idx}. {req_name}:\n   ❌ Подходящих моделей не найдено")

        match_text = "\n".join(result_lines)

        # Stage 4: Generate Excel report
        await status_msg.edit_text(
            f"{summary_text}\n{match_text}\n\n"
            "Этап 3/3: Генерация Excel отчета..."
        )

        excel_path = generate_report(
            requirements=requirements,
            match_results=match_results,
            output_dir=TEMP_DIR,
            threshold=settings.match_threshold,
            min_percentage=80.0,  # Показывать только модели с совпадением >= 80%
        )

        # Save search history (non-critical — don't break main flow)
        try:
            await save_search_history(
                user_id=user_id,
                docx_filename=file_name,
                requirements=requirements,
                results_summary=match_summary,
            )
        except Exception as e:
            logger.error(f"Failed to save search history: {e}")

        # Send Excel file to user
        excel_file = FSInputFile(excel_path, filename=os.path.basename(excel_path))
        await message.answer_document(
            document=excel_file,
            caption=(
                f"Отчет готов!\n\n"
                f"{summary_text}\n{match_text}\n\n"
                f"📊 Детальное сравнение — в приложенном Excel файле."
            ),
        )

        # Delete status message
        await status_msg.delete()

        logger.info(
            f"Document processed for user {user_id}: {len(items)} items, "
            f"{match_summary.get('total_models_found', 0)} models found"
        )

    except ValueError as e:
        logger.error(f"Document parsing error for user {user_id}: {e}")
        await status_msg.edit_text(f"Ошибка при обработке документа:\n{e}")
    except Exception as e:
        logger.error(f"Unexpected error processing document for user {user_id}: {e}", exc_info=True)
        await status_msg.edit_text(
            "Произошла ошибка при обработке документа.\n"
            "Попробуйте позже или обратитесь к администратору."
        )
    finally:
        # Cleanup temp files
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.debug(f"Temp DOCX removed: {file_path}")

        # Cleanup Excel file (if generated)
        if "excel_path" in locals() and os.path.exists(excel_path):
            os.remove(excel_path)
            logger.debug(f"Temp Excel removed: {excel_path}")
