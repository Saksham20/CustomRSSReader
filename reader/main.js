const AIM = "https://analyticsindiamag.com/ns/aim-daily";
const MEDIA = "http://search.yahoo.com/mrss/";
const FEED_URL = "aim-daily-news.xml";

const app = document.querySelector("#app");
const editionDate = document.querySelector("#edition-date");
const editionSub = document.querySelector("#edition-sub");
const themeToggle = document.querySelector("#theme-toggle");

const savedTheme = localStorage.getItem("aim-theme");
if (savedTheme === "night") applyTheme("night");

themeToggle.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "night" ? "paper" : "night";
  applyTheme(next);
  localStorage.setItem("aim-theme", next);
});

function applyTheme(theme) {
  if (theme === "night") {
    document.documentElement.dataset.theme = "night";
    themeToggle.textContent = "Paper";
    themeToggle.setAttribute("aria-pressed", "true");
  } else {
    delete document.documentElement.dataset.theme;
    themeToggle.textContent = "Night";
    themeToggle.setAttribute("aria-pressed", "false");
  }
}

function nodeText(parent, ns, name) {
  const node = parent.getElementsByTagNameNS(ns, name)[0];
  return node ? node.textContent.trim() : "";
}

function localText(parent, name) {
  const node = parent.getElementsByTagName(name)[0];
  return node ? node.textContent.trim() : "";
}

function formatWhen(iso, options) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    ...options,
  }).format(date);
}

