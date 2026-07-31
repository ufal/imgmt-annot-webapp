#!/usr/bin/env python3
"""
webapp_to_orig.py — Convert an annotated webapp batch pair back to the original format.

Reads from the split batch format produced by orig_to_webapp.py / prepare_batch.py:

  <batch_dir>/
      bbs/<image_id>/<lang>.json        — image metadata + original boxes
      pairs/<pair_id>/alignments.json   — pair metadata
      datasets/<annotator>/<pair_id>/annotations.json  — corrected boxes (post-annotation)

If --annotator is given, the corrected annotations.json written by the webapp is
used for box coordinates and texts (the expected use after annotation is complete).
Otherwise the original boxes from the bbs/ files are used.

Image metadata (PNG dimensions, URLs, licensing) and alignment_method are taken
from the batch files and need no separate template.

The webapp allows n:m alignments; the original format only supports implicit 1:1
alignment by index.  Therefore:
  • Only boxes participating in strictly 1:1 alignments are emitted.
  • Multi-aligned or unaligned boxes are skipped with a warning.

Usage:
    python webapp_to_orig.py <batch_dir> <pair_id> <output_json>
                             [--annotator USER]

Examples:
    # Use original (pre-annotation) boxes
    python webapp_to_orig.py ./batch pair_001 ./out/543/es-it.json

    # Use boxes corrected by an annotator
    python webapp_to_orig.py ./batch pair_001 ./out/543/es-it.json --annotator ann1
"""

import argparse
import json
import sys
from pathlib import Path


def _collect_one_to_one(
    alignments: list[dict],
    a_key: str,
    b_key: str,
) -> tuple[dict[str, str], set[str], set[str]]:
    """
    Return:
      pairs   — {a_id: b_id} for strictly 1:1 aligned pairs
      skip_a  — a-IDs excluded (multi-aligned in the a-direction)
      skip_b  — b-IDs excluded (multi-aligned in the b-direction)
    """
    a_counts: dict[str, int] = {}
    b_counts: dict[str, int] = {}
    for aln in alignments:
        a_counts[aln[a_key]] = a_counts.get(aln[a_key], 0) + 1
        b_counts[aln[b_key]] = b_counts.get(aln[b_key], 0) + 1

    pairs: dict[str, str] = {}
    for aln in alignments:
        aid, bid = aln[a_key], aln[b_key]
        if a_counts[aid] == 1 and b_counts[bid] == 1:
            pairs[aid] = bid

    all_a = {aln[a_key] for aln in alignments}
    all_b = {aln[b_key] for aln in alignments}
    return pairs, all_a - set(pairs.keys()), all_b - set(pairs.values())


def _int_suffix(box_id: str) -> int:
    """Sort key: extract trailing integer from a box ID such as 'A3' or '3'."""
    suffix = box_id.lstrip("ABab")
    return int(suffix) if suffix.isdigit() else 0


