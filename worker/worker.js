/**
 * Κοντά σου relay — a tiny Cloudflare Worker.
 *
 * Forwards two read-only sources that only answer from Greek networks, adding CORS so the page can
 * call them too. Nothing is rewritten or disguised: the upstream sees a normal request from
 * Cloudflare's network with this worker's own User-Agent.
 *
 * A Worker runs in the data centre nearest its caller, so only callers in Greece reach the
 * upstreams (Athens). To serve the API server abroad as well, every successful ministry fetch is
 * kept in KV (binding CACHE); when the upstream refuses, the stored copy is served instead.
 * Greek visitors' browsers call /warm, which fetches the rota page and its documents into KV.
 *
 *   /oasa/api/?act=getStopArrivals&p1=60134   ->  https://telematics.oasa.gr/api/?act=...
 *   /moh/articles/citizen/...                 ->  https://www.moh.gov.gr/articles/citizen/...
 *   /warm                                     ->  refresh the ministry copy (at most hourly)
 *   /probe                                    ->  reports whether both upstreams answer from here
 */
const UPSTREAMS = { oasa: "https://telematics.oasa.gr", moh: "https://www.moh.gov.gr" };
const ROTA_PATH = "/articles/citizen/efhmeries-nosokomeiwn/68-efhmeries-nosokomeiwn-attikhs";
const UA = "konta-sou-relay/0.2 (+https://github.com/chamitro/konta-sou)";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS" };
const KV_TTL = 14 * 86400;        // keep ministry copies two weeks
const STORE_EVERY = 30 * 60e3;    // re-store a path at most every 30 min (free KV: 1000 writes/day)
const WARM_EVERY = 60 * 60e3;

const json = (o, status = 200) => Response.json(o, { status, headers: CORS });

async function upstream(target) {
  return fetch(target, { headers: { "User-Agent": UA, "Accept-Language": "el" }, signal: AbortSignal.timeout(15000) });
}

/** Fetch a ministry path; on success store it in KV, on refusal serve the stored copy. */
async function moh(env, pathAndQuery, ctx) {
  const key = "moh:" + pathAndQuery;
  let r = null;
  try { r = await upstream(UPSTREAMS.moh + pathAndQuery); } catch (e) { r = null; }
  if (r && r.ok) {
    const body = await r.arrayBuffer();
    const ct = r.headers.get("Content-Type") || "application/octet-stream";
    if (env.CACHE) {
      const meta = await env.CACHE.getWithMetadata(key, { type: "stream" }).then(x => x.metadata).catch(() => null);
      if (!meta || Date.now() - meta.ts > STORE_EVERY) ctx.waitUntil(env.CACHE.put(key, body, { metadata: { ct, ts: Date.now() }, expirationTtl: KV_TTL }));
    }
    return new Response(body, { status: 200, headers: { ...CORS, "Content-Type": ct, "Cache-Control": "public, max-age=600", "X-Relay-Source": "upstream" } });
  }
  if (env.CACHE) {
    const hit = await env.CACHE.getWithMetadata(key, { type: "arrayBuffer" }).catch(() => null);
    if (hit && hit.value) return new Response(hit.value, { status: 200, headers: { ...CORS, "Content-Type": (hit.metadata && hit.metadata.ct) || "application/octet-stream", "Cache-Control": "public, max-age=600", "X-Relay-Source": "kv", "X-Relay-Stored": String((hit.metadata && hit.metadata.ts) || "") } });
  }
  return new Response(r ? await r.text() : "upstream unreachable", { status: r ? r.status : 502, headers: CORS });
}

const API_ORIGIN = "https://konta-sou.onrender.com";

export default {
  /** Cron trigger (see wrangler.toml): keeps the free API instance awake and warm. */
  async scheduled(event, env, ctx) {
    for (const p of ["/healthz", "/api/fuel/latest"]) {
      try { await fetch(API_ORIGIN + p, { headers: { "User-Agent": UA }, signal: AbortSignal.timeout(60000) }); } catch (e) { /* the next tick retries */ }
    }
  },

  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const colo = (request.cf && request.cf.colo) || null;
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });

    if (url.pathname === "/probe") {
      const out = { colo, kv: !!env.CACHE };
      for (const [k, base] of Object.entries(UPSTREAMS)) {
        const target = k === "oasa" ? base + "/api/?act=webGetLines" : base + ROTA_PATH;
        try { const r = await upstream(target); out[k] = r.status; } catch (e) { out[k] = String(e); }
      }
      return json(out);
    }

    if (url.pathname === "/warm") {
      if (!env.CACHE) return json({ error: "no KV binding" }, 500);
      const last = await env.CACHE.get("warm:ts").catch(() => null);
      if (last && Date.now() - Number(last) < WARM_EVERY && !url.searchParams.has("force")) return json({ skipped: true, colo, last: Number(last) });
      let page;
      try { page = await upstream(UPSTREAMS.moh + ROTA_PATH); } catch (e) { return json({ ok: false, colo, error: String(e) }); }
      if (!page.ok) return json({ ok: false, colo, status: page.status });   // not in Greece: nothing to do
      const html = await page.text();
      ctx.waitUntil(env.CACHE.put("moh:" + ROTA_PATH, html, { metadata: { ct: page.headers.get("Content-Type") || "text/html", ts: Date.now() }, expirationTtl: KV_TTL }));
      const ids = [...new Set([...html.matchAll(/fdl=(\d+)/g)].map(m => m[1]))].slice(0, 10);
      let stored = 0;
      for (const id of ids) {
        const key = "moh:" + ROTA_PATH + "?fdl=" + id;
        if (await env.CACHE.get(key, { type: "stream" }).catch(() => null)) continue;   // documents never change once posted
        try {
          const d = await upstream(UPSTREAMS.moh + ROTA_PATH + "?fdl=" + id);
          if (d.ok) { await env.CACHE.put(key, await d.arrayBuffer(), { metadata: { ct: d.headers.get("Content-Type") || "application/octet-stream", ts: Date.now() }, expirationTtl: KV_TTL }); stored++; }
        } catch (e) { /* skip this document */ }
      }
      await env.CACHE.put("warm:ts", String(Date.now()));
      return json({ ok: true, colo, documents: ids.length, stored });
    }

    const [, key, ...rest] = url.pathname.split("/");
    const base = UPSTREAMS[key];
    if (!base) return new Response("not found", { status: 404, headers: CORS });
    const pathAndQuery = "/" + rest.join("/") + url.search;
    if (key === "moh") return moh(env, pathAndQuery, ctx);

    // OASA: live data, pass straight through with a short edge cache
    const r = await fetch(base + pathAndQuery, { headers: { "User-Agent": UA }, cf: { cacheTtl: 15, cacheEverything: true } });
    const headers = new Headers(CORS);
    headers.set("Content-Type", r.headers.get("Content-Type") || "application/octet-stream");
    headers.set("Cache-Control", "public, max-age=15");
    return new Response(r.body, { status: r.status, headers });
  },
};
