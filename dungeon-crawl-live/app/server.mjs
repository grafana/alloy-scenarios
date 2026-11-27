import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { extname, resolve, sep } from "node:path";

const data = process.env.DATA_DIR || "/data";
const publicDir = resolve("public");
const sdkDir = resolve("node_modules/@grafana/faro-web-sdk/dist/bundle");
const viewerDir = resolve(data, "viewers");
mkdirSync(viewerDir, { recursive: true });
const crawlers = new Set(["4122", "4119"]);

function readViewer(req, res) {
  const cookie = /(?:^|; *)borant_viewer=([a-f0-9-]{36})(?:;|$)/.exec(
    req.headers.cookie || "",
  );
  const id = cookie?.[1] || randomUUID();
  if (!cookie)
    res.setHeader(
      "Set-Cookie",
      "borant_viewer=" +
        id +
        "; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000",
    );
  const file = resolve(viewerDir, id + ".json");
  return {
    file,
    favourites: existsSync(file) ? JSON.parse(readFileSync(file)) : [],
  };
}
const types = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "text/javascript",
  ".webp": "image/webp",
  ".woff2": "font/woff2",
};
const server = createServer(async (req, res) => {
  function json(status, body) {
    res.writeHead(status, {
      "content-type": "application/json",
      "cache-control": "no-store",
    });
    res.end(JSON.stringify(body));
  }
  try {
    const url = new URL(req.url, "http://game");
    if (url.pathname === "/collect" && req.method === "POST") {
      // Same-origin transport also works when a hosted lab exposes only the game port.
      const collector =
        process.env.FARO_COLLECTOR_URL ||
        "http://host.docker.internal:12347/collect";
      const upstream = await fetch(collector, {
        method: "POST",
        body: req,
        duplex: "half",
        signal: AbortSignal.timeout(10000),
        headers: { "content-type": "application/json" },
      });
      res.writeHead(upstream.status);
      res.end(await upstream.text());
      return;
    }
    if (url.pathname === "/api/config") {
      return json(200, {
        grafana: process.env.GRAFANA_URL,
        grafanaPort: process.env.GRAFANA_PORT || "3000",
      });
    }
    if (url.pathname === "/api/favourites" && req.method === "GET") {
      return json(200, { favourites: readViewer(req, res).favourites });
    }
    if (
      url.pathname.startsWith("/api/favourites/") &&
      ["PUT", "DELETE"].includes(req.method)
    ) {
      const id = url.pathname.slice("/api/favourites/".length);
      if (!crawlers.has(id))
        return json(422, {
          error: "The watchlist requires a numeric crawler ID.",
        });
      const { file, favourites } = readViewer(req, res);
      const next = new Set(favourites);
      if (req.method === "PUT") next.add(id);
      else next.delete(id);
      writeFileSync(file + ".tmp", JSON.stringify([...next]));
      renameSync(file + ".tmp", file);
      return json(200, { favourites: [...next] });
    }
    if (req.method !== "GET") return json(405, { error: "Method unavailable" });
    const file =
      url.pathname === "/faro.js"
        ? resolve(sdkDir, "faro-web-sdk.iife.js")
        : resolve(
            publicDir,
            "." + (url.pathname === "/" ? "/index.html" : url.pathname),
          );
    if (
      file !== resolve(sdkDir, "faro-web-sdk.iife.js") &&
      !file.startsWith(publicDir + sep)
    ) {
      return json(404, { error: "Unknown file" });
    }
    if (!Object.hasOwn(types, extname(file)) || !existsSync(file))
      return json(404, { error: "Unknown file" });
    res.writeHead(200, { "content-type": types[extname(file)] });
    res.end(readFileSync(file));
  } catch (error) {
    console.error(error.message);
    json(500, {
      error: "The duty desk could not complete the request. Try again.",
    });
  }
});
server.listen(8088, "0.0.0.0");
