/**
 * Κοντά σου relay — a tiny Cloudflare Worker.
 *
 * Forwards two read-only sources that only answer from some networks, adding CORS so the
 * page can call them too. Nothing is rewritten or disguised: the upstream sees a normal
 * request from Cloudflare's network with this worker's own User-Agent.
 *
 *   /oasa/api/?act=getStopArrivals&p1=60134   ->  https://telematics.oasa.gr/api/?act=...
 *   /moh/articles/citizen/...                 ->  https://www.moh.gov.gr/articles/citizen/...
 *   /probe                                    ->  reports whether both upstreams answer from here
 */
const UPSTREAMS = { oasa: "https://telematics.oasa.gr", moh: "https://www.moh.gov.gr" };
const UA = "konta-sou-relay/0.1 (+https://github.com/chamitro/konta-sou)";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS" };

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    if (url.pathname === "/probe") {
      const out = { colo: request.cf && request.cf.colo };  // which Cloudflare data centre ran this request
      for (const [k, base] of Object.entries(UPSTREAMS)) {
        const target = k === "oasa" ? base + "/api/?act=webGetLines" : base + "/articles/citizen/efhmeries-nosokomeiwn/68-efhmeries-nosokomeiwn-attikhs";
        try { const r = await fetch(target, { headers: { "User-Agent": UA }, signal: AbortSignal.timeout(15000) }); out[k] = r.status; }
        catch (e) { out[k] = String(e); }
      }
      return Response.json(out, { headers: CORS });
    }
    const [, key, ...rest] = url.pathname.split("/");
    const base = UPSTREAMS[key];
    if (!base) return new Response("not found", { status: 404, headers: CORS });
    const target = base + "/" + rest.join("/") + url.search;
    const cacheTtl = key === "oasa" ? 15 : 600; // live arrivals: 15 s; ministry pages/documents: 10 min
    const upstream = await fetch(target, { headers: { "User-Agent": UA, "Accept-Language": "el" }, cf: { cacheTtl, cacheEverything: true } });
    const headers = new Headers(CORS);
    headers.set("Content-Type", upstream.headers.get("Content-Type") || "application/octet-stream");
    headers.set("Cache-Control", `public, max-age=${cacheTtl}`);
    return new Response(upstream.body, { status: upstream.status, headers });
  },
};
