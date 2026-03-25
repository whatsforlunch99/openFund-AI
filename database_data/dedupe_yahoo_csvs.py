#!/usr/bin/env python3
import csv
import os
from collections import OrderedDict

BASE_DIR = "/Users/jiani/Desktop/finance_database/yahoo_data/csv_files"

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


def repair_dict_reader_row(row, headers):
    """
    csv.DictReader stores overflow columns under key None when a data row has
    more fields than the header (e.g. unquoted comma in matched_name:
    ``Amazon.com, Inc.``). Re-stitch into declared columns so DictWriter works.
    """
    row = dict(row)
    extra = row.pop(None, None)
    if extra is not None and not isinstance(extra, list):
        extra = [extra]
    if extra:
        joined_extra = ",".join(str(x) for x in extra)
        if "matched_name" in headers and "source_url" in headers:
            su = (row.get("source_url") or "").strip()
            mn = (row.get("matched_name") or "").strip()
            # Typical split: name fragment in matched_name, ", Inc." in source_url, URL in extra
            if su and not su.lower().startswith("http"):
                row["matched_name"] = f"{mn}, {su}".strip().strip(",")
            row["source_url"] = joined_extra
        elif headers:
            lh = headers[-1]
            prev = row.get(lh, "")
            row[lh] = f"{prev},{joined_extra}" if str(prev).strip() else joined_extra
    # Only keys declared in header (never pass None key to DictWriter)
    return {h: row.get(h, "") for h in headers}


def dedupe_file(path, filename):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        headers = [h for h in (reader.fieldnames or []) if h is not None]
        rows = [repair_dict_reader_row(r, headers) for r in reader]

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
        writer = csv.DictWriter(f, fieldnames=headers, quoting=csv.QUOTE_MINIMAL)
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
