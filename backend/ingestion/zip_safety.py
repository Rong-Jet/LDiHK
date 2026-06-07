from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from zipfile import ZipFile, ZipInfo


class UnsafeZipEntryError(ValueError):
    pass


@dataclass(frozen=True)
class SafeZipMember:
    source_path: str
    zip_info: ZipInfo


def iter_safe_zip_members(zip_file: ZipFile):
    for zip_info in zip_file.infolist():
        source_path = safe_zip_member_path(zip_info.filename)
        if zip_info.is_dir():
            continue
        yield SafeZipMember(source_path=source_path, zip_info=zip_info)


def safe_zip_member_path(member_name: str) -> str:
    if "\x00" in member_name:
        raise UnsafeZipEntryError("ZIP member path contains a null byte")

    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/"):
        raise UnsafeZipEntryError(f"unsafe absolute ZIP member path: {member_name}")
    if re.match(r"^[A-Za-z]:", normalized):
        raise UnsafeZipEntryError(
            f"unsafe drive-qualified ZIP member path: {member_name}"
        )

    parts: list[str] = []
    for part in PurePosixPath(normalized).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise UnsafeZipEntryError(f"unsafe traversal ZIP member path: {member_name}")
        parts.append(part)

    if not parts:
        raise UnsafeZipEntryError("ZIP member path is empty")
    return "/".join(parts)
