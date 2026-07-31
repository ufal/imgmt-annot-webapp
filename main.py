"""
IMGMT Annotation Webapp — FastAPI Backend
==========================================
Provides REST endpoints to support the annotation correction tool.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"
DATASETS_DIR = DATA_DIR / "datasets"
FRONTEND_DIR = BASE_DIR / "frontend"

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="IMGMT Annotation Webapp", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (CSS, JS helpers, etc.)
if (FRONTEND_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _load_users() -> dict[str, Any]:
    """Load the users → dataset mapping from users.json."""
    if not USERS_FILE.exists():
        return {}
    with USERS_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _sanitise_id(value: str) -> str:
    """
    Allow only safe path components (alphanumeric, dash, underscore).
    Raises HTTP 400 for anything that looks like a path traversal attempt.
    """
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", value):
        raise HTTPException(status_code=400, detail=f"Invalid identifier: {value!r}")
    return value


def _safe_path(base: Path, *parts: str) -> Path:
    """
    Build a path from *parts* under *base* and verify (after resolution) that
    the result is strictly inside *base*.  Raises HTTP 400 if the resolved path
    would escape the base directory.
    """
    candidate = base.joinpath(*parts).resolve()
    resolved_base = base.resolve()
    try:
        candidate.relative_to(resolved_base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path component detected.")
    return candidate


def _user_dataset_dir(user_id: str) -> Path:
    return _safe_path(DATASETS_DIR, user_id)


def _annotation_path(user_id: str, pair_id: str) -> Path:
    return _safe_path(DATASETS_DIR, user_id, pair_id, "annotations.json")


def _svg_path(user_id: str, pair_id: str, side: str) -> Path:
    """Return path to svgA.svg or svgB.svg for a given user/pair."""
    filename = "svgA.svg" if side == "A" else "svgB.svg"
    return _safe_path(DATASETS_DIR, user_id, pair_id, filename)


def _validate_user(user_id: str) -> dict[str, Any]:
    """Return user config or raise 404."""
    users = _load_users()
    if user_id not in users:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")
    return users[user_id]


def _validate_pair(user_id: str, pair_id: str) -> None:
    """Check the pair belongs to the user or raise 403/404."""
    user = _validate_user(user_id)
    if pair_id not in user.get("datasets", []):
        raise HTTPException(
            status_code=403,
            detail=f"Pair '{pair_id}' is not assigned to user '{user_id}'.",
        )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BoundingBox(BaseModel):
    id: str
    x: float
    y: float
    width: float
    height: float
    text: str


class AnnotationSide(BaseModel):
    boxes: list[BoundingBox]


class Alignment(BaseModel):
    boxA: str
    boxB: str


class Annotations(BaseModel):
    svgA: AnnotationSide
    svgB: AnnotationSide
    alignments: list[Alignment]
    images_identical: bool | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_index():
    """Serve the single-page frontend."""
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


# ------ Auth ----------------------------------------------------------------


@app.get("/api/login/{user_id}")
async def login(user_id: str):
    """
    Validate a user ID and return the user's display name and assigned pairs.
    This is a simple ID-based login — no passwords.
    """
    _sanitise_id(user_id)
    user = _validate_user(user_id)
    return {
        "user_id": user_id,
        "display_name": user.get("display_name", user_id),
        "datasets": user.get("datasets", []),
    }


# ------ Dataset listing -----------------------------------------------------


@app.get("/api/users/{user_id}/pairs")
async def list_pairs(user_id: str):
    """List all SVG/JSON pairs assigned to a user."""
    _sanitise_id(user_id)
    user = _validate_user(user_id)
    pairs = []
    for pair_id in user.get("datasets", []):
        pair_dir = _safe_path(DATASETS_DIR, user_id, pair_id)
        pairs.append(
            {
                "pair_id": pair_id,
                "has_svgA": (pair_dir / "svgA.svg").exists(),
                "has_svgB": (pair_dir / "svgB.svg").exists(),
                "has_annotations": (pair_dir / "annotations.json").exists(),
            }
        )
    return {"user_id": user_id, "pairs": pairs}


# ------ SVG serving ---------------------------------------------------------


@app.get("/api/users/{user_id}/pairs/{pair_id}/svg/{side}")
async def get_svg(user_id: str, pair_id: str, side: str):
    """
    Serve the SVG file for a given side ('A' or 'B').
    Returns the raw SVG with the correct content-type.
    """
    _sanitise_id(user_id)
    _sanitise_id(pair_id)
    if side not in ("A", "B"):
        raise HTTPException(status_code=400, detail="Side must be 'A' or 'B'.")
    _validate_pair(user_id, pair_id)
    svg_file = _svg_path(user_id, pair_id, side)
    if not svg_file.exists():
        raise HTTPException(status_code=404, detail=f"SVG{side} not found for pair '{pair_id}'.")
    return Response(content=svg_file.read_bytes(), media_type="image/svg+xml")


# ------ Annotations ---------------------------------------------------------


@app.get("/api/users/{user_id}/pairs/{pair_id}/annotations")
async def get_annotations(user_id: str, pair_id: str):
    """Return the JSON annotations for a user/pair."""
    _sanitise_id(user_id)
    _sanitise_id(pair_id)
    _validate_pair(user_id, pair_id)
    ann_file = _annotation_path(user_id, pair_id)
    if not ann_file.exists():
        # Return an empty skeleton if the file doesn't exist yet.
        return {"svgA": {"boxes": []}, "svgB": {"boxes": []}, "alignments": [], "images_identical": None}
    with ann_file.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@app.put("/api/users/{user_id}/pairs/{pair_id}/annotations")
async def save_annotations(user_id: str, pair_id: str, payload: Annotations):
    """
    Persist updated annotations back to the JSON file.
    The entire annotations object is replaced (full PUT semantics).
    """
    _sanitise_id(user_id)
    _sanitise_id(pair_id)
    _validate_pair(user_id, pair_id)
    ann_file = _annotation_path(user_id, pair_id)
    ann_file.parent.mkdir(parents=True, exist_ok=True)
    data = payload.model_dump()
    with ann_file.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return {"status": "saved"}


# ------ Users admin (read-only helper) --------------------------------------


@app.get("/api/users")
async def list_users():
    """Return a list of known user IDs (for admin/debugging purposes)."""
    users = _load_users()
    return {
        "users": [
            {"user_id": uid, "display_name": info.get("display_name", uid)}
            for uid, info in users.items()
        ]
    }
