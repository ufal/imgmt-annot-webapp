#!/usr/bin/env python3
"""Sort bounding boxes in an existing webapp data directory.

The sort is performed in place on the shared native-format BB files.  Box IDs
are preserved so that existing alignments and annotations remain valid.

Usage:
    python sort_bbs.py <data_dir> [--user USER_ID]
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


def find_bb_files(data_dir: Path, user_id: str | None = None) -> list[Path]:
    """Return BB files, optionally limited to pairs assigned to a user."""
    if user_id is None:
        return sorted((data_dir / "bbs").glob("*/*.json"))

    users_file = data_dir / "users.json"
    with users_file.open("r", encoding="utf-8") as fh:
        users = json.load(fh)
    if user_id not in users:
        raise ValueError(f"User not found in {users_file}: {user_id}")

    bb_files: set[Path] = set()
    for pair_id in users[user_id].get("datasets", []):
        alignment_file = data_dir / "pairs" / pair_id / "alignments.json"
        if not alignment_file.exists():
            raise FileNotFoundError(f"Alignment file not found: {alignment_file}")
        with alignment_file.open("r", encoding="utf-8") as fh:
            pair = json.load(fh)
        image_id = pair["image_id"]
        for language_key in ("src_lang", "tgt_lang"):
            bb_files.add(data_dir / "bbs" / image_id / f"{pair[language_key]}.json")

    return sorted(bb_files)


def sort_bbs(data_dir: Path, user_id: str | None = None) -> int:
    """Sort BB files, optionally limited to pairs assigned to a user."""
    bb_files = find_bb_files(data_dir, user_id)
    for bb_file in bb_files:
        if not bb_file.exists():
            raise FileNotFoundError(f"BB file not found: {bb_file}")
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
    parser.add_argument(
        "--user",
        dest="user_id",
        help="Sort only BBs belonging to pairs assigned to this user.",
    )
    args = parser.parse_args()

    if not args.data_dir.is_dir():
        parser.error(f"data directory not found: {args.data_dir}")

    count = sort_bbs(args.data_dir, args.user_id)
    scope = f" assigned to {args.user_id!r}" if args.user_id else ""
    print(f"Sorted {count} BB file(s){scope} in {args.data_dir / 'bbs'}")


if __name__ == "__main__":
    main()
