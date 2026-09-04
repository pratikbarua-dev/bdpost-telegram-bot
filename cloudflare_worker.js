/**
 * Cloudflare Worker for Proxying, Masking Server IP, and High-Performance Batch Tracking
 * Deploy this on Cloudflare Workers (Free tier: 100,000 requests/day).
 *
 * Capabilities:
 * 1. GET /?url=... -> Direct transparent proxy with Cloudflare Anycast IP masking.
 * 2. POST /v1/batch-track -> Bounded concurrent batch tracking with 7s per-item timeout.
 */

const DEFAULT_USER_AGENT =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36";

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

    // 3. Batch Tracking Route: POST /v1/batch-track
    if (url.pathname === "/v1/batch-track" && request.method === "POST") {
      return handleBatchTracking(request);
    }

    // 4. Single URL Transparent Proxy Route: /?url=...
    const targetUrl = url.searchParams.get("url");
    if (!targetUrl) {
      return new Response(JSON.stringify({ error: "Missing 'url' query parameter" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    try {
      const forwardHeaders = new Headers();
      const forbiddenHeaders = [
        "host",
        "connection",
        "cf-connecting-ip",
        "cf-ray",
        "cf-visitor",
        "x-real-ip",
        "x-proxy-secret",
      ];

      for (const [key, value] of request.headers.entries()) {
        if (!forbiddenHeaders.includes(key.toLowerCase())) {
          forwardHeaders.set(key, value);
        }
      }

      if (!forwardHeaders.has("user-agent")) {
        forwardHeaders.set("user-agent", DEFAULT_USER_AGENT);
      }

      const init = {
        method: request.method,
        headers: forwardHeaders,
      };

      if (request.method !== "GET" && request.method !== "HEAD") {
        init.body = await request.arrayBuffer();
      }

      const response = await fetch(targetUrl, init);

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

/**
 * Executes a batch of tracking checks concurrently with per-item timeout isolation.
 */
async function handleBatchTracking(request) {
  try {
    const payload = await request.json();
    const items = payload.items || [];
    const batchId = payload.batch_id || `batch_${Date.now()}`;

    // Max 25 items per batch to comply with Cloudflare subrequest limits (max 50)
    const limitedItems = items.slice(0, 25);

    const results = await Promise.allSettled(
      limitedItems.map((item) => fetchSingleTracking(item))
    );

    const processedResults = results.map((res, index) => {
      if (res.status === "fulfilled") {
        return res.value;
      } else {
        return {
          tracking_number: limitedItems[index].tracking_number,
          carrier: limitedItems[index].carrier || "cainiao",
          status: "error",
          error: res.reason?.message || "Subrequest failed",
          events: [],
        };
      }
    });

    return new Response(
      JSON.stringify({
        batch_id: batchId,
        processed_at: new Date().toISOString(),
        total_count: limitedItems.length,
        results: processedResults,
      }),
      {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*",
        },
      }
    );
  } catch (err) {
    return new Response(JSON.stringify({ error: "Invalid batch payload: " + err.message }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
}

async function fetchSingleTracking(item) {
  const num = (item.tracking_number || "").trim().toUpperCase();
  const carrier = item.carrier || "cainiao";
  const timeoutMs = item.timeout_ms || 7000;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    let targetUrl = `https://global.cainiao.com/global/detail.json?mailNos=${encodeURIComponent(num)}&lang=en-US`;
    let headers = {
      "User-Agent": DEFAULT_USER_AGENT,
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "en-US,en;q=0.9",
      "Referer": `https://global.cainiao.com/newDetail.htm?mailNoList=${encodeURIComponent(num)}&otherMailNoList=`,
    };

    const res = await fetch(targetUrl, {
      method: "GET",
      headers,
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      return {
        tracking_number: num,
        carrier,
        status: "http_error",
        http_code: res.status,
        raw_data: null,
      };
    }

    const data = await res.json();
    return {
      tracking_number: num,
      carrier,
      status: data?.success ? "success" : "empty",
      http_code: res.status,
      raw_data: data,
    };
  } catch (err) {
    clearTimeout(timeoutId);
    return {
      tracking_number: num,
      carrier,
      status: err.name === "AbortError" ? "timeout" : "error",
      error: err.message,
      raw_data: null,
    };
  }
}
