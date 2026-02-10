"""
Модуль для сопоставления требований тендера с моделями оборудования в БД.

Основные функции:
- find_matching_models: главная функция поиска и сопоставления
- calculate_match_percentage: вычисление процента совпадения характеристик
- compare_spec_values: сравнение отдельных значений характеристик
- categorize_matches: группировка результатов по категориям (идеально/частично/не подходит)
- deduplicate_models: дедупликация моделей (выбор лучшей версии из дублей)
"""

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence

from config import settings
from database.crud import get_model_by_name, get_models_by_category, get_all_models
from database.models import Model
from utils.logger import logger


# ════════════════════════════════════════════════════════════════════════════
# Сравнение значений характеристик
# ════════════════════════════════════════════════════════════════════════════


def compare_spec_values(
    required_value: Any,
    model_value: Any,
    key: str,
    allow_lower: bool = False,
) -> bool:
    """
    Сравнение значения характеристики модели с требуемым значением.

    Args:
        required_value: Требуемое значение из ТЗ
        model_value: Значение из модели
        key: Ключ характеристики (для логирования)
        allow_lower: Допускать ли значения ниже требуемых (для числовых характеристик)

    Returns:
        True если значение соответствует требованию, False иначе

    Правила сравнения:
    - Boolean: строгое равенство (True == True)
    - Числовые: >= required_value (или == при allow_lower=False)
    - Строковые: регистронезависимое сравнение (case-insensitive)
    - None: если model_value отсутствует → False
    """
    # Если в модели нет этой характеристики
    if model_value is None:
        return False

    # Boolean характеристики (поддержка протоколов, функций)
    if isinstance(required_value, bool):
        return bool(model_value) == required_value

    # Числовые характеристики (порты, мощность, память)
    # Try to convert string numbers to float for comparison
    req_num = None
    model_num = None

    if isinstance(required_value, (int, float)):
        req_num = float(required_value)
    elif isinstance(required_value, str):
        try:
            req_num = float(required_value.replace(',', '.'))
        except (ValueError, AttributeError):
            pass

    if isinstance(model_value, (int, float)):
        model_num = float(model_value)
    elif isinstance(model_value, str):
        try:
            model_num = float(model_value.replace(',', '.'))
        except (ValueError, AttributeError):
            pass

    # If both are numbers, do numeric comparison
    if req_num is not None and model_num is not None:
        if allow_lower:
            # Допускаем 5% отклонение вниз
            threshold = req_num * 0.95
            return model_num >= threshold
        else:
            # Строгое: модель должна иметь >= требуемого
            return model_num >= req_num

    # Строковые характеристики (категории, названия)
    if isinstance(required_value, str) and isinstance(model_value, str):
        # Case-insensitive сравнение
        return required_value.strip().lower() == model_value.strip().lower()

    # Для всех остальных типов - строгое равенство
    return required_value == model_value


# ════════════════════════════════════════════════════════════════════════════
# Вычисление процента совпадения
# ════════════════════════════════════════════════════════════════════════════


def calculate_match_percentage(
    required_specs: Dict[str, Any],
    model_specs: Dict[str, Any],
    allow_lower: bool = False,
) -> Dict[str, Any]:
    """
    Вычисление процента совпадения характеристик модели с требованиями.

    Args:
        required_specs: Требуемые характеристики из ТЗ
        model_specs: Характеристики модели из БД
        allow_lower: Допускать ли значения ниже требуемых

    Returns:
        Dict с ключами:
        - match_percentage (float): процент совпадения (0-100)
        - matched_specs (List[str]): список совпавших характеристик
        - missing_specs (List[str]): список отсутствующих характеристик
        - different_specs (Dict[str, tuple]): характеристики с другими значениями
          формат: {key: (required_value, model_value)}
    """
    if not required_specs:
        return {
            "match_percentage": 100.0,
            "matched_specs": [],
            "missing_specs": [],
            "different_specs": {},
        }

    total_specs = len(required_specs)
    matched_count = 0
    matched_specs = []
    missing_specs = []
    different_specs = {}

    for key, required_value in required_specs.items():
        model_value = model_specs.get(key)

        # Характеристика отсутствует в модели
        if model_value is None:
            missing_specs.append(key)
            continue

        # Сравнение значений
        if compare_spec_values(required_value, model_value, key, allow_lower):
            matched_count += 1
            matched_specs.append(key)
        else:
            different_specs[key] = (required_value, model_value)

    match_percentage = (matched_count / total_specs) * 100.0

    return {
        "match_percentage": round(match_percentage, 2),
        "matched_specs": matched_specs,
        "missing_specs": missing_specs,
        "different_specs": different_specs,
    }


