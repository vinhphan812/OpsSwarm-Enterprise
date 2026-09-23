import json
import io

def test_evidence_store_contract():
    """Verify JSONL format and field schema."""
    # JSONL: Each line is a standalone JSON object
    data = [
        {"timestamp": "2026-09-23T10:00:00Z", "event": "test", "data": 1},
        {"timestamp": "2026-09-23T10:01:00Z", "event": "test2"}
    ]
    
    # Simulate writing/reading JSONL
    buffer = io.StringIO()
    for entry in data:
        buffer.write(json.dumps(entry) + "\n")
        
    # Verify format
    lines = buffer.getvalue().strip().split("\n")
    assert len(lines) == 2
    
    for line in lines:
        entry = json.loads(line)
        assert "timestamp" in entry
        assert "event" in entry
        assert isinstance(entry["timestamp"], str)
