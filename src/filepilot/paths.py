"""Constrain all file operations to the selected directory."""

import stat
from pathlib import Path


class FilePilotError(Exception):
    """A readable configuration or operation error."""


def root_directory(path: Path) -> Path:
    root = path.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise FilePilotError(f"Not a directory: {root}")
    return root


def is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def is_hidden(path: Path) -> bool:
    return path.name.startswith(".") or bool(
        getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
        & stat.FILE_ATTRIBUTE_HIDDEN
    )


def validate_relative(value: str, *, internal: bool = False) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise FilePilotError(f"Expected a relative path with forward slashes: {value!r}")
    parts = value.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    for part in parts:
        if (
            part in ("", ".", "..")
            or part.endswith((" ", "."))
            or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
            or part.split(".")[0].upper() in reserved
        ):
            raise FilePilotError(f"Unsafe or non-portable path: {value!r}")
        if part.casefold() == ".filepilot" and not internal:
            raise FilePilotError("The .filepilot directory is reserved for history.")


def safe_path(root: Path, relative: str, *, internal: bool = False) -> Path:
    validate_relative(relative, internal=internal)
    candidate = root
    for part in relative.split("/"):
        candidate = candidate / part
        if is_link(candidate):
            raise FilePilotError(f"Symbolic links and junctions are not followed: {candidate}")
    if not candidate.resolve().is_relative_to(root):
        raise FilePilotError(f"Path escapes the selected folder: {relative}")
    return candidate