function clock(iso) {
  return formatWhen(iso, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

function longDate(iso) {
  return formatWhen(iso, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([key, value]) => {
    if (value == null || value === false) return;
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  });
  for (const child of [].concat(children || [])) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

function parseDescription(html) {
  const doc = new DOMParser().parseFromString(`<article>${html}</article>`, "text/html");
  const paragraphs = [...doc.querySelectorAll("p")].map((p) => p.textContent.trim()).filter(Boolean);
  const points = [...doc.querySelectorAll("li")].map((li) => li.textContent.trim()).filter(Boolean);
  const summary = paragraphs[0] || "";
  const frame = paragraphs.length > 1 ? paragraphs[paragraphs.length - 1] : "";
  return { summary, points, frame: frame === summary ? "" : frame };
}

function splitBriefing(text) {
  const paragraphs = text
    .split(/\n\s*\n/)
    .map((part) => part.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  let headline = "";
  const body = [];
  paragraphs.forEach((paragraph) => {
    const match = paragraph.match(/^The morning's through-line:\s*(.*)$/i);
    if (match && !headline) {
      headline = match[1].replace(/\.$/, "");
      return;
    }
    body.push(paragraph);
  });
  return { headline, body };
}

function splitKicker(paragraph) {
  const match = paragraph.match(/^([^,.?!]{3,48})\.\s+([\s\S]+)$/);
  if (!match) return { kicker: "", text: paragraph };
  return { kicker: match[1], text: match[2] };
}

function readFeed(xml) {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  if (doc.querySelector("parsererror")) {
    throw new Error("The news feed could not be read.");
  }
  const channel = doc.getElementsByTagName("channel")[0];
  const edition = channel.getElementsByTagNameNS(AIM, "edition")[0];
  const latest = edition ? edition.getElementsByTagNameNS(AIM, "latestLongForm")[0] : null;
  const items = [...channel.getElementsByTagName("item")].map((item) => {
    const thumb = item.getElementsByTagNameNS(MEDIA, "thumbnail")[0];
    const categories = [...item.getElementsByTagName("category")].map((node) => node.textContent.trim());
    return {
      title: localText(item, "title"),
      link: localText(item, "link"),
      publishedIst: nodeText(item, AIM, "publishedIst"),
      format: nodeText(item, AIM, "format") || categories[0] || "Video",
      categories,
      thumb: thumb ? thumb.getAttribute("url") : "",
      ...parseDescription(localText(item, "description")),
    };
  });
  return {
    briefing: edition ? nodeText(edition, AIM, "briefing") : "",
    method: edition ? nodeText(edition, AIM, "method") : "",
    scannedAtIst: edition ? nodeText(edition, AIM, "scannedAtIst") : "",
    editionDate: edition ? edition.getAttribute("date") : "",
    longFormCount: edition ? nodeText(edition, AIM, "longFormCount") : "",
    shortCount: edition ? nodeText(edition, AIM, "shortCount") : String(items.length),
    videosTab: edition ? nodeText(edition, AIM, "videosTab") : "https://www.youtube.com/@aimmediahouse/videos",
    shortsTab: edition ? nodeText(edition, AIM, "shortsTab") : "https://www.youtube.com/@aimmediahouse/shorts",
    latestLongForm: latest
      ? {
          title: latest.textContent.trim(),
          published: latest.getAttribute("published") || "",
          videoId: latest.getAttribute("videoId") || "",
        }
      : null,
    items,
  };
}

function render(feed) {
  const { headline, body } = splitBriefing(feed.briefing);
  const scanClock = clock(feed.scannedAtIst);
  const editionLabel = feed.editionDate
    ? longDate(`${feed.editionDate}T12:00:00+05:30`)
    : "Today’s edition";

  document.title = `AIM Front Page · ${editionLabel}`;
  editionDate.textContent = editionLabel;
  editionSub.textContent = scanClock ? `Scanned ${scanClock} IST` : "AIM Network";

  const leadChildren = [];
  leadChildren.push(el("p", { class: "kicker" }, "Morning edition"));
  if (headline) leadChildren.push(el("h1", { class: "display" }, headline));
  body.forEach((paragraph, index) => {
    const { kicker, text } = splitKicker(paragraph);
    if (!kicker) {
      leadChildren.push(el("p", { class: index === 0 && !headline ? "display" : "lede" }, paragraph));
      return;
    }
    leadChildren.push(
      el("section", { class: "brief-block" }, [
        el("h2", null, kicker),
        el("p", null, text),
      ]),
    );
  });

  const storyNodes = feed.items.map((item, index) => {
    const id = `story-${index + 1}`;
    const when = clock(item.publishedIst);
    const points = item.points.map((point, pointIndex) =>
      el("li", null, [
        el("span", null, String(pointIndex + 1).padStart(2, "0")),
        el("p", null, point),
      ]),
    );
    const figure = item.thumb
      ? el("img", {
          class: "thumb",
          src: item.thumb,
          alt: `Published frame from “${item.title}”`,
          width: "360",
          height: "560",
        })
      : el("div", { class: "thumb", role: "img", "aria-label": "No frame available" });

    figure.addEventListener?.("error", () => {
      if (item.link && figure.tagName === "IMG" && !figure.dataset.fallback) {
        const idMatch = item.link.match(/v=([^&]+)/);
        if (idMatch) {
          figure.dataset.fallback = "1";
          figure.src = `https://i.ytimg.com/vi/${idMatch[1]}/hqdefault.jpg`;
        }
      }
    });

    return el("article", { class: "story", id }, [
      el("div", null, [
        el("p", { class: "story-kicker" }, [
          when ? el("time", { datetime: item.publishedIst }, `${when} IST`) : null,
          el("span", null, item.categories.join(" · ") || item.format),
        ]),
        el("h2", null, el("a", { href: `#${id}` }, item.title)),
        item.summary ? el("p", { class: "dek" }, item.summary) : null,
        points.length ? el("ol", { class: "points" }, points) : null,
        item.frame
          ? el("div", { class: "frame" }, [el("h3", null, "On screen"), el("p", null, item.frame)])
          : null,
        item.link
          ? el(
              "a",
              { class: "watch", href: item.link, target: "_blank", rel: "noopener noreferrer" },
              "Watch on YouTube",
            )
          : null,
      ]),
      figure,
    ]);
  });

  const links = feed.items.map((item, index) =>
    el("a", { href: `#story-${index + 1}` }, [
      el("time", null, clock(item.publishedIst) || String(index + 1).padStart(2, "0")),
      el("span", null, item.title),
    ]),
  );

  const latest = feed.latestLongForm;
  const latestLine = latest
    ? `Newest long video is still “${latest.title},” posted ${longDate(latest.published)} at ${clock(latest.published)} IST.`
    : "No earlier long video was listed.";

  const rail = el("aside", { class: "rail" }, [
    el("div", { class: "facts" }, [
      el("div", { class: "fact" }, [el("b", null, feed.shortCount || "0"), el("span", null, "Shorts")]),
      el("div", { class: "fact" }, [el("b", null, feed.longFormCount || "0"), el("span", null, "Long videos")]),
    ]),
    el("p", { class: "rail-note" }, [
      feed.longFormCount === "0" ? "No long-form upload in this scan. " : "",
      latestLine,
    ]),
    el("p", { class: "rail-links" }, [
      el("a", { href: feed.videosTab }, "Videos"),
      el("a", { href: feed.shortsTab }, "Shorts"),
    ]),
    el("nav", { class: "story-nav", "aria-label": "Stories in this edition" }, links),
  ]);

  app.replaceChildren(
    el("div", { class: "layout" }, [
      rail,
        el("div", { class: "sheet" }, [
        el("section", { class: "lead", "aria-label": "Morning briefing" }, leadChildren),
        el("section", { class: "stories", id: "stories", "aria-label": "Stories" }, storyNodes),
      ]),
    ]),
  );

  const colophon = el("footer", { class: "colophon" }, [
    feed.method ? el("p", null, feed.method) : null,
    el("p", null, [
      "The page reads ",
      el("a", { href: FEED_URL }, "aim-daily-news.xml"),
      ". Serve the repository root and open this page so the feed can load.",
    ]),
  ]);
  document.querySelector(".colophon")?.remove();
  app.insertAdjacentElement("afterend", colophon);

  const articles = [...app.querySelectorAll(".story")];
  const navLinks = [...app.querySelectorAll(".story-nav a")];
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          navLinks.forEach((link) => link.classList.remove("is-current"));
          const current = navLinks.find((link) => link.getAttribute("href") === `#${entry.target.id}`);
          current?.classList.add("is-current");
        });
      },
      { rootMargin: "-20% 0px -65% 0px", threshold: 0 },
    );
    articles.forEach((article) => observer.observe(article));
  }
}

async function init() {
  try {
    const response = await fetch(FEED_URL);
    if (!response.ok) throw new Error(`Feed responded ${response.status}`);
    render(readFeed(await response.text()));
  } catch (error) {
    app.replaceChildren(
      el("p", { class: "status" }, "The edition could not be loaded."),
      el(
        "p",
        { class: "colophon" },
        "Open this page through a local server at the repository root so it can read aim-daily-news.xml.",
      ),
    );
    console.error(error);
  }
}

init();
