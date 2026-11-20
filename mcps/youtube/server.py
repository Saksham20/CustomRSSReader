#!/usr/bin/env python3
"""Read-only YouTube discovery, metadata, and transcript MCP for the news pipeline.

Discovery uses the official YouTube Data API. Transcript retrieval uses a
public Invidious instance's captions API and is best effort: an instance that
is down or has no caption track is reported per video, not hidden.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from mcp.server.fastmcp import FastMCP

API_ROOT = "https://www.googleapis.com/youtube/v3"
API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
REQUEST_TIMEOUT = float(os.environ.get("YOUTUBE_REQUEST_TIMEOUT", "20"))
MAX_PARALLEL_TRANSCRIPTS = max(1, min(int(os.environ.get("YOUTUBE_TRANSCRIPT_WORKERS", "4")), 8))
DEFAULT_LANGUAGES = ["en", "en-US", "en-GB"]
# Public instances from https://docs.invidious.io/instances/
DEFAULT_INVIDIOUS_INSTANCES = (
    "https://yt.chocolatemoo53.com",
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.tiekoetter.com",
)
INVIDIOUS_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/vtt, application/json, */*",
}
_LABEL_GUESSES = {
    "en": (
        "English",
        "English (United States)",
        "English (US)",
        "English (auto-generated)",
    ),
}
SHORT_CANDIDATE_MAX_SECONDS = 180
MAX_VIDEO_IDS_PER_CALL = 50
MAX_TRANSCRIPT_CHARS = 40000
CACHE_ROOT = Path(os.environ.get("YOUTUBE_MCP_CACHE", Path(__file__).parent / ".cache"))
CACHE_LOCK = threading.Lock()

mcp = FastMCP("youtube-news-source")


class YouTubeError(RuntimeError):
    """A safe, user-facing YouTube retrieval error."""


def _cache_path(namespace: str, key: str) -> Path:
    safe_key = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
    return CACHE_ROOT / namespace / f"{safe_key}.json"


def _read_cache(namespace: str, key: str, max_age_seconds: int | None = None) -> Any | None:
    path = _cache_path(namespace, key)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if max_age_seconds is not None and time.time() - raw.get("cached_at", 0) > max_age_seconds:
            return None
        return raw.get("data")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def _write_cache(namespace: str, key: str, data: Any) -> None:
    path = _cache_path(namespace, key)
    try:
        with CACHE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"cached_at": time.time(), "data": data}, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(path)
    except OSError:
        # Caching is an optimization; retrieval should still work in read-only VMs.
        pass


def _api_get(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    if not API_KEY:
        raise YouTubeError(
            "YOUTUBE_API_KEY is not configured. Create a YouTube Data API v3 key and "
            "add it to the MCP server environment."
        )
    try:
        response = requests.get(
            f"{API_ROOT}/{endpoint}",
            params={**params, "key": API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", "")
            except ValueError:
                detail = ""
            raise YouTubeError(f"YouTube API returned HTTP {response.status_code}: {detail or response.reason}")
        return response.json()
    except requests.RequestException as error:
        raise YouTubeError(f"Could not reach the YouTube Data API: {error}") from error


def _normalize_channel(channel: str) -> tuple[str, str]:
    """Return (lookup kind, value) for a channel ID, handle, or channel URL."""
    raw = channel.strip()
    if not raw:
        raise YouTubeError("Provide a YouTube channel ID, @handle, or channel URL.")
    if re.fullmatch(r"UC[A-Za-z0-9_-]{20,}", raw):
        return "id", raw
    if raw.startswith("@"):
        return "handle", raw[1:]
    if "://" in raw:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if not (host.endswith("youtube.com") or host.endswith("youtube-nocookie.com")):
            raise YouTubeError("The URL must be a YouTube channel URL.")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "channel" and parts[1].startswith("UC"):
            return "id", parts[1]
        if parts and parts[0].startswith("@"):
            return "handle", parts[0][1:]
        if parts and parts[0] == "user" and len(parts) >= 2:
            return "username", parts[1]
        raise YouTubeError("Could not identify a channel from that URL. Use its @handle or UC channel ID.")
    if raw.startswith("UC"):
        return "id", raw
    return "handle", raw.lstrip("@")


def _channel_details(channel: str) -> dict[str, Any]:
    kind, value = _normalize_channel(channel)
    cache_key = f"{kind}-{value}"
    cached = _read_cache("channels", cache_key, 86400)
    if cached:
        return cached
    params: dict[str, Any] = {"part": "id,snippet,contentDetails", "maxResults": 1}
    params[{"id": "id", "handle": "forHandle", "username": "forUsername"}[kind]] = value
    result = _api_get("channels", params)
    items = result.get("items", [])
    if not items:
        raise YouTubeError(f"No public YouTube channel matched {channel!r}.")
    item = items[0]
    details = {
        "channel_id": item["id"],
        "title": item.get("snippet", {}).get("title", ""),
        "uploads_playlist_id": item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", ""),
        "channel_url": f"https://www.youtube.com/channel/{item['id']}",
    }
    if not details["uploads_playlist_id"]:
        raise YouTubeError("The channel response did not include an uploads playlist.")
    _write_cache("channels", cache_key, details)
    return details


def _duration_seconds(duration: str) -> int:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not match:
        return 0
    hours, minutes, seconds = (int(value or 0) for value in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _video_metadata(video_ids: list[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for video_id in video_ids:
        cached = _read_cache("videos", video_id, 86400)
        if cached:
            found[video_id] = cached
        else:
            missing.append(video_id)
    for start in range(0, len(missing), MAX_VIDEO_IDS_PER_CALL):
        batch = missing[start : start + MAX_VIDEO_IDS_PER_CALL]
        result = _api_get(
            "videos",
            {"part": "snippet,contentDetails,status", "id": ",".join(batch), "maxResults": len(batch)},
        )
        for item in result.get("items", []):
            video_id = item["id"]
            snippet = item.get("snippet", {})
            duration = item.get("contentDetails", {}).get("duration", "")
            seconds = _duration_seconds(duration)
            found[video_id] = {
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "duration": duration,
                "duration_seconds": seconds,
                # The Data API has no authoritative Shorts flag. Keep this explicit as a heuristic.
                "format": "short_candidate" if 0 < seconds <= SHORT_CANDIDATE_MAX_SECONDS else "video",
                "format_basis": "duration_heuristic_180_seconds" if 0 < seconds <= SHORT_CANDIDATE_MAX_SECONDS else "upload_metadata",
                "thumbnail": snippet.get("thumbnails", {}).get("high", snippet.get("thumbnails", {}).get("default", {})).get("url", ""),
            }
            _write_cache("videos", video_id, found[video_id])
    return found


def _parse_published(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _recent_uploads(channel: str, hours: int, max_results: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if hours < 1 or hours > 168:
        raise YouTubeError("hours must be between 1 and 168.")
    if max_results < 1 or max_results > 200:
        raise YouTubeError("max_results must be between 1 and 200.")
    details = _channel_details(channel)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    ids: list[str] = []
    token = None
    while len(ids) < max_results:
        params: dict[str, Any] = {
            "part": "contentDetails,snippet",
            "playlistId": details["uploads_playlist_id"],
            "maxResults": min(50, max_results - len(ids)),
        }
        if token:
            params["pageToken"] = token
        page = _api_get("playlistItems", params)
        stop = False
        for item in page.get("items", []):
            content = item.get("contentDetails", {})
            video_id = content.get("videoId")
            published = content.get("videoPublishedAt") or item.get("snippet", {}).get("publishedAt", "")
            if not video_id or not published:
                continue
            try:
                if _parse_published(published) < cutoff:
                    stop = True
                    break
            except ValueError:
                continue
            ids.append(video_id)
            if len(ids) >= max_results:
                break
        token = page.get("nextPageToken")
        if stop or not token or len(ids) >= max_results:
            break
    metadata = _video_metadata(ids) if ids else {}
    uploads = sorted(metadata.values(), key=lambda video: video["published_at"], reverse=True)
    # Recheck on video publication timestamps, since playlist-entry timestamps can differ.
    uploads = [video for video in uploads if _parse_published(video["published_at"]) >= cutoff]
    return details, uploads


def _invidious_instances() -> list[str]:
    configured = os.environ.get("INVIDIOUS_INSTANCES", "").strip() or os.environ.get("INVIDIOUS_BASE_URL", "").strip()
    if not configured:
        return list(DEFAULT_INVIDIOUS_INSTANCES)
    bases = []
    for part in configured.split(","):
        base = part.strip().rstrip("/")
        if base:
            bases.append(base if "://" in base else f"https://{base}")
    return bases or list(DEFAULT_INVIDIOUS_INSTANCES)


def _language_match(code: str, languages: list[str]) -> int | None:
    normalized = (code or "").lower().replace("_", "-")
    if not normalized:
        return None
    primary = normalized.split("-", 1)[0]
    for index, wanted in enumerate(languages):
        target = wanted.lower().replace("_", "-")
        if normalized == target or primary == target.split("-", 1)[0]:
            return index
    return None


_CUE_TIME = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})"
)
_WORD_MARK = re.compile(r"<(\d{2}:\d{2}:\d{2}\.\d{3})><c>")


def _strip_caption_tags(text: str) -> str:
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def _vtt_cues(payload: str) -> list[list[str]]:
    cues: list[list[str]] = []
    for block in re.split(r"\n{2,}", payload):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        match = _CUE_TIME.match(lines[0])
        if match is None and len(lines) > 1:
            match = _CUE_TIME.match(lines[1])
            lines = lines[1:]
        if match is None:
            continue
        cues.append(lines[1:])
    return cues


def _words_in_timed_line(line: str) -> list[str]:
    parts = _WORD_MARK.split(line)
    words = _strip_caption_tags(parts[0]).split()
    index = 1
    while index + 1 < len(parts):
        token = _strip_caption_tags(parts[index + 1].split("</c>")[0])
        if token:
            words.extend(token.split())
        index += 2
    return words


def _vtt_to_text(payload: str) -> str:
    """Turn WebVTT into plain text without repeating YouTube's rolling cues."""
    if "<c>" in payload:
        words: list[str] = []
        for lines in _vtt_cues(payload):
            for line in lines:
                if "<c>" not in line:
                    continue
                for word in _words_in_timed_line(line):
                    if words and words[-1] == word:
                        continue
                    words.append(word)
        if words:
            return " ".join(words)
    pieces: list[str] = []
    previous = ""
    for lines in _vtt_cues(payload):
        text = _strip_caption_tags(" ".join(lines))
        if not text or text == previous:
            continue
        extra = text[len(previous):].strip() if previous and text.startswith(previous) else text
        if extra:
            pieces.append(extra)
        previous = text
    return " ".join(pieces)


