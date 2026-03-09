# Test Plan

Use this plan to verify current behavior quickly.

## Core Runtime Checks

1. API starts
```bash
python main.py --serve --port 8000
```
Expect: `/openapi.json` and `/health` reachable.

2. Runner script help
```bash
./scripts/run.sh --help
```
Expect: options list including `--no-chat`, `--funds`, `--no-backends`, `--no-seed`.

3. Data manager help
```bash
python -m data_manager --help
```
Expect: subcommands list including `populate`, `sql`, `distribute-funds`.

## Data Path Checks

4. Seed backends
```bash
python -m data_manager populate
```

5. Load funds (existing mode)
```bash
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode existing
```

6. SQL sanity query
```bash
python -m data_manager sql "SELECT * FROM fund_info LIMIT 5"
```
Expect: JSON output, no serializer error.

## API Contract Checks

7. Register/login
- `POST /register` with new username should return `200`.
- Duplicate username should return `409`.
- `POST /login` with bad password should return `401`.

8. Chat
- `POST /chat` with valid query should return `200` or `408` depending on runtime latency.

9. Conversation fetch
- `GET /conversations/{id}` returns `200` for known id, `404` for unknown id.
