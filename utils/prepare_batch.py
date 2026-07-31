#!/usr/bin/env python3
"""
prepare_batch.py — Sample N image pairs from an original-data directory and
produce a ready-to-use webapp batch directory.

The script recursively searches <data_dir> for original-format JSON files
(files whose name matches the pattern <src>-<tgt>.json inside a directory
that also contains an svg/ sub-directory), randomly selects up to <n_pairs>
of them, converts each one with orig_to_webapp, and writes the result under
<output_dir>/pair_NNN/.

Usage:
    python prepare_batch.py <data_dir> <n_pairs> <output_dir> [--seed SEED]

Arguments:
    data_dir    Root directory that contains the original image records
                (e.g. orig_data/train).
    n_pairs     Number of image pairs to include in the batch.
    output_dir  Destination directory for the webapp batch.

Options:
    --seed SEED  Random seed for reproducible sampling (default: none).

Example:
    python prepare_batch.py ../orig_data/train 5 ./batches/batch_01 --seed 42
"""

import argparse
import random
import sys
from pathlib import Path

# Allow importing sibling script without installing a package
_UTILS_DIR = Path(__file__).parent
sys.path.insert(0, str(_UTILS_DIR))
from orig_to_webapp import convert  # noqa: E402


def find_orig_jsons(data_dir: Path) -> list[Path]:
    """Return all original-format JSON files found under data_dir."""
    results = []
    for json_file in sorted(data_dir.rglob("*.json")):
        # Each record lives in a directory that also has an svg/ sub-directory
        if (json_file.parent / "svg").is_dir():
            results.append(json_file)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare a webapp annotation batch from original-format data."
    )
    parser.add_argument("data_dir", type=Path, help="Root directory of original data.")
    parser.add_argument("n_pairs", type=int, help="Number of image pairs to include.")
    parser.add_argument("output_dir", type=Path, help="Destination webapp batch directory.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible sampling.")
    args = parser.parse_args()

    if not args.data_dir.exists():
        print(f"Error: data directory not found: {args.data_dir}", file=sys.stderr)
        sys.exit(1)

    if args.n_pairs < 1:
        print("Error: n_pairs must be a positive integer.", file=sys.stderr)
        sys.exit(1)

    all_jsons = find_orig_jsons(args.data_dir)
    if not all_jsons:
        print(f"Error: no original-format JSON files found under {args.data_dir}", file=sys.stderr)
        sys.exit(1)

    if args.seed is not None:
        random.seed(args.seed)

    n = min(args.n_pairs, len(all_jsons))
    if n < args.n_pairs:
        print(
            f"Warning: only {len(all_jsons)} record(s) available; "
            f"producing {n} pair(s) instead of {args.n_pairs}.",
            file=sys.stderr,
        )

    selected = random.sample(all_jsons, n)

    print(f"Converting {n} pair(s) into {args.output_dir} …")
    for idx, json_file in enumerate(selected, start=1):
        pair_id = f"pair_{idx:03d}"
        out = args.output_dir / pair_id
        print(f"  [{idx}/{n}] {json_file.relative_to(args.data_dir)}  →  {pair_id}")
        convert(json_file, out)

    print(f"\nDone. Batch written to: {args.output_dir}")
    print(f"Pair IDs: {', '.join(f'pair_{i:03d}' for i in range(1, n + 1))}")


if __name__ == "__main__":
    main()
