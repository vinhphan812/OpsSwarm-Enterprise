"""Independent evidence verification CLI tests."""

from opsswarm.cli import VERIFY_INVALID, VERIFY_OK, main
from opsswarm.evidence import EvidenceStore


def test_verify_cli_pass(tmp_path, capsys):
    store = EvidenceStore(tmp_path)
    store.append("run", "checkpoint", {"phase": "start"})
    assert main(["evidence", "verify", "run", "--data-dir", str(tmp_path)]) == VERIFY_OK
    assert "PASS" in capsys.readouterr().out


def test_verify_cli_fail(tmp_path, capsys):
    store = EvidenceStore(tmp_path)
    store.append("run", "checkpoint", {"phase": "start"})
    path = tmp_path / "evidence" / "run.jsonl"
    path.write_text(path.read_text().replace("start", "tampered"), encoding="utf-8")
    assert main(["evidence", "verify", "run", "--data-dir", str(tmp_path)]) == VERIFY_INVALID
    captured = capsys.readouterr()
    assert "FAIL" in captured.err
    assert "ERROR" in captured.err


def test_cli_unsupported_command(capsys):
    from opsswarm.cli import main
    import pytest
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_cli_unsupported_evidence_command(capsys):
    from opsswarm.cli import main, VERIFY_USAGE
    import pytest
    with pytest.raises(SystemExit) as exc:
        main(["evidence", "unknown"])
    assert exc.value.code == VERIFY_USAGE


