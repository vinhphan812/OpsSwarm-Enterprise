"""OpsSwarm command-line utilities."""

from __future__ import annotations

import argparse
import os
import sys

from .evidence import EvidenceStore

VERIFY_OK = 0
VERIFY_INVALID = 1
VERIFY_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opsswarm")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evidence = subparsers.add_parser("evidence", help="Evidence audit operations")
    evidence_subparsers = evidence.add_subparsers(dest="evidence_command", required=True)
    verify = evidence_subparsers.add_parser("verify", help="Verify an evidence hash chain")
    verify.add_argument("run_id")
    verify.add_argument(
        "--data-dir", default=os.environ.get("OPSWARM_DATA_DIR", "runtime-data")
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a deterministic process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "evidence" and args.evidence_command == "verify":
        valid, errors = EvidenceStore(args.data_dir).verify(args.run_id)
        if valid:
            print(f"PASS: evidence chain valid for run {args.run_id}")
            return VERIFY_OK
        print(f"FAIL: evidence chain invalid for run {args.run_id}", file=sys.stderr)
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return VERIFY_INVALID
    parser.error("unsupported command")
    return VERIFY_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
