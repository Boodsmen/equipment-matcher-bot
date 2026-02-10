"""
Модуль для генерации Excel отчетов с результатами сопоставления моделей.

Структура отчета:
- Лист 1: "Сводка" — таблица всех найденных моделей с процентами совпадения
- Листы 2+: "Детальное сравнение - <Модель>" — характеристика-в-характеристику

Форматирование:
- Заголовки: жирный шрифт, серая заливка
- Статусы: цветовая кодировка (зеленый ✅ / желтый ⚠️ / красный ❌)
- Автоподбор ширины колонок
- Фильтры на первом листе
"""

import os
from datetime import datetime
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


def _create_summary_sheet(wb: Workbook, match_results: Dict[str, Any], threshold: int) -> None:
    """
    Создание листа "Сводка" с таблицей всех найденных моделей.

    Колонки:
    - № — порядковый номер
    - Позиция ТЗ — название требования из ТЗ
    - Модель — название модели
    - Источник — source_file (v20, v29, ESR и т.д.)
    - % совпадения — процент совпадения характеристик
    - Статус — эмодзи (✅ / ⚠️ / ❌)
    - Примечания — краткое описание несовпадений
    """
    ws = wb.active
    ws.title = "Сводка"

    # Заголовки
    headers = ["№", "Позиция ТЗ", "Модель", "Источник", "% совпадения", "Статус", "Примечания"]
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
                model_name = match["model_name"]
                source_file = match["source_file"]
                percentage = match["match_percentage"]
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
                ws.append([row_num - 1, req_name, model_name, source_file, percentage, status_emoji, notes_str])

                # Заливка строки по статусу
                color = _get_status_color(percentage, threshold)
                for col in range(1, len(headers) + 1):
                    ws.cell(row=row_num, column=col).fill = PatternFill(
                        start_color=color, end_color=color, fill_type="solid"
                    )

                # Форматирование процента (центр)
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

    Колонки:
    - Характеристика — канонический ключ (ports_1g_sfp, power_watt и т.д.)
    - Требуется — значение из ТЗ
    - В модели — значение из raw_specifications (исходное)
    - Статус — эмодзи (✅ / ❌ / —)

    ВАЖНО: Используем raw_specifications для отображения, но сравнение идёт по specifications
    """
    model_name = match["model_name"]
    source_file = match["source_file"]

    # Название листа (ограничение Excel: макс. 31 символ)
    sheet_name = f"{model_name[:25]} ({source_file})"[:31]
    ws = wb.create_sheet(title=sheet_name)

    # Заголовок листа
    ws.append([f"Детальное сравнение: {model_name}"])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center")

    ws.append([])  # Пустая строка

    # Заголовки таблицы
    headers = ["Характеристика", "Требуется", "В модели", "Статус"]
    ws.append(headers)
    _format_header(ws, row=3, columns=len(headers))

    required_specs = requirement.get("required_specs", {})
    model_specs = match["specifications"]
    raw_specs = match.get("raw_specifications", {})
    matched_specs = match["matched_specs"]
    missing_specs = match["missing_specs"]
    different_specs = match["different_specs"]

    # Создаём обратный маппинг: канонический ключ -> исходное название колонки
    # (для отображения читаемого названия характеристики)
    canonical_to_readable = {}
    for key in required_specs.keys():
        # Пытаемся найти в raw_specifications название колонки, которое соответствует этому ключу
        # (это упрощенная версия, в идеале нужен reverse normalization_map)
        canonical_to_readable[key] = key.replace("_", " ").title()

    row_num = 4
    for key, required_value in required_specs.items():
        readable_key = canonical_to_readable.get(key, key)
        model_value = model_specs.get(key)

        # Для отображения используем raw_specifications
        # Ищем в raw_specs значение по каноническому ключу (это упрощение, в идеале нужен reverse mapping)
        display_value = raw_specs.get(key) if raw_specs else model_value
        if display_value is None:
            display_value = model_value

        # Статус
        if key in matched_specs:
            status = "✅ Совпадает"
            color = COLOR_GREEN
        elif key in missing_specs:
            status = "❌ Отсутствует"
            color = COLOR_RED
            display_value = "—"
        elif key in different_specs:
            status = "❌ Не совпадает"
            color = COLOR_RED
        else:
            status = "—"
            color = None

        ws.append([readable_key, str(required_value), str(display_value), status])

        # Заливка строки
        if color:
            for col in range(1, len(headers) + 1):
                ws.cell(row=row_num, column=col).fill = PatternFill(
                    start_color=color, end_color=color, fill_type="solid"
                )

        row_num += 1

    # Автоподбор ширины
    _auto_size_columns(ws)

    logger.debug(f"Detailed sheet created for {model_name}")


def generate_report(
    requirements: Dict[str, Any],
    match_results: Dict[str, Any],
    output_dir: str = "temp_files",
    threshold: int = 70,
) -> str:
    """
    Генерация Excel отчета с результатами сопоставления.

    Args:
        requirements: Исходные требования из OpenAI
        match_results: Результаты сопоставления от matcher.find_matching_models()
        output_dir: Папка для сохранения файла
        threshold: Порог для частичного совпадения (из config)

    Returns:
        Путь к сгенерированному Excel файлу

    Структура файла:
    - Лист 1: "Сводка" — все найденные модели с процентами и статусами
    - Листы 2+: "Детальное сравнение - <Модель>" — по одному для каждой идеальной/частичной модели
    """
    logger.info("Starting Excel report generation...")

    wb = Workbook()

    # Лист 1: Сводка
    _create_summary_sheet(wb, match_results, threshold)

    # Листы 2+: Детальное сравнение (только для идеальных и частичных совпадений)
    detailed_count = 0
    max_detailed_sheets = 50  # Ограничение для производительности

    for result in match_results.get("results", []):
        requirement = result["requirement"]

        # Идеальные совпадения
        for match in result["matches"].get("ideal", []):
            if detailed_count >= max_detailed_sheets:
                break
            _create_detailed_sheet(wb, match, requirement)
            detailed_count += 1

        # Частичные совпадения (топ-3 для каждой позиции)
        for match in result["matches"].get("partial", [])[:3]:
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