def _looks_like_vtt(payload: str, content_type: str) -> bool:
    kind = content_type.lower()
    if "text/vtt" in kind or "webvtt" in kind:
        return True
    sample = payload.lstrip()[:40].upper()
    return sample.startswith("WEBVTT")


def _caption_tracks(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        tracks = payload.get("captions")
        if isinstance(tracks, list):
            return [track for track in tracks if isinstance(track, dict)]
    if isinstance(payload, list):
        return [track for track in payload if isinstance(track, dict)]
    return []


def _track_language(track: dict[str, Any]) -> str:
    return str(track.get("language_code") or track.get("languageCode") or "")


def _track_label(track: dict[str, Any]) -> str:
    return str(track.get("label") or "")


def _choose_track(tracks: list[dict[str, Any]], languages: list[str]) -> dict[str, Any] | None:
    ranked = [(match, track) for track in tracks if (match := _language_match(_track_language(track), languages)) is not None]
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def _invidious_get(url: str) -> requests.Response:
    response = requests.get(url, timeout=REQUEST_TIMEOUT, headers=INVIDIOUS_HEADERS)
    response.raise_for_status()
    return response


def _caption_candidates(base: str, video_id: str, languages: list[str]) -> list[tuple[str, str, str]]:
    """Return (url, language, label) attempts. A failed track list does not drop the host."""
    candidates: list[tuple[str, str, str]] = []
    try:
        listed = _invidious_get(f"{base}/api/v1/captions/{video_id}")
        tracks = _caption_tracks(listed.json() if listed.content else {})
    except (requests.RequestException, ValueError):
        tracks = []
    track = _choose_track(tracks, languages)
    if track is not None:
        caption_url = str(track.get("url") or "")
        if caption_url:
            target = caption_url if "://" in caption_url else urljoin(base + "/", caption_url.lstrip("/"))
            candidates.append((target, _track_language(track), _track_label(track)))
    primaries: list[str] = []
    for language in languages:
        primary = language.lower().replace("_", "-").split("-", 1)[0]
        if primary and primary not in primaries:
            primaries.append(primary)
    for primary in primaries:
        for label in _LABEL_GUESSES.get(primary, ()):
            query = urlencode({"label": label})
            candidates.append((f"{base}/api/v1/captions/{video_id}?{query}", primary, label))
        candidates.append((f"{base}/api/v1/captions/{video_id}?lang={primary}", primary, ""))
    unique: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for item in candidates:
        if item[0] in seen:
            continue
        seen.add(item[0])
        unique.append(item)
    return unique


def _transcript_from_body(body: str, content_type: str, language: str, label: str, instance: str) -> dict[str, Any] | None:
    if not _looks_like_vtt(body, content_type):
        return None
    text = _vtt_to_text(body)
    if not text:
        return None
    return {
        "status": "available",
        "language": language,
        "is_generated": "auto-generated" in label.lower(),
        "text": text[:MAX_TRANSCRIPT_CHARS],
        "truncated": len(text) > MAX_TRANSCRIPT_CHARS,
        "instance": instance,
    }


def _fetch_invidious_transcript(video_id: str, languages: list[str]) -> dict[str, Any]:
    errors: list[str] = []
    for base in _invidious_instances():
        found_text = False
        for target, language, label in _caption_candidates(base, video_id, languages):
            try:
                caption = _invidious_get(target)
            except requests.RequestException as error:
                errors.append(f"{target}: {error}")
                continue
            if not caption.text.strip():
                errors.append(f"{target}: caption track was empty")
                continue
            result = _transcript_from_body(
                caption.text,
                caption.headers.get("content-type", ""),
                language,
                label,
                base,
            )
            if result is not None:
                return result
            found_text = True
        if not found_text and not any(error.startswith(base) or error.startswith(f"{base}/") for error in errors):
            errors.append(f"{base}: no caption track for {', '.join(languages)}")
    return {
        "status": "unavailable",
        "language": "",
        "is_generated": None,
        "text": "",
        "error": ("; ".join(errors) or "No Invidious instance returned captions.")[:500],
    }


def _transcript(video_id: str, languages: list[str]) -> dict[str, Any]:
    cache_key = f"invidious-v3-{video_id}-{','.join(languages)}"
    cached = _read_cache("transcripts", cache_key)
    if cached:
        if cached.get("status") == "available":
            return cached
        path = _cache_path("transcripts", cache_key)
        try:
            cached_at = json.loads(path.read_text(encoding="utf-8")).get("cached_at", 0)
        except (OSError, json.JSONDecodeError, AttributeError):
            cached_at = 0
        if time.time() - cached_at < 600:
            return cached
    result = _fetch_invidious_transcript(video_id, languages)
    # Successful results are read without expiry; failures expire after ten minutes.
    _write_cache("transcripts", cache_key, result)
    return result


def _parse_video_ids(value: str) -> list[str]:
    ids: list[str] = []
    for part in re.split(r"[\s,]+", value.strip()):
        if not part:
            continue
        parsed = urlparse(part if "://" in part else f"https://www.youtube.com/watch?v={part}")
        host = (parsed.hostname or "").lower()
        video_id = ""
        if host.endswith("youtu.be"):
            video_id = parsed.path.strip("/").split("/")[0]
        elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
            if parsed.path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [""])[0]
            elif parsed.path.startswith("/shorts/") or parsed.path.startswith("/embed/"):
                video_id = parsed.path.split("/")[2]
        elif "://" not in part:
            video_id = part
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise YouTubeError(f"Invalid YouTube video ID or URL: {part!r}")
        if video_id not in ids:
            ids.append(video_id)
    if not ids:
        raise YouTubeError("Provide at least one YouTube video ID or URL.")
    if len(ids) > MAX_VIDEO_IDS_PER_CALL:
        raise YouTubeError(f"A single request can include at most {MAX_VIDEO_IDS_PER_CALL} videos.")
    return ids