# ════════════════════════════════════════════════════════════════════════════
# Категоризация результатов
# ════════════════════════════════════════════════════════════════════════════


def categorize_matches(
    matches: List[Dict[str, Any]], threshold: int = 70
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Группировка результатов сопоставления по категориям.

    Args:
        matches: Список результатов с процентами совпадения
        threshold: Порог для частичного совпадения (по умолчанию 70%)

    Returns:
        Dict с категориями:
        - ideal: модели с 100% совпадением
        - partial: модели с совпадением >= threshold и < 100%
        - not_matched: модели с совпадением < threshold
    """
    ideal = []
    partial = []
    not_matched = []

    for match in matches:
        percentage = match["match_percentage"]
        if percentage == 100.0:
            ideal.append(match)
        elif percentage >= threshold:
            partial.append(match)
        else:
            not_matched.append(match)

    # Сортировка по убыванию процента совпадения
    ideal.sort(key=lambda x: x["model_name"])
    partial.sort(key=lambda x: x["match_percentage"], reverse=True)
    not_matched.sort(key=lambda x: x["match_percentage"], reverse=True)

    logger.info(
        f"Categorized: {len(ideal)} ideal, {len(partial)} partial, {len(not_matched)} not matched"
    )

    return {"ideal": ideal, "partial": partial, "not_matched": not_matched}


# ════════════════════════════════════════════════════════════════════════════
# Дедупликация моделей
# ════════════════════════════════════════════════════════════════════════════


def _parse_version_priority(source_file: str) -> float:
    """
    Извлечение приоритета версии из имени source_file.

    Правила:
    - 'finalUPDv.X.Y' → 1000 + Y (напр. finalUPDv.1.2 → 1002)
    - 'finalUPD' (без версии) → 1000
    - 'vNN' → NN (напр. v21 → 21, v33 → 33)
    - 'vNN.M' → NN (дробная часть .M игнорируется для основного приоритета)
    - суффикс '_new' → +0.5
    - без версии → 0
    """
    if not source_file:
        return 0

    priority = 0.0

    # finalUPDv.X.Y — высший приоритет
    m = re.search(r'finalUPDv\.(\d+)\.(\d+)', source_file)
    if m:
        priority = 1000 + int(m.group(2))
    elif 'finalUPD' in source_file:
        priority = 1000
    else:
        # vNN или vNN.M
        m = re.search(r'v(\d+)(?:\.(\d+))?', source_file)
        if m:
            priority = int(m.group(1))

    # _new суффикс даёт бонус +0.5
    if '_new' in source_file:
        priority += 0.5

    return priority


def deduplicate_models(models: Sequence[Model]) -> List[Model]:
    """
    Дедупликация списка моделей: для каждого model_name оставляет лучшую версию.

    Критерии выбора лучшей версии (по приоритету):
    1. Количество непустых specifications (больше = лучше)
    2. Версия из source_file (finalUPD > v21 > v20 > без версии)

    Также фильтрует модели с пустыми specifications ({}).
    """
    # Фильтрация моделей с пустыми specs
    non_empty = [m for m in models if m.specifications]
    filtered_count = len(models) - len(non_empty)
    if filtered_count:
        logger.info(f"Filtered out {filtered_count} models with empty specifications")

    # Группировка по model_name
    groups: Dict[str, List[Model]] = defaultdict(list)
    for model in non_empty:
        groups[model.model_name].append(model)

    # Выбор лучшей версии из каждой группы
    result = []
    for name, group in groups.items():
        if len(group) == 1:
            result.append(group[0])
        else:
            # Сортировка: сначала по кол-ву specs (desc), потом по версии (desc)
            best = max(
                group,
                key=lambda m: (
                    len(m.specifications) if m.specifications else 0,
                    _parse_version_priority(m.source_file or ""),
                ),
            )
            result.append(best)

    logger.info(
        f"Deduplicated: {len(models)} → {len(result)} models "
        f"({len(models) - len(result)} duplicates removed)"
    )

    return result


# ════════════════════════════════════════════════════════════════════════════
# Основная функция поиска и сопоставления
# ════════════════════════════════════════════════════════════════════════════


async def find_matching_models(requirements: Dict[str, Any]) -> Dict[str, Any]:
    """
    Поиск и сопоставление моделей по требованиям из ТЗ.

    Args:
        requirements: Структура требований от OpenAI:
        {
            "items": [
                {
                    "model_name": "MES3710P" | null,
                    "category": "Коммутаторы" | null,
                    "required_specs": {
                        "ports_1g_sfp": 24,
                        "power_watt": 200,
                        ...
                    }
                }
            ]
        }

    Returns:
        Dict с результатами:
        {
            "results": [
                {
                    "requirement": {...},  # Исходное требование
                    "matches": {
                        "ideal": [...],
                        "partial": [...],
                        "not_matched": [...]
                    }
                }
            ],
            "summary": {
                "total_requirements": int,
                "total_models_found": int,
                "ideal_matches": int,
                "partial_matches": int
            }
        }

    Стратегия поиска (fallback):
    1. Если указано model_name → поиск по названию модели (игнорируя category)
    2. Если указано category → поиск только в этой категории
    3. Если category=null → поиск по всей БД (лимит 200 моделей)
    """
    items = requirements.get("items", [])
    if not items:
        logger.warning("No items in requirements")
        return {
            "results": [],
            "summary": {
                "total_requirements": 0,
                "total_models_found": 0,
                "ideal_matches": 0,
                "partial_matches": 0,
            },
        }

    results = []
    total_models_found = 0
    ideal_matches = 0
    partial_matches = 0

    threshold = settings.match_threshold
    allow_lower = settings.allow_lower_values

    logger.info(
        f"Starting matching with threshold={threshold}%, allow_lower={allow_lower}"
    )

    for idx, item in enumerate(items, 1):
        model_name = item.get("model_name")
        category = item.get("category")
        required_specs = item.get("required_specs", {})

        logger.info(
            f"[Requirement {idx}/{len(items)}] model_name={model_name}, category={category}, specs={len(required_specs)}"
        )

        # ────────────── СТРАТЕГИЯ ПОИСКА ──────────────

        candidates = []

        # 1. Если указано точное название модели
        if model_name:
            logger.info(f"Searching by model_name: {model_name}")
            candidates = await get_model_by_name(model_name)
            logger.info(f"Found {len(candidates)} models by name")

        # 2. Если указана категория (но не модель)
        elif category:
            logger.info(f"Searching by category: {category}")
            candidates = await get_models_by_category(category)

            # Expand search for switch categories
            # In CSV, switches are categorized as "Управляемый" (managed) rather than "Коммутаторы" (switches)
            if category == "Коммутаторы":
                managed_switches = await get_models_by_category("Управляемый")
                candidates.extend(managed_switches)
                logger.info(f"Found {len(candidates)} models (including 'Управляемый' subcategory)")
            else:
                logger.info(f"Found {len(candidates)} models in category")

        # 3. Поиск по всей БД (если ничего не указано)
        else:
            logger.info("Searching across all models (no model_name or category)")
            all_models = await get_all_models()
            # Ограничиваем для производительности (топ-200)
            candidates = list(all_models[:200])
            logger.info(f"Limited to {len(candidates)} models for performance")

        # ────────────── ДЕДУПЛИКАЦИЯ ──────────────

        if settings.deduplicate_models:
            candidates = deduplicate_models(candidates)

        # ────────────── СОПОСТАВЛЕНИЕ ──────────────

        matches = []
        for model in candidates:
            match_result = calculate_match_percentage(
                required_specs=required_specs,
                model_specs=model.specifications,
                allow_lower=allow_lower,
            )

            matches.append(
                {
                    "model_id": model.id,
                    "model_name": model.model_name,
                    "category": model.category,
                    "source_file": model.source_file,
                    "match_percentage": match_result["match_percentage"],
                    "matched_specs": match_result["matched_specs"],
                    "missing_specs": match_result["missing_specs"],
                    "different_specs": match_result["different_specs"],
                    "specifications": model.specifications,
                    "raw_specifications": model.raw_specifications,
                }
            )

        # ────────────── КАТЕГОРИЗАЦИЯ ──────────────

        categorized = categorize_matches(matches, threshold)

        results.append({"requirement": item, "matches": categorized})

        # Статистика
        total_models_found += len(matches)
        ideal_matches += len(categorized["ideal"])
        partial_matches += len(categorized["partial"])

    # ────────────── ИТОГОВАЯ СВОДКА ──────────────

    summary = {
        "total_requirements": len(items),
        "total_models_found": total_models_found,
        "ideal_matches": ideal_matches,
        "partial_matches": partial_matches,
    }

    logger.info(f"Matching completed: {summary}")

    return {"results": results, "summary": summary}
