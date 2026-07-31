#!/usr/bin/env python3
"""
webapp_to_orig.py — Convert a webapp pair directory back to the original format.

The webapp allows n:m alignments, while the original format only supports
implicit 1:1 alignment by index position.  This script therefore:
  • Emits only boxes that participate in a 1:1 alignment.
  • Skips boxes that are unaligned or involved in multi-alignments, and
    prints a warning for each skipped box.

Because metadata (licensing, image URLs, alignment_method, …) is not stored
in the webapp format, an original JSON file must be supplied as a template.
The bounding boxes and texts in the output are taken from the corrected
webapp annotations; everything else is copied from the template.

Usage:
    python webapp_to_orig.py <pair_dir> <orig_template_json> <output_json>

Example:
    python webapp_to_orig.py ./data/datasets/user1/pair_001 \\
        ./orig_data/train/543/es-it.json \\
        ./out/543/es-it.json
"""

import argparse
import json
import sys
from pathlib import Path


def _collect_one_to_one(alignments: list[dict]) -> tuple[dict[str, str], set[str], set[str]]:
    """
    Return:
      pairs    — {box_a_id: box_b_id} for strictly 1:1 aligned pairs
      skip_a   — set of A-box IDs excluded (unaligned or multi-aligned)
      skip_b   — set of B-box IDs excluded (unaligned or multi-aligned)
    """
    a_counts: dict[str, int] = {}
    b_counts: dict[str, int] = {}
    for aln in alignments:
        a_counts[aln["boxA"]] = a_counts.get(aln["boxA"], 0) + 1
        b_counts[aln["boxB"]] = b_counts.get(aln["boxB"], 0) + 1

    pairs: dict[str, str] = {}
    for aln in alignments:
        aid, bid = aln["boxA"], aln["boxB"]
        if a_counts[aid] == 1 and b_counts[bid] == 1:
            pairs[aid] = bid

    all_a = {aln["boxA"] for aln in alignments}
    all_b = {aln["boxB"] for aln in alignments}
    skip_a = all_a - set(pairs.keys())
    skip_b = all_b - set(pairs.values())
    return pairs, skip_a, skip_b


def convert(pair_dir: Path, template_json: Path, output_json: Path) -> None:
    ann_file = pair_dir / "annotations.json"
    if not ann_file.exists():
        raise FileNotFoundError(f"annotations.json not found in {pair_dir}")

    with ann_file.open("r", encoding="utf-8") as fh:
        annotations = json.load(fh)

    with template_json.open("r", encoding="utf-8") as fh:
        template = json.load(fh)

    # Index boxes by id
    boxes_a = {b["id"]: b for b in annotations["svgA"]["boxes"]}
    boxes_b = {b["id"]: b for b in annotations["svgB"]["boxes"]}
    alignments = annotations.get("alignments", [])

    pairs, skip_a, skip_b = _collect_one_to_one(alignments)

    # Warn about excluded boxes
    for aid in sorted(skip_a):
        print(f"Warning: A-box {aid!r} is unaligned or multi-aligned — excluded.", file=sys.stderr)
    for bid in sorted(skip_b):
        print(f"Warning: B-box {bid!r} is unaligned or multi-aligned — excluded.", file=sys.stderr)

    # Also warn about boxes not in any alignment at all
    aligned_a = {aln["boxA"] for aln in alignments}
    aligned_b = {aln["boxB"] for aln in alignments}
    for aid in sorted(set(boxes_a) - aligned_a):
        print(f"Warning: A-box {aid!r} has no alignment entry — excluded.", file=sys.stderr)
    for bid in sorted(set(boxes_b) - aligned_b):
        print(f"Warning: B-box {bid!r} has no alignment entry — excluded.", file=sys.stderr)

    # Build ordered lists of 1:1 pairs, preserving A-box order (numeric sort on ID suffix)
    def _box_sort_key(aid: str) -> int:
        suffix = aid.lstrip("ABab")
        return int(suffix) if suffix.isdigit() else 0

    ordered_a_ids = sorted(pairs.keys(), key=_box_sort_key)
    src_texts, src_bbs, tgt_texts, tgt_bbs = [], [], [], []
    for aid in ordered_a_ids:
        bid = pairs[aid]
        ba = boxes_a[aid]
        bb = boxes_b[bid]
        src_texts.append(ba["text"])
        src_bbs.append({"x": ba["x"], "y": ba["y"], "w": ba["width"], "h": ba["height"]})
        tgt_texts.append(bb["text"])
        tgt_bbs.append({"x": bb["x"], "y": bb["y"], "w": bb["width"], "h": bb["height"]})

    # Compose output using template for metadata
    output = {
        "alignment_method": template.get("alignment_method", "manual"),
        "source_language": template["source_language"],
        "source_PNG": template.get("source_PNG", {}),
        "source_texts": src_texts,
        "source_text_bounding_boxes": src_bbs,
        "target_language": template["target_language"],
        "target_PNG": template.get("target_PNG", {}),
        "target_texts": tgt_texts,
        "target_text_bounding_boxes": tgt_bbs,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=4)

    print(
        f"Written {len(src_texts)} aligned pair(s) to {output_json}"
        + (
            f" ({len(skip_a) + len(set(boxes_a) - aligned_a)} A-box(es) and "
            f"{len(skip_b) + len(set(boxes_b) - aligned_b)} B-box(es) excluded)"
            if skip_a or skip_b or (set(boxes_a) - aligned_a) or (set(boxes_b) - aligned_b)
            else ""
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a webapp pair directory back to original JSON format."
    )
    parser.add_argument("pair_dir", type=Path, help="Webapp pair directory (contains annotations.json).")
    parser.add_argument(
        "orig_template_json",
        type=Path,
        help="Original JSON file used as a metadata template (licensing, image URLs, …).",
    )
    parser.add_argument("output_json", type=Path, help="Destination original-format JSON file.")
    args = parser.parse_args()

    for p in (args.pair_dir, args.orig_template_json):
        if not p.exists():
            print(f"Error: path not found: {p}", file=sys.stderr)
            sys.exit(1)

    convert(args.pair_dir, args.orig_template_json, args.output_json)


if __name__ == "__main__":
    main()
