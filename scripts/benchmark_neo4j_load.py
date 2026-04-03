#!/usr/bin/env python3
"""Benchmark Neo4j graph load throughput for fresh-all workflows.

Usage examples:
  .venv/bin/python scripts/benchmark_neo4j_load.py --mode online --runs 1
  .venv/bin/python scripts/benchmark_neo4j_load.py --mode offline --runs 1
  .venv/bin/python scripts/benchmark_neo4j_load.py --mode auto --runs 3 --target-seconds 180
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _run_loader(repo_root: Path, mode: str, timeout_s: float | None) -> tuple[int, float, dict[str, Any], str, bool]:
    env = dict(os.environ)
    env["NEO4J_FRESH_IMPORT_MODE"] = mode
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "data_loader.py"),
        "--load-mode",
        "fresh-all",
        "--components",
        "neo4j",
        "--stats-dir",
        str(repo_root / "database" / "stats_data"),
        "--text-dir",
        str(repo_root / "database" / "text_data"),
        "--neo4j-csv-dir",
        str(repo_root / "database" / "graph_data" / "neo4j_export"),
    ]
    t0 = time.time()
    timed_out = False
    try:
        p = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        timed_out = True
        p = subprocess.CompletedProcess(cmd, returncode=124, stdout=e.stdout or "", stderr=e.stderr or "")
    elapsed = time.time() - t0
    payload: dict[str, Any] = {}
    err = ""
    try:
        payload = json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        err = "loader stdout is not valid JSON"
    return p.returncode, elapsed, payload, err or (p.stderr or ""), timed_out


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark Neo4j fresh-all import timing.")
    ap.add_argument("--mode", choices=["auto", "offline", "online"], default="auto")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--target-seconds", type=float, default=180.0)
    ap.add_argument("--timeout-seconds", type=float, default=0.0, help="Per-run timeout; 0 disables timeout.")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    results: list[dict[str, Any]] = []

    for i in range(args.runs):
        timeout_s = args.timeout_seconds if args.timeout_seconds and args.timeout_seconds > 0 else None
        rc, elapsed, payload, err, timed_out = _run_loader(repo_root, args.mode, timeout_s)
        neo4j = ((payload.get("neo4j") or {}).get("neo4j") or {}) if isinstance(payload, dict) else {}
        neo4j_top = (payload.get("neo4j") or {}) if isinstance(payload, dict) else {}
        rel_rows = (((neo4j.get("validation") or {}).get("relationship_checks") or {}).get("graph_relationships") or {}).get("rows")
        rel_loaded = (((neo4j.get("load_result") or {}).get("relationships_loaded")) if isinstance(neo4j.get("load_result"), dict) else None)
        used_offline = bool((neo4j.get("offline_import") or {}).get("ok"))
        rows_for_rate = rel_loaded if isinstance(rel_loaded, int) and rel_loaded > 0 else rel_rows
        rows_per_sec = (rows_for_rate / elapsed) if isinstance(rows_for_rate, int) and elapsed > 0 else None
        results.append(
            {
                "run": i + 1,
                "return_code": rc,
                "elapsed_seconds": round(elapsed, 3),
                "mode": args.mode,
                "used_offline_import": used_offline,
                "relationship_rows_expected": rel_rows,
                "relationship_rows_loaded": rel_loaded,
                "rows_per_second": round(rows_per_sec, 2) if isinstance(rows_per_sec, float) else None,
                "error": (
                    err
                    or str(neo4j_top.get("error") or "")
                    or str((neo4j.get("offline_import") or {}).get("error") or "")
                ) if rc != 0 or err or neo4j_top.get("status") == "error" else "",
                "timed_out": timed_out,
            }
        )

    elapsed_vals = [r["elapsed_seconds"] for r in results if isinstance(r.get("elapsed_seconds"), (int, float))]
    any_fail = any(
        r.get("timed_out")
        or r.get("return_code") not in (0,)
        or bool(r.get("error"))
        for r in results
    )
    median_s = statistics.median(elapsed_vals) if elapsed_vals else None
    p95_s = max(elapsed_vals) if elapsed_vals else None
    summary = {
        "target_seconds": args.target_seconds,
        "pass_median": bool((not any_fail) and median_s is not None and median_s <= args.target_seconds),
        "median_seconds": round(median_s, 3) if isinstance(median_s, (int, float)) else None,
        "p95_seconds": round(p95_s, 3) if isinstance(p95_s, (int, float)) else None,
        "runs": results,
    }
    print(json.dumps(summary, indent=2))
    return 0 if summary["pass_median"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

