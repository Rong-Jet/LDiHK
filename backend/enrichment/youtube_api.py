from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv import load_dotenv


MAX_VIDEO_IDS_PER_REQUEST = 50
YOUTUBE_VIDEOS_LIST_URL = "https://www.googleapis.com/youtube/v3/videos"


class YouTubeApiError(RuntimeError):
    pass


class YouTubeDataApiClient:
    def __init__(self, api_key: str, *, timeout_seconds: int = 30):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(
        cls, *, env_path: Path | str | None = None, timeout_seconds: int = 30
    ) -> YouTubeDataApiClient:
        if env_path is None:
            load_dotenv()
        else:
            load_dotenv(dotenv_path=Path(env_path))

        api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("youtube_api_key_missing")
        return cls(api_key, timeout_seconds=timeout_seconds)

    def list_videos(self, video_ids: Sequence[str]) -> list[dict[str, object]]:
        video_ids = list(video_ids)
        if not video_ids:
            return []
        if len(video_ids) > MAX_VIDEO_IDS_PER_REQUEST:
            raise ValueError("videos.list accepts at most 50 video IDs")

        query = urlencode(
            {
                "part": "contentDetails,status",
                "id": ",".join(video_ids),
                "key": self.api_key,
            }
        )
        url = f"{YOUTUBE_VIDEOS_LIST_URL}?{query}"
        try:
            with urlopen(url, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise YouTubeApiError(_http_error_message(error)) from error
        except URLError as error:
            raise YouTubeApiError(str(error.reason)) from error
        except json.JSONDecodeError as error:
            raise YouTubeApiError("invalid_json_response") from error

        if not isinstance(payload, dict):
            raise YouTubeApiError("invalid_response")
        if "error" in payload:
            raise YouTubeApiError(_api_error_message(payload["error"]))

        items = payload.get("items", [])
        if not isinstance(items, list):
            raise YouTubeApiError("invalid_items_response")
        return [item for item in items if isinstance(item, dict)]


def _http_error_message(error: HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except Exception:
        return f"http_{error.code}"
    return _api_error_message(payload.get("error", payload))


def _api_error_message(error_payload: object) -> str:
    if isinstance(error_payload, dict):
        message = error_payload.get("message")
        if isinstance(message, str) and message:
            return message
        code = error_payload.get("code")
        if code is not None:
            return f"api_error_{code}"
    return "api_error"

