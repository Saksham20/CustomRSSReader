const AIM = "https://analyticsindiamag.com/ns/aim-daily";
const MEDIA = "http://search.yahoo.com/mrss/";

function nodeText(parent, ns, name) {
  const node = parent.getElementsByTagNameNS(ns, name)[0];
  return node ? node.textContent.trim() : "";
}

function localText(parent, name) {
  const node = parent.getElementsByTagName(name)[0];
  return node ? node.textContent.trim() : "";
}

export function formatWhen(iso, options) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    ...options,
  }).format(date);
}

export function clock(iso) {
  return formatWhen(iso, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

export function longDate(iso) {
  return formatWhen(iso, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function dayKey(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function parseDescription(html) {
  const doc = new DOMParser().parseFromString(`<article>${html}</article>`, "text/html");
  const paragraphs = [...doc.querySelectorAll("p")].map((node) => node.textContent.trim()).filter(Boolean);
  const points = [...doc.querySelectorAll("li")].map((node) => node.textContent.trim()).filter(Boolean);
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

export function splitKicker(paragraph) {
  const match = paragraph.match(/^([^,.?!]{3,48})\.\s+([\s\S]+)$/);
  if (!match) return { kicker: "", text: paragraph };
  return { kicker: match[1], text: match[2] };
}

function readEdition(edition) {
  const latest = edition.getElementsByTagNameNS(AIM, "latestLongForm")[0];
  return {
    briefing: nodeText(edition, AIM, "briefing"),
    method: nodeText(edition, AIM, "method"),
    scannedAtIst: nodeText(edition, AIM, "scannedAtIst"),
    editionDate: edition.getAttribute("date") || "",
    longFormCount: nodeText(edition, AIM, "longFormCount"),
    shortCount: nodeText(edition, AIM, "shortCount"),
    videosTab: nodeText(edition, AIM, "videosTab") || "https://www.youtube.com/@aimmediahouse/videos",
    shortsTab: nodeText(edition, AIM, "shortsTab") || "https://www.youtube.com/@aimmediahouse/shorts",
    latestLongForm: latest
      ? {
          title: latest.textContent.trim(),
          published: latest.getAttribute("published") || "",
          videoId: latest.getAttribute("videoId") || "",
        }
      : null,
  };
}

export function readFeed(xml) {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  if (doc.querySelector("parsererror")) {
    throw new Error("The news feed could not be read.");
  }
  const channel = doc.getElementsByTagName("channel")[0];
  const editions = [...channel.getElementsByTagNameNS(AIM, "edition")]
    .map(readEdition)
    .sort((a, b) => b.editionDate.localeCompare(a.editionDate));
  const edition = editions[0] || null;
  const items = [...channel.getElementsByTagName("item")].map((item, index) => {
    const thumb = item.getElementsByTagNameNS(MEDIA, "thumbnail")[0];
    const categories = [...item.getElementsByTagName("category")].map((node) => node.textContent.trim());
    return {
      id: `story-${index + 1}`,
      title: localText(item, "title"),
      link: localText(item, "link"),
      publishedIst: nodeText(item, AIM, "publishedIst"),
      day: dayKey(nodeText(item, AIM, "publishedIst")),
      format: nodeText(item, AIM, "format") || categories[0] || "Video",
      categories,
      thumb: thumb ? thumb.getAttribute("url") : "",
      ...parseDescription(localText(item, "description")),
    };
  });
  const { headline, body } = splitBriefing(edition?.briefing || "");
  return { edition, headline, body, items };
}

export const feedUrl = `${import.meta.env.BASE_URL}aim-daily-news.xml`;
