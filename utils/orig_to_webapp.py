#!/usr/bin/env python3
"""
orig_to_webapp.py — Convert one original-format record to the batch format.

The batch format separates bounding-box data (shared per image/language) from
pair-specific alignment data:

  <batch_dir>/
      bbs/<image_id>/<lang>.json   — boxes + image metadata (created once per lang)
      bbs/<image_id>/<lang>.svg    — SVG (copied once per lang)
      pairs/<pair_id>/
          alignments.json          — 1:1 alignment indices + pair metadata

The same image may appear in several language pairs; storing BBs once avoids
duplication and ensures a single source of truth for BB annotation.

A helper function assemble_webapp_pair() assembles a webapp-ready pair directory
(annotations.json + SVGs) from the split files, for use by prepare_batch.py or
for ad-hoc single-pair set-up.

Original format (one JSON file per language-pair per image):
  <data_root>/<image_id>/<src>-<tgt>.json   — texts + bounding boxes
  <data_root>/<image_id>/svg/<src>.svg       — source SVG
  <data_root>/<image_id>/svg/<tgt>.svg       — target SVG

Usage:
    python orig_to_webapp.py <orig_json> <batch_dir> [--pair-id ID]
                             [--assemble-to WEBAPP_PAIR_DIR]

Example:
    python orig_to_webapp.py ../orig_data/train/543/es-it.json ./batch --pair-id pair_001
    python orig_to_webapp.py ../orig_data/train/543/es-it.json ./batch \\
        --pair-id pair_001 --assemble-to ./data/datasets/user1/pair_001
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def _write_bb_file(
    bb_file: Path,
    image_id: str,
    language: str,
    png_meta: dict,
    texts: list,
    bbs: list,
) -> None:
    """Write a BB file for one image/language; skips if the file already exists."""
    if bb_file.exists():
        return
    if len(texts) != len(bbs):
        raise ValueError(
            f"texts length ({len(texts)}) != bounding_boxes length ({len(bbs)}) "
            f"for image {image_id!r}, language {language!r}"
        )
    boxes = [
        {
            "id": str(i + 1),
            "x": bb["x"],
            "y": bb["y"],
            "w": bb["w"],
            "h": bb["h"],
            "text": text,
        }
        for i, (bb, text) in enumerate(zip(bbs, texts))
    ]
    data = {
        "image_id": image_id,
        "language": language,
        "png": png_meta,
        "boxes": boxes,
    }
    with bb_file.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def convert(
    orig_json: Path,
    batch_dir: Path,
    pair_id: str,
    data_dir: Path | None = None,
) -> dict:
    """
    Convert one original-format JSON file to the split batch format.

    Writes:
      <batch_dir>/bbs/<image_id>/<src_lang>.json   (skipped if exists)
      <batch_dir>/bbs/<image_id>/<src_lang>.svg    (skipped if exists)
      <batch_dir>/bbs/<image_id>/<tgt_lang>.json   (skipped if exists)
      <batch_dir>/bbs/<image_id>/<tgt_lang>.svg    (skipped if exists)
      <batch_dir>/pairs/<pair_id>/alignments.json

    Returns a dict suitable for an entry in mapping.json:
      {image_id, src_lang, tgt_lang, orig_json (relative to data_dir if given)}
    """
    with orig_json.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    image_id = orig_json.parent.name
    src_lang = data["source_language"]
    tgt_lang = data["target_language"]

    bbs_dir = batch_dir / "bbs" / image_id
    bbs_dir.mkdir(parents=True, exist_ok=True)

    # Write BB files (one per language; idempotent — skips if already written)
    _write_bb_file(
        bbs_dir / f"{src_lang}.json",
        image_id,
        src_lang,
        data.get("source_PNG", {}),
        data["source_texts"],
        data["source_text_bounding_boxes"],
    )
    _write_bb_file(
        bbs_dir / f"{tgt_lang}.json",
        image_id,
        tgt_lang,
        data.get("target_PNG", {}),
        data["target_texts"],
        data["target_text_bounding_boxes"],
    )

    # Copy SVG files (once per language; skipped if already copied)
    svg_dir = orig_json.parent / "svg"
    for lang in (src_lang, tgt_lang):
        src_svg = svg_dir / f"{lang}.svg"
        dest_svg = bbs_dir / f"{lang}.svg"
        if src_svg.exists() and not dest_svg.exists():
            shutil.copy2(src_svg, dest_svg)
        elif not src_svg.exists():
            print(f"Warning: SVG not found: {src_svg}", file=sys.stderr)

    # Write alignment file (1:1 by index position)
    n_src = len(data["source_texts"])
    n_tgt = len(data["target_texts"])
    n = min(n_src, n_tgt)
    if n_src != n_tgt:
        print(
            f"Warning: {n_src} source and {n_tgt} target boxes; "
            f"only {n} alignment(s) produced.",
            file=sys.stderr,
        )

    pair_dir = batch_dir / "pairs" / pair_id
    pair_dir.mkdir(parents=True, exist_ok=True)
    alignment_data = {
        "image_id": image_id,
        "src_lang": src_lang,
        "tgt_lang": tgt_lang,
        "alignment_method": data.get("alignment_method", ""),
        "alignments": [{"src_box": str(i + 1), "tgt_box": str(i + 1)} for i in range(n)],
    }
    with (pair_dir / "alignments.json").open("w", encoding="utf-8") as fh:
        json.dump(alignment_data, fh, ensure_ascii=False, indent=2)

    orig_json_str = (
        str(orig_json.relative_to(data_dir)) if data_dir else str(orig_json)
    )
    return {
        "image_id": image_id,
        "src_lang": src_lang,
        "tgt_lang": tgt_lang,
        "orig_json": orig_json_str,
    }


def assemble_webapp_pair(
    batch_dir: Path,
    pair_id: str,
    webapp_pair_dir: Path,
) -> None:
    """
    Assemble a webapp-ready pair directory from the split batch files.

    Reads:
      <batch_dir>/pairs/<pair_id>/alignments.json
      <batch_dir>/bbs/<image_id>/<src_lang>.json
      <batch_dir>/bbs/<image_id>/<tgt_lang>.json
      <batch_dir>/bbs/<image_id>/<src_lang>.svg
      <batch_dir>/bbs/<image_id>/<tgt_lang>.svg

    Writes:
      <webapp_pair_dir>/annotations.json  (webapp format)
      <webapp_pair_dir>/svgA.svg
      <webapp_pair_dir>/svgB.svg
    """
    aln_file = batch_dir / "pairs" / pair_id / "alignments.json"
    with aln_file.open("r", encoding="utf-8") as fh:
        aln_data = json.load(fh)

    image_id = aln_data["image_id"]
    src_lang = aln_data["src_lang"]
    tgt_lang = aln_data["tgt_lang"]

    bbs_dir = batch_dir / "bbs" / image_id

    with (bbs_dir / f"{src_lang}.json").open("r", encoding="utf-8") as fh:
        src_bb_data = json.load(fh)
    with (bbs_dir / f"{tgt_lang}.json").open("r", encoding="utf-8") as fh:
        tgt_bb_data = json.load(fh)

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
        for a in aln_data["alignments"]
    ]

    annotations = {
        "svgA": {"boxes": boxes_a},
        "svgB": {"boxes": boxes_b},
        "alignments": alignments,
    }

    webapp_pair_dir.mkdir(parents=True, exist_ok=True)
    with (webapp_pair_dir / "annotations.json").open("w", encoding="utf-8") as fh:
        json.dump(annotations, fh, ensure_ascii=False, indent=2)

    for lang, dest_name in ((src_lang, "svgA.svg"), (tgt_lang, "svgB.svg")):
        src_svg = bbs_dir / f"{lang}.svg"
        if src_svg.exists():
            shutil.copy2(src_svg, webapp_pair_dir / dest_name)
        else:
            print(f"Warning: SVG not found: {src_svg}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert an original-format JSON record to the split batch format "
            "(bbs/<image_id>/<lang>.json + pairs/<pair_id>/alignments.json)."
        )
    )
    parser.add_argument("orig_json", type=Path, help="Path to the original JSON file.")
    parser.add_argument(
        "batch_dir",
        type=Path,
        help="Root of the batch directory to write into.",
    )
    parser.add_argument(
        "--pair-id",
        default="pair_001",
        help="Pair identifier to use (default: pair_001).",
    )
    parser.add_argument(
        "--assemble-to",
        type=Path,
        metavar="WEBAPP_PAIR_DIR",
        help=(
            "If given, also assemble a webapp-ready pair directory "
            "(annotations.json + SVGs) at this path."
        ),
    )
    args = parser.parse_args()

    if not args.orig_json.exists():
        print(f"Error: file not found: {args.orig_json}", file=sys.stderr)
        sys.exit(1)

    meta = convert(args.orig_json, args.batch_dir, args.pair_id)
    print(
        f"Split format written to {args.batch_dir} "
        f"(image {meta['image_id']!r}, {meta['src_lang']}-{meta['tgt_lang']}, "
        f"pair {args.pair_id!r})"
    )

    if args.assemble_to:
        assemble_webapp_pair(args.batch_dir, args.pair_id, args.assemble_to)
        print(f"Webapp pair assembled at {args.assemble_to}")


if __name__ == "__main__":
    main()
