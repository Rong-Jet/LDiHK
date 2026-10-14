from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

from backend.ingestion.fingerprints import event_fingerprint, event_fingerprints
from backend.ingestion.models import ParsedEvent


def watch(video_id: str, minute: int, **overrides) -> ParsedEvent:
    fields = {
        "event_type": "watch",
        "product": "youtube",
        "occurred_at": datetime(2026, 6, 6, 8, minute, 12, tzinfo=timezone.utc),
        "video_id": video_id,
        "channel_id": "UC123",
    }
    fields.update(overrides)
    return ParsedEvent(**fields)


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

    def test_sequence_and_source_path_do_not_contribute(self):
        # Previously the record index and file path were hashed, so a newer
        # (newest-first) export or an HTML<->JSON switch duplicated every event.
        common_fields = {
            "event_type": "watch",
            "product": "youtube",
            "occurred_at": datetime(2026, 6, 6, 8, 53, tzinfo=timezone.utc),
            "video_id": "abc123",
        }

        first = event_fingerprint(
            ParsedEvent(**common_fields, sequence=1),
            user_id="user-1",
            source_path="Takeout/YouTube and YouTube Music/history/watch-history.html",
        )
        second = event_fingerprint(
            ParsedEvent(**common_fields, sequence=2),
            user_id="user-1",
            source_path="other-zip/Takeout/history/watch-history.json",
        )

        self.assertEqual(first, second)

    def test_event_fingerprint_matches_batch_fingerprint_for_first_occurrence(self):
        event = watch("abc123", 53)

        single = event_fingerprint(event, user_id="user-1", source_path="a.html")
        batch = event_fingerprints([event], user_id="user-1", source_path="b.json")

        self.assertEqual(batch, [single])

    def test_timestamps_are_normalised_to_utc_whole_seconds(self):
        utc = watch("abc123", 53)
        cest_with_fraction = watch(
            "abc123",
            53,
            occurred_at=datetime(
                2026, 6, 6, 10, 53, 12, 345000, tzinfo=timezone(timedelta(hours=2))
            ),
        )
        naive = watch("abc123", 53, occurred_at=datetime(2026, 6, 6, 8, 53, 12))

        fingerprints = [
            event_fingerprint(event, user_id="user-1", source_path="x")
            for event in (utc, cest_with_fraction, naive)
        ]

        self.assertEqual(len(set(fingerprints)), 1)

    def test_identity_fields_contribute(self):
        base = watch("abc123", 53)
        variants = [
            watch("other", 53),
            watch("abc123", 54),
            watch("abc123", 53, channel_id="UC999"),
            watch("abc123", 53, event_type="like"),
            watch("abc123", 53, platform="tiktok"),
        ]

        base_fingerprint = event_fingerprint(base, user_id="user-1", source_path="x")
        self.assertNotEqual(
            base_fingerprint,
            event_fingerprint(base, user_id="user-2", source_path="x"),
        )
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertNotEqual(
                    base_fingerprint,
                    event_fingerprint(variant, user_id="user-1", source_path="x"),
                )

    def test_presentation_fields_do_not_contribute(self):
        base = watch("abc123", 53, title="Example", raw_status=None, duration_seconds=60)
        variant = watch(
            "abc123",
            53,
            title="Watched Example",
            raw_status="private",
            duration_seconds=12,
            product="youtube_music",
        )

        self.assertEqual(
            event_fingerprint(base, user_id="user-1", source_path="x"),
            event_fingerprint(variant, user_id="user-1", source_path="x"),
        )

    def test_title_is_used_only_without_video_id(self):
        common = {
            "event_type": "liked_post",
            "product": "posts",
            "platform": "instagram",
            "occurred_at": datetime(2026, 6, 5, 13, 27, tzinfo=timezone.utc),
        }

        first = event_fingerprint(
            ParsedEvent(**common, title="creator_one"), user_id="u", source_path="x"
        )
        same_normalised = event_fingerprint(
            ParsedEvent(**common, title="  CREATOR_one "), user_id="u", source_path="x"
        )
        other = event_fingerprint(
            ParsedEvent(**common, title="creator_two"), user_id="u", source_path="x"
        )

        self.assertEqual(first, same_normalised)
        self.assertNotEqual(first, other)

    def test_search_query_contributes(self):
        common = {
            "event_type": "search",
            "product": "youtube",
            "occurred_at": datetime(2026, 6, 6, 6, 53, 12, tzinfo=timezone.utc),
        }

        first = event_fingerprint(
            ParsedEvent(**common, search_query="cats"), user_id="u", source_path="x"
        )
        second = event_fingerprint(
            ParsedEvent(**common, search_query="dogs"), user_id="u", source_path="x"
        )

        self.assertNotEqual(first, second)

    def test_identical_events_in_one_list_get_distinct_occurrence_fingerprints(self):
        repeated = watch(None, 53, channel_id=None, raw_status="deleted")
        other = watch("abc123", 50)

        fingerprints = event_fingerprints(
            [repeated, other, repeated, repeated],
            user_id="user-1",
            source_path="watch-history.html",
        )

        self.assertEqual(len(fingerprints), 4)
        self.assertEqual(len(set(fingerprints)), 4)
        # The first occurrence is the same key event_fingerprint() produces.
        self.assertEqual(
            fingerprints[0],
            event_fingerprint(repeated, user_id="user-1", source_path="x"),
        )
        # Re-running the same list is stable.
        self.assertEqual(
            fingerprints,
            event_fingerprints(
                [repeated, other, repeated, repeated],
                user_id="user-1",
                source_path="elsewhere.json",
            ),
        )

    def test_newer_export_with_prepended_record_shares_existing_fingerprints(self):
        old_export = [watch(f"video-{index}", 59 - index) for index in range(10)]
        newer_export = [watch("brand-new", 59, occurred_at=datetime(
            2026, 6, 6, 9, 30, tzinfo=timezone.utc
        ))] + [
            # Re-numbered sequences, as a real newer export would have.
            ParsedEvent(**{**event.__dict__, "sequence": event.sequence + 1})
            for event in old_export
        ]

        old_fingerprints = event_fingerprints(
            old_export, user_id="user-1", source_path="takeout-1/watch-history.html"
        )
        new_fingerprints = event_fingerprints(
            newer_export, user_id="user-1", source_path="takeout-2/watch-history.html"
        )

        self.assertEqual(len(set(old_fingerprints) & set(new_fingerprints)), 10)
        self.assertEqual(len(set(new_fingerprints) - set(old_fingerprints)), 1)

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

    def test_native_id_fingerprint_is_unchanged_from_version_1(self):
        # Rows imported before the content-based strategy must keep deduping.
        event = ParsedEvent(
            event_type="comment",
            product="youtube",
            occurred_at=datetime(2026, 6, 6, 8, 53, tzinfo=timezone.utc),
            native_id="comment-123",
        )
        legacy_payload = json.dumps(
            {
                "version": 1,
                "strategy": "native_id",
                "user_id": "user-1",
                "event_type": "comment",
                "native_id": "comment-123",
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

        self.assertEqual(
            event_fingerprint(event, user_id="user-1", source_path="x"),
            hashlib.sha256(legacy_payload.encode("utf-8")).hexdigest(),
        )

    def test_native_id_events_are_not_occurrence_counted(self):
        event = ParsedEvent(
            event_type="playlist_add",
            product="youtube",
            occurred_at=None,
            video_id="abc123",
            native_id="item-1",
        )

        fingerprints = event_fingerprints(
            [event, event], user_id="user-1", source_path="x"
        )

        self.assertEqual(fingerprints[0], fingerprints[1])

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
        content = event_fingerprint(
            ParsedEvent(**common_fields),
            user_id="user-1",
            source_path="comments/comments.csv",
        )

        self.assertNotEqual(native, content)


if __name__ == "__main__":
    unittest.main()
