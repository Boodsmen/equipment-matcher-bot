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
import time
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
    def extract_number(val):
        """
        Извлечение числового значения из различных форматов.

        Поддерживаемые форматы:
        - Простые числа: 24, 200.5, -40
        - Строки с единицами: "24 порта", "200 Вт", "2 ГБ"
        - Дробные числа: "1.5 Гбит/с", "2,5 ГБ" (точка и запятая)
        - Диапазоны: "10-20" → 20 (максимум), "от 100 до 200" → 200
        - Умножение: "2x4" → 8, "4 блока по 8" → 32
        - Отрицательные: "-40°C" → -40
        - Префиксы: "до 1000" → 1000, "не менее 500" → 500
        """
        if isinstance(val, (int, float)):
            return float(val)

        if not isinstance(val, str):
            return None

        # Замена запятых на точки для дробных чисел
        val_normalized = val.replace(',', '.')

        # Диапазоны: "10-20", "от 100 до 200"
        # Берем максимальное значение (наиболее строгое требование)
        range_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|до)\s*(\d+(?:\.\d+)?)', val_normalized)
        if range_match:
            return max(float(range_match.group(1)), float(range_match.group(2)))

        # Умножение: "2x4", "4 блока по 8 портов"
        mult_match = re.search(r'(\d+)\s*(?:x|×|блок\w*\s+по)\s*(\d+)', val_normalized, re.IGNORECASE)
        if mult_match:
            return float(mult_match.group(1)) * float(mult_match.group(2))

        # Префиксы: "до 1000", "не менее 500", "минимум 100"
        prefix_match = re.search(r'(?:до|не\s+менее|минимум|максимум)\s+(\d+(?:\.\d+)?)', val_normalized, re.IGNORECASE)
        if prefix_match:
            return float(prefix_match.group(1))

        # Простое число (целое или дробное) в строке
        # Ищем первое число, включая отрицательные
        match = re.search(r"[-+]?\d*\.?\d+", val_normalized)
        if match:
            return float(match.group())

        return None

    # Извлекаем числовые значения из обоих параметров
    req_num = extract_number(required_value)
    model_num = extract_number(model_value)

    # Если оба значения числовые - выполняем числовое сравнение
    if req_num is not None and model_num is not None:
        if allow_lower:
            # Допускаем 5% отклонение вниз
            threshold = req_num * 0.95
            result = model_num >= threshold
            logger.debug(
                f"Numeric comparison for '{key}': required={req_num}, model={model_num}, "
                f"threshold={threshold:.2f}, allow_lower=True, result={result}"
            )
            return result
        else:
            # Строгое: модель должна иметь >= требуемого
            result = model_num >= req_num
            logger.debug(
                f"Numeric comparison for '{key}': required={req_num}, model={model_num}, "
                f"allow_lower=False, result={result}"
            )
            return result

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

    # Mapping категорий к подкатегориям для расширенного поиска
    CATEGORY_SUBCATEGORIES = {
        "Коммутаторы": ["Управляемый", "Неуправляемый", "Промышленный"],
        "Маршрутизаторы": ["Универсальный шлюз безопасности", "Модульный"],
        # Добавить другие категории по мере необходимости
    }

    for idx, item in enumerate(items, 1):
        model_name = item.get("model_name")
        category = item.get("category")
        required_specs = item.get("required_specs", {})

        logger.info(
            f"[Requirement {idx}/{len(items)}] model_name={model_name}, category={category}, specs={len(required_specs)}"
        )

        # ────────────── СТРАТЕГИЯ ПОИСКА ──────────────

        candidates = []
        search_start_time = time.time()

        # 1. Если указано точное название модели
        if model_name:
            logger.info(f"Searching by model_name: {model_name}")
            candidates = await get_model_by_name(model_name)
            search_time = time.time() - search_start_time
            logger.info(f"Found {len(candidates)} models by name in {search_time:.3f}s")

        # 2. Если указана категория (но не модель)
        elif category:
            logger.info(f"Searching by category: {category}")
            candidates = await get_models_by_category(category)
            initial_count = len(candidates)

            # Расширенный поиск по подкатегориям
            if category in CATEGORY_SUBCATEGORIES:
                for subcategory in CATEGORY_SUBCATEGORIES[category]:
                    subcategory_models = await get_models_by_category(subcategory)
                    candidates.extend(subcategory_models)
                    logger.debug(f"Added {len(subcategory_models)} models from subcategory '{subcategory}'")

                search_time = time.time() - search_start_time
                logger.info(
                    f"Found {len(candidates)} models (base: {initial_count}, "
                    f"subcategories: {len(candidates) - initial_count}) in {search_time:.3f}s"
                )
            else:
                search_time = time.time() - search_start_time
                logger.info(f"Found {len(candidates)} models in category in {search_time:.3f}s")

        # 3. Поиск по всей БД (если ничего не указано)
        else:
            logger.info("Searching across all models (no model_name or category)")
            all_models = await get_all_models()
            candidates = list(all_models)
            search_time = time.time() - search_start_time
            logger.info(f"Found {len(candidates)} models in database in {search_time:.3f}s")

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
