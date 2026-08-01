"""
IMGMT Annotation Webapp — FastAPI Backend
==========================================
Provides REST endpoints to support the annotation correction tool.

Data layout
-----------
  data/
    bbs/<image_id>/<lang>.json   — bounding boxes shared across all pairs for that image
    bbs/<image_id>/<lang>.svg    — SVG shared across all pairs for that image
    pairs/<pair_id>/
        alignments.json          — pair-specific alignments + image/lang metadata
    users.json                   — user → assigned pair IDs mapping

Writing bounding boxes to the per-image bbs/ files (rather than per-pair copies)
means that BB corrections are shared automatically across every pair that references
the same image.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"
BBS_DIR = DATA_DIR / "bbs"
PAIRS_DIR = DATA_DIR / "pairs"
FRONTEND_DIR = BASE_DIR / "frontend"


def _set_data_dir(data_dir: Path) -> None:
    """Configure the directory containing users, bounding boxes, and pairs."""
    global DATA_DIR, USERS_FILE, BBS_DIR, PAIRS_DIR
    DATA_DIR = data_dir.resolve()
    USERS_FILE = DATA_DIR / "users.json"
    BBS_DIR = DATA_DIR / "bbs"
    PAIRS_DIR = DATA_DIR / "pairs"

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


def _load_pair_meta(pair_id: str) -> dict[str, Any]:
    """
    Load pair metadata from pairs/<pair_id>/alignments.json or raise 404.

    The returned dict contains at minimum: image_id, src_lang, tgt_lang, alignments.
    """
    pair_file = _safe_path(PAIRS_DIR, pair_id, "alignments.json")
    if not pair_file.exists():
        raise HTTPException(
            status_code=404, detail=f"Pair '{pair_id}' data not found."
        )
    with pair_file.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _strip_side_prefix(box_id: str) -> str:
    """Strip the leading 'A' or 'B' (case-insensitive) added by the webapp format."""
    if box_id and box_id[0] in "ABab":
        return box_id[1:]
    return box_id


def _image_size(bb_data: dict[str, Any]) -> dict[str, float] | None:
    """Return the source image dimensions stored in the BB metadata."""
    size = bb_data.get("png", {}).get("size", {})
    width, height = size.get("width"), size.get("height")
    if width is None or height is None:
        return None
    return {"width": width, "height": height}


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


class TranslationRequest(BaseModel):
    texts: list[str]


def _translate_text(text: str) -> dict[str, str | None]:
    """Translate one label to English using Google's free translation endpoint."""
    if not text.strip():
        return {"translation": None, "source_language": None}
    query = urllib.parse.urlencode(
        {"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text}
    )
    request = urllib.request.Request(
        f"https://translate.googleapis.com/translate_a/single?{query}",
        headers={"User-Agent": "IMGMT-annot-webapp"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.loads(response.read().decode("utf-8"))
    translated = "".join(part[0] for part in (result[0] or []) if part and part[0])
    return {
        "translation": translated or None,
        "source_language": result[2] if len(result) > 2 else None,
    }


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
        pair_file = _safe_path(PAIRS_DIR, pair_id, "alignments.json")
        if pair_file.exists():
            with pair_file.open("r", encoding="utf-8") as fh:
                meta = json.load(fh)
            image_id = meta.get("image_id", "")
            src_lang = meta.get("src_lang", "")
            tgt_lang = meta.get("tgt_lang", "")
            try:
                has_svgA = _safe_path(BBS_DIR, image_id, f"{src_lang}.svg").exists()
                has_svgB = _safe_path(BBS_DIR, image_id, f"{tgt_lang}.svg").exists()
                has_annotations = (
                    _safe_path(BBS_DIR, image_id, f"{src_lang}.json").exists()
                    and _safe_path(BBS_DIR, image_id, f"{tgt_lang}.json").exists()
                )
            except HTTPException:
                has_svgA = has_svgB = has_annotations = False
        else:
            has_svgA = has_svgB = has_annotations = False
        pairs.append(
            {
                "pair_id": pair_id,
                "has_svgA": has_svgA,
                "has_svgB": has_svgB,
                "has_annotations": has_annotations,
            }
        )
    return {"user_id": user_id, "pairs": pairs}


# ------ SVG serving ---------------------------------------------------------


@app.get("/api/users/{user_id}/pairs/{pair_id}/svg/{side}")
async def get_svg(user_id: str, pair_id: str, side: str):
    """
    Serve the SVG file for a given side ('A' or 'B').
    Returns the raw SVG with the correct content-type.
    SVGs are stored per-image under bbs/<image_id>/<lang>.svg.
    """
    _sanitise_id(user_id)
    _sanitise_id(pair_id)
    if side not in ("A", "B"):
        raise HTTPException(status_code=400, detail="Side must be 'A' or 'B'.")
    _validate_pair(user_id, pair_id)
    meta = _load_pair_meta(pair_id)
    image_id = meta["image_id"]
    lang = meta["src_lang"] if side == "A" else meta["tgt_lang"]
    svg_file = _safe_path(BBS_DIR, image_id, f"{lang}.svg")
    if not svg_file.exists():
        raise HTTPException(status_code=404, detail=f"SVG{side} not found for pair '{pair_id}'.")
    return Response(content=svg_file.read_bytes(), media_type="image/svg+xml")


# ------ Annotations ---------------------------------------------------------


@app.get("/api/users/{user_id}/pairs/{pair_id}/annotations")
async def get_annotations(user_id: str, pair_id: str):
    """
    Return the JSON annotations for a user/pair.

    Bounding boxes are read from the shared bbs/<image_id>/<lang>.json files so that
    any corrections made while annotating one pair are visible in all pairs that
    reference the same image.  Alignments are read from pairs/<pair_id>/alignments.json.
    """
    _sanitise_id(user_id)
    _sanitise_id(pair_id)
    _validate_pair(user_id, pair_id)
    pair_file = _safe_path(PAIRS_DIR, pair_id, "alignments.json")
    if not pair_file.exists():
        # Return an empty skeleton if the pair hasn't been set up yet.
        return {
            "svgA": {"boxes": []},
            "svgB": {"boxes": []},
            "alignments": [],
            "images_identical": None,
        }
    with pair_file.open("r", encoding="utf-8") as fh:
        aln_data = json.load(fh)
    image_id = aln_data["image_id"]
    src_lang = aln_data["src_lang"]
    tgt_lang = aln_data["tgt_lang"]
    src_bb_file = _safe_path(BBS_DIR, image_id, f"{src_lang}.json")
    tgt_bb_file = _safe_path(BBS_DIR, image_id, f"{tgt_lang}.json")
    if not src_bb_file.exists() or not tgt_bb_file.exists():
        return {
            "svgA": {"boxes": []},
            "svgB": {"boxes": []},
            "alignments": [],
            "images_identical": aln_data.get("images_identical"),
        }
    with src_bb_file.open("r", encoding="utf-8") as fh:
        src_bb_data = json.load(fh)
    with tgt_bb_file.open("r", encoding="utf-8") as fh:
        tgt_bb_data = json.load(fh)
    # Convert from BB-file format (w/h, numeric IDs) to webapp format (width/height, A/B-prefixed IDs)
    boxes_a = [
        {
            "id": f"A{b['id']}",
            "x": b["x"],
            "y": b["y"],
            "width": b["w"],
            "height": b["h"],
            "text": b["text"],
        }
        for b in src_bb_data["boxes"]
    ]
    boxes_b = [
        {
            "id": f"B{b['id']}",
            "x": b["x"],
            "y": b["y"],
            "width": b["w"],
            "height": b["h"],
            "text": b["text"],
        }
        for b in tgt_bb_data["boxes"]
    ]
    alignments = [
        {"boxA": f"A{a['src_box']}", "boxB": f"B{a['tgt_box']}"}
        for a in aln_data.get("alignments", [])
    ]
    return {
        "svgA": {"boxes": boxes_a, "image_size": _image_size(src_bb_data)},
        "svgB": {"boxes": boxes_b, "image_size": _image_size(tgt_bb_data)},
        "alignments": alignments,
        "images_identical": aln_data.get("images_identical"),
    }


@app.put("/api/users/{user_id}/pairs/{pair_id}/annotations")
async def save_annotations(user_id: str, pair_id: str, payload: Annotations):
    """
    Persist updated annotations.

    Bounding boxes are written to the shared bbs/<image_id>/<lang>.json files so
    that BB corrections are propagated automatically to every other pair that
    references the same image.  Alignments are written to
    pairs/<pair_id>/alignments.json (pair-specific).
    """
    _sanitise_id(user_id)
    _sanitise_id(pair_id)
    _validate_pair(user_id, pair_id)
    meta = _load_pair_meta(pair_id)
    image_id = meta["image_id"]
    src_lang = meta["src_lang"]
    tgt_lang = meta["tgt_lang"]
    data = payload.model_dump()
    # --- Save BB files (shared per image) ------------------------------------
    for side_key, lang in (("svgA", src_lang), ("svgB", tgt_lang)):
        bb_file = _safe_path(BBS_DIR, image_id, f"{lang}.json")
        # Preserve top-level metadata (image_id, language, png) if the file exists.
        if bb_file.exists():
            with bb_file.open("r", encoding="utf-8") as fh:
                existing = json.load(fh)
        else:
            existing = {"image_id": image_id, "language": lang, "png": {}}
        existing["boxes"] = [
            {
                "id": _strip_side_prefix(b["id"]),
                "x": b["x"],
                "y": b["y"],
                "w": b["width"],
                "h": b["height"],
                "text": b["text"],
            }
            for b in data[side_key]["boxes"]
        ]
        bb_file.parent.mkdir(parents=True, exist_ok=True)
        with bb_file.open("w", encoding="utf-8") as fh:
            json.dump(existing, fh, ensure_ascii=False, indent=2)
    # --- Save alignment file (pair-specific) ---------------------------------
    aln_file = _safe_path(PAIRS_DIR, pair_id, "alignments.json")
    # Keep all existing metadata fields; replace alignments only.
    aln_data = dict(meta)
    aln_data["alignments"] = [
        {
            "src_box": _strip_side_prefix(a["boxA"]),
            "tgt_box": _strip_side_prefix(a["boxB"]),
        }
        for a in data["alignments"]
    ]
    aln_data["images_identical"] = data["images_identical"]
    aln_file.parent.mkdir(parents=True, exist_ok=True)
    with aln_file.open("w", encoding="utf-8") as fh:
        json.dump(aln_data, fh, ensure_ascii=False, indent=2)
    return {"status": "saved"}


# ------ Translation ----------------------------------------------------------


@app.post("/api/translate")
async def translate_labels(payload: TranslationRequest):
    """Return English translations and detected languages for SVG labels."""
    if len(payload.texts) > 100 or any(len(text) > 500 for text in payload.texts):
        raise HTTPException(status_code=400, detail="Too many or too-long labels.")
    semaphore = asyncio.Semaphore(10)

    async def translate_one(text: str) -> dict[str, str | None]:
        async with semaphore:
            try:
                return await asyncio.to_thread(_translate_text, text)
            except Exception:
                # Translation is an optional UI enhancement; keep individual failures
                # from preventing the annotation panel from loading.
                return {"translation": None, "source_language": None}

    results = await asyncio.gather(*(translate_one(text) for text in payload.texts))
    return {"translations": results}


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the IMGMT annotation webapp.")
    parser.add_argument(
        "data_dir",
        nargs="?",
        type=Path,
        default=DATA_DIR,
        help="Directory containing users.json, bbs/, and pairs/ (default: ./data).",
    )
    args = parser.parse_args()
    _set_data_dir(args.data_dir)

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
