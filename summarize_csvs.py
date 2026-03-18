#!/usr/bin/env python3
import csv
import re
from pathlib import Path
from collections import Counter, deque

def human_bytes(n):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"

def to_bool_token(v):
    v = v.strip().lower()
    if v in {"true", "false", "yes", "no", "0", "1"}:
        return v
    return None

def to_number(v):
    try:
        if v.strip() == "":
            return None
        return float(v)
    except Exception:
        return None

DATE_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^\d{4}/\d{2}/\d{2}$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$"),
    re.compile(r"^\d{4}/\d{2}/\d{2}[ T]\d{2}:\d{2}(:\d{2})?$"),
]

def looks_like_date(v):
    v = v.strip()
    if not v:
        return False
    for p in DATE_PATTERNS:
        if p.match(v):
            return True
    return False

def title_from_header(name):
    return " ".join([w.capitalize() for w in name.replace("-", "_").split("_")])

MEANING_MAP = [
    (re.compile(r"^symbol$", re.I), "Identifier for the traded instrument", "identity/listing"),
    (re.compile(r"^(isin|cusip|figi|composite_figi|shareclass_figi)$", re.I), "Standard security identifier", "identity/listing"),
    (re.compile(r"^name$", re.I), "Full name of the traded instrument", "identity"),
    (re.compile(r"^exchange$", re.I), "Listing exchange", "listing/market"),
    (re.compile(r"^market$", re.I), "Market or trading venue", "listing/market"),
    (re.compile(r"currency$", re.I), "Denomination or trading currency", "trading/settlement"),
    (re.compile(r"^(sector|industry_group|industry)$", re.I), "Industry classification", "taxonomy"),
    (re.compile(r"^(category_group|category|family)$", re.I), "Product classification", "taxonomy"),
    (re.compile(r"^(country|state|city|zipcode)$", re.I), "Geographic location or domicile", "domicile/location"),
    (re.compile(r"^market_cap$", re.I), "Size of the issuer by market capitalization", "fundamentals"),
    (re.compile(r"^(summary|website)$", re.I), "Descriptive metadata", "documentation"),
    (re.compile(r"^cryptocurrency$", re.I), "Underlying crypto asset", "instrument details"),
    (re.compile(r"^base_currency$", re.I), "Base currency in a currency pair", "trading/settlement"),
    (re.compile(r"^quote_currency$", re.I), "Quote currency in a currency pair", "trading/settlement"),
]

def detect_delimiter(sample_text):
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=[",", ";"])
        if dialect.delimiter in [",", ";"]:
            return dialect.delimiter
    except Exception:
        pass
    # Fallback: count separators in sample text
    comma = sample_text.count(",")
    semicolon = sample_text.count(";")
    return ";" if semicolon > comma else ","

