"""
Direct table-based requirements parser for structured tender documents.

This parser handles documents with structured tables (like Table 2 format):
| Наименование товара | № п/п | Наименование характеристики | Значение | Единица |

Each row becomes a separate requirement, avoiding AI aggregation issues.
"""

import json
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from utils.logger import logger


# ═══════════════════════════════════════════════════════════════════════════
# Normalization Map Loader
# ═══════════════════════════════════════════════════════════════════════════


def _load_normalization_map() -> Dict[str, str]:
    """
    Load normalization map and create reverse lookup: variant -> canonical_key.

    Returns:
        Dict mapping lowercase characteristic variants to canonical keys.
    """
    norm_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "normalization_map.json"
    )

    try:
        with open(norm_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        reverse_map = {}
        for canonical_key, variants in data.get("canonical_keys", {}).items():
            for variant in variants:
                clean_variant = variant.lower().strip()
                reverse_map[clean_variant] = canonical_key

        logger.info(f"Loaded normalization map: {len(reverse_map)} variants -> {len(data.get('canonical_keys', {}))} canonical keys")
        return reverse_map

    except Exception as e:
        logger.error(f"Failed to load normalization_map.json: {e}")
        return {}


_NORMALIZATION_MAP = _load_normalization_map()


def normalize_characteristic_name(name: str) -> Optional[str]:
    """
    Normalize a characteristic name to its canonical key.

    Args:
        name: Raw characteristic name from table.

    Returns:
        Canonical key or None if not found.
    """
    clean_name = name.lower().strip()
    return _NORMALIZATION_MAP.get(clean_name)


# ═══════════════════════════════════════════════════════════════════════════
# Value Parsing
# ═══════════════════════════════════════════════════════════════════════════


def parse_value(value_str: str, unit: str = "") -> Any:
    """
    Parse a characteristic value from table cell.

    Handles:
    - Comparison operators: ≥, ≤, >, <, =
    - Boolean values: Да/Нет, Yes/No
    - Numeric values: 6000, 24, 1.5
    - Text values: "Управляемый", "AC", etc.

    Args:
        value_str: Value from "Значение характеристики" column.
        unit: Unit from "Единица измерения" column (optional).

    Returns:
        Parsed value (int, float, bool, or str).
    """
    if not value_str:
        return None

    value_str = value_str.strip()

    # Boolean values
    if value_str.lower() in ["да", "yes", "истина", "true"]:
        return True
    if value_str.lower() in ["нет", "no", "ложь", "false"]:
        return False

    # Remove comparison operators (we treat "≥ 6000" as "6000")
    # The matcher will handle >= logic based on characteristic type
    value_clean = re.sub(r'^[≥≤><≠=]\s*', '', value_str)

    # Try to extract number
    # Handle ranges like "> 2 и ≤ 4" -> take the stricter value (4)
    numbers = re.findall(r'[\d,]+\.?\d*', value_clean)
    if numbers:
        # Take the last (usually stricter) number
        num_str = numbers[-1].replace(',', '')
        try:
            # Check if it's an integer
            if '.' not in num_str:
                return int(num_str)
            else:
                return float(num_str)
        except ValueError:
            pass

    # Return as string if not a number or bool
    return value_str


# ═══════════════════════════════════════════════════════════════════════════
# Table Detection
# ═══════════════════════════════════════════════════════════════════════════


def _is_characteristics_table(table) -> bool:
    """
    Check if a table has the expected characteristics format.

    Expected headers (flexible matching):
    - Column with "характеристик" or "наименование"
    - Column with "значение" or "value"

    Args:
        table: python-docx Table object.

    Returns:
        True if table matches characteristics format.
    """
    if not table.rows or len(table.rows) < 2:
        return False

    # Check first row for expected headers
    header_row = table.rows[0]
    headers = [cell.text.lower().strip() for cell in header_row.cells]

    # Must have columns for characteristic name and value
    has_characteristic = any("характеристик" in h or "наименование" in h for h in headers)
    has_value = any("значение" in h or "value" in h for h in headers)

    return has_characteristic and has_value


# ═══════════════════════════════════════════════════════════════════════════
# Table Parsing
# ═══════════════════════════════════════════════════════════════════════════


def _parse_table_row(row) -> Optional[Dict[str, Any]]:
    """
    Parse a single table row into a requirement dict.

    Expected format:
    | Наименование товара | № п/п | Наименование характеристики | Значение | Единица |

    Args:
        row: python-docx Row object.

    Returns:
        Dict with keys: item_name, item_number, characteristic_name,
        canonical_key, value, unit, parsed_value
        Returns None if row is header or invalid.
    """
    cells = [cell.text.strip() for cell in row.cells]

    if len(cells) < 4:
        return None

    item_name = cells[0] if len(cells) > 0 else ""
    item_number = cells[1] if len(cells) > 1 else ""
    char_name = cells[2] if len(cells) > 2 else ""
    value = cells[3] if len(cells) > 3 else ""
    unit = cells[4] if len(cells) > 4 else ""

    # Skip header rows
    if not char_name or "характеристик" in char_name.lower():
        return None

    # Normalize characteristic name
    canonical_key = normalize_characteristic_name(char_name)
    if not canonical_key:
        logger.debug(f"Could not normalize characteristic: '{char_name}'")
        # Keep raw name for now, might still be useful
        canonical_key = char_name.lower().replace(" ", "_")

    # Parse value
    parsed_value = parse_value(value, unit)

    return {
        "item_name": item_name,
        "item_number": item_number,
        "characteristic_name": char_name,
        "canonical_key": canonical_key,
        "value": value,
        "unit": unit,
        "parsed_value": parsed_value,
    }


def _group_requirements_by_item(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group parsed rows by equipment item.

    Uses item_number prefix (e.g., "1.1", "1.2" -> item 1, "2.1", "2.2" -> item 2).

    Args:
        rows: List of parsed row dicts.

    Returns:
        Dict mapping item_number_prefix -> list of requirements.
    """
    groups = defaultdict(list)

    for row in rows:
        item_num = row["item_number"]

        # Extract prefix (e.g., "1.1" -> "1", "2.3" -> "2")
        match = re.match(r'^(\d+)', item_num)
        if match:
            prefix = match.group(1)
        else:
            prefix = "default"

        groups[prefix].append(row)

    return groups


def _build_item_dict(
    item_prefix: str,
    requirements: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Build a single item dict from grouped requirements.

    Args:
        item_prefix: Item number prefix (e.g., "1", "2").
        requirements: List of requirement dicts for this item.

    Returns:
        Dict compatible with OpenAI format:
        {
            "item_name": "Коммутатор (тип 1)",
            "quantity": null,
            "model_name": null,
            "category": "Коммутаторы",
            "required_specs": {...}
        }
    """
    if not requirements:
        return None

    # Use first requirement's item_name
    item_name = requirements[0]["item_name"]

    # Try to infer category from item_name
    category = None
    item_lower = item_name.lower()
    if "коммутатор" in item_lower or "switch" in item_lower:
        category = "Коммутаторы"
    elif "маршрутизатор" in item_lower or "router" in item_lower:
        category = "Маршрутизаторы"

    # Build required_specs dict
    required_specs = {}
    for req in requirements:
        canonical_key = req["canonical_key"]
        parsed_value = req["parsed_value"]

        if parsed_value is not None:
            required_specs[canonical_key] = parsed_value

    return {
        "item_name": f"{item_name} (позиция {item_prefix})",
        "quantity": None,
        "model_name": None,
        "category": category,
        "required_specs": required_specs,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Main Parser
# ═══════════════════════════════════════════════════════════════════════════


def parse_requirements_from_tables(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Parse requirements from structured tables in a DOCX file.

    This is the main entry point. Returns None if no suitable tables found.

    Args:
        file_path: Path to DOCX file.

    Returns:
        Dict with 'items' list (compatible with OpenAI format), or None if parsing failed.
    """
    try:
        doc = Document(file_path)
    except Exception as e:
        logger.error(f"Failed to open DOCX: {e}")
        return None

    logger.info(f"Analyzing {len(doc.tables)} tables in document")

    # Find characteristics table
    characteristics_table = None
    for idx, table in enumerate(doc.tables):
        if _is_characteristics_table(table):
            logger.info(f"Found characteristics table at index {idx} ({len(table.rows)} rows)")
            characteristics_table = table
            break

    if not characteristics_table:
        logger.info("No structured characteristics table found")
        return None

    # Parse all rows
    parsed_rows = []
    for row in characteristics_table.rows[1:]:  # Skip header
        parsed = _parse_table_row(row)
        if parsed:
            parsed_rows.append(parsed)

    logger.info(f"Parsed {len(parsed_rows)} requirement rows from table")

    if not parsed_rows:
        return None

    # Group by item
    groups = _group_requirements_by_item(parsed_rows)
    logger.info(f"Grouped into {len(groups)} equipment items")

    # Build items list
    items = []
    for prefix in sorted(groups.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        item_dict = _build_item_dict(prefix, groups[prefix])
        if item_dict:
            items.append(item_dict)

    result = {"items": items}

    logger.info(
        f"Table parser extracted {len(items)} items, "
        f"total specs: {sum(len(item['required_specs']) for item in items)}"
    )

    return result
