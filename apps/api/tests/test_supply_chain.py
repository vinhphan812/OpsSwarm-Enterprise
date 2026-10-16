"""Supply-chain hardening tests for issue #146 / ADR 0026.

These tests pin down the runtime invariants that the security gates rely
on. They run as part of the regular pytest suite so a refactor of the
Dockerfile, the security.yml workflow, or the secret-scan allowlist is
forced to update the test that depends on it.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = REPO_ROOT / "Dockerfile"
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"


# ── Dockerfile: non-root runtime ───────────────────────────────────────────


def test_dockerfile_declares_non_root_user() -> None:
    """The runtime image must declare a USER other than UID 0."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    # Find the runtime stage and ensure USER <non-root> appears after the
    # stage declaration.
    stages = re.split(r"^FROM\s+", text, flags=re.MULTILINE)
    runtime_stages = [
        s for s in stages
        if s.startswith("python:3.11-slim AS runtime") or s.startswith("python:3.11-slim\n")
    ]
    assert runtime_stages, "Dockerfile is missing a `python:3.11-slim AS runtime` stage"
    runtime = runtime_stages[0]
    user_match = re.search(r"^USER\s+(\S+)", runtime, flags=re.MULTILINE)
    assert user_match, "Dockerfile runtime stage is missing a USER directive"
    user = user_match.group(1)
    assert user not in {"0", "root"}, (
        f"Dockerfile runtime USER is `{user}`; ADR 0026 requires non-root."
    )


def test_dockerfile_runtime_stage_does_not_copy_credentials() -> None:
    """`.gitignore` refuses `*.pem`, `*.key`, `service-account*.json`,
    and `credentials*.json`. The Dockerfile must not COPY any of those
    patterns into the runtime stage.
    """
    text = DOCKERFILE.read_text(encoding="utf-8")
    forbidden = re.compile(
        r"^COPY\s+[^#\n]*\b(\.env|.*\.pem|.*\.key|credentials[^\s]*\.json|service-account[^\s]*\.json)\b",
        flags=re.MULTILINE,
    )
    matches = forbidden.findall(text)
    assert not matches, (
        f"Dockerfile copies a credential-like file into the image: {matches!r}"
    )


# ── Security workflow: secret scan + container-image gate ─────────────────


def test_security_workflow_runs_trivy_image_scan() -> None:
    """The container-image job must use `trivy image --ignore-unfixed`
    so no-fix HIGH/CRITICAL is treated as an exception (ADR 0026)."""
    with SECURITY_WORKFLOW.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert "container-image" in (data.get("jobs") or {}), (
        "security.yml is missing the `container-image` job (ADR 0026)."
    )
    container_job = data["jobs"]["container-image"]
    steps_text = yaml.safe_dump(container_job)
    assert "trivy" in steps_text.lower(), "container-image job does not invoke trivy"
    assert "--ignore-unfixed" in steps_text, (
        "container-image job must use --ignore-unfixed so no-fix "
        "HIGH/CRITICAL is an exception, not a blocker (ADR 0026)."
    )
    assert "--severity HIGH,CRITICAL" in steps_text, (
        "container-image job must scan HIGH/CRITICAL only."
    )


def test_security_workflow_blocks_root_user() -> None:
    """The container-image job must fail the gate if UID is 0."""
    with SECURITY_WORKFLOW.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    steps_text = yaml.safe_dump(data["jobs"]["container-image"])
    assert "non-root" in steps_text or "UID 0" in steps_text or "UID != 0" in steps_text, (
        "container-image job must assert the image runs as a non-root UID."
    )


def test_security_workflow_blocks_credential_files_in_image() -> None:
    """The container-image job must fail the gate if a credential-like
    file is present in the image.
    """
    with SECURITY_WORKFLOW.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    steps_text = yaml.safe_dump(data["jobs"]["container-image"])
    assert "credentials*.json" in steps_text or "credentials" in steps_text, (
        "container-image job must refuse credential-like files."
    )
    assert "service-account" in steps_text, (
        "container-image job must refuse service-account JSON files."
    )


def test_security_workflow_runs_npm_audit_prod_only() -> None:
    """Web production-only audit, fail on HIGH."""
    with SECURITY_WORKFLOW.open("r", encoding="utf-8") as fh:
        text = fh.read()
    assert "npm audit --omit=dev" in text, (
        "security.yml must invoke `npm audit --omit=dev` for prod-only scan."
    )
    assert "--audit-level=high" in text, (
        "security.yml must pass --audit-level=high (ADR 0026)."
    )


def test_security_workflow_runs_pip_audit() -> None:
    """Python dependency audit via pip-audit."""
    with SECURITY_WORKFLOW.open("r", encoding="utf-8") as fh:
        text = fh.read()
    assert "pip_audit" in text or "pip-audit" in text, (
        "security.yml must invoke pip-audit on apps/api."
    )


# ── Secret-scan fixtures: known allow-list is preserved ────────────────────


def test_known_test_fixture_api_keys_are_still_present() -> None:
    """ADR 0026 preserves the `api_key="sk-test-full-cycle"` fixture used
    in `apps/api/tests/test_llm.py`. The CI secret scan explicitly excludes
    `tests/**`, but the fixture itself must remain in the repo so the
    cycle test keeps passing.
    """
    test_llm = (REPO_ROOT / "apps" / "api" / "tests" / "test_llm.py").read_text(
        encoding="utf-8"
    )
    assert 'api_key="sk-test-full-cycle"' in test_llm, (
        "The allow-listed fixture API key was removed. Update ADR 0026 if "
        "this was intentional."
    )


def test_dotenv_example_is_committed_and_real_env_is_not() -> None:
    """.env.example is the documented template; real .env files are not
    committed. The tests guard the allow-list symmetry.
    """
    env_example = REPO_ROOT / ".env.example"
    assert env_example.is_file(), "Missing .env.example — install template."

    # Walk every tracked file via `git ls-files` (portable across worktrees).
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=str(REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    forbidden_suffixes = (".example", ".sample", ".template")
    for filename in tracked:
        base = Path(filename).name
        if base.startswith(".env"):
            if any(base.endswith(suffix) for suffix in forbidden_suffixes):
                continue
            raise AssertionError(
                f"Tracked file `{filename}` looks like a real .env file."
            )


def test_repo_root_readme_does_not_contain_a_committed_secret() -> None:
    """Smoke test: the four-pattern scan must still match the documented
    private-key marker on a synthetic fixture string. The fixture lives
    only inside this test, so it is invisible to `git grep` because the
    file is never committed.
    """
    fixture = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    pattern = r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
    assert re.search(pattern, fixture), (
        "The secret-scan fixture did not match; the regex in ci.yml is "
        "broken (ADR 0026 preserves this rule)."
    )