def summarize_file(path: Path, unique_cap=5000, top_k=20, cat_ratio=0.05, cat_count=50):
    size_bytes = path.stat().st_size
    # Read sample for delimiter detection
    sample_lines = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for _ in range(50):
            line = f.readline()
            if not line:
                break
            if line.strip():
                sample_lines.append(line)
    sample_text = "".join(sample_lines)
    delimiter = detect_delimiter(sample_text)

    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            return {
                "file": path.name,
                "size": size_bytes,
                "delimiter": delimiter,
                "rows": 0,
                "columns": [],
                "col_stats": [],
            }

        col_count = len(header)
        non_empty = [0] * col_count
        examples = [deque(maxlen=3) for _ in range(col_count)]

        unique_sets = [set() for _ in range(col_count)]
        unique_capped = [False] * col_count

        bool_possible = [True] * col_count
        num_possible = [True] * col_count
        int_possible = [True] * col_count
        date_possible = [True] * col_count
        num_min = [None] * col_count
        num_max = [None] * col_count
        num_count = [0] * col_count

        counters = [Counter() for _ in range(col_count)]

        rows = 0
        for row in reader:
            rows += 1
            # Normalize row length
            if len(row) < col_count:
                row = row + [""] * (col_count - len(row))
            elif len(row) > col_count:
                row = row[:col_count]

            for i, val in enumerate(row):
                v = val.strip()
                if v != "":
                    non_empty[i] += 1
                    if v not in examples[i]:
                        examples[i].append(v)
                    # unique tracking
                    if not unique_capped[i]:
                        unique_sets[i].add(v)
                        if len(unique_sets[i]) > unique_cap:
                            unique_sets[i].clear()
                            unique_capped[i] = True

                    # categorical counts (kept regardless, but only useful if categorical)
                    counters[i][v] += 1

                    # boolean detection
                    if bool_possible[i] and to_bool_token(v) is None:
                        bool_possible[i] = False

                    # numeric detection
                    if num_possible[i]:
                        num = to_number(v)
                        if num is None:
                            num_possible[i] = False
                            int_possible[i] = False
                        else:
                            num_count[i] += 1
                            if num_min[i] is None or num < num_min[i]:
                                num_min[i] = num
                            if num_max[i] is None or num > num_max[i]:
                                num_max[i] = num
                            if int_possible[i] and ("." in v or "e" in v.lower()):
                                int_possible[i] = False

                    # date detection
                    if date_possible[i] and not looks_like_date(v):
                        date_possible[i] = False

        col_stats = []
        for i, name in enumerate(header):
            missing = rows - non_empty[i]
            missing_pct = (missing / rows * 100) if rows else 0
            # determine type
            if non_empty[i] == 0:
                inferred_type = "empty"
            elif bool_possible[i]:
                inferred_type = "boolean"
            elif num_possible[i]:
                inferred_type = "integer" if int_possible[i] else "float"
            elif date_possible[i]:
                inferred_type = "date/time"
            else:
                # decide categorical vs text
                if unique_capped[i]:
                    is_categorical = False
                else:
                    uniq = len(unique_sets[i])
                    ratio = (uniq / non_empty[i]) if non_empty[i] else 0
                    is_categorical = (ratio <= cat_ratio) or (uniq <= cat_count)
                inferred_type = "categorical" if is_categorical else "text"

            numeric_range = None
            if inferred_type in {"integer", "float"} and num_count[i] > 0:
                numeric_range = (num_min[i], num_max[i], num_count[i])

            unique_count = None
            if unique_capped[i]:
                unique_count = f"> {unique_cap}"
            else:
                unique_count = str(len(unique_sets[i]))

            top_categories = []
            if inferred_type == "categorical":
                total = non_empty[i] if non_empty[i] else 0
                for val, cnt in counters[i].most_common(top_k):
                    pct = (cnt / total * 100) if total else 0
                    top_categories.append(f"{val} ({cnt}, {pct:.1f}%)")

            meaning = None
            element = None
            for pattern, m, e in MEANING_MAP:
                if pattern.search(name):
                    meaning = m
                    element = e
                    break
            if meaning is None:
                meaning = title_from_header(name)
                element = "unknown"

            col_stats.append({
                "name": name,
                "non_empty": non_empty[i],
                "missing": missing,
                "missing_pct": missing_pct,
                "examples": list(examples[i]),
                "numeric_range": numeric_range,
                "inferred_type": inferred_type,
                "unique_count": unique_count,
                "top_categories": top_categories,
                "meaning": meaning,
                "element": element,
            })

    return {
        "file": path.name,
        "size": size_bytes,
        "delimiter": delimiter,
        "rows": rows,
        "columns": header,
        "col_stats": col_stats,
    }

def write_markdown(summaries, out_path: Path):
    lines = []
    lines.append("# CSV Data Summary")
    lines.append("")
    lines.append("Generated by `summarize_csvs.py`.")
    lines.append("")

    for s in summaries:
        lines.append(f"## {s['file']}")
        lines.append("")
        lines.append(f"File size: {human_bytes(s['size'])}")
        lines.append(f"Delimiter: `{s['delimiter']}`")
        lines.append(f"Rows (excluding header): {s['rows']}")
        lines.append(f"Columns: {len(s['columns'])}")
        lines.append("")
        lines.append("| Column | Type | Missing % | Unique | Top Categories | Numeric Range | Potential Meaning | Element | Examples |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for c in s["col_stats"]:
            top_cats = "; ".join(c["top_categories"]) if c["top_categories"] else ""
            if c["numeric_range"]:
                nmin, nmax, ncount = c["numeric_range"]
                rng = f"{nmin} .. {nmax} ({ncount} numeric)"
            else:
                rng = ""
            uniq = c["unique_count"] if c["unique_count"] is not None else ""
            ex = ""
            if c["inferred_type"] != "categorical":
                ex = ", ".join(c["examples"]) if c["examples"] else ""
            lines.append(
                f"| {c['name']} | {c['inferred_type']} | {c['missing_pct']:.2f}% | {uniq} | {top_cats} | {rng} | {c['meaning']} | {c['element']} | {ex} |"
            )
        lines.append("")
        lines.append("Column insights:")
        for c in s["col_stats"]:
            missing = f"{c['missing_pct']:.2f}%"
            examples = ""
            if c["inferred_type"] != "categorical":
                examples = ", ".join(c["examples"]) if c["examples"] else "n/a"
            cats = ""
            if c["inferred_type"] == "categorical":
                cats = "; ".join(c["top_categories"]) if c["top_categories"] else "n/a"
            narrative = (
                f"- `{c['name']}` is a `{c['inferred_type']}` column that describes "
                f"\"{c['meaning']}\" (element: `{c['element']}`). Missing: {missing}."
            )
            if c["inferred_type"] == "categorical":
                narrative += f" Categories: {cats}."
            else:
                narrative += f" Examples: {examples}."
            lines.append(narrative)
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    cwd = Path(__file__).resolve().parent
    csv_files = sorted(cwd.glob("*.csv"))
    summaries = [summarize_file(p) for p in csv_files]
    out_path = cwd / "DATA_SUMMARY.md"
    write_markdown(summaries, out_path)
    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()
