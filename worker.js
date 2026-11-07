/**
 * Cloudflare Worker v2.7 - Geil + Vavoo (s addonSig tokenom)
 */

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS, HEAD',
  'Access-Control-Allow-Headers': 'Content-Type, Range, User-Agent, Accept, Authorization, X-Requested-With',
  'Access-Control-Max-Age': '86400',
  'Access-Control-Expose-Headers': 'Content-Length, Content-Range, Accept-Ranges, Location',
};

const SIG_TTL = 300;

function getClientIP(request) {
  try { const v = new URL(request.url).searchParams.get('ip'); if (v && v.trim()) return v.trim(); } catch {}
  const h = request.headers.get('CF-Connecting-IP');
  return h || null;
}

// Headeri za geil resolve — oponašaju pravi browser XHR (BEZ Origin!)
const GEIL_RESOLVE_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) Gecko/20100101 Firefox/153.0',
  'Accept': '*/*',
  'Accept-Language': 'en-US,en;q=0.5',
  'Referer': 'https://geil.to/',
  'Sec-Fetch-Dest': 'empty',
  'Sec-Fetch-Mode': 'cors',
  'Sec-Fetch-Site': 'same-origin',
};

class ExtractorError extends Error {
  constructor(m) { super(m); this.name = 'ExtractorError'; }
}

// --- Geil resolve (s addonSig tokenom) ---
async function resolveGeilPlayUrl(playUrl) {
  // Dohvati addonSig token (isto kao Enigma2 skripta)
  let sig = await fetchAddonSigWithCache(null);
  if (sig) {
    console.log(`[Geil] Using addonSig token (${sig.substring(0, 30)}...)`);
  } else {
    console.warn(`[Geil] No addonSig available, trying without signature`);
  }

  const regions = ['US', 'HR', 'DE', 'GB'];
  for (const region of regions) {
    const resolveUrl = `https://geil.to/live/resolve?region=${region}&language=en&url=${encodeURIComponent(playUrl)}`;
    const headers = { ...GEIL_RESOLVE_HEADERS };
    if (sig) headers['mediahubmx-signature'] = sig;

    try {
      const resp = await fetch(resolveUrl, { headers });
      if (!resp.ok) {
        console.warn(`[Geil] Resolve ${region} → ${resp.status}`);
        continue;
      }
      const data = await resp.json();
      const streamUrl = data.url || (Array.isArray(data) ? data[0]?.url : null);
      if (streamUrl) {
        console.log(`[Geil] Resolved (${region}): ${streamUrl.substring(0, 80)}`);
        return streamUrl;
      }
    } catch (e) {
      console.warn(`[Geil] Resolve ${region} exception: ${e.message}`);
    }
  }
  return null;
}

// --- Debug ---
async function debugFetch(urlParam) {
  const url = decodeURIComponent(urlParam);
  const results = { target_url: url, steps: [] };
  let streamUrl = null;

  if (url.includes('/live/play/')) {
    // Prvo dohvati token
    const sig = await fetchAddonSigWithCache(null);
    results.addon_sig_available = !!sig;
    if (sig) results.addon_sig_preview = sig.substring(0, 50) + '...';

    for (const region of ['US', 'HR', 'DE', 'GB']) {
      const resolveUrl = `https://geil.to/live/resolve?region=${region}&language=en&url=${encodeURIComponent(url)}`;
      const headers = { ...GEIL_RESOLVE_HEADERS };
      if (sig) headers['mediahubmx-signature'] = sig;

      try {
        const r = await fetch(resolveUrl, { headers });
        const body = await r.text();
        results.steps.push({
          step: `resolve_${region}`,
          status: r.status,
          body_preview: body.substring(0, 400),
          sent_signature: !!sig
        });
        if (r.ok) {
          try {
            const data = JSON.parse(body);
            const su = data.url || (Array.isArray(data) ? data[0]?.url : null);
            if (su) { streamUrl = su; results.resolved_stream_url = su; results.working_region = region; break; }
          } catch {}
        }
      } catch (e) {
        results.steps.push({ step: `resolve_${region}`, error: e.message });
      }
    }
  } else {
    streamUrl = url;
  }

  if (streamUrl) {
    results.summary = `✅ Resolve uspio. Worker će vratiti 302 redirect.`;
    results.location = streamUrl;
  } else {
    results.summary = "❌ Resolve nije uspio ni s jednom regijom (čak i s tokenom).";
  }
  return results;
}

