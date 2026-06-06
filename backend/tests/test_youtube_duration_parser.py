import unittest

from backend.enrichment.durations import parse_youtube_duration


class YoutubeDurationParserTests(unittest.TestCase):
    def test_parses_minutes_and_seconds(self):
        self.assertEqual(parse_youtube_duration("PT15M33S"), 933)

    def test_parses_hours_minutes_seconds_and_days(self):
        self.assertEqual(parse_youtube_duration("PT1H2M3S"), 3723)
        self.assertEqual(parse_youtube_duration("P1DT2H"), 93600)

    def test_parses_zero_duration(self):
        self.assertEqual(parse_youtube_duration("PT0S"), 0)

    def test_rejects_empty_or_ambiguous_durations(self):
        for duration in ("P", "PT", "P1M", "not-a-duration"):
            with self.subTest(duration=duration):
                with self.assertRaises(ValueError):
                    parse_youtube_duration(duration)


if __name__ == "__main__":
    unittest.main()

