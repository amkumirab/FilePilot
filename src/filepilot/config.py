"""Ordered, explicitly validated TOML organization rules."""

import string
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .paths import FilePilotError, validate_relative

FIELDS = {"name", "stem", "ext", "year", "month", "day"}


def validate_template(template: str, *, filename: bool = False) -> None:
    if not isinstance(template, str) or not template:
        raise FilePilotError("Templates must be nonempty strings.")
    try:
        for _, field, spec, conversion in string.Formatter().parse(template):
            if field is not None and (field not in FIELDS or spec or conversion):
                raise FilePilotError(f"Unsupported template field: {field!r}")
        sample = template.format(
            name="sample.pdf", stem="sample", ext=".pdf", year="2026", month="01", day="02"
        )
    except (ValueError, KeyError) as exc:
        raise FilePilotError(f"Invalid template: {template!r}") from exc
    validate_relative(sample)
    if filename and "/" in sample:
        raise FilePilotError("The rename template must produce a filename, not a path.")


@dataclass(frozen=True)
class Rule:
    name: str
    extensions: tuple[str, ...]
    target: str
    contains: str = ""
    rename: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise FilePilotError("Each rule needs a nonempty name.")
        if not isinstance(self.contains, str):
            raise FilePilotError("contains must be a string.")
        if not isinstance(self.extensions, (tuple, list)) or any(
            not isinstance(ext, str) or not ext.lstrip(".") or not ext.lstrip(".").isalnum()
            for ext in self.extensions
        ):
            raise FilePilotError("extensions must contain simple suffixes such as 'pdf'.")
        object.__setattr__(
            self, "extensions", tuple(ext.lstrip(".").casefold() for ext in self.extensions)
        )
        validate_template(self.target)
        if self.rename is not None:
            validate_template(self.rename, filename=True)

    def matches(self, path: Path) -> bool:
        return (not self.extensions or path.suffix.lstrip(".").casefold() in self.extensions) and (
            self.contains.casefold() in path.name.casefold()
        )


DEFAULT_RULES = tuple(
    Rule(name, tuple(extensions.split()), name)
    for name, extensions in (
        ("Documents", "pdf doc docx txt odt rtf"),
        ("Spreadsheets", "xls xlsx csv tsv ods"),
        ("Pictures", "jpg jpeg png gif webp svg heic bmp"),
        ("Videos", "mp4 mkv mov avi webm"),
        ("Audio", "mp3 wav flac m4a ogg"),
        ("Archives", "zip 7z rar tar gz bz2 xz"),
    )
)

EXAMPLE_CONFIG = """# First matching rule wins. Dates use the file's modification time.
# {ext} includes the dot; {name} includes the original extension.

[[rules]]
name = "Invoices"
extensions = ["pdf"]
contains = "invoice"
target = "Invoices/{year}/{month}"
rename = "{year}-{month}-{day}_{stem}{ext}"

[[rules]]
name = "Documents"
extensions = ["pdf", "docx", "txt"]
target = "Documents"

[[rules]]
name = "Pictures"
extensions = ["jpg", "jpeg", "png", "webp"]
target = "Pictures/{year}/{month}"

# Unmatched files stay in place. To match everything else, add a final rule
# with target = "Other" and no extensions list.
"""


def load_rules(path: Path) -> tuple[Rule, ...]:
    try:
        with path.open("rb") as stream:
            config = tomllib.load(stream)
    except tomllib.TOMLDecodeError as exc:
        raise FilePilotError(f"Invalid TOML in {path}: {exc}") from exc
    if set(config) != {"rules"} or not isinstance(config["rules"], list) or not config["rules"]:
        raise FilePilotError("Configuration must contain one or more [[rules]] records.")
    rules = []
    allowed = {"name", "extensions", "target", "contains", "rename"}
    for record in config["rules"]:
        if not isinstance(record, dict) or set(record) - allowed:
            raise FilePilotError(f"Unknown rule fields; allowed: {', '.join(sorted(allowed))}")
        if not {"name", "target"} <= set(record):
            raise FilePilotError("Each rule requires name and target.")
        rules.append(Rule(**{**{"extensions": ()}, **record}))
    return tuple(rules)
