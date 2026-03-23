from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import database


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


# ── Draw ──────────────────────────────────────────────────────────────────────

@app.get("/api/draw")
def draw():
    return {"mission": database.draw_mission()}


class PathItem(BaseModel):
    id: int
    name: str
    notes: Optional[str] = None


class AcceptBody(BaseModel):
    path: list[PathItem]


class SkipBody(BaseModel):
    path: list[PathItem]


@app.post("/api/accept")
def accept(body: AcceptBody):
    path = [{"id": p.id, "name": p.name} for p in body.path]
    database.accept_mission([p["id"] for p in path])
    database.log_history(path, "accepted")
    return {"ok": True}


@app.post("/api/skip")
def skip(body: SkipBody):
    path = [{"id": p.id, "name": p.name} for p in body.path]
    database.log_history(path, "skipped")
    return {"ok": True}


@app.get("/api/status")
def status():
    return database.get_pool_status()


# ── Items ─────────────────────────────────────────────────────────────────────

@app.get("/api/items")
def list_items():
    return {"items": database.get_items_tree()}


class CreateItemBody(BaseModel):
    name: str
    parent_id: Optional[int] = None
    notes: Optional[str] = None
    required_count: int = 1


@app.post("/api/items")
def create_item(body: CreateItemBody):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    if body.parent_id is not None:
        if database.get_depth(body.parent_id) >= 3:
            raise HTTPException(status_code=400, detail="Maximum 3 levels of nesting")
    notes = body.notes.strip() if body.notes else None
    return {"item": database.create_item(name, body.parent_id, notes, body.required_count)}


class UpdateItemBody(BaseModel):
    name: str
    notes: Optional[str] = None
    required_count: int = 1


@app.put("/api/items/{item_id}")
def update_item(item_id: int, body: UpdateItemBody):
    notes = body.notes.strip() if body.notes else None
    item = database.update_item(item_id, body.name.strip(), notes, body.required_count)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"item": item}


@app.post("/api/items/{item_id}/toggle")
def toggle_item(item_id: int):
    return database.toggle_consumed(item_id)


@app.delete("/api/items/{item_id}")
def delete_item(item_id: int):
    database.delete_item(item_id)
    return {"ok": True}


@app.post("/api/reset")
def reset():
    database.reset_all()
    return {"ok": True}


# ── History ───────────────────────────────────────────────────────────────────

@app.get("/api/history")
def get_history():
    return {"history": database.get_history()}


@app.delete("/api/history")
def clear_history():
    database.clear_history()
    return {"ok": True}