@mcp.tool()
def list_recent_uploads(channel: str, hours: int = 24, max_results: int = 100) -> dict[str, Any]:
    """List a channel's uploads published within the last N hours, newest first.

    `channel` accepts a YouTube @handle, UC channel ID, or channel URL. `hours`
    is measured from the current UTC instant. `format=short_candidate` only means
    duration is at most 180 seconds; YouTube's Data API does not identify Shorts.
    """
    details, uploads = _recent_uploads(channel, hours, max_results)
    return {
        "channel": details,
        "window_hours": hours,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "count": len(uploads),
        "uploads": uploads,
        "notes": [
            "Results use YouTube Data API publication timestamps and are sorted newest first.",
            "short_candidate is a duration heuristic, not an authoritative YouTube Shorts label.",
        ],
    }


@mcp.tool()
def get_video_metadata(video_ids_or_urls: str) -> dict[str, Any]:
    """Get title, description, publish time, duration, and thumbnail for videos.

    Pass comma- or whitespace-separated video IDs/URLs (up to 50). This uses
    YouTube Data API metadata only and does not fetch transcripts.
    """
    video_ids = _parse_video_ids(video_ids_or_urls)
    videos = _video_metadata(video_ids)
    return {"count": len(videos), "videos": [videos[video_id] for video_id in video_ids if video_id in videos]}


