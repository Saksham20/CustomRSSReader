import { useEffect, useState } from "react";
import { clock, dayKey, feedUrl, longDate, readFeed, splitKicker } from "./feed.js";

function useTheme() {
  const [theme, setTheme] = useState(
    () => document.documentElement.dataset.theme || "paper",
  );

  useEffect(() => {
    if (theme === "night") document.documentElement.dataset.theme = "night";
    else delete document.documentElement.dataset.theme;
    localStorage.setItem("aim-theme", theme);
  }, [theme]);

  return [theme, () => setTheme((current) => (current === "night" ? "paper" : "night"))];
}

function useCurrentStory(idKey) {
  const ids = idKey ? idKey.split("|") : [];
  const [current, setCurrent] = useState(ids[0] || "");

  useEffect(() => {
    if (!ids.length || !("IntersectionObserver" in window)) return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) setCurrent(entry.target.id);
        });
      },
      { rootMargin: "-20% 0px -65% 0px" },
    );
    ids.forEach((id) => {
      const node = document.getElementById(id);
      if (node) observer.observe(node);
    });
    return () => observer.disconnect();
  }, [idKey]);

  return current;
}

function Frame({ item, note }) {
  const [src, setSrc] = useState(item.thumb);
  if (!src) return null;
  return (
    <figure className="frame">
      <img
        className="thumb"
        src={src}
        alt={`Published frame from “${item.title}”`}
        onError={() => {
          const id = item.link?.match(/[?&]v=([^&]+)/)?.[1];
          if (id && !src.includes("hqdefault")) {
            setSrc(`https://i.ytimg.com/vi/${id}/hqdefault.jpg`);
          }
        }}
      />
      <figcaption className="caption">Published frame</figcaption>
      {note ? <p>{note}</p> : null}
    </figure>
  );
}

