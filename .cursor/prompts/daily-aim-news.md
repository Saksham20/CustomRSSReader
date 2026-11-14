# Daily AIM news edition

Update `latest-news.xml` with Analytics India Magazine uploads published during
the rolling 24 hours ending now. Work only on the current branch and push only
to `cursor/daily-aim-news-summary-55ad`.

## Source gathering

1. Call `youtube-news-source.list_recent_uploads` once with
   `channel="https://www.youtube.com/@aimmediahouse/videos"` and `hours=24`.
2. Do not browse YouTube, launch a computer/browser agent, watch or download
   videos, or retry missing captions through other tools. Discovery returns the
   supported metadata: publication time, title, description, duration, URL,
   and video ID. Caption text is fetched separately by the summarizer tool.
3. If there are no uploads, stop without changing the feed.
4. For each returned video, ask the `source-summarizer` subagent for one JSON
   summary. Run these independent summaries in parallel. Pass the complete
   upload record; each summarizer calls
   `youtube-news-source.get_video_transcripts` for its assigned video. Do not
   ask subagents to discover additional sources.
5. If the transcript is unavailable, use only the supplied title and
   description, state the limitation, and avoid claims that require hearing or
   seeing the video. Treat `short_candidate` as a duration heuristic, not proof
   of a YouTube Short. Do not claim visual analysis; this workflow does not
   retrieve video frames.

## Feed update

1. Read the existing `latest-news.xml` and preserve its RSS namespaces,
   historical editions, and existing items.
2. Create the current edition in the format already used by the feed. Include
   the scan time in UTC and IST, the exact publication window, counts, channel
   links, a concise briefing, and a short method note that states which source
   fields were available and any transcript gaps.
3. Add one item per useful upload, newest first. Preserve source attribution,
   dates, names, figures, URLs, and uncertainty. Deduplicate by `news:videoId`
   and `guid`; do not create an item whose supplied source has too little
   information for a reliable summary.
4. Keep each source link and publication time. Use the existing item structure
   and HTML description pattern, including key points. Do not invent quotes,
   details, visual observations, or facts from other uploads.
5. Validate that the XML parses, all new items have unique video IDs and
   GUIDs, all included publication times fall within the requested window, and
   the newest edition is first. Do not run a rewrite tool if it could remove
   facts or change identifiers.

Before committing, confirm the current branch is
`cursor/daily-aim-news-summary-55ad`. Commit and push only to that branch.
