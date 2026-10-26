# Relay worker

Deploy on Cloudflare Workers (free plan is enough). Either connect this repository under **Workers & Pages → Create → Import a repository** (root directory `worker`, worker name `konta-sou`; every push then redeploys), or by hand:

1. Create a free account at https://dash.cloudflare.com, open **Workers & Pages → Create → Create Worker**, name it `konta-sou`, click Deploy.
2. Click **Edit code**, replace the contents with `worker.js` from this folder, click **Deploy**.
3. Open `https://konta-sou.<your-subdomain>.workers.dev/probe`. If it shows `{"oasa":200,"moh":200}`, the relay works.
4. On the API server set `OASA_API_URL=https://konta-sou.<your-subdomain>.workers.dev/oasa/api/` and `MOH_BASE_URL=https://konta-sou.<your-subdomain>.workers.dev/moh`, then redeploy.

## Ministry copy for callers outside Greece

A Worker runs in the Cloudflare data centre nearest its *caller*. Callers in Greece land in Athens, where
OASA and the ministry answer; callers abroad (the API server, GitHub Actions) do not. So the worker keeps a
copy of the ministry's rota page and documents in Workers KV (binding `CACHE`, namespace `konta-cache`):

- `/warm` fetches the rota page and the documents it links into KV (at most once an hour). The app page
  calls it on every visit, so any visitor in Greece refreshes the copy.
- `/moh/...` tries the ministry first and serves the KV copy when the ministry refuses (`X-Relay-Source: kv`).

Deploy from a machine with the API token (template "Edit Cloudflare Workers"):
`CLOUDFLARE_API_TOKEN=... npx wrangler deploy` from the repository root. The GitHub-connected build does the
same on every push when its queue is healthy.
