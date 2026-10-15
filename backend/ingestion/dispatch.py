from __future__ import annotations

import fnmatch
import posixpath
from dataclasses import dataclass
from importlib import import_module

from backend.ingestion.models import ParserCallable


@dataclass(frozen=True)
class ParserRoute:
    parser_name: str
    callable_path: str
    path_pattern: str


@dataclass(frozen=True)
class DispatchResult:
    source_path: str
    parser_name: str | None
    callable_path: str | None
    ignored: bool
    reason: str | None = None

    def load_parser(self) -> ParserCallable:
        if self.callable_path is None:
            raise LookupError("ignored ZIP member has no parser")
        return resolve_parser(self.callable_path)


WATCH_HISTORY_CALLABLE = "backend.ingestion.parsers.watch_history:parse_watch_history"
SEARCH_HISTORY_CALLABLE = "backend.ingestion.parsers.search_history:parse_search_history"
YOUTUBE_ACTIVITY_AUTO_CALLABLE = (
    "backend.ingestion.parsers.youtube_activity_auto:parse_youtube_activity_auto"
)
TIKTOK_WATCH_HISTORY_CALLABLE = (
    "backend.ingestion.parsers.tiktok_watch_history:parse_tiktok_watch_history"
)
INSTAGRAM_ACTIVITY_CALLABLE = (
    "backend.ingestion.parsers.instagram_activity:parse_instagram_activity"
)
SUBSCRIPTIONS_CALLABLE = "backend.ingestion.parsers.subscriptions:parse_subscriptions"
LIKES_PLAYLISTS_CALLABLE = (
    "backend.ingestion.parsers.likes_playlists:parse_likes_playlists"
)
COMMENTS_LIVE_CHAT_CALLABLE = (
    "backend.ingestion.parsers.comments_live_chat:parse_comments_live_chat"
)


def _routes(parser_name: str, callable_path: str, *patterns: str) -> tuple[ParserRoute, ...]:
    return tuple(
        ParserRoute(
            parser_name=parser_name,
            callable_path=callable_path,
            path_pattern=pattern,
        )
        for pattern in patterns
    )


# Instagram offers every export as HTML or JSON; both use the same base names.
_INSTAGRAM_ACTIVITY_BASES = (
    "your_instagram_activity/story_interactions/stories_viewed",
    "your_instagram_activity/story_interactions/story_likes",
    "your_instagram_activity/likes/liked_posts",
    "your_instagram_activity/saved/saved_posts",
    "ads_information/ads_and_topics/posts_viewed",
    "ads_information/ads_and_topics/videos_watched",
    "your_instagram_activity/content/posts",
    "your_instagram_activity/content/posts_*",
    "your_instagram_activity/content/reels",
    "your_instagram_activity/content/stories",
    "your_instagram_activity/followers_and_following/recently_unfollowed_profiles",
    "connections/followers_and_following/recently_unfollowed_profiles",
)


DISPATCH_TABLE: tuple[ParserRoute, ...] = (
    *_routes(
        "watch_history",
        WATCH_HISTORY_CALLABLE,
        "watch-history.html",
        "watch-history.json",
        # German Takeout ("YouTube und YouTube Music/Verlauf/...").
        "verlauf/wiedergabeverlauf.html",
        "verlauf/wiedergabeverlauf.json",
    ),
    *_routes(
        "search_history",
        SEARCH_HISTORY_CALLABLE,
        "search-history.json",
        "search-history.html",
        "my activity/youtube/myactivity.json",
        "my activity/youtube/myactivity.html",
        "verlauf/suchverlauf.html",
        "verlauf/suchverlauf.json",
    ),
    *_routes(
        "tiktok_watch_history",
        TIKTOK_WATCH_HISTORY_CALLABLE,
        "user_data_tiktok.json",
        # Older TikTok exports ("Activity" -> "Video Browsing History").
        "user_data.json",
    ),
    *_routes(
        "instagram_activity",
        INSTAGRAM_ACTIVITY_CALLABLE,
        *(f"{base}.html" for base in _INSTAGRAM_ACTIVITY_BASES),
        *(f"{base}.json" for base in _INSTAGRAM_ACTIVITY_BASES),
        "your_instagram_activity/messages/**/*.html",
        "your_instagram_activity/messages/**/message_*.json",
    ),
    *_routes(
        "subscriptions",
        SUBSCRIPTIONS_CALLABLE,
        "subscriptions.csv",
        "subscriptions.json",
        "abos/abos.csv",
        "abos/abos.json",
    ),
    *_routes(
        "likes_playlists",
        LIKES_PLAYLISTS_CALLABLE,
        "likes.json",
        "playlists/*.json",
        # Current Takeout format: one "<playlist>-videos.csv" per playlist.
        "playlists/*.csv",
    ),
    *_routes(
        "comments_live_chat",
        COMMENTS_LIVE_CHAT_CALLABLE,
        "comments.csv",
        "live chats.csv",
        # German Takeout: "Kommentare/Kommentare.csv", one CSV per chat in "Livechats/".
        "kommentare/*.csv",
        "livechats/*.csv",
        "my-comments/*.html",
        "my-live-chat-messages/*.html",
        "youtube*/meine kommentare/*.html",
        "youtube*/meine-live-chat-nachrichten/*.html",
    ),
)

