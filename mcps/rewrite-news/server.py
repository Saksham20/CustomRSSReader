#!/usr/bin/env python3
"""MCP server that rewrites the news XML through the Cursor Python SDK.

The key is never stored in this repository. Name the GitHub Actions secret
CURSOR_API_KEY. Locally, export the same name before Cursor starts. The
project file .cursor/mcp.json passes it through as ${env:CURSOR_API_KEY}.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

PLACEHOLDER_KEYS = {"", "YOUR_CURSOR_API_KEY", "placeholder"}
MODEL = {
    "id": "gemini-3.8-flash",
    "params": [{"id": "reasoning_effort", "value": "low"}],
}


def git_root(start: Path) -> Path | None:
    """Walk up to the repository that contains this checkout."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def repository_root() -> Path:
    """Directory whose `.cursor/usage.json` is the committed usage ledger.

    Prefer the repo that contains this file. A copy launched from the checkout
    still records against that checkout, which is the process working directory.
    """
    from_server = git_root(Path(__file__))
    if from_server is not None:
        return from_server
    from_cwd = git_root(Path.cwd())
    if from_cwd is not None:
        return from_cwd
    return Path(__file__).resolve().parents[2]


REPO_ROOT = repository_root()
DEFAULT_FEED = REPO_ROOT / "latest-news.xml"

mcp = FastMCP("aim-news-rewrite")
USAGE_PATH = REPO_ROOT / ".cursor" / "usage.json"
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "total_tokens",
)

PROMPT = """Rewrite this news XML so the prose sounds clear and natural.

Keep every fact. That includes names, titles, numbers, dates, times, quotes,
attributions, video ids, URLs, and the on-screen notes.

Keep the document structure. Do not add, remove, or reorder elements.
Do not change attributes, namespaces, links, or ids.
Change only the human-readable wording in titles, the briefing, descriptions,
key points, and captions.

Return the XML document only. Do not wrap it in Markdown.
"""


def strip_fences(text: str) -> str:
    cleaned = text.strip()
    match = re.fullmatch(r"```(?:xml)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return cleaned


def video_ids(xml_text: str) -> list[str]:
    root = ElementTree.fromstring(xml_text)
    return [
        (element.text or "").strip()
        for element in root.iter()
        if element.tag.endswith("videoId") and (element.text or "").strip()
    ]


def validate_rewrite(source: str, rewritten: str) -> str:
    document = strip_fences(rewritten)
    try:
        rewritten_ids = video_ids(document)
    except ElementTree.ParseError as error:
        raise ValueError(f"Gemini returned XML that does not parse: {error}") from error
    source_ids = video_ids(source)
    if rewritten_ids != source_ids:
        raise ValueError(
            "Gemini changed the video ids. The rewrite was rejected so no detail would be dropped."
        )
    return document


def load_xml(xml_path: str, xml: str) -> tuple[str, Path | None]:
    if xml.strip():
        return xml, None
    path = Path(xml_path).expanduser() if xml_path else DEFAULT_FEED
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.is_file():
        raise FileNotFoundError(f"News XML was not found at {path}")
    return path.read_text(encoding="utf-8"), path


def empty_usage() -> dict[str, int]:
    return {field: 0 for field in TOKEN_FIELDS}


def usage_counts(usage: object) -> dict[str, int]:
    counts = empty_usage()
    if usage is None:
        return counts
    for field in TOKEN_FIELDS:
        value = getattr(usage, field, 0)
        counts[field] = int(value or 0)
    return counts


def record_usage(result: object, path: Path = USAGE_PATH) -> dict:
    """Add one SDK run to the cumulative usage ledger and return the new totals."""
    counts = usage_counts(getattr(result, "usage", None))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        raw = handle.read()
        try:
            ledger = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            ledger = {}
        totals = ledger.get("totals") if isinstance(ledger.get("totals"), dict) else empty_usage()
        totals["calls"] = int(totals.get("calls") or 0) + 1
        for field in TOKEN_FIELDS:
            totals[field] = int(totals.get(field) or 0) + counts[field]
        calls = ledger.get("calls") if isinstance(ledger.get("calls"), list) else []
        calls.append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "run_id": getattr(result, "id", ""),
                "status": getattr(result, "status", ""),
                "model": MODEL,
                **counts,
            }
        )
        document = {"model": MODEL, "totals": totals, "calls": calls}
        handle.seek(0)
        handle.truncate()
        json.dump(document, handle, indent=2)
        handle.write("\n")
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return totals


def rewrite_with_gemini(xml_text: str) -> str:
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if api_key in PLACEHOLDER_KEYS:
        raise RuntimeError(
            "CURSOR_API_KEY is not set. Add it as a GitHub repository secret named "
            "CURSOR_API_KEY, and export that same variable in the environment that launches Cursor."
        )
    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, ModelParameterValue, ModelSelection

    result = Agent.prompt(
        f"{PROMPT}\n\n{xml_text}",
        AgentOptions(
            api_key=api_key,
            model=ModelSelection(
                id=MODEL["id"],
                params=[
                    ModelParameterValue(id=parameter["id"], value=parameter["value"])
                    for parameter in MODEL["params"]
                ],
            ),
            local=LocalAgentOptions(cwd=str(REPO_ROOT)),
            tools=[],
        ),
    )
    record_usage(result)
    if result.status != "finished" or not result.result:
        raise RuntimeError(f"The rewrite did not finish (status: {result.status}).")
    return validate_rewrite(xml_text, result.result)


@mcp.tool()
def rewrite_news_xml(xml_path: str = "", xml: str = "", output_path: str = "") -> str:
    """Rewrite the news XML in clearer language without dropping facts.

    Pass xml_path to read a file, or xml to pass the document itself.
    When both are empty, the repository file latest-news.xml is used.
    Set output_path to also save the rewritten document. The source file is left unchanged.
    """
    source, _ = load_xml(xml_path, xml)
    rewritten = rewrite_with_gemini(source)
    if output_path.strip():
        destination = Path(output_path).expanduser()
        if not destination.is_absolute():
            destination = REPO_ROOT / destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rewritten, encoding="utf-8")
    return rewritten


if __name__ == "__main__":
    mcp.run(transport="stdio")
