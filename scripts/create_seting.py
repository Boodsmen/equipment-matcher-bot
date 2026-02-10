"""Утилита для создания файлов настроек разработки (*_seting.py).

Создаёт вспомогательные файлы с суффиксом _seting для удобства
разработки и отладки отдельных компонентов проекта.

Использование (через Docker):
    docker exec tender_matcher_bot python scripts/create_seting.py --list
    docker exec tender_matcher_bot python scripts/create_seting.py --all
    docker exec tender_matcher_bot python scripts/create_seting.py db
    docker exec tender_matcher_bot python scripts/create_seting.py openai
    docker exec tender_matcher_bot python scripts/create_seting.py matcher
"""

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")

# Шаблоны файлов _seting
TEMPLATES: dict[str, dict[str, str]] = {
    "db": {
        "filename": "db_seting.py",
        "description": "Проверка подключения к БД и состояния данных",
        "content": '''\
"""Проверка подключения к БД и состояния данных (_seting)."""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import async_session_maker, engine
from database.crud import get_models_count, get_all_models
from sqlalchemy import text


async def check_db():
    """Проверить подключение и вывести статистику БД."""
    print("=" * 50)
    print("DB SETING — Проверка базы данных")
    print("=" * 50)

    # Проверка подключения
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT version()"))
        version = result.scalar()
        print(f"PostgreSQL: {version}")

    # Количество моделей
    count = await get_models_count()
    print(f"Моделей в БД: {count}")

    # Категории
    async with async_session_maker() as session:
        result = await session.execute(
            text("SELECT category, COUNT(*) FROM models GROUP BY category ORDER BY COUNT(*) DESC")
        )
        rows = result.fetchall()
        if rows:
            print("\\nКатегории:")
            for cat, cnt in rows:
                print(f"  {cat or 'Без категории'}: {cnt}")

    # Пример модели
    models = await get_all_models()
    if models:
        m = models[0]
        print(f"\\nПример модели: {m.model_name}")
        print(f"  Категория: {m.category}")
        print(f"  Источник: {m.source_file}")
        specs = m.specifications or {}
        print(f"  Характеристик (normalized): {len(specs)}")
        for k, v in list(specs.items())[:5]:
            print(f"    {k}: {v}")
        if len(specs) > 5:
            print(f"    ... и ещё {len(specs) - 5}")

    # Проверка таблиц
    async with async_session_maker() as session:
        result = await session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = [r[0] for r in result.fetchall()]
        print(f"\\nТаблицы: {', '.join(tables)}")

    await engine.dispose()
    print("\\n✓ БД работает корректно")


if __name__ == "__main__":
    asyncio.run(check_db())
''',
    },
    "openai": {
        "filename": "openai_seting.py",
        "description": "Тест подключения к OpenAI и проверка промптов",
        "content": '''\
"""Тест подключения к OpenAI и проверка промптов (_seting)."""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from openai import AsyncOpenAI


async def check_openai():
    """Проверить подключение к OpenAI API."""
    print("=" * 50)
    print("OPENAI SETING — Проверка OpenAI API")
    print("=" * 50)

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    print(f"Router model: {settings.openai_router_model}")
    print(f"Parser model: {settings.openai_model}")

    # Тестовый запрос (минимальный, дешёвый)
    print("\\nТестовый запрос к Router модели...")
    try:
        response = await client.chat.completions.create(
            model=settings.openai_router_model,
            messages=[{"role": "user", "content": "Ответь одним словом: работает?"}],
            max_tokens=10,
        )
        answer = response.choices[0].message.content
        tokens = response.usage
        print(f"  Ответ: {answer}")
        print(f"  Токены: input={tokens.prompt_tokens}, output={tokens.completion_tokens}")
        print("  ✓ Router модель работает")
    except Exception as e:
        print(f"  ✗ Ошибка: {e}")

    # Проверка canonical keys
    from services.openai_service import _CANONICAL_KEYS
    print(f"\\nКаноническ ключей загружено: {len(_CANONICAL_KEYS)}")
    if _CANONICAL_KEYS:
        print(f"  Примеры: {', '.join(_CANONICAL_KEYS[:10])}...")

    print("\\n✓ OpenAI API настроен корректно")


if __name__ == "__main__":
    asyncio.run(check_openai())
''',
    },
    "matcher": {
        "filename": "matcher_seting.py",
        "description": "Тестирование логики сопоставления (для этапа 3)",
        "content": '''\
"""Тестирование логики сопоставления моделей (_seting)."""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import async_session_maker, engine
from database.crud import get_all_models, search_models_by_specs


async def test_matcher():
    """Тестовое сопоставление с примером требований."""
    print("=" * 50)
    print("MATCHER SETING — Тестирование сопоставления")
    print("=" * 50)

    # Пример требований из ТЗ (для тестирования)
    test_requirements = {
        "ports_1g_sfp": 4,
        "ports_10g_sfp_plus": 2,
    }

    print(f"Тестовые требования: {test_requirements}")

    # Поиск по JSONB @> оператору
    print("\\nПоиск через search_models_by_specs (точное совпадение JSONB)...")
    results = await search_models_by_specs(test_requirements)
    print(f"  Найдено: {len(results)} моделей")
    for m in results[:5]:
        print(f"  - {m.model_name} ({m.category})")

    # Все модели для ручной проверки
    all_models = await get_all_models()
    print(f"\\nВсего моделей в БД: {len(all_models)}")

    # Проверка наличия ключей
    key_stats: dict[str, int] = {}
    for m in all_models:
        specs = m.specifications or {}
        for k in specs:
            key_stats[k] = key_stats.get(k, 0) + 1

    print(f"Уникальных ключей в specs: {len(key_stats)}")
    print("\\nТоп-15 ключей по частоте:")
    for k, v in sorted(key_stats.items(), key=lambda x: -x[1])[:15]:
        print(f"  {k}: {v} моделей")

    await engine.dispose()
    print("\\n✓ Тест сопоставления завершён")


if __name__ == "__main__":
    asyncio.run(test_matcher())
''',
    },
    "import": {
        "filename": "import_seting.py",
        "description": "Проверка состояния импорта CSV данных",
        "content": '''\
"""Проверка состояния импорта CSV данных (_seting)."""

import asyncio
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import async_session_maker, engine
from database.crud import get_all_models
from sqlalchemy import text

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


async def check_import():
    """Проверить состояние импорта и качество данных."""
    print("=" * 50)
    print("IMPORT SETING — Проверка импорта данных")
    print("=" * 50)

    # CSV файлы
    csv_dir = os.path.join(DATA_DIR, "csv")
    csv_files = [f for f in os.listdir(csv_dir) if f.endswith(".csv")] if os.path.isdir(csv_dir) else []
    print(f"CSV файлов в data/csv/: {len(csv_files)}")

    # normalization_map
    norm_path = os.path.join(DATA_DIR, "normalization_map.json")
    if os.path.exists(norm_path):
        with open(norm_path, "r", encoding="utf-8") as f:
            norm = json.load(f)
        keys = norm.get("canonical_keys", {})
        print(f"Канонических ключей в normalization_map: {len(keys)}")
    else:
        print("normalization_map.json НЕ НАЙДЕН!")

    all_models = await get_all_models()
    print(f"\\nМоделей в БД: {len(all_models)}")

    # По файлам-источникам
    by_file: dict[str, int] = {}
    empty_specs = 0
    for m in all_models:
        by_file[m.source_file] = by_file.get(m.source_file, 0) + 1
        if not m.specifications:
            empty_specs += 1

    print(f"Файлов-источников: {len(by_file)}")
    print(f"Моделей без характеристик: {empty_specs}")

    print("\\nМоделей по файлам:")
    for f, cnt in sorted(by_file.items()):
        print(f"  {f}: {cnt}")

    # Модели без model_name
    async with async_session_maker() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM models WHERE model_name IS NULL OR model_name = \'\'")
        )
        no_name = result.scalar()
        print(f"\\nМоделей без имени: {no_name}")

    await engine.dispose()
    print("\\n✓ Проверка импорта завершена")


if __name__ == "__main__":
    asyncio.run(check_import())
''',
    },
}