@mcp.tool()
def get_video_transcripts(video_ids_or_urls: str, languages: str = "en,en-US,en-GB") -> dict[str, Any]:
    """Retrieve captions for up to 50 videos from a public Invidious instance.

    This is a separate, best-effort transcript operation intended for the
    source-summarizer subagent. Pass one video or a comma/space-separated batch.
    The tool calls Invidious `GET /api/v1/captions/:id?lang=en` (and the English
    label URLs) even when the bare track list is refused. Set `INVIDIOUS_INSTANCES`
    or `INVIDIOUS_BASE_URL` to override the documented public instances. Each result
    has status, language, generated flag, and text. No browser is launched and
    no video file is downloaded.
    """
    video_ids = _parse_video_ids(video_ids_or_urls)
    language_list = [language.strip() for language in languages.split(",") if language.strip()][:10] or DEFAULT_LANGUAGES
    transcripts: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_TRANSCRIPTS, len(video_ids))) as pool:
        futures = {pool.submit(_transcript, video_id, language_list): video_id for video_id in video_ids}
        for future in as_completed(futures):
            video_id = futures[future]
            try:
                transcripts[video_id] = future.result()
            except Exception as error:
                transcripts[video_id] = {
                    "status": "unavailable",
                    "language": "",
                    "is_generated": None,
                    "text": "",
                    "error": str(error)[:500],
                }
    return {
        "count": len(video_ids),
        "videos": [
            {
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "transcript": transcripts[video_id],
            }
            for video_id in video_ids
        ],
        "notes": [
            "Transcripts come from an Invidious instance's captions API as WebVTT, then plain text.",
            "An unavailable transcript means no instance returned that caption track.",
        ],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
