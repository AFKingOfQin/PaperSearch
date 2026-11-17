import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

MAX_LINE_BYTES = 256 * 1024


class RecordError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def clean(value: object, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise RecordError("invalid_text")
    if any(
        unicodedata.category(c) in {"Cc", "Cs"} and c not in "\t\r\n" for c in value
    ):
        raise RecordError("invalid_text")
    result = " ".join(unicodedata.normalize("NFC", value).split())
    if not result and not empty:
        raise RecordError("invalid_text")
    return result


def utc(value):
    if not isinstance(value, str):
        raise RecordError("invalid_timestamp")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise RecordError("missing_timezone")
    return (
        stamp.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def iso_day(value):
    if not isinstance(value, str):
        raise RecordError("invalid_date")
    return date.fromisoformat(value).isoformat()


def version(value: object) -> int | None:
    if value is not None and (type(value) is not int or not 1 <= value <= 2**31 - 1):
        raise RecordError("invalid_version")
    return value


def arxiv_id(value: object) -> tuple[str, int | None]:
    if not isinstance(value, str) or len(value) > 100:
        raise RecordError("invalid_paper_id")
    identifier = re.sub(r"^arxiv:", "", value, count=1, flags=re.IGNORECASE)
    match = re.fullmatch(
        r"(?:(?P<modern>[0-9]{2}(?:0[1-9]|1[0-2])\.[0-9]{4,5})|"
        r"(?P<archive>[a-z][a-z0-9-]*)(?:\.[A-Za-z]{2})?/(?P<old>[0-9]{2}(?:0[1-9]|1[0-2])[0-9]{3}))"
        r"(?:v(?P<v>[1-9][0-9]{0,9}))?",
        identifier,
    )
    if not match:
        raise RecordError("invalid_paper_id")
    if match["modern"]:
        month, serial = match["modern"].split(".")
        if (
            "0701" <= month <= "0703"
            or len(serial) != (4 if "0704" <= month <= "1412" else 5)
            or int(serial) == 0
        ):
            raise RecordError("invalid_paper_id")
    else:
        month, serial = match["old"][:4], match["old"][4:]
        if "0703" < month < "9107" or int(serial) == 0:
            raise RecordError("invalid_paper_id")
    base = match["modern"] or f"{match['archive']}/{match['old']}"
    return "arxiv:" + base, version(int(match["v"]) if match["v"] else None)


def strings(value: object, limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise RecordError("invalid_list")
    return [clean(item, 1024) for item in value]


def validate_url(value):
    if not isinstance(value, str) or not value.isascii() or len(value) > 2048:
        raise RecordError("invalid_url")
    if re.search(r"[\s\x00-\x1f\x7f\\]", value):
        raise RecordError("invalid_url")
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
    ):
        raise RecordError("invalid_url")
    return value


@dataclass(frozen=True)
class Payload:
    title: str
    abstract: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    published: str | None
    source_url: str
    doi: str | None

    @classmethod
    def parse(cls, row: dict) -> "Payload":
        return cls(
            title=clean(row.get("title"), 4096),
            abstract=clean(row.get("abstract", ""), 65536, empty=True),
            authors=tuple(strings(row.get("authors", []), 4096)),
            categories=tuple(sorted(set(strings(row.get("categories", []), 256)))),
            published=iso_day(row["published"])
            if row.get("published") is not None
            else None,
            source_url=validate_url(row.get("source_url")),
            doi=clean(row["doi"], 512) if row.get("doi") is not None else None,
        )


@dataclass(frozen=True)
class Revision:
    paper_id: str
    version_rank: int
    source_updated_at: str
    payload: Payload


def snapshot_record(row: dict) -> tuple:
    paper, suffix = arxiv_id(row.get("id"))
    history = row.get("versions", [])
    if not isinstance(history, list) or len(history) > 4096:
        raise RecordError("invalid_history")
    dates = {}
    for entry in history:
        if not isinstance(entry, dict):
            raise RecordError("invalid_history")
        label, created = entry.get("version"), entry.get("created")
        if not isinstance(label, str) or not re.fullmatch(r"v[1-9][0-9]{0,9}", label):
            raise RecordError("invalid_history")
        n = version(int(label[1:]))
        if n in dates or not isinstance(created, str) or len(created) > 64:
            raise RecordError("invalid_history")
        try:
            stamp = parsedate_to_datetime(created)
            if stamp.tzinfo is None:
                raise ValueError("missing timezone")
            dates[n] = utc(stamp.astimezone(timezone.utc).isoformat())
        except (ValueError, OverflowError) as exc:
            raise RecordError("invalid_history") from exc
    revision = max(dates, default=suffix)
    if suffix is not None and revision != suffix:
        raise RecordError("version_mismatch")
    times = [dates[revision]] if dates else []
    if row.get("update_date") is not None:
        times.append(utc(iso_day(row["update_date"]) + "T00:00:00Z"))
    if not times:
        raise RecordError("missing_source_time")
    authors = []
    parsed = row.get("authors_parsed")
    if parsed is not None and not isinstance(parsed, list):
        raise RecordError("invalid_authors")
    if parsed:
        for name in parsed:
            if not isinstance(name, list) or len(name) < 2:
                raise RecordError("invalid_authors")
            last, first, *suffixes = [
                clean(part, 1024, empty=True) for part in name[:3]
            ]
            authors.append(" ".join([first, last, *suffixes]).strip())
    elif row.get("authors") is not None:
        byline = clean(row["authors"], 1024, empty=True)
        authors = [byline] if byline else []
    categories = clean(row.get("categories", ""), 8192, empty=True).split()
    payload = Payload.parse(
        dict(
            title=row.get("title"),
            abstract=row.get("abstract", ""),
            authors=authors,
            categories=categories,
            doi=row.get("doi"),
            published=dates[1][:10] if 1 in dates else None,
            source_url="https://arxiv.org/abs/" + paper.removeprefix("arxiv:"),
        )
    )
    return paper, revision, max(times), payload


def parse_record(raw: bytes, fmt: str) -> Revision:
    row = json.loads(raw)
    if not isinstance(row, dict):
        raise RecordError("invalid_record")
    if fmt == "arxiv":
        paper, revision, updated, payload = snapshot_record(row)
    elif fmt == "fixture":
        identifier = row.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,79}", identifier
        ):
            raise RecordError("invalid_paper_id")
        paper = "fixture:" + identifier
        revision = version(row.get("source_version"))
        updated = utc(row.get("source_updated_at"))
        payload = Payload.parse(
            {"source_url": "https://example.invalid/papers/" + identifier, **row}
        )
    else:
        raise RecordError("invalid_format")
    return Revision(paper, revision or 0, updated, payload)


def revision_values(revision):
    return dict(
        paper=revision.paper_id,
        rank=revision.version_rank,
        stamp=revision.source_updated_at,
        payload=canonical(asdict(revision.payload)).encode().hex(),
    )
