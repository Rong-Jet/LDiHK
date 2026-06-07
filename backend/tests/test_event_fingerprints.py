from __future__ import annotations

from datetime import datetime, timezone
import unittest

from backend.ingestion.fingerprints import event_fingerprint
from backend.ingestion.models import ParsedEvent


class EventFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_deterministic_for_same_event(self):
        event = ParsedEvent(
            event_type="watch",
            product="youtube",
            occurred_at=datetime(2026, 6, 6, 8, 53, 12, tzinfo=timezone.utc),
            video_id="abc123",
            channel_id="UC123",
            sequence=7,
        )

        first = event_fingerprint(
            event,
            user_id="user-1",
            source_path="Takeout/YouTube and YouTube Music/history/watch-history.html",
        )
        second = event_fingerprint(
            event,
            user_id="user-1",
            source_path="Takeout/YouTube and YouTube Music/history/watch-history.html",
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_sequence_contributes_when_native_id_is_absent(self):
        common_fields = {
            "event_type": "watch",
            "product": "youtube",
            "occurred_at": datetime(2026, 6, 6, 8, 53, tzinfo=timezone.utc),
            "video_id": "abc123",
        }

        first = event_fingerprint(
            ParsedEvent(**common_fields, sequence=1),
            user_id="user-1",
            source_path="watch-history.html",
        )
        second = event_fingerprint(
            ParsedEvent(**common_fields, sequence=2),
            user_id="user-1",
            source_path="watch-history.html",
        )

        self.assertNotEqual(first, second)

    def test_native_id_dominates_sequence_and_source_path(self):
        common_fields = {
            "event_type": "comment",
            "product": "youtube",
            "occurred_at": datetime(2026, 6, 6, 8, 53, tzinfo=timezone.utc),
            "native_id": "comment-123",
        }

        first = event_fingerprint(
            ParsedEvent(**common_fields, sequence=1),
            user_id="user-1",
            source_path="comments/comments.csv",
        )
        second = event_fingerprint(
            ParsedEvent(**common_fields, sequence=99),
            user_id="user-1",
            source_path="archive/comments/comments.csv",
        )

        self.assertEqual(first, second)

    def test_native_and_sequence_fingerprints_do_not_collide(self):
        common_fields = {
            "event_type": "comment",
            "product": "youtube",
            "occurred_at": datetime(2026, 6, 6, 8, 53, tzinfo=timezone.utc),
            "sequence": 1,
        }

        native = event_fingerprint(
            ParsedEvent(**common_fields, native_id="comment-123"),
            user_id="user-1",
            source_path="comments/comments.csv",
        )
        sequence = event_fingerprint(
            ParsedEvent(**common_fields),
            user_id="user-1",
            source_path="comments/comments.csv",
        )

        self.assertNotEqual(native, sequence)


if __name__ == "__main__":
    unittest.main()
