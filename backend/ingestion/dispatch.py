from __future__ import annotations

import fnmatch
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


DISPATCH_TABLE: tuple[ParserRoute, ...] = (
    ParserRoute(
        parser_name="watch_history",
        callable_path="backend.ingestion.parsers.watch_history:parse_watch_history",
        path_pattern="watch-history.html",
    ),
    ParserRoute(
        parser_name="watch_history",
        callable_path="backend.ingestion.parsers.watch_history:parse_watch_history",
        path_pattern="watch-history.json",
    ),
    ParserRoute(
        parser_name="subscriptions",
        callable_path="backend.ingestion.parsers.subscriptions:parse_subscriptions",
        path_pattern="subscriptions.csv",
    ),
    ParserRoute(
        parser_name="subscriptions",
        callable_path="backend.ingestion.parsers.subscriptions:parse_subscriptions",
        path_pattern="subscriptions.json",
    ),
    ParserRoute(
        parser_name="likes_playlists",
        callable_path="backend.ingestion.parsers.likes_playlists:parse_likes_playlists",
        path_pattern="likes.json",
    ),
    ParserRoute(
        parser_name="likes_playlists",
        callable_path="backend.ingestion.parsers.likes_playlists:parse_likes_playlists",
        path_pattern="playlists/*.json",
    ),
    ParserRoute(
        parser_name="comments_live_chat",
        callable_path=(
            "backend.ingestion.parsers.comments_live_chat:parse_comments_live_chat"
        ),
        path_pattern="comments.csv",
    ),
    ParserRoute(
        parser_name="comments_live_chat",
        callable_path=(
            "backend.ingestion.parsers.comments_live_chat:parse_comments_live_chat"
        ),
        path_pattern="live chats.csv",
    ),
    ParserRoute(
        parser_name="comments_live_chat",
        callable_path=(
            "backend.ingestion.parsers.comments_live_chat:parse_comments_live_chat"
        ),
        path_pattern="my-comments/*.html",
    ),
    ParserRoute(
        parser_name="comments_live_chat",
        callable_path=(
            "backend.ingestion.parsers.comments_live_chat:parse_comments_live_chat"
        ),
        path_pattern="my-live-chat-messages/*.html",
    ),
)


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

    for route in DISPATCH_TABLE:
        if _matches(normalized_path, route.path_pattern):
            return DispatchResult(
                source_path=source_path,
                parser_name=route.parser_name,
                callable_path=route.callable_path,
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
