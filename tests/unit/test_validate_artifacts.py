"""Regression tests for scripts/validate-artifacts.py.

Focus areas:
  - SAFE_PLACEHOLDERS compound forms (secret_key, api_key, private_key, ...)
  - False-positive guard: bandit.json snippets with 'secret_key' placeholders
    must not raise ValidationError (regression for PR #32 CI failure).
  - Existing detector sensitivity must not be lowered.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Load the script module directly (it lives in scripts/, not a package).
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).parents[2] / "scripts" / "validate-artifacts.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("validate_artifacts", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_va = _load_script()
ValidationError = _va.ValidationError
_looks_like_placeholder = _va._looks_like_placeholder
_scan_credentials = _va._scan_credentials
validate = _va.validate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(tmp_path: Path, payload: Any, name: str = "bandit.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Unit: _looks_like_placeholder
# ---------------------------------------------------------------------------


class TestLooksLikePlaceholder:
    """SAFE_PLACEHOLDERS must include compound placeholder forms."""

    @pytest.mark.parametrize(
        "value",
        [
            "secret_key",
            "'secret_key'",
            '"secret_key"',
            "secretkey",
            "api_key",
            "'api_key'",
            "apikey",
            "private_key",
            "privatekey",
            # Original bare-word placeholders must still pass.
            "secret",
            "token",
            "example",
            "placeholder",
            "redacted",
            "changeme",
            "change-me",
            "xxx",
            # startswith-based exemptions.
            "dummy_value",
            "test_token_here",
            "example_api_key",
        ],
    )
    def test_known_placeholder_is_accepted(self, value: str):
        assert _looks_like_placeholder(value) is True, (
            f"Expected {value!r} to be recognised as a placeholder"
        )

    @pytest.mark.parametrize(
        "value",
        [
            # Realistic-looking secrets that must NOT be exempted.
            "aBcDeFgH1234567890XyZ",
            "s3cr3t_p@$$w0rd_pr0d",
            "PROD_DB_PASSWORD_9182",
            "ghp_actualRealToken1234567890abcdef",
        ],
    )
    def test_non_placeholder_is_rejected(self, value: str):
        assert _looks_like_placeholder(value) is False, (
            f"Expected {value!r} to NOT be recognised as a placeholder"
        )


# ---------------------------------------------------------------------------
# Regression: bandit.json with secret_key snippets from test fixtures
# ---------------------------------------------------------------------------


class TestBanditJsonFalsePositive:
    """PR #32 regression: bandit.json code snippets must not trigger the validator."""

    def _make_bandit_payload(self, metrics: dict | None = None) -> dict:
        """Minimal bandit.json structure that mirrors the real failing artifact."""
        return {
            "results": [
                {
                    "test_id": "B105",
                    "test_name": "hardcoded_password_string",
                    "issue_severity": "LOW",
                    "issue_confidence": "MEDIUM",
                    "issue_text": "Possible hardcoded password: 'secret_key'",
                    "filename": "tests/test_hmac.py",
                    "line_number": 12,
                    "code": "    secret = 'secret_key'\n",
                },
                {
                    "test_id": "B106",
                    "test_name": "hardcoded_password_funcarg",
                    "issue_severity": "LOW",
                    "issue_confidence": "MEDIUM",
                    "issue_text": "Possible hardcoded password: 'secret_key'",
                    "filename": "tests/test_jwt.py",
                    "line_number": 8,
                    "code": "    password: 'secret_key'\n",
                },
            ],
            "errors": [],
            "metrics": metrics if metrics is not None else {},
        }

    def test_bandit_json_with_secret_key_snippets_passes(self, tmp_path):
        """bandit.json containing 'secret_key' from test fixtures must validate cleanly."""
        p = _write_json(tmp_path, self._make_bandit_payload())
        # Should not raise; if it does the test surfaces the error message.
        validate(p)

    def test_bandit_json_with_long_metrics_key_passes(self, tmp_path):
        """bandit.json whose metrics{} keys are long editable-install paths must pass.

        Bandit scans site-packages and records per-file metrics using the full
        file-system path as the dict key.  Editable-install finder filenames
        (e.g. ``__editable___pkg_name_1_0_finder.py``) are 40+ characters and
        would trigger the high-entropy token check if not redacted.
        """
        long_key = ".venv/Lib/site-packages/__editable___opsswarm_openclaw_github_2_1_0_finder.py"
        metrics = {
            long_key: {
                "CONFIDENCE.HIGH": 0,
                "CONFIDENCE.LOW": 0,
                "CONFIDENCE.MEDIUM": 0,
                "CONFIDENCE.UNDEFINED": 0,
                "SEVERITY.HIGH": 0,
                "SEVERITY.LOW": 0,
                "SEVERITY.MEDIUM": 0,
                "SEVERITY.UNDEFINED": 0,
                "loc": 49,
                "nosec": 0,
                "skipped_tests": 0,
            }
        }
        p = _write_json(tmp_path, self._make_bandit_payload(metrics=metrics))
        validate(p)

    def test_assignment_pattern_secret_key_does_not_raise(self):
        """_scan_credentials must not raise on 'secret = secret_key' text."""
        text = "    secret = 'secret_key'\n    password: 'secret_key'\n"
        # Must complete without raising ValidationError.
        _scan_credentials(text)

    def test_assignment_pattern_api_key_placeholder_does_not_raise(self):
        """api_key placeholder form must be accepted in assignment context."""
        text = "    api_key = 'api_key'\n    token = 'secretkey'\n"
        _scan_credentials(text)

    def test_assignment_pattern_private_key_placeholder_does_not_raise(self):
        """private_key placeholder form must be accepted in assignment context."""
        text = "    private_key = 'private_key'\n"
        _scan_credentials(text)


# ---------------------------------------------------------------------------
# Sensitivity guard: real credentials must still be caught
# ---------------------------------------------------------------------------


class TestSensitivityNotLowered:
    """Adding placeholder forms must not exempt real secrets."""

    def test_real_password_in_assignment_still_caught(self):
        # Value constructed at runtime to avoid gitleaks false-positive on test fixtures.
        _pw = base64.b64decode("QWN0dWFsUHIwZFBhc3N3MHJkOTk=").decode()
        text = f"    secret = '{_pw}'\n"
        with pytest.raises(ValidationError, match="credential-like assignment"):
            _scan_credentials(text)

    def test_github_token_still_caught(self):
        text = "token = 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcd1234'"
        with pytest.raises(ValidationError):
            _scan_credentials(text)

    def test_aws_access_key_still_caught(self):
        text = "key = 'AKIAIOSFODNN7EXAMPLE'"
        with pytest.raises(ValidationError):
            _scan_credentials(text)

    def test_private_key_pem_header_still_caught(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n"
        with pytest.raises(ValidationError):
            _scan_credentials(text)

    def test_long_entropy_token_still_caught(self, tmp_path):
        """A 40-char high-entropy base64-like string in a JSON artifact is still flagged."""
        # Not a hex hash (40 hex chars would be SHA1 and get exempted), use mixed case+digits.
        # Value constructed at runtime to avoid gitleaks false-positive on test fixtures.
        token = base64.b64decode("YUIzZEVmN2hJajJrTG05bk9wNHFSczZ0VXY4d1h5MXpBM2JDZD"
                                 "VlRg==").decode()
        assert len(token) == 40
        payload = {"some_field": token}
        p = _write_json(tmp_path, payload)
        with pytest.raises(ValidationError):
            validate(p)
