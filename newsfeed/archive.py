"""Move news out of the live feed without making an agent read it.

`keep_latest_24_hours` leaves the rolling 24 hours in `latest-news.xml` and
appends everything older to `latest-news_older.xml`.

`delete_older_than_30_days` removes stories and editions in that older file
once they are more than 30 days old.

`write_day_slices` writes one small XML file per calendar day in India time,
plus a date index. The site fetches a single day when a reader asks for it.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LATEST_PATH = ROOT / "latest-news.xml"
OLDER_PATH = ROOT / "latest-news_older.xml"
NEWS_DIR = ROOT / "news"

IST = ZoneInfo("Asia/Kolkata")
NEWS = "urn:latest-news:1"
MEDIA = "http://search.yahoo.com/mrss/"
ATOM = "http://www.w3.org/2005/Atom"
PREFIX = {ATOM: "atom", MEDIA: "media", NEWS: "news"}
WINDOW = timedelta(hours=24)
RETENTION = timedelta(days=30)
DAY_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.xml$")

ET.register_namespace("atom", ATOM)
ET.register_namespace("media", MEDIA)
ET.register_namespace("news", NEWS)


def keep_latest_24_hours(
    latest_path: Path = LATEST_PATH,
    older_path: Path = OLDER_PATH,
    now: datetime | None = None,
) -> dict[str, int]:
    """Keep a rolling 24 hours in the live feed and move the rest."""
    moment = _now(now)
    cutoff = moment - WINDOW
    latest_meta, latest_editions, latest_items = _read(latest_path)
    older_meta, older_editions, older_items = _read(older_path) if older_path.exists() else ({}, [], [])

    stay_items = [item for item in latest_items if _item_time(item) >= cutoff]
    move_items = [item for item in latest_items if _item_time(item) < cutoff]
    stay_editions = [edition for edition in latest_editions if _edition_stays(edition, moment, cutoff)]
    move_editions = [edition for edition in latest_editions if not _edition_stays(edition, moment, cutoff)]

    stay_ids = {_item_id(item) for item in stay_items}
    stay_dates = {_edition_date(edition) for edition in stay_editions}
    archived_items = _merge_items(older_items, move_items, drop_ids=stay_ids)
    archived_editions = _merge_editions(older_editions, move_editions, drop_dates=stay_dates)

    _write_feed(latest_path, latest_meta, stay_editions, stay_items, _LIVE_COMMENT)
    older_shell = older_meta or _shell("News older than 24 hours and newer than 30 days.", older_path.name, moment)
    _write_feed(older_path, older_shell, archived_editions, archived_items, _OLDER_COMMENT)
    return {
        "latest_items": len(stay_items),
        "latest_editions": len(stay_editions),
        "moved_items": len(move_items),
        "moved_editions": len(move_editions),
        "older_items": len(archived_items),
        "older_editions": len(archived_editions),
    }


def delete_older_than_30_days(
    older_path: Path = OLDER_PATH,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete editions and stories in the older file that are past 30 days."""
    moment = _now(now)
    if not older_path.exists():
        return {"removed_items": 0, "removed_editions": 0, "older_items": 0, "older_editions": 0}
    cutoff = moment - RETENTION
    oldest_day = (moment.astimezone(IST).date() - RETENTION).isoformat()
    meta, editions, items = _read(older_path)
    kept_items = [item for item in items if _item_time(item) >= cutoff]
    kept_editions = [edition for edition in editions if _edition_date(edition) >= oldest_day]
    _write_feed(older_path, meta, kept_editions, kept_items, _OLDER_COMMENT)
    return {
        "removed_items": len(items) - len(kept_items),
        "removed_editions": len(editions) - len(kept_editions),
        "older_items": len(kept_items),
        "older_editions": len(kept_editions),
    }


