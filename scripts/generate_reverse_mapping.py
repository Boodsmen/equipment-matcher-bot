"""
Скрипт для генерации reverse mapping из normalization_map.json.

Reverse mapping: canonical_key → самое читаемое название.
Используется для отображения характеристик в Excel отчете.

Критерии выбора "лучшего" названия:
1. Исключаем технические суффиксы (.1, .2, "(характеристика не является обязательной...)")
2. Выбираем самое короткое название
3. Предпочитаем названия без скобок
"""

import json
import re
from pathlib import Path


def clean_column_name(name: str) -> str:
    """Очистка названия колонки от технических суффиксов."""
    # Убрать суффикс .1, .2 и т.д.
    name = re.sub(r'\.\d+$', '', name)
    # Убрать суффикс "(характеристика не является обязательной...)"
    name = re.sub(r'\(характеристика не является обязательной[^)]*\)$', '', name)
    return name.strip()


def select_best_name(synonyms: list[str]) -> str:
    """Выбор лучшего (самого читаемого) названия из списка синонимов."""
    if not synonyms:
        return ""

    # Очищаем все названия от технических суффиксов
    cleaned = [clean_column_name(name) for name in synonyms]
    # Удаляем дубликаты, сохраняя порядок
    unique_names = []
    seen = set()
    for name in cleaned:
        if name and name not in seen:
            unique_names.append(name)
            seen.add(name)

    if not unique_names:
        return synonyms[0]  # fallback

    # Критерии выбора:
    # 1. Без скобок (приоритет)
    # 2. Самое короткое
    names_without_parens = [name for name in unique_names if '(' not in name]
    if names_without_parens:
        return min(names_without_parens, key=len)

    return min(unique_names, key=len)


def generate_reverse_mapping(
    normalization_map_path: Path,
    output_path: Path
) -> None:
    """Генерация reverse mapping из normalization_map.json."""

    # Загрузка normalization_map.json
    with open(normalization_map_path, 'r', encoding='utf-8') as f:
        normalization_data = json.load(f)

    canonical_keys = normalization_data.get('canonical_keys', {})

    # Создание reverse mapping
    reverse_mapping = {}
    for canonical_key, synonyms in canonical_keys.items():
        best_name = select_best_name(synonyms)
        reverse_mapping[canonical_key] = best_name

    # Сохранение в JSON
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(reverse_mapping, f, ensure_ascii=False, indent=2)

    print(f"[OK] Reverse mapping created successfully!")
    print(f"     Input: {normalization_map_path}")
    print(f"     Output: {output_path}")
    print(f"     Total canonical keys: {len(reverse_mapping)}")

    # Показать примеры
    print("\nExamples:")
    for i, (canonical_key, readable_name) in enumerate(list(reverse_mapping.items())[:5], 1):
        print(f"   {i}. {canonical_key} -> {readable_name}")


if __name__ == '__main__':
    # Пути к файлам
    project_root = Path(__file__).parent.parent
    normalization_map_path = project_root / 'data' / 'normalization_map.json'
    output_path = project_root / 'data' / 'reverse_normalization_map.json'

    # Проверка наличия входного файла
    if not normalization_map_path.exists():
        print(f"[ERROR] {normalization_map_path} not found")
        exit(1)

    # Генерация reverse mapping
    generate_reverse_mapping(normalization_map_path, output_path)
