#!/usr/bin/env python3
"""
Clean-wheel smoke harness for OpsSwarm Enterprise.

Validates a built wheel by installing it in an isolated venv and verifying:
1. Package imports resolve to site-packages (not repo source)
2. pip check passes (no broken dependencies)
3. /health endpoint returns the expected contract
4. External config and OPSWARM_DATA_DIR work correctly

Usage:
    python smoke-wheel.py <wheel-path> <config-path> [--port <port>]

Arguments:
    wheel-path:  Path to the built .whl file
    config-path: Path to a YAML config file (e.g., config/test.yaml)
    port:       Optional port for health check (default: 8765)

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
    2 - Invalid arguments or setup error
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path

EXPECTED_HEALTH = {"ok": True, "version": "2.1.0", "architecture": "openclaw+github"}


def parse_args() -> tuple[Path, Path, int]:
    parser = argparse.ArgumentParser(description="Smoke test for OpsSwarm wheel")
    parser.add_argument("wheel", type=Path, help="Path to wheel file")
    parser.add_argument("config", type=Path, help="Path to config YAML file")
    parser.add_argument("--port", type=int, default=8765, help="Port for health check")
    args = parser.parse_args()

    if not args.wheel.exists():
        print(f"ERROR: Wheel not found: {args.wheel}", file=sys.stderr)
        sys.exit(2)
    if not args.config.exists():
        print(f"ERROR: Config not found: {args.config}", file=sys.stderr)
        sys.exit(2)

    return args.wheel, args.config, args.port


def create_venv(dest: Path) -> Path:
    """Create an isolated venv and return the python executable path."""
    if dest.exists():
        shutil.rmtree(dest)
    venv.create(dest, with_pip=True)
    if os.name == "nt":
        return dest / "Scripts" / "python.exe"
    return dest / "bin" / "python"


def install_wheel(python: Path, wheel: Path) -> None:
    """Install the wheel into the venv."""
    result = subprocess.run(
        [str(python), "-m", "pip", "install", str(wheel)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Failed to install wheel:\n{result.stderr}", file=sys.stderr)
        sys.exit(2)
    print(f"Installed wheel: {wheel.name}")


def check_import_origin(python: Path) -> bool:
    """Verify that opsswarm imports come from site-packages, not repo source."""
    # Don't set OPSWARM_CONFIG - let it use defaults (None). Setting it to empty string
    # causes load_config() to treat Path("") as a config path and fail.
    result = subprocess.run(
        [str(python), "-c", "import opsswarm.api; print(opsswarm.api.__file__)"],
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k not in ("OPSWARM_CONFIG", "OPSWARM_DATA_DIR")},
    )

    if result.returncode != 0:
        print(f"ERROR: Failed to import opsswarm:\n{result.stderr}", file=sys.stderr)
        return False

    module_path = result.stdout.strip()
    print(f"Module loaded from: {module_path}")

    # Must be in site-packages, not the repo source
    if "site-packages" not in module_path:
        print(f"FAIL: Module not from site-packages: {module_path}", file=sys.stderr)
        return False

    print("PASS: Import resolves to site-packages")
    return True


def check_pip_check(python: Path) -> bool:
    """Verify pip check passes (no broken dependencies)."""
    result = subprocess.run(
        [str(python), "-m", "pip", "check"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"FAIL: pip check found issues:\n{result.stdout}", file=sys.stderr)
        return False

    print("PASS: pip check clean")
    return True


def check_health(python: Path, config_path: Path, port: int) -> bool:
    """Start server briefly and check /health endpoint."""
    # Resolve config to absolute path BEFORE changing cwd
    config_path = config_path.resolve()

    # Use a temp directory for working directory (outside repo)
    with tempfile.TemporaryDirectory() as tmpdir:
        env = {
            **os.environ,
            "OPSWARM_CONFIG": str(config_path),
            "OPSWARM_DATA_DIR": tmpdir,
            # No GITHUB_TOKEN - we're testing the health endpoint only
        }

        # Start uvicorn in background using the venv Python (not host sys.executable)
        proc = subprocess.Popen(
            [
                str(python), "-m", "uvicorn",
                "opsswarm.api:app",
                "--host", "127.0.0.1",
                "--port", str(port),
            ],
            cwd=tmpdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            time.sleep(3)  # Give server time to start

            # Try to connect
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                conn.request("GET", "/health")
                response = conn.getresponse()
                body = response.read().decode("utf-8")
            finally:
                conn.close()

            if response.status != 200:
                print(f"FAIL: /health returned {response.status}: {body}", file=sys.stderr)
                return False

            try:
                data = json.loads(body)
            except json.JSONDecodeError as e:
                print(f"FAIL: Invalid JSON from /health: {e}", file=sys.stderr)
                return False

            if data != EXPECTED_HEALTH:
                print(f"FAIL: Unexpected health response: {data}", file=sys.stderr)
                print(f"Expected: {EXPECTED_HEALTH}", file=sys.stderr)
                return False

            print("PASS: /health returns expected contract")
            return True

        except Exception as e:
            print(f"ERROR: Health check failed: {e}", file=sys.stderr)
            return False

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> int:
    wheel_path, config_path, port = parse_args()

    print(f"=== Clean Wheel Smoke Test ===")
    print(f"Wheel: {wheel_path}")
    print(f"Config: {config_path}")
    print(f"Port: {port}")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        venv_path = Path(tmpdir) / "venv"
        python = create_venv(venv_path)

        print(f"Created venv: {venv_path}")
        install_wheel(python, wheel_path)
        print()

        checks = [
            ("Import origin", lambda: check_import_origin(python)),
            ("pip check", lambda: check_pip_check(python)),
            ("Health endpoint", lambda: check_health(python, config_path, port)),
        ]

        results = []
        for name, fn in checks:
            print(f"--- {name} ---")
            results.append(fn())
            print()

        print("=== Summary ===")
        all_passed = all(results)
        for (name, _), passed in zip(checks, results):
            status = "PASS" if passed else "FAIL"
            print(f"  {name}: {status}")

        if all_passed:
            print("\nAll checks PASSED")
            return 0
        else:
            print("\nSome checks FAILED", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
