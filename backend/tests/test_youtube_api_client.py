import json
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from backend.enrichment.youtube_api import YouTubeDataApiClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class YouTubeDataApiClientTests(unittest.TestCase):
    def test_calls_videos_list_with_duration_and_status_parts(self):
        response = FakeResponse(
            {"items": [{"id": "a", "contentDetails": {"duration": "PT1M"}}]}
        )

        with patch("backend.enrichment.youtube_api.urlopen", return_value=response) as urlopen:
            items = YouTubeDataApiClient("api-key").list_videos(["a", "b"])

        requested_url = urlopen.call_args.args[0]
        query = parse_qs(urlparse(requested_url).query)
        self.assertEqual(query["part"], ["contentDetails,status"])
        self.assertEqual(query["id"], ["a,b"])
        self.assertEqual(query["key"], ["api-key"])
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)
        self.assertEqual(items, [{"id": "a", "contentDetails": {"duration": "PT1M"}}])

    def test_rejects_more_than_50_video_ids(self):
        client = YouTubeDataApiClient("api-key")

        with self.assertRaises(ValueError):
            client.list_videos([f"video-{index:02d}" for index in range(51)])


if __name__ == "__main__":
    unittest.main()

