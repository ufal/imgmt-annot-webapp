"""Readers for the original and native webapp alignment formats."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _safe_component(base: Path, *parts: str) -> Path:
    candidate = (base.joinpath(*parts)).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError("Alignment data references a path outside its data directory") from exc
    return candidate


def _original_file(data_dir: Path, pair_id: str) -> Path:
    """Resolve an original pair ID such as ``1095/hu-pt``."""
    if Path(pair_id).is_absolute() or ".." in Path(pair_id).parts:
        raise ValueError(f"Invalid original pair ID: {pair_id!r}")
    candidates = [data_dir / f"{pair_id}.json", data_dir / "train" / f"{pair_id}.json"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Original alignment not found for pair {pair_id!r}")


def _image_size(png: dict[str, Any]) -> dict[str, float] | None:
    size = png.get("size", {})
    if "width" not in size or "height" not in size:
        return None
    return {"width": size["width"], "height": size["height"]}


def _side(
    boxes: list[dict[str, Any]],
    prefix: str,
    comment: str = "",
    png: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "boxes": [
            {
                "id": f"{prefix}{box.get('id', str(index))}",
                "x": box["x"],
                "y": box["y"],
                "width": box["width"] if "width" in box else box["w"],
                "height": box["height"] if "height" in box else box["h"],
                "text": box["text"],
            }
            for index, box in enumerate(boxes, 1)
        ],
        "comment": comment,
    }
    if png is not None:
        result["image_size"] = _image_size(png)
    return result


def read_original_alignment(data_dir: Path, pair_id: str) -> dict[str, Any]:
    """Read an original-format alignment into the webapp annotation structure."""
    original_file = _original_file(data_dir, pair_id)
    data = _read_json(original_file)
    source_boxes = [
        {**box, "text": text}
        for text, box in zip(data["source_texts"], data["source_text_bounding_boxes"])
    ]
    target_boxes = [
        {**box, "text": text}
        for text, box in zip(data["target_texts"], data["target_text_bounding_boxes"])
    ]
    count = min(len(source_boxes), len(target_boxes))
    return {
        "image_id": original_file.parent.name,
        "svgA": _side(source_boxes, "A", png=data.get("source_PNG", {})),
        "svgB": _side(target_boxes, "B", png=data.get("target_PNG", {})),
        "alignments": [
            {"boxA": f"A{index}", "boxB": f"B{index}"}
            for index in range(1, count + 1)
        ],
        "images_identical": None,
        "comment": "",
        "alignment_method": data.get("alignment_method"),
        "src_lang": data["source_language"],
        "tgt_lang": data["target_language"],
    }


def read_webapp_alignment(data_dir: Path, pair_id: str) -> dict[str, Any]:
    """Read a native webapp pair into the common webapp annotation structure."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", pair_id):
        raise ValueError(f"Invalid webapp pair ID: {pair_id!r}")
    pair_file = data_dir / "pairs" / pair_id / "alignments.json"
    alignment_data = _read_json(pair_file)
    image_id = alignment_data["image_id"]
    src_lang = alignment_data["src_lang"]
    tgt_lang = alignment_data["tgt_lang"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", image_id):
        raise ValueError(f"Invalid image ID: {image_id!r}")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", src_lang) or not re.fullmatch(
        r"[A-Za-z0-9_-]+", tgt_lang
    ):
        raise ValueError("Invalid language ID in alignment metadata")
    bbs_dir = _safe_component(data_dir, "bbs", image_id)
    source = _read_json(_safe_component(bbs_dir, f"{src_lang}.json"))
    target = _read_json(_safe_component(bbs_dir, f"{tgt_lang}.json"))
    return {
        "image_id": image_id,
        "svgA": _side(source["boxes"], "A", source.get("comment", ""), source.get("png", {})),
        "svgB": _side(target["boxes"], "B", target.get("comment", ""), target.get("png", {})),
        "alignments": [
            {"boxA": f"A{alignment['src_box']}", "boxB": f"B{alignment['tgt_box']}"}
            for alignment in alignment_data.get("alignments", [])
        ],
        "images_identical": alignment_data.get("images_identical"),
        "comment": alignment_data.get("comment", ""),
        "alignment_method": alignment_data.get("alignment_method"),
        "src_lang": src_lang,
        "tgt_lang": tgt_lang,
    }


def original_pair_id(annotation: dict[str, Any], image_id: str | None = None) -> str:
    """Return the original-format pair ID represented by a webapp annotation."""
    if image_id is None:
        image_id = annotation.get("image_id")
    if not image_id:
        raise ValueError("Webapp annotation does not contain an image ID")
    try:
        source_language = annotation["src_lang"]
        target_language = annotation["tgt_lang"]
    except KeyError as exc:
        raise ValueError("Webapp annotation does not contain language metadata") from exc
    return f"{image_id}/{source_language}-{target_language}"


# Short aliases make the readers convenient to use from scripts.
read_orig = read_original_alignment
read_webapp = read_webapp_alignment
get_orig_pair_id = original_pair_id
