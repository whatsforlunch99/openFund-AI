#!/usr/bin/env python3
import csv
import os
from collections import OrderedDict

BASE_DIR = "/Users/jiani/Desktop/finance_database/yahoo_data"

KEY_RULES = {
    "index_levels.csv": ["index_id", "date", "source"],
    "yahoo_timeseries.csv": ["index_id", "date", "source"],
    "yahoo_indicators.csv": ["index_id", "yahoo_symbol", "indicator_group", "indicator_name", "as_of_date"],
    "index_symbol_map.csv": ["index_id", "yahoo_symbol"],
}


def make_key(row, headers, key_fields=None):
    if key_fields:
        return tuple(row.get(k, "") for k in key_fields)
    return tuple(row.get(h, "") for h in headers)


def is_indicator_empty(val):
    if val is None:
        return True
    s = str(val).strip()
    if s == "":
        return True
    if s.lower() == "{}":
        return True
    return False


def dedupe_file(path, filename):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)

    before = len(rows)
    dropped_empty = 0
    seen = OrderedDict()

    key_fields = KEY_RULES.get(filename)
    for row in rows:
        if filename == "yahoo_indicators.csv" and is_indicator_empty(row.get("indicator_value", "")):
            dropped_empty += 1
            continue
        key = make_key(row, headers, key_fields)
        if key in seen:
            continue
        seen[key] = row

    out_rows = list(seen.values())
    after = len(out_rows)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in out_rows:
            writer.writerow(row)

    return before, after, dropped_empty


def main():
    csv_files = sorted([f for f in os.listdir(BASE_DIR) if f.endswith(".csv")])
    if not csv_files:
        print("No CSV files found in", BASE_DIR)
        return

    total_before = total_after = total_dropped_empty = 0
    for filename in csv_files:
        path = os.path.join(BASE_DIR, filename)
        before, after, dropped_empty = dedupe_file(path, filename)
        total_before += before
        total_after += after
        total_dropped_empty += dropped_empty
        print(f"{filename}: {before} -> {after} (dropped empty indicators: {dropped_empty})")

    print("Summary:")
    print(f"- Total rows before: {total_before}")
    print(f"- Total rows after:  {total_after}")
    print(f"- Total empty indicators dropped: {total_dropped_empty}")


if __name__ == "__main__":
    main()
