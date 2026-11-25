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
for (const dir of ["runs", "receipts"])
  mkdirSync(`${data}/${dir}`, { recursive: true });

function save(file, record) {
  // Publish a complete record before the browser or Alloy can observe it.
  writeFileSync(file + ".tmp", JSON.stringify(record) + "\n");
  renameSync(file + ".tmp", file);
}

const modes = { baseline: "1.0", incident: "1.1", rollback: "1.0" };
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
    if (req.method === "POST" && url.pathname === "/api/runs") {
      const mode = url.searchParams.get("mode");
      if (!Object.hasOwn(modes, mode))
        return json(400, { error: "Unknown checkpoint" });
      const run = {
        id: randomUUID(),
        started: Date.now(),
        mode,
        release: modes[mode],
        earned: mode !== "baseline",
      };
      save(`${data}/runs/${run.id}.json`, run);
      return json(201, run);
    }
    const match = /^\/api\/runs\/([a-f0-9-]{36})(?:\/(earn|claim))?$/.exec(
      url.pathname,
    );
    if (match) {
      const [, id, action] = match;
      const file = `${data}/runs/${id}.json`;
      if (!existsSync(file)) return json(404, { error: "Unknown attempt" });
      const run = JSON.parse(readFileSync(file));
      if (req.method === "GET" && !action) return json(200, run);
      if (req.method !== "POST")
        return json(405, { error: "Action requires POST" });
      if (action === "earn") {
        run.earned = true;
        save(file, run);
        return json(200, run);
      }
      if (action === "claim" && run.earned) {
        // The receipt IS the durable grant. Retries return the item recorded on disk.
        const receipt = `${data}/receipts/${id}.jsonl`;
        if (!existsSync(receipt))
          save(receipt, {
            timestamp: new Date().toISOString(),
            event_name: "key_granted",
            run_id: id,
            release: run.release,
            item: { id: "brass-key", name: "Brass key" },
          });
        return json(200, JSON.parse(readFileSync(receipt)).item);
      }
      return json(409, { error: "Earn the crawler box first" });
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