# ---------------------------------------------------------------------------
# Language-independent fallback for files inside a YouTube Takeout folder.
#
# Folder names are localised ("YouTube and YouTube Music", "YouTube und
# YouTube Music", "YouTube y YouTube Music", ...) but always start with
# "YouTube"; file names inside them are localised too.  Files the table above
# does not know are routed by structure:
#   <My Activity>/YouTube/<file>.json|html -> search history (as in English)
#   any other YouTube .json/.html file     -> youtube_activity_auto, which
#                                             classifies every record by URL
# ---------------------------------------------------------------------------

LOCALIZED_SUBSCRIPTION_STEMS = frozenset(
    {
        "subscriptions",
        "abos",  # de
        "suscripciones",  # es
        "abonnements",  # fr
        "iscrizioni",  # it
        "inscrições",  # pt
        "inscricoes",
        "abonnementen",  # nl
    }
)
LOCALIZED_PLAYLIST_FOLDERS = frozenset(
    {
        "playlists",
        "playlist",  # it
        "listas de reproducción",  # es
        "listas de reproduccion",
        "listas de reprodução",  # pt
        "listas de reproducao",
        "afspeellijsten",  # nl
    }
)
LOCALIZED_COMMENT_FOLDERS = frozenset(
    {
        "my-comments",
        "my-live-chat-messages",
        "meine kommentare",  # de
        "meine-kommentare",
        "meine-live-chat-nachrichten",
    }
)
_ACTIVITY_EXTENSIONS = frozenset({".json", ".html", ".htm"})
_HTML_EXTENSIONS = frozenset({".html", ".htm"})


def dispatch_member_path(source_path: str) -> DispatchResult:
    normalized_path = normalize_member_path(source_path)
    if is_unsafe_member_path(normalized_path):
        return DispatchResult(
            source_path=source_path,
            parser_name=None,
            callable_path=None,
            ignored=True,
            reason="unsafe_path",
        )

    route = _table_route(normalized_path) or _youtube_folder_route(normalized_path)
    if route is not None:
        return DispatchResult(
            source_path=source_path,
            parser_name=route[0],
            callable_path=route[1],
            ignored=False,
        )

    return DispatchResult(
        source_path=source_path,
        parser_name=None,
        callable_path=None,
        ignored=True,
        reason="no_parser",
    )


def parser_name_for_path(source_path: str) -> str | None:
    return dispatch_member_path(source_path).parser_name


def resolve_parser(callable_path: str) -> ParserCallable:
    module_name, separator, function_name = callable_path.partition(":")
    if not separator or not module_name or not function_name:
        raise ValueError(f"invalid parser callable path: {callable_path}")

    parser = getattr(import_module(module_name), function_name)
    if not callable(parser):
        raise TypeError(f"parser is not callable: {callable_path}")
    return parser


def normalize_member_path(source_path: str) -> str:
    parts = [
        part
        for part in source_path.replace("\\", "/").strip("/").split("/")
        if part and part != "."
    ]
    return "/".join(part.lower() for part in parts)


def is_unsafe_member_path(normalized_path: str) -> bool:
    return any(part == ".." for part in normalized_path.split("/"))


def _table_route(normalized_path: str) -> tuple[str, str] | None:
    for route in DISPATCH_TABLE:
        if _matches(normalized_path, route.path_pattern):
            return route.parser_name, route.callable_path
    return None


def _youtube_folder_route(normalized_path: str) -> tuple[str, str] | None:
    parts = normalized_path.split("/")
    folders, file_name = parts[:-1], parts[-1]
    youtube_index = next(
        (index for index, folder in enumerate(folders) if folder.startswith("youtube")),
        None,
    )
    if youtube_index is None:
        return None

    stem, extension = posixpath.splitext(file_name)
    inner_folders = folders[youtube_index + 1 :]
    parent = inner_folders[-1] if inner_folders else None

    if extension == ".csv":
        if stem in LOCALIZED_SUBSCRIPTION_STEMS:
            return "subscriptions", SUBSCRIPTIONS_CALLABLE
        if parent in LOCALIZED_PLAYLIST_FOLDERS:
            return "likes_playlists", LIKES_PLAYLISTS_CALLABLE
        return None

    if extension not in _ACTIVITY_EXTENSIONS:
        return None
    if parent in LOCALIZED_COMMENT_FOLDERS:
        if extension in _HTML_EXTENSIONS:
            return "comments_live_chat", COMMENTS_LIVE_CHAT_CALLABLE
        return None
    if parent in LOCALIZED_PLAYLIST_FOLDERS:
        if extension == ".json":
            return "likes_playlists", LIKES_PLAYLISTS_CALLABLE
        return None
    if stem in LOCALIZED_SUBSCRIPTION_STEMS:
        if extension == ".json":
            return "subscriptions", SUBSCRIPTIONS_CALLABLE
        return None

    is_my_activity_file = (
        parent is None and folders[youtube_index] == "youtube" and youtube_index > 0
    )
    if is_my_activity_file:
        # "<My Activity, localised>/YouTube/<MyActivity, localised>.json|html":
        # like the English route, only searches are imported from My Activity.
        return "search_history", SEARCH_HISTORY_CALLABLE

    return "youtube_activity_auto", YOUTUBE_ACTIVITY_AUTO_CALLABLE


def _matches(normalized_path: str, path_pattern: str) -> bool:
    normalized_pattern = normalize_member_path(path_pattern)
    if "/" not in normalized_pattern:
        return (
            normalized_path == normalized_pattern
            or normalized_path.endswith(f"/{normalized_pattern}")
        )
    return fnmatch.fnmatch(normalized_path, normalized_pattern) or fnmatch.fnmatch(
        normalized_path, f"*/{normalized_pattern}"
    )
