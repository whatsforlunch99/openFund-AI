# Runtime Guide

This project runs as a live system. `demo/` package is not required for runtime.

## Recommended Start

```bash
./scripts/run.sh
```

`run.sh` can:
- bootstrap `.env` from `.env.example`
- install deps (`--install-deps`)
- start local backends (`--no-backends` to skip)
- seed baseline data (`--no-seed` to skip)
- load funds dataset (`--funds existing|fresh-symbols|fresh-all|skip`)
- run API + interactive CLI chat (`--no-chat` for API-only)

## Manual Start

```bash
python main.py --serve --port 8000
```

## Stop Backends

```bash
./scripts/stop.sh
```

## Health Check

```bash
python scripts/check_health.py --port 8000
```

or call:

```bash
curl http://127.0.0.1:8000/health
```
