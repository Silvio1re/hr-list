// main.ts
const VAVOO_UA = "VAVOO/2.6";

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const target = url.searchParams.get("url");
  if (!target) {
    return new Response("Missing 'url' parameter", { status: 400 });
  }

  try {
    const resp = await fetch(target, {
      headers: {
        "User-Agent": VAVOO_UA,
        "Referer": "https://vavoo.to/",
      },
    });
    return new Response(resp.body, {
      status: resp.status,
      headers: {
        "Content-Type": resp.headers.get("Content-Type") || "application/vnd.apple.mpegurl",
      },
    });
  } catch (e) {
    return new Response(`Proxy error: ${e.message}`, { status: 500 });
  }
});
