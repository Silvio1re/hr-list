// main.ts – Deno proxy za Vavoo (s ispravnim routingom)
const VAVOO_UA = "VAVOO/2.6";

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const target = url.searchParams.get("url");
  
  // Ako nema 'url' parametra, vrati upute
  if (!target) {
    return new Response(
      "Vavoo Proxy\n\nKoristi: ?url=https://vavoo.to/vavoo-iptv/play/[ID]",
      { status: 200, headers: { "Content-Type": "text/plain" } }
    );
  }

  try {
    const resp = await fetch(target, {
      headers: {
        "User-Agent": VAVOO_UA,
        "Referer": "https://vavoo.to/",
        "Origin": "https://vavoo.to",
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
