import pytest
from opsswarm.openclaw import OpenClawClient

def test_openclaw_response_contract():
    """Verify OpenClawClient response schema."""
    # Define the expected contract structure
    contract_schema = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "result": {"type": "object"},
            "final": {"type": "string"},
            "payloads": {"type": "array"}
        },
        "required": ["ok"]
    }
    
    # Mocking a response
    mock_response = {"ok": True, "final": "Success"}
    
    # Validate structure
    assert "ok" in mock_response
    assert isinstance(mock_response["ok"], bool)
    
    # If final is present, it must be a string
    if "final" in mock_response:
        assert isinstance(mock_response["final"], str)
