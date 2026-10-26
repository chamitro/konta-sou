# Relay worker

Deploy on Cloudflare Workers (free plan is enough):

1. Create a free account at https://dash.cloudflare.com, open **Workers & Pages → Create → Create Worker**, name it `konta-sou-relay`, click Deploy.
2. Click **Edit code**, replace the contents with `worker.js` from this folder, click **Deploy**.
3. Open `https://konta-sou-relay.<your-subdomain>.workers.dev/probe`. If it shows `{"oasa":200,"moh":200}`, the relay works.
4. On the API server set `OASA_API_URL=https://konta-sou-relay.<your-subdomain>.workers.dev/oasa/api/` and `MOH_BASE_URL=https://konta-sou-relay.<your-subdomain>.workers.dev/moh`, then redeploy.
