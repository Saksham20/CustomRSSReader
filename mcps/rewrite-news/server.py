#!/usr/bin/env python3
"""MCP server that rewrites the AIM news XML through the Cursor Python SDK.

The key is never stored in this repository. Name the GitHub Actions secret
CURSOR_API_KEY. Locally, export the same name before Cursor starts. The
project file .cursor/mcp.json passes it through as ${env:CURSOR_API_KEY}.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from mcp.server.mcpserver import MCPServer

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEED = REPO_ROOT / "aim-daily-news.xml"
PLACEHOLDER_KEYS = {"", "YOUR_CURSOR_API_KEY", "placeholder"}
MODEL = {
    "id": "gemini-3.8-flash",
    "params": [{"id": "reasoning_effort", "value": "low"}],
}

mcp = MCPServer("aim-news-rewrite")

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
    if result.status != "finished" or not result.result:
        raise RuntimeError(f"The rewrite did not finish (status: {result.status}).")
    return validate_rewrite(xml_text, result.result)


@mcp.tool()
def rewrite_news_xml(xml_path: str = "", xml: str = "", output_path: str = "") -> str:
    """Rewrite the AIM daily news XML in clearer language without dropping facts.

    Pass xml_path to read a file, or xml to pass the document itself.
    When both are empty, the repository file aim-daily-news.xml is used.
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
