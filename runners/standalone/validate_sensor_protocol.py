"""Validate the frozen 6B-2G design artifact; does not fetch or score market data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dx27.intelligence.sentinel.research.sensor_protocol import verify_protocol_lock


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol-dir', type=Path, default=Path(__file__).resolve().parents[2] /
                        'research/sentinel/6b-2g-contracts')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    report = verify_protocol_lock(args.protocol_dir / 'protocol.json',
                                  args.protocol_dir / 'protocol_lock.json')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'protocol_validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
