# CustomRSSReader

## YouTube source MCP

The read-only `youtube-news-source` MCP finds recent uploads and exposes
separate metadata and transcript tools. Discovery does not fetch transcripts:
the `source-summarizer` subagent calls the transcript tool for its assigned
video. It does not open a browser or download videos. Transcript retrieval is
best effort and reports its status explicitly.

### Setup

1. Enable **YouTube Data API v3** in a Google Cloud project and create an API
   key. Restrict the key to YouTube Data API v3 where possible.
2. Set `YOUTUBE_API_KEY` in the environment used to start Cursor locally.
3. Run `.cursor/install.sh` (or install `mcps/youtube/requirements.txt`) and
   restart Cursor so it reloads `.cursor/mcp.json`.
4. For Cursor Cloud Agents, configure the MCP in the Cloud Agents MCP settings
   as a stdio server using `python3` and the repository path
   `mcps/youtube/server.py`. Add `YOUTUBE_API_KEY` as that server's secret
   environment variable. Cloud Agent MCP settings and secrets are managed in
   Cursor; the checked-in `.cursor/mcp.json` is the local project configuration.

The server needs no YouTube OAuth because it reads public channel/video
metadata. The API key is required for discovery. Public caption retrieval uses
`youtube-transcript-api`, which is unofficial and may be rate-limited or blocked
by YouTube; unavailable transcripts are returned as data rather than triggering
browser automation. API and transcript responses are cached under
`mcps/youtube/.cache/` when the runtime permits writing there. The cache is
local, untracked, and safe to delete.

### MCP tools

- `list_recent_uploads(channel, hours=24, max_results=100)` lists recent uploads
  without requesting captions.
- `get_video_metadata(video_ids_or_urls)` fetches metadata for up to 50 videos.
- `get_video_transcripts(video_ids_or_urls, languages="en,en-US,en-GB")`
  retrieves captions for up to 50 videos. This is an unofficial, best-effort
  path through `youtube-transcript-api`; Google's caption listing does not
  return caption text, and its download method requires permission to edit the
  video. [Google caption API](https://developers.google.com/youtube/data/reference/rest/v3/captions/download)

The channel accepts an `@handle`, a `UC…` channel ID, or a YouTube channel URL.
The last 24 hours means the exact rolling window ending at the retrieval time,
not the current calendar date. YouTube's Data API does not expose a definitive
Shorts flag, so the server labels clips of at most 180 seconds
`short_candidate`; do not treat that heuristic as proof of format. The API
returns public upload metadata, but it does not guarantee an upload is visible
in the Shorts surface.

### Suggested daily run

Use the run instructions in `.cursor/prompts/daily-aim-news.md`. In brief:

1. Call `list_recent_uploads` once for the channel and desired time window.
2. Skip an empty result. Otherwise, dispatch one `.cursor/agents/source-summarizer.md`
   task per returned video, passing its JSON upload record. Each summarizer calls
   `get_video_transcripts` for its assigned video; it needs no browser or web
   search.
3. Merge the summaries into the newest `news:edition` and `item` entries in
   `latest-news.xml`. Preserve existing editions and item IDs, and deduplicate
   by video ID.
4. Validate the XML and the date window before committing to the requested
   branch. Keep transcript-unavailable items clearly grounded in their supplied
   title and description.

The main efficiency gain is that discovery, metadata lookup, transcript
retrieval, and caching happen in code, while parallel summarizers only handle
editorial work.

## Run the daily workflow locally

The SDK runner loads only `CURSOR_API_KEY` and `YOUTUBE_API_KEY` from the
repository `.env` file. It defines the YouTube and XML rewrite MCP servers
inline, so it does not load other Cursor project or user MCP settings. Cursor's
Python SDK supports inline stdio MCP servers for local agents. [SDK reference](https://cursor.com/docs/sdk/python)

```sh
cp .env.example .env
# Fill in CURSOR_API_KEY and YOUTUBE_API_KEY in .env
bash .cursor/install.sh
python3 scripts/run_daily_local.py
```

By default the agent retrieves and summarizes sources, then returns a proposed
feed update without editing files. Add `--apply` to let it update the local
`latest-news.xml`. The runner always prohibits committing or pushing. Keep `.env`
private; it is excluded from Git.

### Test the YouTube MCP with a URL

Use the simple URL checker to inspect a single video or the latest channel
uploads. Edit the `YOUTUBE_URL` variable near the top of the script, then run:

```sh
python3 scripts/test_youtube_mcp.py
```

For a channel URL it checks up to 100 uploads from the last 24 hours. For a
video URL it checks that video. It prints the returned metadata and the first
100 transcript words. Both scripts use `python-dotenv` to read keys from `.env`
without custom parsing. The tester calls the same tool functions as the YouTube
MCP and never invokes the Cursor model or writes the news feed.