def convert(
    batch_dir: Path,
    pair_id: str,
    output_json: Path,
    annotator: str | None = None,
) -> None:
    """
    Convert one batch pair back to the original JSON format.

    If *annotator* is given, box data is taken from the corrected
    datasets/<annotator>/<pair_id>/annotations.json; otherwise the original
    boxes from bbs/<image_id>/<lang>.json are used.
    """
    # --- Load pair metadata ---------------------------------------------------
    aln_file = batch_dir / "pairs" / pair_id / "alignments.json"
    if not aln_file.exists():
        raise FileNotFoundError(f"Alignment file not found: {aln_file}")
    with aln_file.open("r", encoding="utf-8") as fh:
        aln_data = json.load(fh)

    image_id = aln_data["image_id"]
    src_lang = aln_data["src_lang"]
    tgt_lang = aln_data["tgt_lang"]
    alignment_method = aln_data.get("alignment_method", "manual")

    bbs_dir = batch_dir / "bbs" / image_id

    # --- Load image metadata (PNG info) from BB files -------------------------
    for lang in (src_lang, tgt_lang):
        bb_path = bbs_dir / f"{lang}.json"
        if not bb_path.exists():
            raise FileNotFoundError(f"BB file not found: {bb_path}")

    with (bbs_dir / f"{src_lang}.json").open("r", encoding="utf-8") as fh:
        src_bb_file = json.load(fh)
    with (bbs_dir / f"{tgt_lang}.json").open("r", encoding="utf-8") as fh:
        tgt_bb_file = json.load(fh)

    src_png = src_bb_file.get("png", {})
    tgt_png = tgt_bb_file.get("png", {})

    # --- Load box data (corrected or original) --------------------------------
    if annotator:
        ann_file = batch_dir / "datasets" / annotator / pair_id / "annotations.json"
        if not ann_file.exists():
            raise FileNotFoundError(
                f"Corrected annotations not found for annotator {annotator!r}: {ann_file}"
            )
        with ann_file.open("r", encoding="utf-8") as fh:
            webapp_ann = json.load(fh)

        # webapp format: boxes have 'width'/'height' and IDs like 'A1', 'B1'
        boxes_a = {b["id"]: b for b in webapp_ann["svgA"]["boxes"]}
        boxes_b = {b["id"]: b for b in webapp_ann["svgB"]["boxes"]}
        alignments_raw = webapp_ann.get("alignments", [])

        pairs, skip_a, skip_b = _collect_one_to_one(alignments_raw, "boxA", "boxB")

        for aid in sorted(skip_a):
            print(f"Warning: A-box {aid!r} is multi-aligned — excluded.", file=sys.stderr)
        for bid in sorted(skip_b):
            print(f"Warning: B-box {bid!r} is multi-aligned — excluded.", file=sys.stderr)

        aligned_a = {aln["boxA"] for aln in alignments_raw}
        aligned_b = {aln["boxB"] for aln in alignments_raw}
        for aid in sorted(set(boxes_a) - aligned_a):
            print(f"Warning: A-box {aid!r} has no alignment — excluded.", file=sys.stderr)
        for bid in sorted(set(boxes_b) - aligned_b):
            print(f"Warning: B-box {bid!r} has no alignment — excluded.", file=sys.stderr)

        ordered_a_ids = sorted(pairs.keys(), key=_int_suffix)
        src_texts, src_bbs_out, tgt_texts, tgt_bbs_out = [], [], [], []
        for aid in ordered_a_ids:
            bid = pairs[aid]
            ba, bb = boxes_a[aid], boxes_b[bid]
            src_texts.append(ba["text"])
            src_bbs_out.append({"x": ba["x"], "y": ba["y"], "w": ba["width"], "h": ba["height"]})
            tgt_texts.append(bb["text"])
            tgt_bbs_out.append({"x": bb["x"], "y": bb["y"], "w": bb["width"], "h": bb["height"]})

    else:
        # Use original boxes from bbs/ + initial alignments from pairs/
        src_boxes_raw = {b["id"]: b for b in src_bb_file["boxes"]}
        tgt_boxes_raw = {b["id"]: b for b in tgt_bb_file["boxes"]}
        alignments_raw = aln_data["alignments"]

        pairs, skip_a, skip_b = _collect_one_to_one(alignments_raw, "src_box", "tgt_box")

        for aid in sorted(skip_a):
            print(f"Warning: src-box {aid!r} is multi-aligned — excluded.", file=sys.stderr)
        for bid in sorted(skip_b):
            print(f"Warning: tgt-box {bid!r} is multi-aligned — excluded.", file=sys.stderr)

        ordered_src_ids = sorted(pairs.keys(), key=_int_suffix)
        src_texts, src_bbs_out, tgt_texts, tgt_bbs_out = [], [], [], []
        for sid in ordered_src_ids:
            tid = pairs[sid]
            bs = src_boxes_raw[sid]
            bt = tgt_boxes_raw[tid]
            src_texts.append(bs["text"])
            src_bbs_out.append({"x": bs["x"], "y": bs["y"], "w": bs["w"], "h": bs["h"]})
            tgt_texts.append(bt["text"])
            tgt_bbs_out.append({"x": bt["x"], "y": bt["y"], "w": bt["w"], "h": bt["h"]})

    # --- Write output ---------------------------------------------------------
    output = {
        "alignment_method": alignment_method,
        "source_language": src_lang,
        "source_PNG": src_png,
        "source_texts": src_texts,
        "source_text_bounding_boxes": src_bbs_out,
        "target_language": tgt_lang,
        "target_PNG": tgt_png,
        "target_texts": tgt_texts,
        "target_text_bounding_boxes": tgt_bbs_out,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=4)

    src = "corrected annotations" if annotator else "original boxes"
    print(f"Written {len(src_texts)} aligned pair(s) from {src} to {output_json}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert an annotated batch pair back to the original JSON format."
    )
    parser.add_argument(
        "batch_dir",
        type=Path,
        help="Root of the batch directory (contains bbs/, pairs/, datasets/).",
    )
    parser.add_argument("pair_id", help="Pair identifier (e.g. pair_001).")
    parser.add_argument("output_json", type=Path, help="Destination original-format JSON file.")
    parser.add_argument(
        "--annotator",
        metavar="USER",
        default=None,
        help=(
            "If given, use this annotator's corrected annotations "
            "(datasets/<USER>/<pair_id>/annotations.json) instead of the original boxes."
        ),
    )
    args = parser.parse_args()

    if not args.batch_dir.exists():
        print(f"Error: batch directory not found: {args.batch_dir}", file=sys.stderr)
        sys.exit(1)

    convert(args.batch_dir, args.pair_id, args.output_json, args.annotator)


if __name__ == "__main__":
    main()