// --- HLS proxy (za Vavoo) ---
async function proxyHLS(streamUrl, request, workerOrigin) {
  const fetchHeaders = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) Gecko/20100101 Firefox/153.0',
    'Accept': '*/*',
    'Referer': 'https://vavoo.to/',
  };
  const range = request.headers.get('Range');
  if (range) fetchHeaders['Range'] = range;

  let response;
  try {
    response = await fetch(streamUrl, { headers: fetchHeaders });
  } catch (e) {
    return new Response(`Upstream fetch error: ${e.message}`, {
      status: 502, headers: { ...CORS_HEADERS, 'Content-Type': 'text/plain' }
    });
  }

  if (!response.ok) {
    const errText = await response.text().catch(() => '');
    return new Response(`Upstream returned ${response.status}\nURL: ${streamUrl}\nBody: ${errText.substring(0, 300)}`, {
      status: response.status, headers: { ...CORS_HEADERS, 'Content-Type': 'text/plain' }
    });
  }

  const contentType = (response.headers.get('Content-Type') || '').toLowerCase();
  const cleanUrl = streamUrl.split('?')[0];
  const isPlaylist = contentType.includes('mpegurl') || cleanUrl.endsWith('.m3u8');

  if (!isPlaylist) {
    const headers = { ...CORS_HEADERS };
    for (const k of ['Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges']) {
      const v = response.headers.get(k);
      if (v) headers[k] = v;
    }
    return new Response(response.body, { status: response.status, headers });
  }

  const text = await response.text();
  const baseUrl = new URL(streamUrl);
  const rewritten = text.split('\n').map(line => {
    const trimmed = line.trim();
    if (!trimmed) return line;
    if (trimmed.includes('URI="')) {
      return trimmed.replace(/URI="([^"]*)"/g, (m, uri) => {
        if (!uri) return m;
        return `URI="${workerOrigin}/manifest.m3u8?url=${encodeURIComponent(new URL(uri, baseUrl).href)}"`;
      });
    }
    if (trimmed.startsWith('#')) return line;
    return `${workerOrigin}/manifest.m3u8?url=${encodeURIComponent(new URL(trimmed, baseUrl).href)}`;
  });

  return new Response(rewritten.join('\n'), {
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/vnd.apple.mpegurl; charset=utf-8' },
  });
}

// --- Vavoo token (isto kao Enigma2 skripta) ---
const PING_URLS = ["https://www.vavoo.tv/api/app/ping", "https://www.vypn.net/api/app/ping"];
const BASE_SITES = ["https://vavoo.to", "https://kool.to"];

function base64UrlDecode(s) { const p = s.length % 4; const t = s + (p ? '='.repeat(4 - p) : ''); const b = atob(t); return decodeURIComponent([...b].map(c => '%' + c.charCodeAt(0).toString(16).padStart(2, '0')).join('')); }
function base64UrlEncode(s) { return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }
function rewriteAddonSigIp(sig, ip) { try { const o = JSON.parse(base64UrlDecode(sig)); if (!o?.data) return sig; const d = JSON.parse(o.data); const c = Array.isArray(d.ips) ? d.ips : []; d.ips = [ip, ...c.filter(x => x && x !== ip)]; if (typeof d.ip === 'string') d.ip = ip; o.data = JSON.stringify(d); return base64UrlEncode(JSON.stringify(o)); } catch { return sig; } }

