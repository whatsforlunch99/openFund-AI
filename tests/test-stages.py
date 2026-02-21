"""Stage tests as specified in docs/test_plan.md. One file, grouped by stage."""

import sys
from io import StringIO

import pytest


# --- Stage 1: Config and minimal main ---


class TestStage1ConfigAndMain:
    """Runnable: PYTHONPATH=. python main.py prints ready message and exits 0."""

    def test_load_config_returns_config(self) -> None:
        """load_config() returns a Config instance populated from env."""
        from config.config import load_config, Config

        cfg = load_config()
        assert isinstance(cfg, Config)
        assert hasattr(cfg, "milvus_uri")
        assert hasattr(cfg, "analyst_api_url")

    def test_main_prints_ready_message(self) -> None:
        """main() prints 'OpenFund-AI ready (config loaded)'."""
        from main import main

        buf = StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            main()
            out = buf.getvalue()
        finally:
            sys.stdout = old_stdout
        assert "OpenFund-AI ready (config loaded)" in out
