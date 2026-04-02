from __future__ import annotations

import importlib
import os
import platform
import sys
from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _try_import(module: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module)
        return True, "import ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def run_doctor() -> list[CheckResult]:
    results: list[CheckResult] = []

    results.append(
        CheckResult(
            name="python",
            ok=True,
            detail=f"{sys.version.split()[0]} ({sys.executable})",
        )
    )

    # Project requires >=3.11; Docling+torch ecosystem is typically stable on 3.11/3.12.
    py_ok = sys.version_info >= (3, 11) and sys.version_info < (3, 13)
    results.append(
        CheckResult(
            name="python_supported_for_docling",
            ok=py_ok,
            detail="recommended 3.11/3.12 for docling+torch" if not py_ok else "ok",
        )
    )

    results.append(CheckResult(name="os", ok=True, detail=f"{platform.system()} {platform.release()}"))
    results.append(CheckResult(name="arch", ok=True, detail=platform.machine()))

    ok, detail = _try_import("docling")
    results.append(CheckResult(name="docling", ok=ok, detail=detail))

    # DocumentConverter import is the critical path.
    try:
        from docling.document_converter import DocumentConverter  # type: ignore

        results.append(CheckResult(name="docling.document_converter", ok=True, detail=f"OK: {DocumentConverter}"))
    except Exception as e:
        results.append(
            CheckResult(
                name="docling.document_converter",
                ok=False,
                detail=f"{type(e).__name__}: {e}",
            )
        )

    # Torch is often the root cause on Windows.
    ok, detail = _try_import("torch")
    results.append(CheckResult(name="torch", ok=ok, detail=detail))

    # Optional fallback parser
    ok, detail = _try_import("pypdf")
    results.append(CheckResult(name="pypdf (fallback)", ok=ok, detail=detail))

    # Environment hints
    results.append(
        CheckResult(
            name="env",
            ok=True,
            detail="; ".join(
                [
                    f"VIRTUAL_ENV={os.environ.get('VIRTUAL_ENV','') or '(none)'}",
                    f"PATH_has_pip={'pip' in (os.environ.get('PATH','') or '').lower()}",
                ]
            ),
        )
    )

    return results


def format_doctor_report(results: list[CheckResult]) -> str:
    lines: list[str] = []
    width = max(len(r.name) for r in results) if results else 10
    for r in results:
        status = "OK" if r.ok else "FAIL"
        lines.append(f"{r.name.ljust(width)}  {status}  {r.detail}")
    return "\n".join(lines)

