
import json
import hashlib
from opsswarm.evidence import EvidenceStore

def test_tamper_detection(tmp_path):
    ev = EvidenceStore(data_dir=str(tmp_path))
    run_id = "tamper_run"

    # 1. Create a chain
    ev.append(run_id, "S4.finding", {"task_id": "T1", "finding": "F1"})
    ev.append(run_id, "S4.finding", {"task_id": "T2", "finding": "F2"})

    records = ev.list(run_id)
    assert len(records) == 2

    # 2. Verify helper
    def verify_chain(records):
        prev_sig = "GENESIS"
        for r in records:
            kind = r["kind"]
            payload = r["payload"]

            # Recompute signature
            # We need the same logic as _signature_with_chain
            # Copy-pasting logic from evidence.py for verification
            # This is not ideal as it duplicates logic but it's a test case.

            # The logic in EvidenceStore._signature_with_chain:
            # sig_input = f"{kind}:{json.dumps(stable, sort_keys=True, default=str)}:{prev_sig}"

            # Let's replicate the stable payload extraction
            from opsswarm.evidence import SIGNATURE_KEY_FIELDS
            key_fields = SIGNATURE_KEY_FIELDS.get(kind)
            if key_fields is None:
                stable = {k: v for k, v in payload.items()
                          if k not in ('timestamp', 'eid', 'id', 'run_id')}
            else:
                stable = {k: payload.get(k) for k in key_fields if k in payload}

            sig_input = f"{kind}:{json.dumps(stable, sort_keys=True, default=str)}:{prev_sig}"
            recomputed = hashlib.sha256(sig_input.encode("utf-8")).hexdigest()[:16]

            if recomputed != r["signature"]:
                return False, f"Signature mismatch for {r['id']}: expected {r['signature']}, got {recomputed}"

            prev_sig = r["signature"]
        return True, "Chain valid"

    is_valid, msg = verify_chain(records)
    assert is_valid, msg

    # 3. Tamper
    records[1]["payload"]["finding"] = "TAMPERED"

    # 4. Re-verify
    is_valid, msg = verify_chain(records)
    assert not is_valid, "Tampering should have been detected"
