import json
import os
import random
import sqlite3
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "dododo.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                name           TEXT NOT NULL,
                parent_id      INTEGER REFERENCES items(id) ON DELETE CASCADE,
                sort_order     INTEGER NOT NULL DEFAULT 0,
                notes          TEXT,
                required_count INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS item_states (
                item_id     INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
                consumed    INTEGER NOT NULL DEFAULT 0,
                draw_count  INTEGER NOT NULL DEFAULT 0,
                consumed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                path_json  TEXT NOT NULL,
                action     TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        # migrate existing DBs
        for col, dflt in [("notes", "NULL"), ("required_count", "1")]:
            try:
                conn.execute(f"ALTER TABLE items ADD COLUMN {col} TEXT DEFAULT {dflt}")
                conn.commit()
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("ALTER TABLE item_states ADD COLUMN draw_count INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            pass


# ── internal helpers ──────────────────────────────────────────────────────────

def _all_children(conn: sqlite3.Connection, parent_id: Optional[int]) -> list[dict]:
    if parent_id is None:
        rows = conn.execute(
            "SELECT id, name, parent_id FROM items WHERE parent_id IS NULL ORDER BY sort_order, name"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name, parent_id FROM items WHERE parent_id = ? ORDER BY sort_order, name",
            (parent_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _available(conn: sqlite3.Connection, parent_id: Optional[int]) -> list[dict]:
    """Items not yet fully consumed at this level (draw_count < required_count)."""
    base = (
        "SELECT i.id, i.name, i.notes, i.required_count, i.parent_id, "
        "COALESCE(s.draw_count, 0) AS draw_count "
        "FROM items i LEFT JOIN item_states s ON s.item_id = i.id "
        "WHERE {} AND COALESCE(s.draw_count, 0) < i.required_count "
        "ORDER BY i.sort_order, i.name"
    )
    if parent_id is None:
        rows = conn.execute(base.format("i.parent_id IS NULL")).fetchall()
    else:
        rows = conn.execute(base.format("i.parent_id = ?"), (parent_id,)).fetchall()
    return [dict(r) for r in rows]


def _reset_level(conn: sqlite3.Connection, parent_id: Optional[int]):
    if parent_id is None:
        conn.execute(
            "UPDATE item_states SET consumed = 0, draw_count = 0, consumed_at = NULL "
            "WHERE item_id IN (SELECT id FROM items WHERE parent_id IS NULL)"
        )
    else:
        conn.execute(
            "UPDATE item_states SET consumed = 0, draw_count = 0, consumed_at = NULL "
            "WHERE item_id IN (SELECT id FROM items WHERE parent_id = ?)",
            (parent_id,),
        )


def _pick(conn: sqlite3.Connection, parent_id: Optional[int]) -> Optional[dict]:
    """Pick a random unconsumed item at this level; reset level first if exhausted."""
    avail = _available(conn, parent_id)
    if not avail:
        all_items = _all_children(conn, parent_id)
        if not all_items:
            return None  # nothing exists at this level
        _reset_level(conn, parent_id)
        conn.commit()
        avail = all_items
    return random.choice(avail)


# ── public API ────────────────────────────────────────────────────────────────

def draw_mission() -> Optional[dict]:
    """
    Returns {"path": [{"id":…,"name":…,"notes":…}, …]} with 1–3 items,
    or None if the pool is completely empty.
    Resets each level lazily and independently.
    """
    def node(item): return {
        "id": item["id"], "name": item["name"], "notes": item.get("notes"),
        "required_count": item.get("required_count", 1), "draw_count": item.get("draw_count", 0),
    }

    with get_conn() as conn:
        l1 = _pick(conn, None)
        if l1 is None:
            return None
        path = [node(l1)]

        if not _all_children(conn, l1["id"]):
            return {"path": path}
        l2 = _pick(conn, l1["id"])
        if l2 is None:
            return {"path": path}
        path.append(node(l2))

        if not _all_children(conn, l2["id"]):
            return {"path": path}
        l3 = _pick(conn, l2["id"])
        if l3 is None:
            return {"path": path}
        path.append(node(l3))

        return {"path": path}


def accept_mission(item_ids: list[int]):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        for iid in item_ids:
            row = conn.execute(
                "SELECT i.required_count, COALESCE(s.draw_count, 0) AS draw_count "
                "FROM items i LEFT JOIN item_states s ON s.item_id = i.id WHERE i.id = ?",
                (iid,),
            ).fetchone()
            if not row:
                continue
            new_count = row["draw_count"] + 1
            consumed = 1 if new_count >= row["required_count"] else 0
            conn.execute(
                "UPDATE item_states SET draw_count = ?, consumed = ?, consumed_at = ? WHERE item_id = ?",
                (new_count, consumed, now if consumed else None, iid),
            )
        conn.commit()


def get_pool_status() -> dict:
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM items WHERE parent_id IS NULL"
        ).fetchone()[0]
        remaining = conn.execute(
            "SELECT COUNT(*) FROM items i "
            "LEFT JOIN item_states s ON s.item_id = i.id "
            "WHERE i.parent_id IS NULL AND COALESCE(s.consumed, 0) = 0"
        ).fetchone()[0]
    return {"total": total, "remaining": remaining}


def get_items_tree() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT i.id, i.name, i.notes, i.required_count, i.parent_id, i.sort_order, "
            "COALESCE(s.consumed, 0) AS consumed, COALESCE(s.draw_count, 0) AS draw_count "
            "FROM items i LEFT JOIN item_states s ON s.item_id = i.id "
            "ORDER BY i.parent_id, i.sort_order, i.name"
        ).fetchall()

    nodes: dict[int, dict] = {r["id"]: {**dict(r), "children": []} for r in rows}
    roots: list[dict] = []
    for node in nodes.values():
        pid = node["parent_id"]
        if pid is None:
            roots.append(node)
        elif pid in nodes:
            nodes[pid]["children"].append(node)
    return roots


def get_depth(item_id: int) -> int:
    with get_conn() as conn:
        depth, cur = 1, item_id
        while True:
            row = conn.execute(
                "SELECT parent_id FROM items WHERE id = ?", (cur,)
            ).fetchone()
            if not row or row["parent_id"] is None:
                break
            depth += 1
            cur = row["parent_id"]
    return depth


def create_item(name: str, parent_id: Optional[int], notes: Optional[str] = None, required_count: int = 1) -> dict:
    with get_conn() as conn:
        order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM items WHERE parent_id IS ?",
            (parent_id,),
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO items (name, notes, required_count, parent_id, sort_order) VALUES (?, ?, ?, ?, ?)",
            (name, notes, max(1, required_count), parent_id, order),
        )
        iid = cur.lastrowid
        conn.execute("INSERT INTO item_states (item_id) VALUES (?)", (iid,))
        conn.commit()
    return {"id": iid, "name": name, "notes": notes, "required_count": required_count,
            "parent_id": parent_id, "consumed": 0, "draw_count": 0, "children": []}


def update_item(item_id: int, name: str, notes: Optional[str] = None, required_count: int = 1) -> Optional[dict]:
    with get_conn() as conn:
        conn.execute(
            "UPDATE items SET name = ?, notes = ?, required_count = ? WHERE id = ?",
            (name, notes, max(1, required_count), item_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT i.id, i.name, i.notes, i.required_count, i.parent_id, "
            "COALESCE(s.consumed, 0) AS consumed, COALESCE(s.draw_count, 0) AS draw_count "
            "FROM items i LEFT JOIN item_states s ON s.item_id = i.id WHERE i.id = ?",
            (item_id,),
        ).fetchone()
    return dict(row) if row else None


def toggle_consumed(item_id: int) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT i.required_count, COALESCE(s.consumed, 0) AS consumed "
            "FROM items i LEFT JOIN item_states s ON s.item_id = i.id WHERE i.id = ?",
            (item_id,),
        ).fetchone()
        if not row:
            return {"consumed": False}
        new_consumed = 0 if row["consumed"] else 1
        new_draw_count = row["required_count"] if new_consumed else 0
        conn.execute(
            "UPDATE item_states SET consumed = ?, draw_count = ?, consumed_at = ? WHERE item_id = ?",
            (new_consumed, new_draw_count, now if new_consumed else None, item_id),
        )
        conn.commit()
    return {"consumed": bool(new_consumed)}


def delete_item(item_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()


def reset_all():
    with get_conn() as conn:
        conn.execute("UPDATE item_states SET consumed = 0, draw_count = 0, consumed_at = NULL")
        conn.commit()


def log_history(path: list[dict], action: str):
    now = datetime.now(timezone.utc).isoformat()
    path_json = json.dumps([{"id": p["id"], "name": p["name"]} for p in path])
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO history (path_json, action, created_at) VALUES (?, ?, ?)",
            (path_json, action, now),
        )
        conn.commit()


def get_history() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, path_json, action, created_at FROM history ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
    return [
        {"id": r["id"], "path": json.loads(r["path_json"]), "action": r["action"], "created_at": r["created_at"]}
        for r in rows
    ]


def clear_history():
    with get_conn() as conn:
        conn.execute("DELETE FROM history")
        conn.commit()
