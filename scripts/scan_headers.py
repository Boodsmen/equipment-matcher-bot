"""
Scan all CSV files in data/csv/ and produce a headers frequency report.

Output: data/headers_report.json
"""

import json
import os
import sys
from collections import defaultdict

import pandas as pd

# Resolve project root so imports work when run as a script
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

CSV_DIR = os.path.join(PROJECT_ROOT, "data", "csv")
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "data", "headers_report.json")


def scan_headers() -> dict:
    headers_info: dict = defaultdict(lambda: {"count": 0, "files": []})
    total_files = 0
    errors = []

    csv_files = [f for f in os.listdir(CSV_DIR) if f.lower().endswith(".csv")]
    csv_files.sort()

    for filename in csv_files:
        filepath = os.path.join(CSV_DIR, filename)
        try:
            df = pd.read_csv(filepath, nrows=0, encoding="utf-8")
        except UnicodeDecodeError:
            try:
                df = pd.read_csv(filepath, nrows=0, encoding="cp1251")
            except Exception as e:
                errors.append({"file": filename, "error": str(e)})
                print(f"  [ERROR] {filename}: {e}")
                continue
        except Exception as e:
            errors.append({"file": filename, "error": str(e)})
            print(f"  [ERROR] {filename}: {e}")
            continue

        total_files += 1
        short_name = os.path.splitext(filename)[0]
        columns = [str(c).strip() for c in df.columns]

        for col in columns:
            headers_info[col]["count"] += 1
            headers_info[col]["files"].append(short_name)

        print(f"  [{total_files:>3}] {filename}: {len(columns)} columns")

    # Sort by frequency descending
    sorted_headers = dict(
        sorted(headers_info.items(), key=lambda x: x[1]["count"], reverse=True)
    )

    report = {
        "headers": sorted_headers,
        "total_files": total_files,
        "total_unique_headers": len(sorted_headers),
        "errors": errors,
    }
    return report


def main():
    print(f"Scanning CSV files in {CSV_DIR} ...")
    if not os.path.isdir(CSV_DIR):
        print(f"Directory not found: {CSV_DIR}")
        sys.exit(1)

    report = scan_headers()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Scanned {report['total_files']} files, "
          f"found {report['total_unique_headers']} unique headers.")
    if report["errors"]:
        print(f"Errors: {len(report['errors'])} files could not be read.")
    print(f"Report saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
