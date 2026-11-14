import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

const root = dirname(fileURLToPath(import.meta.url));
const feedPath = resolve(root, "../latest-news.xml");
const base = process.env.PAGES_BASE || "/";

function newsFeed() {
  return {
    name: "aim-news-feed",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split("?")[0];
        const feedUrl = `${base.endsWith("/") ? base : `${base}/`}latest-news.xml`;
        if (path !== feedUrl && path !== "/latest-news.xml") {
          next();
          return;
        }
        response.setHeader("Content-Type", "application/xml; charset=utf-8");
        response.end(readFileSync(feedPath));
      });
    },
    closeBundle() {
      const dist = resolve(root, "dist");
      mkdirSync(dist, { recursive: true });
      copyFileSync(feedPath, resolve(dist, "latest-news.xml"));
      writeFileSync(resolve(dist, ".nojekyll"), "");
    },
  };
}

export default defineConfig({
  base,
  plugins: [react(), tailwindcss(), newsFeed()],
});
