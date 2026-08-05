#!/usr/bin/env python3

"""Create deterministic Zeek conn.log events for Phase 6 validation."""

import argparse
import json
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument(
        "--append",
        action="store_true",
        help="ajoute les événements au fichier au lieu de le remplacer",
    )
    parser.add_argument(
        "--timestamp-offset",
        type=float,
        default=0,
        help="décalage en secondes appliqué au timestamp courant",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.count < 1:
        raise SystemExit("--count doit etre superieur a zero")

    timestamp = time.time() + args.timestamp_offset
    args.output.parent.mkdir(parents=True, exist_ok=True)

    mode = "a" if args.append else "w"
    with args.output.open(mode, encoding="utf-8") as output_file:
        for sequence in range(args.count):
            event = {
                "ts": timestamp + (sequence / 1_000_000),
                "uid": f"{args.marker}-{sequence:08d}",
                "id.orig_h": "192.0.2.10",
                "id.orig_p": 20000 + (sequence % 40000),
                "id.resp_h": "198.51.100.20",
                "id.resp_p": 502,
                "proto": "tcp",
                "service": "modbus",
                "duration": 0.01,
                "orig_bytes": 12,
                "resp_bytes": 18,
                "conn_state": "SF",
                "local_orig": True,
                "local_resp": False,
                "missed_bytes": 0,
                "history": "ShADadFf",
                "orig_pkts": 4,
                "orig_ip_bytes": 228,
                "resp_pkts": 4,
                "resp_ip_bytes": 234,
            }
            output_file.write(json.dumps(event, separators=(",", ":")))
            output_file.write("\n")

    print(f"{args.count} evenements ecrits dans {args.output}")


if __name__ == "__main__":
    main()
