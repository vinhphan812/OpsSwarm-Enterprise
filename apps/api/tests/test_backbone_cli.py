
import pytest
from unittest.mock import MagicMock, patch
from retailtwin_api.backbone_cli import main
from retailtwin_api.backbone import SALE_COMPLETED

def test_backbone_cli_smoke():
    with patch("retailtwin_api.backbone_cli.load_fixture") as mock_load:
        mock_load.return_value = MagicMock(event_id="test-id", correlation_id="test-corr", event_type=SALE_COMPLETED)
        with patch("retailtwin_api.backbone_cli.run_trace") as mock_run:
            mock_run.return_value = {"report": "success"}
            
            with patch("retailtwin_api.backbone_cli.DEFAULT_FIXTURE", new=MagicMock()):
                exit_code = main(["smoke"])
                assert exit_code == 0
                mock_run.assert_called_once()

def test_backbone_cli_publish():
    with patch("retailtwin_api.backbone_cli.load_fixture") as mock_load:
        mock_load.return_value = MagicMock(event_id="test-id", correlation_id="test-corr", event_type=SALE_COMPLETED)
        with patch("retailtwin_api.backbone_cli.GcloudPipe") as mock_pipe:
            with patch("retailtwin_api.backbone_cli.DEFAULT_FIXTURE", new=MagicMock()):
                exit_code = main(["publish"])
                assert exit_code == 0
                mock_pipe.return_value.publish.assert_called_once()
        
def test_backbone_cli_invalid_command():
    with patch("sys.stderr"):
        with pytest.raises(SystemExit):
            main(["invalid"])

def test_backbone_cli_file_not_found():
    with patch("retailtwin_api.backbone_cli.load_fixture", side_effect=FileNotFoundError):
        with pytest.raises(FileNotFoundError):
            main(["smoke"])

from retailtwin_api.backbone import BackboneError

def test_backbone_cli_backbone_error():
    with patch("retailtwin_api.backbone_cli.load_fixture", side_effect=BackboneError("fail")):
        with patch("sys.stderr"):
            exit_code = main(["smoke"])
            assert exit_code == 1

import os
from pathlib import Path
from retailtwin_api.backbone_cli import _load_env_file

def test_load_env_file():
    env_file = Path("test.env")
    env_file.write_text("KEY=VALUE\n#comment\n\n  KEY2 = VALUE2  \n")
    _load_env_file(env_file)
    assert os.environ["KEY"] == "VALUE"
    assert os.environ["KEY2"] == "VALUE2"
    env_file.unlink()
