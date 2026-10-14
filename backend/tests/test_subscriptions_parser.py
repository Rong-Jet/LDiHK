from __future__ import annotations

import unittest

from backend.ingestion.models import ParseWarning, ParsedSubscription
from backend.ingestion.parsers.subscriptions import parse_subscriptions


class SubscriptionsParserTests(unittest.TestCase):
    def test_standard_csv_headers_emit_subscriptions(self):
        content = (
            "Channel Id,Channel Url,Channel Title\n"
            "UC123,https://www.youtube.com/channel/UC123,Example Channel\n"
            "UC456,https://www.youtube.com/channel/UC456,Another Channel\n"
        ).encode("utf-8")

        result = parse_subscriptions(
            content,
            source_path=(
                "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv"
            ),
        )

        self.assertEqual(
            result.subscriptions,
            [
                ParsedSubscription(
                    channel_id="UC123",
                    channel_url="https://www.youtube.com/channel/UC123",
                    channel_title="Example Channel",
                ),
                ParsedSubscription(
                    channel_id="UC456",
                    channel_url="https://www.youtube.com/channel/UC456",
                    channel_title="Another Channel",
                ),
            ],
        )
        self.assertEqual(result.events, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.records_seen, 2)

    def test_title_and_url_columns_are_optional(self):
        content = "Channel Id\nUC123\n".encode("utf-8")

        result = parse_subscriptions(
            content,
            source_path=(
                "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv"
            ),
        )

        self.assertEqual(
            result.subscriptions,
            [
                ParsedSubscription(
                    channel_id="UC123",
                    channel_url=None,
                    channel_title=None,
                ),
            ],
        )
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.records_seen, 1)

    def test_duplicate_channel_ids_are_deduped_within_one_file(self):
        content = (
            "Channel Id,Channel Url,Channel Title\n"
            "UC123,https://www.youtube.com/channel/UC123,Example Channel\n"
            "UC123,https://www.youtube.com/channel/UC123,Duplicate Channel\n"
            "UC456,https://www.youtube.com/channel/UC456,Another Channel\n"
        ).encode("utf-8")

        result = parse_subscriptions(
            content,
            source_path=(
                "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv"
            ),
        )

        self.assertEqual(
            result.subscriptions,
            [
                ParsedSubscription(
                    channel_id="UC123",
                    channel_url="https://www.youtube.com/channel/UC123",
                    channel_title="Example Channel",
                ),
                ParsedSubscription(
                    channel_id="UC456",
                    channel_url="https://www.youtube.com/channel/UC456",
                    channel_title="Another Channel",
                ),
            ],
        )
        self.assertEqual(result.records_seen, 3)

    def test_malformed_rows_emit_warnings_without_failing(self):
        content = (
            "Channel Id,Channel Url,Channel Title\n"
            ",https://www.youtube.com/channel/missing,Missing ID\n"
            "UC123,https://www.youtube.com/channel/UC123,Example Channel\n"
        ).encode("utf-8")

        result = parse_subscriptions(
            content,
            source_path=(
                "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv"
            ),
        )

        self.assertEqual(
            result.subscriptions,
            [
                ParsedSubscription(
                    channel_id="UC123",
                    channel_url="https://www.youtube.com/channel/UC123",
                    channel_title="Example Channel",
                ),
            ],
        )
        self.assertEqual(
            result.warnings,
            [ParseWarning(code="missing_channel_id", sample="row 1")],
        )
        self.assertEqual(result.records_seen, 2)

    def test_json_subscription_snapshot_emits_subscriptions(self):
        content = b"""
        [
          {
            "Channel Id": "UC123",
            "Channel Url": "https://www.youtube.com/channel/UC123",
            "Channel Title": "Example Channel"
          }
        ]
        """

        result = parse_subscriptions(
            content,
            source_path=(
                "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.json"
            ),
        )

        self.assertEqual(
            result.subscriptions,
            [
                ParsedSubscription(
                    channel_id="UC123",
                    channel_url="https://www.youtube.com/channel/UC123",
                    channel_title="Example Channel",
                ),
            ],
        )
        self.assertEqual(result.events, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.records_seen, 1)

    def test_json_subscription_resource_shape_emits_subscriptions(self):
        content = b"""
        {
          "items": [
            {
              "snippet": {
                "title": "Example Channel",
                "resourceId": {
                  "channelId": "UC123"
                }
              }
            }
          ]
        }
        """

        result = parse_subscriptions(
            content,
            source_path=(
                "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.json"
            ),
        )

        self.assertEqual(
            result.subscriptions,
            [
                ParsedSubscription(
                    channel_id="UC123",
                    channel_url=None,
                    channel_title="Example Channel",
                ),
            ],
        )
        self.assertEqual(result.records_seen, 1)

    def test_localized_csv_headers_emit_subscriptions(self):
        channel_id = "UCabcdefghijklmnopqrstuv"
        cases = {
            "de": "Kanal-ID,Kanal-URL,Kanaltitel",
            "es": "ID del canal,URL del canal,Título del canal",
            "fr": "ID de la chaîne,URL de la chaîne,Titre de la chaîne",
            "it": "ID del canale,URL del canale,Titolo del canale",
            "pt": "ID do canal,URL do canal,Título do canal",
            "nl": "Kanaal-ID,Kanaal-URL,Kanaaltitel",
        }

        for language, header in cases.items():
            with self.subTest(language=language):
                content = (
                    f"﻿{header}\n"
                    f"{channel_id},http://www.youtube.com/channel/{channel_id},Beispielkanal\n"
                ).encode("utf-8")

                result = parse_subscriptions(
                    content,
                    source_path="Takeout/YouTube und YouTube Music/Abos/Abos.csv",
                )

                self.assertEqual(result.warnings, [])
                self.assertEqual(
                    result.subscriptions,
                    [
                        ParsedSubscription(
                            channel_id=channel_id,
                            channel_url=f"http://www.youtube.com/channel/{channel_id}",
                            channel_title="Beispielkanal",
                        )
                    ],
                )

    def test_unknown_header_language_falls_back_to_value_detection(self):
        channel_id = "UCabcdefghijklmnopqrstuv"
        content = (
            "Identyfikator kanału,Adres URL kanału,Nazwa kanału\n"
            f"{channel_id},http://www.youtube.com/channel/{channel_id},Kanał\n"
        ).encode("utf-8")

        result = parse_subscriptions(
            content,
            source_path="Takeout/YouTube i YouTube Music/subskrypcje/subskrypcje.csv",
        )

        self.assertEqual(result.warnings, [])
        self.assertEqual(
            result.subscriptions,
            [
                ParsedSubscription(
                    channel_id=channel_id,
                    channel_url=f"http://www.youtube.com/channel/{channel_id}",
                    channel_title="Kanał",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
