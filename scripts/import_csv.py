"""
Import all CSV files from data/csv/ into the models table with normalization.

Prerequisites:
  1. Database must be running and migrated (alembic upgrade head)
  2. data/normalization_map.json must exist

Usage:
  python scripts/import_csv.py
"""

import asyncio
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

import pandas as pd

# Resolve project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from utils.logger import logger

CSV_DIR = os.path.join(PROJECT_ROOT, "data", "csv")
NORMALIZATION_MAP_PATH = os.path.join(PROJECT_ROOT, "data", "normalization_map.json")

# ──────────────────────────── Category mapping ─────────────────

CATEGORY_MAPPING = {
    "MES": "Коммутаторы",
    "ESR": "Маршрутизаторы",
    "ISS": "Коммутаторы",
    "Fastpath": "Коммутаторы",
    "ME": "Коммутаторы",
    "ROS4": "Коммутаторы",
    "ROS6": "Коммутаторы",
}

# Column names that typically hold the model name
MODEL_NAME_CANDIDATES = [
    "model_name",
    "Model",
    "Модель",
    "Наименование",
    "Наименование модели",
    "Название модели",
    "Unnamed: 0",
]

# Columns to skip when building specifications
SKIP_COLUMNS = {"model_name", "category", "Категория", "Тип коммутатора", "Тип устройства"}


# ──────────────────────────── Normalization helpers ─────────────


def load_normalization_map() -> Dict:
    if not os.path.exists(NORMALIZATION_MAP_PATH):
        logger.warning(
            f"normalization_map.json not found at {NORMALIZATION_MAP_PATH}. "
            "Import will use raw column names."
        )
        return {"canonical_keys": {}}
    with open(NORMALIZATION_MAP_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_column_name(column: str, normalization_map: Dict) -> str:
    """Map a CSV column name to its canonical key."""
    for canonical_key, synonyms in normalization_map.get("canonical_keys", {}).items():
        if column in synonyms:
            return canonical_key
    return column


# Numeric specification keys
NUMERIC_KEYS = {
    "ports_1g_sfp", "ports_10g_sfp", "ports_1000base_t",
    "ports_100base_t", "ports_25g_sfp", "ports_40g_qsfp",
    "ports_100g_qsfp", "ports_combo", "ports_poe",
    "ram_gb", "flash_mb", "packet_buffer_mb",
    "mac_table_size", "vlan_count", "max_routes",
    "mtbf_hours", "weight_kg",
}

# Boolean specification keys
BOOLEAN_KEYS = {
    "ipv6_support", "poe_support", "vlan_support",
    "snmp_support", "ssh_support", "redundancy_support",
    "stacking_support", "mpls_support", "bgp_support",
    "ospf_support", "igmp_support", "qos_support",
    "acl_support", "sflow_support", "netflow_support",
}

COMPLEX_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r'\bпо\b', r'\bх\b', r'\bx\b', r'[+\-*/]',
]]


