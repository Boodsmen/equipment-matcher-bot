"""
Скрипт для ручной обработки ТЗ и проверки результата.
Загружает ТЗ, обрабатывает его и сохраняет Excel отчет.
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from services.docx_parser import parse_requirements_from_tables
from services.matcher import find_matching_models
from services.excel_generator import generate_report


async def process_tz():
    """Обработка ТЗ и генерация отчета."""

    # Путь к ТЗ
    tz_path = project_root / "data" / "sample_tz" / "ТЗ - ЭА.docx"

    print(f"📄 Загрузка ТЗ: {tz_path}")

    # Парсинг требований из таблиц
    print("🔍 Парсинг требований из таблиц...")
    requirements = parse_requirements_from_tables(str(tz_path))

    if not requirements or not requirements.get("items"):
        print("❌ Не удалось извлечь требования из ТЗ")
        return

    print(f"✅ Извлечено {len(requirements['items'])} позиций")
    for i, item in enumerate(requirements['items'], 1):
        specs_count = len(item.get('required_specs', {}))
        print(f"   Позиция {i}: {item.get('category', 'Неизвестно')} - {specs_count} характеристик")

    # Подбор моделей
    print("\n🔍 Подбор моделей...")
    match_results = await find_matching_models(requirements)

    print(f"✅ Результаты подбора:")
    print(f"   Всего позиций: {match_results['summary']['total_requirements']}")
    print(f"   Всего моделей: {match_results['summary']['total_models_found']}")
    print(f"   Идеальных: {match_results['summary']['ideal_matches']}")
    print(f"   Частичных: {match_results['summary']['partial_matches']}")

    # Детали по каждой позиции
    for i, result in enumerate(match_results['results'], 1):
        ideal = len(result['matches']['ideal'])
        partial = len(result['matches']['partial'])
        not_matched = len(result['matches']['not_matched'])
        print(f"\n   Позиция {i}:")
        print(f"     - Идеальных: {ideal}")
        print(f"     - Частичных: {partial}")
        print(f"     - Не подошли: {not_matched}")

        # Покажем топ-3 модели
        top_models = (result['matches']['ideal'][:3] if ideal > 0
                     else result['matches']['partial'][:3])
        if top_models:
            print(f"     Топ-3 модели:")
            for j, model in enumerate(top_models, 1):
                print(f"       {j}. {model['model_name']} - {model['match_percentage']:.1f}% "
                      f"(версия: {model['source_file']})")

    # Генерация Excel отчета
    print("\n📊 Генерация Excel отчета...")
    output_path = generate_report(
        requirements=requirements,
        match_results=match_results,
        output_dir=str(project_root / "temp_files"),
        threshold=70,
        min_percentage=80.0  # Показывать только модели >= 80%
    )

    print(f"✅ Excel отчет создан: {output_path}")
    print(f"\n📁 Файл сохранен в: {output_path}")

    return output_path


if __name__ == "__main__":
    print("=" * 60)
    print("Ручная обработка ТЗ для проверки")
    print("=" * 60)
    print()

    result = asyncio.run(process_tz())

    print("\n" + "=" * 60)
    if result:
        print("✅ ГОТОВО! Проверьте Excel файл.")
    else:
        print("❌ ОШИБКА при обработке")
    print("=" * 60)
