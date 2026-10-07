"""Offline research CSV runner; invoke from the editable-installed environment."""

import argparse
from pathlib import Path

from dx27.intelligence.sentinel.research.trend_tournament import (
    csv_metadata,
    read_csv,
    run_tournament,
    write_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="DX27 research-only Trend Detector Tournament v0.1")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--symbols", help="Explicit comma-separated subset; default requires all Stage-A symbols")
    args = parser.parse_args()
    symbols = args.symbols.split(",") if args.symbols is not None else None
    try:
        result = run_tournament(read_csv(args.input_csv), symbols, input_metadata=csv_metadata(args.input_csv))
        write_outputs(result, args.output_dir)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Wrote {len(result.observations)} research states, {len(result.metrics)} metric rows, "
          f"{len(result.sensitivity)} sensitivity rows to {args.output_dir}")


if __name__ == "__main__":
    main()
