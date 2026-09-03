/**
 * Cloudflare Worker for Proxying & Masking Server IP
 * Deploy this on Cloudflare Workers (Free tier: 100,000 requests/day).
 *
 * How to deploy:
 * 1. Log in to Cloudflare Dashboard -> Workers & Pages -> Create Application -> Worker.
 * 2. Paste this code into the editor.
 * 3. (Optional) Set an environment variable or Secret: PROXY_SECRET = "your-custom-secret"
 * 4. Click Deploy.
 * 5. Add CF_PROXY_URL=https://your-worker-name.your-subdomain.workers.dev in your bot's .env.
 */

export default {
  async fetch(request, env) {
    // 1. Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "*",
        },
      });
    }

    // 2. Validate optional secret if configured
    if (env.PROXY_SECRET) {
      const secret = request.headers.get("x-proxy-secret");
      if (secret !== env.PROXY_SECRET) {
        return new Response(JSON.stringify({ error: "Unauthorized" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }
    }

    const url = new URL(request.url);
    const targetUrl = url.searchParams.get("url");

    if (!targetUrl) {
      return new Response(JSON.stringify({ error: "Missing 'url' query parameter" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    try {
      // Forward the request to target destination
      const forwardHeaders = new Headers();
      const forbiddenHeaders = ["host", "connection", "cf-connecting-ip", "cf-ray", "cf-visitor", "x-real-ip", "x-proxy-secret"];

      for (const [key, value] of request.headers.entries()) {
        if (!forbiddenHeaders.includes(key.toLowerCase())) {
          forwardHeaders.set(key, value);
        }
      }

      const init = {
        method: request.method,
        headers: forwardHeaders,
      };

      if (request.method !== "GET" && request.method !== "HEAD") {
        init.body = await request.arrayBuffer();
      }

      const response = await fetch(targetUrl, init);

      // Return response back to bot
      const responseHeaders = new Headers(response.headers);
      responseHeaders.set("Access-Control-Allow-Origin", "*");

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }
  },
};
