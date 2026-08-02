#!/usr/bin/env python3
"""Sort bounding boxes in an existing webapp data directory.

The sort is performed in place on the shared native-format BB files.  Box IDs
are preserved so that existing alignments and annotations remain valid.

Usage:
    python sort_bbs.py <data_dir>
"""

import argparse
import json
from pathlib import Path


def _position_key(box: dict) -> tuple[float, float]:
    """Sort boxes from top to bottom, then left to right."""
    return (float(box["y"]), float(box["x"]))


def sort_bb_file(bb_file: Path) -> None:
    """Sort one native-format BB file in place."""
    with bb_file.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    boxes = data.get("boxes")
    if not isinstance(boxes, list):
        raise ValueError(f"BB file has no boxes list: {bb_file}")

    boxes.sort(key=_position_key)
    with bb_file.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def find_bb_files(data_dir: Path) -> list[Path]:
    """Return all native-format BB files under a webapp data directory."""
    return sorted((data_dir / "bbs").glob("*/*.json"))


def sort_bbs(data_dir: Path) -> int:
    """Sort all BB files under *data_dir* and return the number processed."""
    bb_files = find_bb_files(data_dir)
    for bb_file in bb_files:
        sort_bb_file(bb_file)
    return len(bb_files)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sort bounding boxes in an existing webapp data directory."
    )
    parser.add_argument(
        "data_dir",
        type=Path,
        help="Root of the webapp data directory (contains bbs/).",
    )
    args = parser.parse_args()

    if not args.data_dir.is_dir():
        parser.error(f"data directory not found: {args.data_dir}")

    count = sort_bbs(args.data_dir)
    print(f"Sorted {count} BB file(s) in {args.data_dir / 'bbs'}")


if __name__ == "__main__":
    main()