def clean_spec_value(key: str, value: Any) -> Optional[Any]:
    """Clean and normalize a specification value."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    value_str = str(value).strip()
    if value_str in ("", "-", "—", "н/д", "N/A", "n/a"):
        return None

    # Numeric keys
    if key in NUMERIC_KEYS:
        # Detect complex expressions
        if any(p.search(value_str) for p in COMPLEX_PATTERNS):
            logger.warning(f"Complex value for {key}: {value_str} — skipping")
            return None
        digits = re.findall(r'\d+\.?\d*', value_str)
        if digits:
            return int(float(digits[0]))
        return None

    # Power (watts)
    if key == "power_watt":
        match = re.search(r'(\d+\.?\d*)\s*(?:Вт|W|вт|w)', value_str, re.IGNORECASE)
        if match:
            return int(float(match.group(1)))
        digits = re.findall(r'\d+\.?\d*', value_str)
        if digits:
            return int(float(digits[0]))
        return None

    # Boolean keys
    if key in BOOLEAN_KEYS:
        val_lower = value_str.lower()
        positive = ("да", "yes", "+", "true", "поддерживается", "есть", "имеется")
        negative = ("нет", "no", "-", "false", "не поддерживается", "отсутствует")
        if any(p in val_lower for p in positive):
            return True
        if any(n in val_lower for n in negative):
            return False
        return None

    # Text — trim whitespace
    return value_str


# ──────────────────────────── Source / category extraction ──────


def extract_source_from_filename(filename: str) -> str:
    """Extract a short source identifier from the CSV filename."""
    name = os.path.splitext(filename)[0]
    # Remove common suffixes
    for suffix in ("_cleaned", "_Лист1", "_Лист2"):
        name = name.replace(suffix, "")
    return name


def extract_category(source_file: str, row_data: Dict) -> Optional[str]:
    """Determine equipment category from row data or filename."""
    # Check if the row has a category column
    for col in ("Тип коммутатора", "Тип устройства", "Категория"):
        val = row_data.get(col)
        if val and str(val).strip():
            return str(val).strip()
    # Fallback to filename-based mapping
    for prefix, cat in CATEGORY_MAPPING.items():
        if prefix.lower() in source_file.lower():
            return cat
    return None


def detect_model_name_column(columns: List[str]) -> Optional[str]:
    """Find which column holds the model name."""
    cols_lower = {c.lower().strip(): c for c in columns}
    for candidate in MODEL_NAME_CANDIDATES:
        if candidate.lower() in cols_lower:
            return cols_lower[candidate.lower()]
    # Heuristic: first column
    return columns[0] if columns else None


# ──────────────────────────── Import logic ─────────────────────


def parse_csv_file(
    filepath: str,
    filename: str,
    normalization_map: Dict,
) -> List[Dict[str, Any]]:
    """Parse a single CSV file and return a list of model dicts ready for DB insert."""
    try:
        df = pd.read_csv(filepath, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(filepath, encoding="cp1251")

    if df.empty:
        logger.warning(f"Empty CSV: {filename}")
        return []

    # Strip column whitespace
    df.columns = [str(c).strip() for c in df.columns]

    model_col = detect_model_name_column(list(df.columns))
    if model_col is None:
        logger.error(f"Cannot detect model_name column in {filename}")
        return []

    source_file = extract_source_from_filename(filename)
    models: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        model_name = row.get(model_col)
        if model_name is None or (isinstance(model_name, float) and pd.isna(model_name)):
            continue
        model_name = str(model_name).strip()
        if not model_name:
            continue

        specifications: Dict[str, Any] = {}
        raw_specifications: Dict[str, str] = {}
        row_dict = row.to_dict()

        for column, value in row_dict.items():
            if column == model_col or column in SKIP_COLUMNS:
                continue
            # Save raw value
            if value is not None and not (isinstance(value, float) and pd.isna(value)):
                raw_specifications[column] = str(value)

            canonical_key = normalize_column_name(column, normalization_map)
            clean_value = clean_spec_value(canonical_key, value)
            if clean_value is not None:
                specifications[canonical_key] = clean_value

        category = extract_category(source_file, row_dict)

        models.append({
            "model_name": model_name,
            "category": category,
            "source_file": source_file,
            "specifications": specifications,
            "raw_specifications": raw_specifications,
        })

    return models


async def import_all_csv():
    """Import all CSV files from data/csv/ into the database."""
    from database.crud import bulk_create_models, delete_all_models, get_models_count

    normalization_map = load_normalization_map()
    logger.info(
        f"Loaded normalization map with "
        f"{len(normalization_map.get('canonical_keys', {}))} canonical keys"
    )

    csv_files = sorted(
        f for f in os.listdir(CSV_DIR) if f.lower().endswith(".csv")
    )
    if not csv_files:
        logger.error(f"No CSV files found in {CSV_DIR}")
        return

    # Clear existing models
    deleted = await delete_all_models()
    if deleted:
        logger.info(f"Cleared {deleted} existing models")

    total_imported = 0
    for i, filename in enumerate(csv_files, 1):
        filepath = os.path.join(CSV_DIR, filename)
        try:
            models_data = parse_csv_file(filepath, filename, normalization_map)
            if models_data:
                count = await bulk_create_models(models_data)
                total_imported += count
                logger.info(f"[{i}/{len(csv_files)}] {filename}: {count} models imported")
            else:
                logger.warning(f"[{i}/{len(csv_files)}] {filename}: no models found")
        except Exception as e:
            logger.error(f"[{i}/{len(csv_files)}] {filename}: ERROR — {e}")

    total_in_db = await get_models_count()
    logger.info(
        f"\nImport complete: {total_imported} models imported from "
        f"{len(csv_files)} files. Total in DB: {total_in_db}"
    )


def main():
    print("Starting CSV import...")
    asyncio.run(import_all_csv())


if __name__ == "__main__":
    main()
