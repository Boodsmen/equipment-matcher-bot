"""
Модуль для генерации Excel отчетов с результатами сопоставления моделей.

Структура отчета:
- Лист 1: "Сводка" — таблица всех найденных моделей с процентами совпадения
- Листы 2+: "Детальное сравнение - <Модель>" — характеристика-в-характеристику

Форматирование:
- Заголовки: жирный шрифт, серая заливка
- Статусы: цветовая кодировка (зеленый ✅ / желтый ⚠️ / красный ❌)
- Версии: цветовая кодировка (finalUPD - зеленый, v29+ - желтый, старые - оранжевый)
- Автоподбор ширины колонок
- Фильтры на первом листе
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from utils.logger import logger

# Цвета для статусов
COLOR_GREEN = "C6EFCE"  # Светло-зеленый (совпадает)
COLOR_YELLOW = "FFEB9C"  # Светло-желтый (частичное)
COLOR_RED = "FFC7CE"  # Светло-красный (не совпадает)
COLOR_GRAY = "D9D9D9"  # Серый (заголовок)
COLOR_ORANGE = "FFD699"  # Оранжевый (старые версии)

# Загрузка reverse mapping для читаемых названий характеристик
_REVERSE_MAPPING_CACHE = None


def _load_reverse_mapping() -> Dict[str, str]:
    """Загрузка reverse_normalization_map.json (с кешированием)."""
    global _REVERSE_MAPPING_CACHE
    if _REVERSE_MAPPING_CACHE is not None:
        return _REVERSE_MAPPING_CACHE

    try:
        reverse_map_path = Path(__file__).parent.parent / "data" / "reverse_normalization_map.json"
        with open(reverse_map_path, "r", encoding="utf-8") as f:
            _REVERSE_MAPPING_CACHE = json.load(f)
        logger.debug(f"Loaded reverse mapping with {len(_REVERSE_MAPPING_CACHE)} keys")
    except Exception as e:
        logger.warning(f"Failed to load reverse_normalization_map.json: {e}")
        _REVERSE_MAPPING_CACHE = {}

    return _REVERSE_MAPPING_CACHE


def _parse_version_from_source(source_file: str) -> str:
    """
    Извлечение читаемой версии из source_file.

    Примеры:
    - "v29" → "v29"
    - "finalUPDv.1.2" → "finalUPD v1.2"
    - "v21_new" → "v21 (new)"
    - без версии → "—"
    """
    if not source_file:
        return "—"

    # finalUPDv.X.Y
    m = re.search(r'finalUPDv\.(\d+)\.(\d+)', source_file)
    if m:
        return f"finalUPD v{m.group(1)}.{m.group(2)}"

    # finalUPD без версии
    if 'finalUPD' in source_file:
        return "finalUPD"

    # vNN или vNN.M
    m = re.search(r'v(\d+)(?:\.(\d+))?', source_file)
    if m:
        version = f"v{m.group(1)}"
        if m.group(2):
            version += f".{m.group(2)}"
        if '_new' in source_file:
            version += " (new)"
        return version

    return source_file  # Fallback


def _get_version_color(source_file: str) -> str:
    """
    Определение цвета для версии.

    Правила:
    - finalUPD* → зеленый
    - v29+ → желтый
    - v20-v28 → оранжевый
    - остальное → None (без цвета)
    """
    if not source_file:
        return None

    # finalUPD - самая актуальная
    if 'finalUPD' in source_file:
        return COLOR_GREEN

    # vNN
    m = re.search(r'v(\d+)', source_file)
    if m:
        version_num = int(m.group(1))
        if version_num >= 29:
            return COLOR_YELLOW  # Новые версии
        elif version_num >= 20:
            return COLOR_ORANGE  # Старые версии
        else:
            return COLOR_RED  # Совсем старые

    return None  # Без цвета


def _auto_size_columns(ws) -> None:
    """Автоподбор ширины колонок по содержимому."""
    for column in ws.columns:
        max_length = 0
        column_letter = get_column_letter(column[0].column)

        for cell in column:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass

        adjusted_width = min(max_length + 2, 50)  # Макс. 50 символов
        ws.column_dimensions[column_letter].width = adjusted_width


def _format_header(ws, row: int, columns: int) -> None:
    """Форматирование строки заголовка (жирный шрифт, серая заливка)."""
    for col in range(1, columns + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color=COLOR_GRAY, end_color=COLOR_GRAY, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _get_status_emoji(match_percentage: float, threshold: int = 70) -> str:
    """Получить эмодзи статуса по проценту совпадения."""
    if match_percentage == 100.0:
        return "✅"
    elif match_percentage >= threshold:
        return "⚠️"
    else:
        return "❌"


def _get_status_color(match_percentage: float, threshold: int = 70) -> str:
    """Получить цвет заливки по проценту совпадения."""
    if match_percentage == 100.0:
        return COLOR_GREEN
    elif match_percentage >= threshold:
        return COLOR_YELLOW
    else:
        return COLOR_RED


def _create_summary_sheet(wb: Workbook, match_results: Dict[str, Any], threshold: int, min_percentage: float = 80.0) -> None:
    """
    Создание листа "Сводка" с таблицей найденных моделей.

    Колонки:
    - № — порядковый номер
    - Позиция ТЗ — название требования из ТЗ
    - Модель — название модели
    - Версия — читаемая версия (v29, finalUPD v1.2) с цветовым кодированием
    - % совпадения — процент совпадения характеристик
    - Статус — эмодзи (✅ / ⚠️ / ❌)
    - Примечания — краткое описание несовпадений

    Args:
        min_percentage: Минимальный процент совпадения для включения в отчет (по умолчанию 80%)
    """
    ws = wb.active
    ws.title = "Сводка"

    # Заголовки
    headers = ["№", "Позиция ТЗ", "Модель", "Версия", "% совпадения", "Статус", "Примечания"]
    ws.append(headers)
    _format_header(ws, row=1, columns=len(headers))

    row_num = 2
    for req_idx, result in enumerate(match_results.get("results", []), 1):
        requirement = result["requirement"]
        req_name = (
            requirement.get("item_name")
            or requirement.get("model_name")
            or f"Позиция {req_idx}"
        )

        # Все найденные модели (сначала идеальные, потом частичные, потом не подошедшие)
        for category_name in ["ideal", "partial", "not_matched"]:
            matches = result["matches"].get(category_name, [])
            for match in matches:
                percentage = match["match_percentage"]

                # ФИЛЬТР: Показываем только модели с совпадением >= min_percentage
                if percentage < min_percentage:
                    continue

                model_name = match["model_name"]
                source_file = match["source_file"]
                version = _parse_version_from_source(source_file)
                status_emoji = _get_status_emoji(percentage, threshold)

                # Примечания: что не совпало
                notes = []
                if match["missing_specs"]:
                    notes.append(f"Отсутствуют: {', '.join(match['missing_specs'][:3])}")
                if match["different_specs"]:
                    diff_keys = list(match["different_specs"].keys())[:2]
                    notes.append(f"Не совпали: {', '.join(diff_keys)}")

                notes_str = "; ".join(notes) if notes else "—"

                # Запись строки
                ws.append([row_num - 1, req_name, model_name, version, percentage, status_emoji, notes_str])

                # Заливка строки по статусу совпадения
                match_color = _get_status_color(percentage, threshold)
                for col in range(1, len(headers) + 1):
                    ws.cell(row=row_num, column=col).fill = PatternFill(
                        start_color=match_color, end_color=match_color, fill_type="solid"
                    )

                # Дополнительное выделение колонки "Версия" по актуальности версии
                version_color = _get_version_color(source_file)
                if version_color:
                    ws.cell(row=row_num, column=4).fill = PatternFill(
                        start_color=version_color, end_color=version_color, fill_type="solid"
                    )
                    # Жирный шрифт для актуальных версий
                    if version_color == COLOR_GREEN:
                        ws.cell(row=row_num, column=4).font = Font(bold=True)

                # Форматирование процента и статуса (центр)
                ws.cell(row=row_num, column=4).alignment = Alignment(horizontal="center")
                ws.cell(row=row_num, column=5).alignment = Alignment(horizontal="center")
                ws.cell(row=row_num, column=6).alignment = Alignment(horizontal="center")

                row_num += 1

    # Автоподбор ширины
    _auto_size_columns(ws)

    # Фильтры
    ws.auto_filter.ref = ws.dimensions

    logger.info(f"Summary sheet created with {row_num - 2} rows")


def _create_detailed_sheet(wb: Workbook, match: Dict[str, Any], requirement: Dict[str, Any]) -> None:
    """
    Создание листа детального сравнения для конкретной модели.

    Содержит:
    1. Метаданные модели (название, категория, версия, процент совпадения)
    2. Таблица сравнения характеристик с читаемыми названиями из reverse mapping

    Колонки:
    - Характеристика — читаемое название из reverse_normalization_map.json
    - Требуется — значение из ТЗ
    - В модели — значение из specifications (нормализованное)
    - Статус — эмодзи (✅ / ❌ / —)
    """
    model_name = match["model_name"]
    source_file = match["source_file"]
    category = match.get("category", "—")
    version = _parse_version_from_source(source_file)
    percentage = match["match_percentage"]

    # Название листа (ограничение Excel: макс. 31 символ)
    sheet_name = f"{model_name[:20]} {version}"[:31]
    ws = wb.create_sheet(title=sheet_name)

    # ═══════════════ СЕКЦИЯ МЕТАДАННЫХ ═══════════════

    # Заголовок
    ws.append([f"Детальное сравнение: {model_name}"])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center")

    ws.append([])  # Пустая строка

    # Метаданные модели
    ws.append(["Категория:", category])
    ws.append(["Версия:", version])
    ws.append(["% совпадения:", f"{percentage}%"])

    # Выделение процента совпадения цветом
    match_color = _get_status_color(percentage, 70)
    ws.cell(row=5, column=2).fill = PatternFill(
        start_color=match_color, end_color=match_color, fill_type="solid"
    )
    ws.cell(row=5, column=2).font = Font(bold=True, size=12)

    # Жирный шрифт для меток
    for row in range(3, 6):
        ws.cell(row=row, column=1).font = Font(bold=True)

    ws.append([])  # Пустая строка

    # ═══════════════ СЕКЦИЯ СРАВНЕНИЯ ═══════════════

    # Заголовки таблицы
    headers = ["Характеристика", "Требуется", "В модели", "Статус"]
    ws.append(headers)
    header_row = 7
    _format_header(ws, row=header_row, columns=len(headers))

    required_specs = requirement.get("required_specs", {})
    model_specs = match["specifications"]
    matched_specs = match["matched_specs"]
    missing_specs = match["missing_specs"]
    different_specs = match["different_specs"]

    # Загружаем reverse mapping для читаемых названий
    reverse_mapping = _load_reverse_mapping()

    row_num = header_row + 1
    for key, required_value in required_specs.items():
        # Используем reverse mapping для читаемого названия
        readable_key = reverse_mapping.get(key, key.replace("_", " ").title())
        model_value = model_specs.get(key)

        # Статус
        if key in matched_specs:
            status = "✅ Совпадает"
            color = COLOR_GREEN
        elif key in missing_specs:
            status = "❌ Отсутствует"
            color = COLOR_RED
            model_value = "—"
        elif key in different_specs:
            status = "❌ Не совпадает"
            color = COLOR_RED
        else:
            status = "—"
            color = None

        # Форматирование значений для отображения
        required_display = str(required_value) if required_value is not None else "—"
        model_display = str(model_value) if model_value is not None else "—"

        ws.append([readable_key, required_display, model_display, status])

        # Заливка строки
        if color:
            for col in range(1, len(headers) + 1):
                ws.cell(row=row_num, column=col).fill = PatternFill(
                    start_color=color, end_color=color, fill_type="solid"
                )

        row_num += 1

    # Автоподбор ширины
    _auto_size_columns(ws)

    logger.debug(f"Detailed sheet created for {model_name} (version: {version}, match: {percentage}%)")


def generate_report(
    requirements: Dict[str, Any],
    match_results: Dict[str, Any],
    output_dir: str = "temp_files",
    threshold: int = 70,
    min_percentage: float = 80.0,
) -> str:
    """
    Генерация Excel отчета с результатами сопоставления.

    Args:
        requirements: Исходные требования из OpenAI
        match_results: Результаты сопоставления от matcher.find_matching_models()
        output_dir: Папка для сохранения файла
        threshold: Порог для частичного совпадения (из config)
        min_percentage: Минимальный процент совпадения для включения в отчет (по умолчанию 80%)

    Returns:
        Путь к сгенерированному Excel файлу

    Структура файла:
    - Лист 1: "Сводка" — модели с совпадением >= min_percentage
    - Листы 2+: "Детальное сравнение - <Модель>" — только для моделей >= min_percentage
    """
    logger.info(f"Starting Excel report generation (min_percentage={min_percentage}%)...")

    wb = Workbook()

    # Лист 1: Сводка (с фильтром по min_percentage)
    _create_summary_sheet(wb, match_results, threshold, min_percentage)

    # Листы 2+: Детальное сравнение (только для моделей >= min_percentage)
    detailed_count = 0
    max_detailed_sheets = 50  # Ограничение для производительности

    for result in match_results.get("results", []):
        requirement = result["requirement"]

        # Идеальные совпадения (с фильтром >= min_percentage)
        for match in result["matches"].get("ideal", []):
            if detailed_count >= max_detailed_sheets:
                break
            if match["match_percentage"] >= min_percentage:
                _create_detailed_sheet(wb, match, requirement)
                detailed_count += 1

        # Частичные совпадения (топ-3 для каждой позиции, с фильтром >= min_percentage)
        partial_filtered = [m for m in result["matches"].get("partial", []) if m["match_percentage"] >= min_percentage]
        for match in partial_filtered[:3]:
            if detailed_count >= max_detailed_sheets:
                break
            _create_detailed_sheet(wb, match, requirement)
            detailed_count += 1

    # Сохранение файла
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"tender_match_report_{timestamp}.xlsx"
    file_path = os.path.join(output_dir, filename)

    wb.save(file_path)
    logger.info(
        f"Excel report generated: {file_path} "
        f"({detailed_count} detailed sheets, {len(wb.sheetnames)} total sheets)"
    )

    return file_path
