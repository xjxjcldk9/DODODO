# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run locally (dev)
uvicorn main:app --reload

# Run with uv
uv run uvicorn main:app --reload

# Install dependencies
uv sync
```

The app is deployed to Railway via the `Procfile` (`uvicorn main:app --host 0.0.0.0 --port $PORT`).

## Architecture

**Stack:** FastAPI backend + vanilla JS SPA frontend. No build step.

- `main.py` — all API routes (`/api/draw`, `/api/items`, `/api/accept`, `/api/skip`, `/api/reset`, `/api/history`). Serves `templates/index.html` at `/`.
- `database.py` — all SQLite logic. DB path defaults to `dododo.db`, overridable via `DB_PATH` env var. Schema migrations are applied inline in `init_db()` via try/except ALTER TABLE.
- `static/` — `app.js` (frontend logic), `style.css`
- `templates/index.html` — single-page app shell

**Data model:**

- `items` — tree structure (up to 3 levels deep), each with `name`, `notes`, `required_count`, `parent_id`, `sort_order`
- `item_states` — tracks `consumed` and `draw_count` per item (separate table, 1:1 with items)
- `history` — log of accepted/skipped draws (stores path as JSON)

**Draw logic (`database.draw_mission`):** Randomly picks one item per tree level (L1 → L2 → L3). Each level resets independently when all items at that level are exhausted (`draw_count >= required_count`). Accepting a draw increments `draw_count`; once it reaches `required_count`, the item is marked consumed.