def list_templates():
    """Показать доступные шаблоны."""
    print("Доступные шаблоны _seting файлов:\n")
    for key, tmpl in TEMPLATES.items():
        status = "✓ существует" if os.path.exists(os.path.join(SCRIPTS_DIR, tmpl["filename"])) else "  не создан"
        print(f"  [{status}] {key:10s} → scripts/{tmpl['filename']}")
        print(f"             {tmpl['description']}\n")


def create_seting(name: str) -> bool:
    """Создать файл _seting по имени шаблона."""
    if name not in TEMPLATES:
        print(f"Неизвестный шаблон: {name}")
        print(f"Доступные: {', '.join(TEMPLATES.keys())}")
        return False

    tmpl = TEMPLATES[name]
    filepath = os.path.join(SCRIPTS_DIR, tmpl["filename"])

    if os.path.exists(filepath):
        print(f"  Файл уже существует: scripts/{tmpl['filename']}")
        return False

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(tmpl["content"])

    print(f"  ✓ Создан: scripts/{tmpl['filename']} — {tmpl['description']}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Создание файлов настроек разработки (*_seting.py)"
    )
    parser.add_argument(
        "templates",
        nargs="*",
        help="Имена шаблонов для создания (db, openai, matcher, import)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="Показать доступные шаблоны",
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Создать все файлы _seting",
    )

    args = parser.parse_args()

    if args.list or (not args.templates and not args.all):
        list_templates()
        return

    templates_to_create = list(TEMPLATES.keys()) if args.all else args.templates

    created = 0
    for name in templates_to_create:
        if create_seting(name):
            created += 1

    print(f"\nСоздано файлов: {created}")


if __name__ == "__main__":
    main()
