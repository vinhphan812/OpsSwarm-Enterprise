"""Unit tests for opsswarm.config module."""
import os

import pytest

from opsswarm.config import load_config, _expand


class TestExpand:
    """Tests for the _expand function."""

    def test_expand_string_no_vars(self):
        """Plain string without variables passes through."""
        result = _expand("hello world")
        assert result == "hello world"

    def test_expand_string_with_env_var(self):
        """String with environment variable gets expanded."""
        os.environ["TEST_VAR"] = "test_value"
        result = _expand("${TEST_VAR}")
        assert result == "test_value"
        del os.environ["TEST_VAR"]

    def test_expand_string_missing_env_var_unchanged(self):
        """Missing environment variable leaves placeholder unchanged."""
        result = _expand("${MISSING_VAR_12345}")
        assert result == "${MISSING_VAR_12345}"

    def test_expand_list(self):
        """List values are recursively expanded."""
        os.environ["LIST_VAL"] = "expanded"
        result = _expand(["static", "${LIST_VAL}"])
        assert result == ["static", "expanded"]
        del os.environ["LIST_VAL"]

    def test_expand_dict(self):
        """Dict values are recursively expanded."""
        os.environ["DICT_VAL"] = "value123"
        result = _expand({"key1": "static", "key2": "${DICT_VAL}"})
        assert result == {"key1": "static", "key2": "value123"}
        del os.environ["DICT_VAL"]

    def test_expand_nested_structure(self):
        """Nested structures are fully expanded."""
        os.environ["OUTER"] = "outer_val"
        os.environ["INNER"] = "inner_val"
        result = _expand({"outer": {"inner": "${INNER}", "static": "static"}})
        assert result == {"outer": {"inner": "inner_val", "static": "static"}}
        del os.environ["OUTER"]
        del os.environ["INNER"]

    def test_expand_non_string_unchanged(self):
        """Non-string values pass through unchanged."""
        assert _expand(123) == 123
        assert _expand(None) is None
        assert _expand(True) is True


class TestLoadConfig:
    """Tests for the load_config function."""

    def test_load_config_default_path(self, monkeypatch, tmp_path):
        """Loads config from default path when env var not set."""
        # Create a temporary config file
        config_content = "repo: test-repo\nlabels:\n  base: [test, label]"
        config_file = tmp_path / "production.yaml"
        config_file.write_text(config_content)

        monkeypatch.setenv("OPSWARM_CONFIG", str(config_file))
        result = load_config()

        assert result["repo"] == "test-repo"
        assert result["labels"]["base"] == ["test", "label"]

    def test_load_config_explicit_path(self, tmp_path):
        """Loads config from explicit path argument."""
        config_content = "repo: explicit-repo\ndebug: true"
        config_file = tmp_path / "explicit.yaml"
        config_file.write_text(config_content)

        result = load_config(str(config_file))

        assert result["repo"] == "explicit-repo"
        assert result["debug"] is True

    def test_load_config_expands_env_vars(self, monkeypatch, tmp_path):
        """Config file values can reference environment variables."""
        monkeypatch.setenv("OPSWARM_CUSTOM_REPO", "env-repo")
        config_content = "repo: ${OPSWARM_CUSTOM_REPO}"
        config_file = tmp_path / "env_expand.yaml"
        config_file.write_text(config_content)

        result = load_config(str(config_file))

        assert result["repo"] == "env-repo"

    def test_load_config_missing_file_raises(self, monkeypatch):
        """Missing config file raises FileNotFoundError."""
        monkeypatch.delenv("OPSWARM_CONFIG", raising=False)
        with pytest.raises(FileNotFoundError):
            load_config("/this/path/does/not/exist/ever.yaml")

    def test_load_config_empty_file(self, tmp_path):
        """Empty config file returns empty dict."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        result = load_config(str(config_file))
        assert result == {}

    def test_load_config_complex_structure(self, tmp_path):
        """Can load complex nested config structure."""
        config_content = """
repo: org/repo
labels:
  base:
    - opsswarm
    - incident
  severity:
    - sev:1
    - sev:2
    - sev:3
openclaw:
  timeout_seconds: 300
persistence:
  enable_atomic_writes: true
  enable_checkpoints: true
"""
        config_file = tmp_path / "complex.yaml"
        config_file.write_text(config_content)

        result = load_config(str(config_file))

        assert result["repo"] == "org/repo"
        assert result["labels"]["base"] == ["opsswarm", "incident"]
        assert result["openclaw"]["timeout_seconds"] == 300
        assert result["persistence"]["enable_atomic_writes"] is True
        assert result["persistence"]["enable_checkpoints"] is True

    def test_load_config_with_list_of_strings(self, monkeypatch, tmp_path):
        """List in config gets expanded when using proper YAML format."""
        monkeypatch.setenv("LABEL_NAME", "expanded-label")
        # Use YAML block format for list to avoid flow sequence issues with ${}
        config_content = "labels:\n  - static\n  - ${LABEL_NAME}"
        config_file = tmp_path / "list.yaml"
        config_file.write_text(config_content)

        result = load_config(str(config_file))

        assert result["labels"] == ["static", "expanded-label"]
