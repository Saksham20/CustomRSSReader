import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from newsfeed.archive import maintain
from newsfeed.archive import NEWS

NOW = datetime(2026, 11, 20, 11, 30, tzinfo=timezone.utc)


def _item(video_id: str, when: datetime, title: str) -> ET.Element:
    item = ET.Element("item")
    ET.SubElement(item, "title").text = title
    link = f"https://www.youtube.com/watch?v={video_id}"
    ET.SubElement(item, "link").text = link
    guid = ET.SubElement(item, "guid", {"isPermaLink": "true"})
    guid.text = link
    ET.SubElement(item, "pubDate").text = when.strftime("%a, %d %b %Y %H:%M:%S +0000")
    ET.SubElement(item, f"{{{NEWS}}}videoId").text = video_id
    ET.SubElement(item, f"{{{NEWS}}}publishedIst").text = when.astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
    ).isoformat()
    ET.SubElement(item, "description").text = f"<p>{title}</p>"
    return item


def _edition(day: str, scanned: datetime) -> ET.Element:
    edition = ET.Element(f"{{{NEWS}}}edition", {"date": day})
    ET.SubElement(edition, f"{{{NEWS}}}scannedAt").text = scanned.strftime("%Y-%m-%dT%H:%M:%SZ")
    ET.SubElement(edition, f"{{{NEWS}}}briefing").text = (
        f"Edition {day}.\n\nThe morning's through-line: {day}."
    )
    return edition


class ArchiveTests(unittest.TestCase):
    def test_split_retention_and_day_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            latest = root / "latest-news.xml"
            older = root / "latest-news_older.xml"
            news = root / "news"
            fresh = _item("freshvid123", NOW - timedelta(hours=2), "Fresh story")
            aging = _item("agingvid123", NOW - timedelta(hours=30), "Aging story")
            ancient = _item("oldvid12345", NOW - timedelta(days=40), "Ancient story")
            editions = [
                _edition("2026-11-20", NOW - timedelta(hours=1)),
                _edition("2026-11-18", NOW - timedelta(days=2)),
                _edition("2026-10-01", NOW - timedelta(days=50)),
            ]
            from newsfeed.archive import _shell, _write_feed

            _write_feed(
                latest,
                _shell("Live", "latest-news.xml", NOW),
                editions,
                [fresh, aging, ancient],
                "  test\n",
            )
            first = maintain(latest, older, news, NOW)
            snapshot = (
                latest.read_text(encoding="utf-8"),
                older.read_text(encoding="utf-8"),
                (news / "days.json").read_text(encoding="utf-8"),
            )
            second = maintain(latest, older, news, NOW)
            self.assertEqual(
                snapshot,
                (
                    latest.read_text(encoding="utf-8"),
                    older.read_text(encoding="utf-8"),
                    (news / "days.json").read_text(encoding="utf-8"),
                ),
            )

            self.assertEqual(first["latest_items"], 1)
            self.assertEqual(first["moved_items"], 2)
            self.assertEqual(first["removed_items"], 1)
            self.assertEqual(first["latest_editions"], 1)
            self.assertGreaterEqual(first["removed_editions"], 1)
            self.assertEqual(second["moved_items"], 0)
            self.assertEqual(second["removed_items"], 0)

            live = ET.parse(latest)
            live_ids = [node.text for node in live.iter(f"{{{NEWS}}}videoId")]
            self.assertEqual(live_ids, ["freshvid123"])
            archived = ET.parse(older)
            archived_ids = [node.text for node in archived.iter(f"{{{NEWS}}}videoId")]
            self.assertEqual(archived_ids, ["agingvid123"])
            self.assertNotIn("oldvid12345", older.read_text(encoding="utf-8"))
            self.assertIn("2026-11-18", older.read_text(encoding="utf-8"))
            self.assertNotIn("2026-10-01", older.read_text(encoding="utf-8"))

            day = (news / "2026-11-19.xml").read_text(encoding="utf-8")
            self.assertIn("Aging story", day)
            self.assertNotIn("Fresh story", day)
            self.assertNotIn("Ancient story", day)
            index = (news / "days.json").read_text(encoding="utf-8")
            self.assertNotIn("Aging story", index)
            self.assertNotIn("<p>", index)
            self.assertIn("2026-11-20", index)


if __name__ == "__main__":
    unittest.main()