def write_day_slices(
    latest_path: Path = LATEST_PATH,
    older_path: Path = OLDER_PATH,
    news_dir: Path = NEWS_DIR,
    now: datetime | None = None,
) -> dict[str, int]:
    """Write one XML file per India-time day, and a date-only index."""
    moment = _now(now)
    oldest_day = (moment.astimezone(IST).date() - RETENTION).isoformat()
    _, latest_editions, latest_items = _read(latest_path)
    _, older_editions, older_items = _read(older_path) if older_path.exists() else ({}, [], [])
    editions = _merge_editions(older_editions, latest_editions, drop_dates=set())
    items = _merge_items(older_items, latest_items, drop_ids=set())
    by_day: dict[str, dict[str, list]] = {}
    for edition in editions:
        day = _edition_date(edition)
        if day and day >= oldest_day:
            by_day.setdefault(day, {"edition": None, "items": []})["edition"] = edition
    for item in items:
        day = _item_day(item)
        if day and day >= oldest_day:
            by_day.setdefault(day, {"edition": None, "items": []})["items"].append(item)

    news_dir.mkdir(parents=True, exist_ok=True)
    days = []
    for day in sorted(by_day, reverse=True):
        bundle = by_day[day]
        bundle["items"].sort(key=_item_time, reverse=True)
        filename = f"{day}.xml"
        label = _day_label(day)
        edition = [bundle["edition"]] if bundle["edition"] is not None else []
        _write_feed(
            news_dir / filename,
            _shell(f"News for {label}.", f"news/{filename}", _bundle_time(bundle["edition"], bundle["items"], moment)),
            edition,
            bundle["items"],
            f"  One calendar day in India time: {label}. The site fetches this file only when that day is selected.\n",
        )
        days.append({"date": day, "label": label})

    index = {"days": days}
    (news_dir / "days.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for path in news_dir.glob("*.xml"):
        if DAY_FILE.match(path.name) and path.stem not in by_day:
            path.unlink()
    return {"days": len(days)}


def maintain(
    latest_path: Path = LATEST_PATH,
    older_path: Path = OLDER_PATH,
    news_dir: Path = NEWS_DIR,
    now: datetime | None = None,
) -> dict[str, int]:
    """Run the 24-hour split, the 30-day delete, and the per-day files."""
    moment = _now(now)
    report = keep_latest_24_hours(latest_path, older_path, moment)
    report.update(delete_older_than_30_days(older_path, moment))
    report.update(write_day_slices(latest_path, older_path, news_dir, moment))
    return report


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _read(path: Path) -> tuple[dict[str, str], list[ET.Element], list[ET.Element]]:
    if not path.exists():
        return {}, [], []
    root = ET.parse(path).getroot()
    channel = root.find("channel")
    if channel is None:
        return {}, [], []
    meta = {}
    for name in ("title", "link", "description", "language", "lastBuildDate", "generator"):
        node = channel.find(name)
        if node is not None and node.text:
            meta[name] = node.text.strip()
    editions = [edition for edition in list(channel) if _local(edition.tag) == "edition"]
    items = [item for item in list(channel) if item.tag == "item"]
    editions.sort(key=_edition_date, reverse=True)
    items.sort(key=_item_time, reverse=True)
    return meta, editions, items


def _shell(description: str, link: str, moment: datetime) -> dict[str, str]:
    return {
        "title": "Latest",
        "link": link,
        "description": description,
        "language": "en",
        "lastBuildDate": format_datetime(moment, usegmt=False),
        "generator": "Latest news reader",
    }


def _write_feed(
    path: Path,
    meta: dict[str, str],
    editions: list[ET.Element],
    items: list[ET.Element],
    comment: str,
) -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!--",
        comment.rstrip("\n"),
        "-->",
        '<rss version="2.0"',
        '     xmlns:atom="http://www.w3.org/2005/Atom"',
        '     xmlns:media="http://search.yahoo.com/mrss/"',
        '     xmlns:news="urn:latest-news:1">',
        "  <channel>",
    ]
    for name in ("title", "link", "description", "language", "lastBuildDate", "generator"):
        if meta.get(name):
            lines.append(f"    <{name}>{_escape(meta[name])}</{name}>")
    lines.append("")
    for edition in editions:
        lines.extend(_serialize(edition, 2))
        lines.append("")
    for item in items:
        lines.extend(_serialize(item, 2))
        lines.append("")
    lines.extend(["  </channel>", "</rss>", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _serialize(element: ET.Element, depth: int) -> list[str]:
    indent = "  " * depth
    name = _qname(element.tag)
    attributes = "".join(
        f' {_qname(key)}="{_escape(value, quote=True)}"' for key, value in element.attrib.items()
    )
    children = list(element)
    text = element.text or ""
    if not children and not text:
        return [f"{indent}<{name}{attributes}/>"]
    if not children:
        body = _cdata(text) if "<" in text or "&" in text else _escape(text)
        return [f"{indent}<{name}{attributes}>{body}</{name}>"]
    lines = [f"{indent}<{name}{attributes}>"]
    if text.strip():
        lines.append(f"{indent}  {_cdata(text) if '<' in text else _escape(text)}")
    for child in children:
        lines.extend(_serialize(child, depth + 1))
    lines.append(f"{indent}</{name}>")
    return lines


def _qname(tag: str) -> str:
    if tag.startswith("{"):
        uri, local = tag[1:].split("}", 1)
        prefix = PREFIX.get(uri)
        return f"{prefix}:{local}" if prefix else local
    return tag


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _escape(value: str, quote: bool = False) -> str:
    text = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if quote:
        text = text.replace('"', "&quot;")
    return text


def _cdata(value: str) -> str:
    return "<![CDATA[" + value.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local(child.tag) == name and child.text:
            return child.text.strip()
    return ""


def _item_time(item: ET.Element) -> datetime:
    raw = _child_text(item, "publishedIst") or _child_text(item, "pubDate")
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)
    if "T" in raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    parsed = parsedate_to_datetime(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _item_day(item: ET.Element) -> str:
    moment = _item_time(item)
    if moment == datetime.min.replace(tzinfo=timezone.utc):
        return ""
    return moment.astimezone(IST).date().isoformat()


def _item_id(item: ET.Element) -> str:
    return _child_text(item, "videoId") or _child_text(item, "guid") or _child_text(item, "link")


def _edition_date(edition: ET.Element) -> str:
    return edition.attrib.get("date", "")


def _edition_stays(edition: ET.Element, moment: datetime, cutoff: datetime) -> bool:
    scanned = _child_text(edition, "scannedAt")
    if scanned:
        try:
            when = datetime.fromisoformat(scanned.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            when = None
        if when is not None and when >= cutoff:
            return True
    return _edition_date(edition) == moment.astimezone(IST).date().isoformat()


def _merge_items(existing: list[ET.Element], incoming: list[ET.Element], drop_ids: set[str]) -> list[ET.Element]:
    merged: dict[str, ET.Element] = {}
    for item in existing + incoming:
        identity = _item_id(item)
        if identity and identity not in drop_ids:
            merged[identity] = item
    items = list(merged.values())
    items.sort(key=_item_time, reverse=True)
    return items


def _merge_editions(
    existing: list[ET.Element], incoming: list[ET.Element], drop_dates: set[str]
) -> list[ET.Element]:
    merged: dict[str, ET.Element] = {}
    for edition in existing + incoming:
        day = _edition_date(edition)
        if day and day not in drop_dates:
            merged[day] = edition
    editions = list(merged.values())
    editions.sort(key=_edition_date, reverse=True)
    return editions


def _bundle_time(edition: ET.Element | None, items: list[ET.Element], moment: datetime) -> datetime:
    scanned = _child_text(edition, "scannedAt") if edition is not None else ""
    if scanned:
        try:
            return datetime.fromisoformat(scanned.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
    if items:
        return _item_time(items[0])
    return moment


def _day_label(day: str) -> str:
    parsed = datetime.strptime(day, "%Y-%m-%d")
    return f"{parsed.strftime('%A')} {parsed.day} {parsed.strftime('%B %Y')}"


_LIVE_COMMENT = """
  Rolling feed. This file keeps editions and stories from the last 24 hours.
  Older stories are in latest-news_older.xml. The site loads one day at a time from news/.
""".strip("\n")

_OLDER_COMMENT = """
  Stories and editions that have left the rolling 24-hour feed.
  Anything older than 30 days is deleted from this file.
""".strip("\n")


if __name__ == "__main__":
    import json

    print(json.dumps(maintain(), indent=2))
