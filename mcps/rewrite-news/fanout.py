#!/usr/bin/env python3
"""Run one source-summarizer per URL, in parallel.

The parent agent decides the list. This job gives each worker exactly one
URL from that list and collects the detailed summaries. Workers do not see
the other URLs.
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import server

AGENT_FILE = server.REPO_ROOT / ".cursor" / "agents" / "source-summarizer.md"
DEFAULT_PARALLELISM = 4


def agent_instructions() -> str:
    text = AGENT_FILE.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, _, body = text.split("---", 2)
        return body.strip()
    return text.strip()


def normalize_sources(payload: object) -> list[dict[str, str]]:
    if isinstance(payload, dict) and isinstance(payload.get("sources"), list):
        payload = payload["sources"]
    if not isinstance(payload, list) or not payload:
        raise ValueError("Pass a JSON list of sources, or an object with a sources list.")
    sources = []
    for item in payload:
        if isinstance(item, str):
            url, kind = item, "web"
        elif isinstance(item, dict) and item.get("url"):
            url = str(item["url"])
            kind = str(item.get("kind") or ("youtube" if "youtube.com" in url or "youtu.be" in url else "web"))
        else:
            raise ValueError("Each source needs a url.")
        sources.append({"url": url, "kind": kind})
    return sources


def summarize_one(source: dict[str, str], instructions: str) -> dict:
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if api_key in server.PLACEHOLDER_KEYS:
        raise RuntimeError(
            "CURSOR_API_KEY is not set. Add it as a GitHub repository secret named "
            "CURSOR_API_KEY, and export that same variable before running this job."
        )
    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, ModelParameterValue, ModelSelection

    message = (
        f"{instructions}\n\n"
        f"Kind: {source['kind']}\n"
        f"URL: {source['url']}\n"
    )
    result = Agent.prompt(
        message,
        AgentOptions(
            api_key=api_key,
            model=ModelSelection(
                id=server.MODEL["id"],
                params=[
                    ModelParameterValue(id=parameter["id"], value=parameter["value"])
                    for parameter in server.MODEL["params"]
                ],
            ),
            local=LocalAgentOptions(cwd=str(server.REPO_ROOT)),
            disallowed_tools=["edit", "shell", "task"],
        ),
    )
    server.record_usage(result)
    summary = result.result if result.status == "finished" else ""
    return {
        "url": source["url"],
        "kind": source["kind"],
        "status": result.status,
        "summary": summary,
    }


def fan_out(sources: list[dict[str, str]], worker, max_workers: int) -> list[dict]:
    workers = max(1, min(max_workers, len(sources)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(worker, sources))


def main(argv: list[str]) -> int:
    raw = Path(argv[1]).read_text(encoding="utf-8") if len(argv) > 1 else sys.stdin.read()
    sources = normalize_sources(json.loads(raw))
    instructions = agent_instructions()
    limit = int(os.environ.get("SUMMARY_PARALLELISM", DEFAULT_PARALLELISM))
    results = fan_out(
        sources,
        lambda source: summarize_one(source, instructions),
        limit,
    )
    json.dump(results, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
