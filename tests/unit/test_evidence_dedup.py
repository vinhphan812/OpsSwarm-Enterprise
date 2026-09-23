"""Unit tests for evidence deduplication."""
import tempfile

from opsswarm.evidence import EvidenceStore


class TestEvidenceDeduplication:
    def test_append_without_event_id_backward_compatible(self):
        """Test that append works without event_id (backward compatibility)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)
            eid, is_dup = store.append("run1", "finding", {"text": "test"})
            assert eid is not None
            assert eid.startswith("EV-")
            assert is_dup is False

    def test_append_with_event_id(self):
        """Test append with event_id stores idempotency_key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)
            eid, is_dup = store.append("run1", "finding", {"text": "test"}, event_id="evt-001")
            assert eid is not None
            assert is_dup is False

            evidence = store.list("run1")
            assert len(evidence) == 1
            assert "idempotency_key" in evidence[0]
            assert evidence[0]["idempotency_key"] != ""

    def test_duplicate_is_skipped(self):
        """Test that duplicate evidence is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)

            # First append
            eid1, is_dup1 = store.append("run1", "finding", {"text": "test1"}, event_id="evt-001")
            assert eid1 is not None
            assert is_dup1 is False

            # Same signature should be detected as duplicate
            eid2, is_dup2 = store.append("run1", "finding", {"text": "test1"}, event_id="evt-002")
            assert is_dup2 is True  # Now returns (None, True) for duplicates

            # Only one evidence record
            evidence = store.list("run1")
            assert len(evidence) == 1

    def test_different_event_id_succeeds(self):
        """Test that different event_ids are not duplicates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)

            eid1, is_dup1 = store.append("run1", "finding", {"text": "test1"}, event_id="evt-001")
            eid2, is_dup2 = store.append("run1", "finding", {"text": "test2"}, event_id="evt-002")

            assert eid1 is not None
            assert eid2 is not None
            assert is_dup1 is False
            assert is_dup2 is False

            # Both should be appended since payloads are different
            evidence = store.list("run1")
            assert len(evidence) == 2

    def test_different_kind_different_key(self):
        """Test that different kinds produce different idempotency keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)

            eid1, is_dup1 = store.append("run1", "finding", {"text": "test"}, event_id="evt-001")
            eid2, is_dup2 = store.append("run1", "verification", {"text": "test"}, event_id="evt-001")

            assert eid1 is not None
            assert eid2 is not None
            assert is_dup1 is False
            assert is_dup2 is False

            evidence = store.list("run1")
            assert len(evidence) == 2

    def test_idempotency_key_format(self):
        """Test idempotency key is SHA256 hash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)

            store.append("run1", "finding", {"text": "test"}, event_id="evt-001")

            evidence = store.list("run1")
            key = evidence[0]["idempotency_key"]

            # SHA256 produces 64 hex characters
            assert len(key) == 64
            assert all(c in "0123456789abcdef" for c in key)

    def test_signature_based_dedup(self):
        """Test signature-based deduplication ignores event_id for duplicate detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)

            # Same payload with different event_ids should be detected as duplicate
            eid1, is_dup1 = store.append("run1", "finding", {"text": "test"}, event_id="evt-001")
            eid2, is_dup2 = store.append("run1", "finding", {"text": "test"}, event_id="evt-002")
            eid3, is_dup3 = store.append("run1", "finding", {"text": "test"}, event_id="evt-003")

            assert eid1 is not None
            assert is_dup1 is False
            assert is_dup2 is True  # Same signature = duplicate
            assert is_dup3 is True  # Same signature = duplicate

            # Only one evidence record
            evidence = store.list("run1")
            assert len(evidence) == 1

            # Duplicate count should be tracked
            assert store.get_duplicate_count() == 2

    def test_duplicate_count_tracking(self):
        """Test duplicate count is properly tracked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)

            # Add unique evidence
            store.append("run1", "finding", {"text": "test1"})
            store.append("run1", "finding", {"text": "test2"})
            store.append("run1", "finding", {"text": "test3"})

            # Add duplicates
            store.append("run1", "finding", {"text": "test1"})
            store.append("run1", "finding", {"text": "test2"})

            assert store.get_duplicate_count() == 2
