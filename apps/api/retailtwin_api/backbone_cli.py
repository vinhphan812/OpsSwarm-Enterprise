"""Publish a sale.completed fixture and trace it through store-events."""

import argparse
import json
import os
import sys
from pathlib import Path

from retailtwin_api.backbone import (
    DEFAULT_FIXTURE,
    BackboneError,
    config_from_env,
    load_fixture,
    require_sale,
    run_trace,
)
from retailtwin_api.backbone_gcp import BigQuerySink, FirestoreRest, GcloudPipe, SubprocessRunner
from retailtwin_api.settings import REPO_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish and trace a sale.completed store event.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("smoke", "publish"):
        command = subcommands.add_parser(name)
        command.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args(argv)
    try:
        _load_env_file(REPO_ROOT / ".env")
        event = load_fixture(args.fixture)
        require_sale(event)
        config = config_from_env()
        runner = SubprocessRunner()
        pipe = GcloudPipe(config, runner)
        if args.command == "publish":
            pipe.publish(event)
            print(json.dumps({"published": event.event_id, "correlation_id": event.correlation_id}))
            return 0
        ledger = FirestoreRest(config, runner)
        report = run_trace(event, pipe, BigQuerySink(config, runner), ledger=ledger, quarantine=ledger)
        print(json.dumps(report))
        return 0
    except BackboneError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
