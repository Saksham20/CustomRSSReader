import { copyFileSync, cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

const root = dirname(fileURLToPath(import.meta.url));
const feedPath = resolve(root, "../latest-news.xml");
const newsDir = resolve(root, "../news");
const base = process.env.PAGES_BASE || "/";

function newsFile(urlPath) {
  const prefix = base.endsWith("/") ? base.slice(0, -1) : base;
  let path = urlPath.split("?")[0];
  if (prefix && path.startsWith(prefix)) path = path.slice(prefix.length);
  if (path === "/latest-news.xml") return { file: feedPath, type: "application/xml; charset=utf-8" };
  const day = path.match(/^\/news\/(\d{4}-\d{2}-\d{2}\.xml|days\.json)$/);
  if (!day) return null;
  return {
    file: resolve(newsDir, day[1]),
    type: day[1].endsWith(".json") ? "application/json; charset=utf-8" : "application/xml; charset=utf-8",
  };
}

function newsFeed() {
  return {
    name: "aim-news-feed",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const match = newsFile(request.url || "");
        if (!match || !existsSync(match.file)) {
          next();
          return;
        }
        response.setHeader("Content-Type", match.type);
        response.end(readFileSync(match.file));
      });
    },
    closeBundle() {
      const dist = resolve(root, "dist");
      mkdirSync(dist, { recursive: true });
      copyFileSync(feedPath, resolve(dist, "latest-news.xml"));
      if (existsSync(newsDir)) cpSync(newsDir, resolve(dist, "news"), { recursive: true });
      writeFileSync(resolve(dist, ".nojekyll"), "");
    },
  };
}

export default defineConfig({
  base,
  plugins: [react(), tailwindcss(), newsFeed()],
});