function buildPingPayload() {
  const ts = Date.now();
  return JSON.stringify({
    token: "", reason: "app-focus", locale: "de", theme: "dark",
    metadata: {
      device: { type: "phone", uniqueId: crypto.randomUUID() },
      os: { name: "android", version: "14", abis: ["arm64-v8a"], host: "android" },
      app: { platform: "android" },
      version: { package: "net.vypn.app", binary: "1.4.1", js: "1.4.1" },
    },
    appFocusTime: 0, playerActive: false, playDuration: 0, devMode: false,
    hasAddon: true, castConnected: false, package: "net.vypn.app", version: "1.4.1",
    process: "app", firstAppStart: ts - 86400000, lastAppStart: ts, ipLocation: null,
    adblockEnabled: true, migrationApplied: false, migrationTargetInstalled: false,
    proxy: { supported: ["ss"], engine: "Mu", ssVersion: "2022", enabled: false, autoServer: true, id: "" },
    iap: { supported: false, error: "" },
  });
}

async function fetchAddonSig(ip) {
  const h = { "user-agent": "okhttp/4.11.0", "accept": "application/json", "content-type": "application/json; charset=utf-8" };
  for (const u of PING_URLS) {
    try {
      const r = await fetch(u, { method: "POST", headers: h, body: buildPingPayload() });
      if (!r.ok) continue;
      const d = await r.json();
      const sig = d?.addonSig || d?.mhub;
      if (sig) {
        console.log(`[AddonSig] Token obtained from ${u}`);
        return ip ? rewriteAddonSigIp(sig, ip) : sig;
      }
    } catch (e) {
      console.warn(`[AddonSig] Ping ${u} failed: ${e.message}`);
    }
  }
  return null;
}

async function fetchAddonSigWithCache(ip) {
  const cacheKey = `https://cache.internal/addonSig_${ip || 'global'}`;
  const cache = caches.default;
  try {
    const c = await cache.match(cacheKey);
    if (c) return await c.text();
  } catch {}
  const sig = await fetchAddonSig(ip);
  if (sig) {
    try {
      await cache.put(cacheKey, new Response(sig, {
        headers: { 'Cache-Control': `s-maxage=${SIG_TTL}` }
      }));
    } catch {}
  }
  return sig;
}

