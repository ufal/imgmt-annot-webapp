#!/usr/bin/env python3
"""
orig_to_webapp.py — Convert one original-format record to a webapp pair directory.

Original format (one JSON file per language-pair per image):
  <data_root>/<image_id>/<src>-<tgt>.json   — texts + bounding boxes
  <data_root>/<image_id>/svg/<src>.svg       — source SVG
  <data_root>/<image_id>/svg/<tgt>.svg       — target SVG

Webapp format (one directory per pair):
  <output_dir>/
      annotations.json  — boxes (A/B) + explicit alignments
      svgA.svg          — source SVG
      svgB.svg          — target SVG

Alignment in the original format is implicit (1:1 by index), so the
produced annotations.json always contains a 1:1 alignment list.

Usage:
    python orig_to_webapp.py <orig_json> <output_dir>

Example:
    python orig_to_webapp.py ../orig_data/train/543/es-it.json ./out/pair_001
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def convert(orig_json: Path, output_dir: Path) -> None:
    with orig_json.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    src_lang = data["source_language"]
    tgt_lang = data["target_language"]
    src_texts = data["source_texts"]
    tgt_texts = data["target_texts"]
    src_bbs = data["source_text_bounding_boxes"]
    tgt_bbs = data["target_text_bounding_boxes"]

    if len(src_texts) != len(src_bbs):
        raise ValueError(
            f"source_texts length ({len(src_texts)}) != "
            f"source_text_bounding_boxes length ({len(src_bbs)})"
        )
    if len(tgt_texts) != len(tgt_bbs):
        raise ValueError(
            f"target_texts length ({len(tgt_texts)}) != "
            f"target_text_bounding_boxes length ({len(tgt_bbs)})"
        )

    # Build box lists; use 'w'/'h' keys from original, mapped to 'width'/'height'
    boxes_a = [
        {
            "id": f"A{i + 1}",
            "x": bb["x"],
            "y": bb["y"],
            "width": bb["w"],
            "height": bb["h"],
            "text": src_texts[i],
        }
        for i, bb in enumerate(src_bbs)
    ]
    boxes_b = [
        {
            "id": f"B{i + 1}",
            "x": bb["x"],
            "y": bb["y"],
            "width": bb["w"],
            "height": bb["h"],
            "text": tgt_texts[i],
        }
        for i, bb in enumerate(tgt_bbs)
    ]

    # 1:1 alignment by position (only up to the shorter list)
    n_aligned = min(len(boxes_a), len(boxes_b))
    alignments = [{"boxA": f"A{i + 1}", "boxB": f"B{i + 1}"} for i in range(n_aligned)]
    if len(boxes_a) != len(boxes_b):
        print(
            f"Warning: source has {len(boxes_a)} boxes and target has {len(boxes_b)} boxes; "
            f"only {n_aligned} alignment(s) produced.",
            file=sys.stderr,
        )

    annotations = {
        "svgA": {"boxes": boxes_a},
        "svgB": {"boxes": boxes_b},
        "alignments": alignments,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    ann_file = output_dir / "annotations.json"
    with ann_file.open("w", encoding="utf-8") as fh:
        json.dump(annotations, fh, ensure_ascii=False, indent=2)

    # Copy SVG files: <image_dir>/svg/<lang>.svg → svgA.svg / svgB.svg
    svg_dir = orig_json.parent / "svg"
    for lang, dest_name in ((src_lang, "svgA.svg"), (tgt_lang, "svgB.svg")):
        src_svg = svg_dir / f"{lang}.svg"
        if src_svg.exists():
            shutil.copy2(src_svg, output_dir / dest_name)
        else:
            print(
                f"Warning: SVG not found: {src_svg}",
                file=sys.stderr,
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert an original-format JSON record to a webapp pair directory."
    )
    parser.add_argument("orig_json", type=Path, help="Path to the original JSON file.")
    parser.add_argument("output_dir", type=Path, help="Destination webapp pair directory.")
    args = parser.parse_args()

    if not args.orig_json.exists():
        print(f"Error: file not found: {args.orig_json}", file=sys.stderr)
        sys.exit(1)

    convert(args.orig_json, args.output_dir)
    print(f"Written to {args.output_dir}")


if __name__ == "__main__":
    main()
