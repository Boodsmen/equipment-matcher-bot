"""Two-stage OpenAI integration: Router (find tech section) + Parser (extract requirements)."""

import json
import os
from typing import Any

from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError

from config import settings
from utils.logger import logger

client = AsyncOpenAI(api_key=settings.openai_api_key)

# Load canonical keys from normalization_map.json for the parser prompt
_CANONICAL_KEYS: list[str] = []
_normalization_map_path = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "normalization_map.json"
)
try:
    with open(_normalization_map_path, "r", encoding="utf-8") as _f:
        _norm_data = json.load(_f)
        _CANONICAL_KEYS = list(_norm_data.get("canonical_keys", {}).keys())
        logger.info(f"Loaded {len(_CANONICAL_KEYS)} canonical keys for OpenAI prompts")
except FileNotFoundError:
    logger.warning(f"normalization_map.json not found at {_normalization_map_path}")
except Exception as e:
    logger.error(f"Error loading normalization_map.json: {e}")


def _build_canonical_keys_description() -> str:
    """Build a formatted list of canonical keys for the parser prompt."""
    if not _CANONICAL_KEYS:
        return "Используй snake_case ключи на английском для характеристик."
    lines = [f"- {key}" for key in _CANONICAL_KEYS]
    return "\n".join(lines)


async def extract_tech_section(document_text: str) -> str:
    """
    Stage A (Router): Find the technical requirements section in a document.

    Uses the cheap model (gpt-4o-mini) to strip legal/commercial boilerplate
    and return only the technical specs section.

    Args:
        document_text: Full text of the tender document.

    Returns:
        Text of the technical requirements section.
    """
    # Truncate very long documents to stay within token limits (~100k chars ≈ 25k tokens)
    max_chars = 100_000
    if len(document_text) > max_chars:
        logger.warning(f"Document too long ({len(document_text)} chars), truncating to {max_chars}")
        document_text = document_text[:max_chars]

    prompt = (
        "Твоя задача — найти в документе раздел с техническими требованиями к оборудованию.\n"
        "Это может быть раздел: \"Технические требования\", \"Спецификация оборудования\", "
        "\"Технические характеристики\", \"Приложение: ТЗ\" и т.п.\n\n"
        "Верни ТОЛЬКО текст этого раздела. Не пересказывай, просто скопируй как есть.\n"
        "Если раздел не найден, верни весь текст.\n\n"
        f"Документ:\n{document_text}"
    )

    try:
        response = await client.chat.completions.create(
            model=settings.openai_router_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=16_000,
        )
        result = response.choices[0].message.content or ""
        tokens_used = response.usage
        logger.info(
            f"Router stage complete: input={tokens_used.prompt_tokens}, "
            f"output={tokens_used.completion_tokens}, "
            f"model={settings.openai_router_model}, "
            f"result_len={len(result)}"
        )
        return result

    except RateLimitError as e:
        logger.error(f"OpenAI rate limit hit (Router): {e}")
        raise
    except APITimeoutError as e:
        logger.error(f"OpenAI timeout (Router): {e}")
        raise
    except APIError as e:
        logger.error(f"OpenAI API error (Router): {e}")
        raise


async def parse_requirements(tech_section: str, file_type: str = "docx") -> dict[str, Any]:
    """
    Stage B (Parser): Extract structured equipment requirements from the tech section.

    Uses the smart model (gpt-4o) with canonical keys from normalization_map.json.

    Args:
        tech_section: Text of the technical requirements section.
        file_type: Source file type (docx, pdf).

    Returns:
        Dict with 'items' list of requirement objects.
    """
    canonical_keys_desc = _build_canonical_keys_description()

    prompt = (
        "Ты - эксперт по телекоммуникационному оборудованию Eltex.\n\n"
        "Проанализируй техническое задание тендера и извлеки требования к оборудованию.\n\n"
        "ВАЖНО: Используй ТОЛЬКО эти ключи для характеристик:\n"
        f"{canonical_keys_desc}\n\n"
        "Верни JSON в следующем формате:\n"
        "{\n"
        '  "items": [\n'
        "    {\n"
        '      "item_name": "Название позиции из ТЗ (как указано в документе)",\n'
        '      "quantity": 1,\n'
        '      "model_name": "Точное название модели (если указано) или null",\n'
        '      "category": "Категория оборудования (Коммутаторы/Маршрутизаторы/Прочее)",\n'
        '      "required_specs": {\n'
        '        "canonical_key": "значение"\n'
        "      }\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Правила:\n"
        "- Числовые характеристики: только числа без единиц измерения (24, а не \"24 порта\")\n"
        "- Булевые характеристики: true/false\n"
        "- Текстовые характеристики: строки без изменений\n"
        "- Если модель не указана явно, поставь model_name: null\n"
        "- Каждая позиция оборудования из ТЗ — отдельный элемент в items\n"
        "- Верни ТОЛЬКО валидный JSON без маркдаун-разметки\n\n"
        f"Технические требования ({file_type}):\n{tech_section}"
    )

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=8_000,
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content or "{}"
        tokens_used = response.usage
        logger.info(
            f"Parser stage complete: input={tokens_used.prompt_tokens}, "
            f"output={tokens_used.completion_tokens}, "
            f"model={settings.openai_model}"
        )

        result = json.loads(raw_content)

        # Validate structure
        if "items" not in result:
            logger.warning("OpenAI response missing 'items' key, wrapping in items list")
            result = {"items": [result] if result else []}

        for item in result["items"]:
            if "required_specs" not in item:
                item["required_specs"] = {}
            if "model_name" not in item:
                item["model_name"] = None
            if "category" not in item:
                item["category"] = None

        logger.info(f"Parsed {len(result['items'])} equipment items from document")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse OpenAI JSON response: {e}")
        return {"items": [], "error": f"Invalid JSON from OpenAI: {e}"}
    except RateLimitError as e:
        logger.error(f"OpenAI rate limit hit (Parser): {e}")
        raise
    except APITimeoutError as e:
        logger.error(f"OpenAI timeout (Parser): {e}")
        raise
    except APIError as e:
        logger.error(f"OpenAI API error (Parser): {e}")
        raise


async def process_document(document_text: str, file_type: str = "docx") -> dict[str, Any]:
    """
    Full document processing pipeline: Router -> Parser.

    Args:
        document_text: Full text of the tender document.
        file_type: Source file type (docx, pdf).

    Returns:
        Dict with 'items' list of parsed equipment requirements.
    """
    logger.info(f"Processing document ({file_type}): {len(document_text)} chars")

    # Stage A: Extract tech section (cheap model)
    tech_section = await extract_tech_section(document_text)
    logger.info(f"Tech section extracted: {len(tech_section)} chars (from {len(document_text)} original)")

    # Stage B: Parse requirements (smart model)
    requirements = await parse_requirements(tech_section, file_type)
    logger.info(f"Requirements parsed: {len(requirements.get('items', []))} items")

    return requirements