class VavooExtractor {
  async resolve(vUrl, ip) {
    const m = vUrl.match(/\/play\/([^/?#]+)/);
    const n = m ? `https://vavoo.to/vavoo-iptv/play/${m[1]}` : vUrl;
    let sig = await fetchAddonSigWithCache(ip);
    const body = JSON.stringify({ language: "de", region: "DE", url: n, clientVersion: "3.0.2" });
    for (let i = 0; i < 2; i++) {
      const h = { "Origin": "https://vavoo.to", "Referer": "https://vavoo.to/", "User-Agent": "MediaHubMX/2", "Accept": "*/*", "Content-Type": "application/json; charset=utf-8" };
      if (sig) h["mediahubmx-signature"] = sig;
      const r = await fetch(`${BASE_SITES[i]}/mediahubmx-resolve.json`, { method: "POST", headers: h, body });
      if ((r.status === 451 || r.status === 502) && i === 0) { sig = (await fetchAddonSigWithCache(ip)) || sig; continue; }
      if (!r.ok) throw new ExtractorError(`Vavoo resolve ${r.status}`);
      const d = await r.json();
      const url = Array.isArray(d) ? (d.find(x => x.url?.startsWith('https://'))?.url || d[0]?.url) : d?.url;
      if (!url) throw new ExtractorError('No stream URL');
      return url;
    }
    throw new ExtractorError('Vavoo resolve failed');
  }
  async handle(vUrl, request, workerOrigin) {
    const ip = getClientIP(request);
    const streamUrl = await this.resolve(vUrl, ip);
    return await proxyHLS(streamUrl, request, workerOrigin);
  }
}

// --- Playlist proxy ---
async function handlePlaylistProxy(request) {
  const url = new URL(request.url);
  const p = url.searchParams.get('url');
  if (!p) return new Response('Missing url', { status: 400, headers: CORS_HEADERS });
  const urls = p.split(';').filter(x => x.trim());
  let out = '';
  for (const u of urls) {
    try {
      const r = await fetch(u, { headers: { 'User-Agent': 'Mozilla/5.0' } });
      if (r.ok) out += await r.text() + '\n';
    } catch {}
  }
  const re = out.split('\n').map(line => {
    const t = line.trim();
    if (!t || t.startsWith('#')) return line;
    return `${url.origin}/manifest.m3u8?url=${encodeURIComponent(t)}`;
  }).join('\n');
  return new Response(re.startsWith('#EXTM3U') ? re : '#EXTM3U\n' + re, {
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/vnd.apple.mpegurl; charset=utf-8' }
  });
}

// --- Info & Status ---
function handleInfoPage(request) {
  const o = new URL(request.url).origin;
  return new Response(`<!DOCTYPE html><html><body style="font-family:sans-serif;background:#0a0a0b;color:#fff;padding:2rem;max-width:900px;margin:auto">
  <h1>Stream Extractor v2.7</h1>
  <p><b>Geil play URL (302 redirect):</b> <code>${o}/manifest.m3u8?url=https://geil.to/live/play/ID</code></p>
  <p><b>Vavoo (proxy):</b> <code>${o}/manifest.m3u8?url=https://vavoo.to/vavoo-iptv/play/ID</code></p>
  <p><b>Debug:</b> <code>${o}/debug?url=&lt;URL&gt;</code></p>
  <p><a href="${o}/status" style="color:#3b82f6">Status</a></p></body></html>`,
  { headers: { ...CORS_HEADERS, 'Content-Type': 'text/html; charset=utf-8' } });
}

function handleStatus(request) {
  return new Response(JSON.stringify({
    status: "operational", version: "2.7", timestamp: new Date().toISOString(),
    supported_services: {
      geil_play_url: { mode: "resolve (s addonSig tokenom) + 302 redirect" },
      vavoo: { mode: "proxy" },
      debug: { path: "/debug?url=<URL>" },
    },
  }, null, 2), { headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' } });
}

// --- Router ---
export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS_HEADERS });
    const url = new URL(request.url);
    const workerOrigin = url.origin;

    try {
      if (url.pathname === '/' || url.pathname === '') return handleInfoPage(request);
      if (url.pathname === '/status') return handleStatus(request);
      if (url.pathname === '/playlist') return await handlePlaylistProxy(request);

      if (url.pathname === '/debug') {
        const u = url.searchParams.get('url');
        if (!u) return new Response('Missing url', { status: 400, headers: CORS_HEADERS });
        const r = await debugFetch(u);
        return new Response(JSON.stringify(r, null, 2), {
          headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' }
        });
      }

      if (url.pathname === '/manifest.m3u8') {
        const targetUrl = url.searchParams.get('url');
        if (!targetUrl) return new Response(JSON.stringify({ error: 'Missing url' }), { status: 400, headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' } });

        if (targetUrl.includes('/live/play/')) {
          const streamUrl = await resolveGeilPlayUrl(targetUrl);
          if (!streamUrl) return new Response(`Geil resolve failed for: ${targetUrl}`, { status: 502, headers: CORS_HEADERS });
          console.log(`[Geil] 302 → ${streamUrl.substring(0, 80)}`);
          return new Response(null, {
            status: 302,
            headers: { ...CORS_HEADERS, 'Location': streamUrl }
          });
        }

        if ((targetUrl.includes('vavoo.to') || targetUrl.includes('kool.to')) && !targetUrl.split('?')[0].endsWith('.m3u8')) {
          const ex = new VavooExtractor();
          return await ex.handle(targetUrl, request, workerOrigin);
        }

        return await proxyHLS(targetUrl, request, workerOrigin);
      }

      return new Response(JSON.stringify({ error: '404' }), { status: 404, headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' } });
    } catch (e) {
      console.error(e.stack);
      return new Response(JSON.stringify({ error: e.message, type: e.name }), { status: 500, headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' } });
    }
  },
};