function KeyPoints({ points }) {
  if (!points.length) return null;
  return (
    <section className="know" aria-label="What you need to know">
      <h3>What you need to know</h3>
      <ol>
        {points.map((point, index) => (
          <li key={point}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <p>{point}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Story({ item, rank }) {
  const Heading = rank === "lead" ? "h2" : "h3";
  return (
    <article className={`story story-${rank}`} id={item.id}>
      <div>
        <p className="story-kicker">
          {item.publishedIst ? (
            <time dateTime={item.publishedIst}>{clock(item.publishedIst)} IST</time>
          ) : null}
          <span>{item.categories.join(" · ") || item.format}</span>
        </p>
        <Heading>
          <a href={`#${item.id}`}>{item.title}</a>
        </Heading>
        {item.summary ? <p className="dek">{item.summary}</p> : null}
        <KeyPoints points={item.points} />
        {rank === "brief" && item.frame ? <p className="on-screen">{item.frame}</p> : null}
        {item.link ? (
          <a className="watch" href={item.link} target="_blank" rel="noopener noreferrer">
            Watch on YouTube
          </a>
        ) : null}
      </div>
      <Frame item={item} note={rank === "brief" ? "" : item.frame} />
    </article>
  );
}

function rankFor(index, isLatestDay) {
  if (!isLatestDay) return "brief";
  if (index === 0) return "lead";
  if (index < 3) return "pair";
  return "brief";
}

export function App() {
  const [theme, toggleTheme] = useTheme();
  const [state, setState] = useState({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetch(feedUrl, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`The feed responded with ${response.status}.`);
        return response.text();
      })
      .then((xml) => setState({ status: "ready", feed: readFeed(xml) }))
      .catch((error) => {
        if (error.name === "AbortError") return;
        setState({ status: "error", message: "The edition could not be loaded." });
      });
    return () => controller.abort();
  }, []);

  const idKey = state.feed?.items.map((item) => item.id).join("|") || "";
  const current = useCurrentStory(idKey);

  if (state.status === "loading") {
    return <p className="status">Opening today’s edition…</p>;
  }
  if (state.status === "error") {
    return <p className="status">{state.message}</p>;
  }

  const { feed } = state;
  const edition = feed.edition;
  const editionLabel = edition?.editionDate
    ? longDate(`${edition.editionDate}T12:00:00+05:30`)
    : "Today’s edition";
  const publication = feed.channelTitle || "Latest";
  document.title = `${publication} · ${editionLabel}`;

  const standfirst = feed.body[0] || "";
  const sections = feed.body.slice(1);
  const days = [];
  feed.items.forEach((item) => {
    const key = item.day || "undated";
    const group = days.find((day) => day.key === key);
    if (group) group.items.push(item);
    else days.push({ key, label: item.publishedIst ? longDate(item.publishedIst) : "Undated", items: [item] });
  });
  days.sort((a, b) => b.key.localeCompare(a.key));
  const latestLong = edition?.latestLongForm;
  const latestDay = latestLong ? dayKey(latestLong.published) : "";
  const latestIsThisEdition = Boolean(latestDay && latestDay === edition?.editionDate);

  return (
    <>
      <a className="skip" href="#stories">
        Skip to stories
      </a>
      <header className="mast">
        <div className="mast-inner">
          <div className="mark" aria-hidden="true">
            L
          </div>
          <div className="mast-title">
            <strong>{publication}</strong>
            <span>News of relevance</span>
          </div>
          <div className="mast-meta">
            <div>
              <div className="edition-date">{editionLabel}</div>
              <span className="edition-sub">
                {edition?.scannedAtIst ? `Scanned ${clock(edition.scannedAtIst)} IST` : "Daily edition"}
              </span>
            </div>
            <button
              className="theme-btn"
              type="button"
              aria-pressed={theme === "night"}
              onClick={toggleTheme}
            >
              {theme === "night" ? "Paper" : "Night"}
            </button>
          </div>
        </div>
      </header>
      <div className="spot" aria-hidden="true" />
      <div className="skyline">
        <p className="skyline-inner">
          <span>{edition?.shortCount || feed.items.length} shorts</span>
          <span>{edition?.longFormCount || "0"} long videos</span>
          {latestLong ? (
            <span>
              {latestIsThisEdition ? "Newest video" : "Latest long video still"}{" "}
              {longDate(latestLong.published)}
            </span>
          ) : null}
          {edition?.videosTab ? <a href={edition.videosTab}>Videos</a> : null}
          {edition?.shortsTab ? <a href={edition.shortsTab}>Shorts</a> : null}
        </p>
      </div>
      <main className="sheet">
        <div className="top">
          <section className="lead" aria-label="Daily briefing">
            <p className="kicker">Today's edition</p>
            {feed.headline ? <h1 className="display">{feed.headline}</h1> : <h1 className="display">{editionLabel}</h1>}
            {standfirst ? <p className="standfirst">{standfirst}</p> : null}
            {sections.length ? (
              <div className="sections">
                {sections.map((paragraph) => {
                  const { kicker, text } = splitKicker(paragraph);
                  return (
                    <section key={paragraph.slice(0, 48)}>
                      {kicker ? <h2>{kicker}</h2> : null}
                      <p>{kicker ? text : paragraph}</p>
                    </section>
                  );
                })}
              </div>
            ) : null}
          </section>
          <aside className="rail">
            <div className="facts">
              <div className="fact">
                <b>{edition?.shortCount || feed.items.length}</b>
                <span>Shorts</span>
              </div>
              <div className="fact">
                <b>{edition?.longFormCount || "0"}</b>
                <span>Long videos</span>
              </div>
            </div>
            <p className="rail-note">
              {edition?.longFormCount === "0" ? "No long-form upload in this scan. " : ""}
              {latestLong
                ? latestIsThisEdition
                  ? `Newest video is “${latestLong.title},” posted ${longDate(latestLong.published)} at ${clock(latestLong.published)} IST.`
                  : `Newest long video is still “${latestLong.title},” posted ${longDate(latestLong.published)} at ${clock(latestLong.published)} IST.`
                : ""}
            </p>
            <nav className="index" aria-label="Stories in this edition">
              {feed.items.map((item) => (
                <a key={item.id} href={`#${item.id}`} className={current === item.id ? "is-current" : undefined}>
                  <time>{clock(item.publishedIst)}</time>
                  <span>{item.title}</span>
                </a>
              ))}
            </nav>
          </aside>
        </div>

        <div id="stories">
          {days.map((day, dayIndex) => {
            const lead = day.items.filter((_, index) => rankFor(index, dayIndex === 0) === "lead");
            const pair = day.items.filter((_, index) => rankFor(index, dayIndex === 0) === "pair");
            const briefs = day.items.filter((_, index) => rankFor(index, dayIndex === 0) === "brief");
            return (
              <section key={day.key} aria-label={day.label}>
                <div className="day-rule">
                  <strong>{day.label}</strong>
                  <span>{dayIndex === 0 ? "Lead edition" : "Earlier edition"}</span>
                </div>
                {lead.map((item) => (
                  <Story key={item.id} item={item} rank="lead" />
                ))}
                {pair.length ? (
                  <div className="pair">
                    {pair.map((item) => (
                      <Story key={item.id} item={item} rank="pair" />
                    ))}
                  </div>
                ) : null}
                {briefs.map((item) => (
                  <Story key={item.id} item={item} rank="brief" />
                ))}
              </section>
            );
          })}
        </div>

        {edition?.method ? (
          <footer className="colophon">
            <p>{edition.method}</p>
            <p>
              This page reads <a href={feedUrl}>latest-news.xml</a> when it loads. A new edition in that file
              appears here without a change to the page itself. GitHub Actions rebuilds the site when the file is
              pushed.
            </p>
          </footer>
        ) : null}
      </main>
    </>
  );
}
