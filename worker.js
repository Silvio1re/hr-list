/**
 * Cloudflare Worker v2.3 - Geil + Vavoo HLS Proxy
 * Resolve-on-demand + browser-like headers
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

// Browser-like headers used for ALL upstream fetches
const BROWSER_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) Gecko/20100101 Firefox/153.0',
  'Accept': '*/*',
  'Accept-Language': 'en-US,en;q=0.5',
  'Referer': 'https://geil.to/',
  'Origin': 'https://geil.to',
  'Sec-Fetch-Dest': 'empty',
  'Sec-Fetch-Mode': 'cors',
  'Sec-Fetch-Site': 'cross-site',
  'Connection': 'keep-alive',
};

class ExtractorError extends Error {
  constructor(m) { super(m); this.name = 'ExtractorError'; }
}

// --- Geil resolve (on-demand) ---
async function resolveGeilPlayUrl(playUrl) {
  const resolveUrl = `https://geil.to/live/resolve?region=US&language=en&url=${encodeURIComponent(playUrl)}`;
  const resolveHeaders = {
    ...BROWSER_HEADERS,
    'Accept': 'application/json, text/plain, */*',
  };
  try {
    const resp = await fetch(resolveUrl, { headers: resolveHeaders });
    if (!resp.ok) {
      console.warn(`[Geil] Resolve HTTP ${resp.status} for ${playUrl}`);
      return null;
    }
    const data = await resp.json();
    return data.url || (Array.isArray(data) ? data[0]?.url : null);
  } catch (e) {
    console.warn(`[Geil] Resolve exception: ${e.message}`);
    return null;
  }
}

// --- HLS proxy (rewrites segments through worker) ---
async function proxyHLS(streamUrl, request, workerOrigin) {
  const fetchHeaders = { ...BROWSER_HEADERS };
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
    return new Response(`Upstream returned ${response.status}`, {
      status: response.status, headers: { ...CORS_HEADERS, 'Content-Type': 'text/plain' }
    });
  }

  const contentType = (response.headers.get('Content-Type') || '').toLowerCase();
  const cleanUrl = streamUrl.split('?')[0];
  const isPlaylist = contentType.includes('mpegurl')
    || contentType.includes('x-mpegurl')
    || cleanUrl.endsWith('.m3u8');

  // Binary passthrough (segment / key / init)
  if (!isPlaylist) {
    const headers = { ...CORS_HEADERS };
    const passthrough = ['Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges'];
    for (const k of passthrough) {
      const v = response.headers.get(k);
      if (v) headers[k] = v;
    }
    return new Response(response.body, { status: response.status, headers });
  }

  // Rewrite m3u8
  const text = await response.text();
  const baseUrl = new URL(streamUrl);
  const lines = text.split('\n');

  const rewritten = lines.map(line => {
    const trimmed = line.trim();
    if (!trimmed) return line;

    if (trimmed.includes('URI="')) {
      return trimmed.replace(/URI="([^"]*)"/g, (m, uri) => {
        if (!uri) return m;
        const abs = new URL(uri, baseUrl).href;
        return `URI="${workerOrigin}/manifest.m3u8?url=${encodeURIComponent(abs)}"`;
      });
    }

    if (trimmed.startsWith('#')) return line;

    const abs = new URL(trimmed, baseUrl).href;
    return `${workerOrigin}/manifest.m3u8?url=${encodeURIComponent(abs)}`;
  });

  return new Response(rewritten.join('\n'), {
    headers: {
      ...CORS_HEADERS,
      'Content-Type': 'application/vnd.apple.mpegurl; charset=utf-8',
      'Cache-Control': 'no-cache, no-store, must-revalidate',
    },
  });
}

// --- Vavoo (unchanged except uses proxyHLS) ---
const PING_URLS = ["https://www.vavoo.tv/api/app/ping", "https://www.vypn.net/api/app/ping"];
const VYPN_PACKAGE = "net.vypn.app";
const VYPN_VERSION = "1.4.1";
const BASE_SITES = ["https://vavoo.to", "https://kool.to"];
const VAVOO_LANGUAGE = "de";
const VAVOO_REGION = "DE";

function base64UrlDecode(s) { const p = s.length % 4; const t = s + (p ? '='.repeat(4 - p) : ''); const b = atob(t); return decodeURIComponent([...b].map(c => '%' + c.charCodeAt(0).toString(16).padStart(2, '0')).join('')); }
function base64UrlEncode(s) { return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }
function rewriteAddonSigIp(sig, ip) {
  try {
    const obj = JSON.parse(base64UrlDecode(sig));
    if (!obj?.data) return sig;
    const d = JSON.parse(obj.data);
    const cur = Array.isArray(d.ips) ? d.ips : [];
    d.ips = [ip, ...cur.filter(x => x && x !== ip)];
    if (typeof d.ip === 'string') d.ip = ip;
    obj.data = JSON.stringify(d);
    return base64UrlEncode(JSON.stringify(obj));
  } catch { return sig; }
}
function buildPingPayload() {
  const ts = Date.now();
  return JSON.stringify({
    token: "", reason: "app-focus", locale: VAVOO_LANGUAGE, theme: "dark",
    metadata: {
      device: { type: "phone", uniqueId: crypto.randomUUID() },
      os: { name: "android", version: "14", abis: ["arm64-v8a"], host: "android" },
      app: { platform: "android" },
      version: { package: VYPN_PACKAGE, binary: VYPN_VERSION, js: VYPN_VERSION },
    },
    appFocusTime: 0, playerActive: false, playDuration: 0, devMode: false,
    hasAddon: true, castConnected: false, package: VYPN_PACKAGE, version: VYPN_VERSION,
    process: "app", firstAppStart: ts - 86400000, lastAppStart: ts, ipLocation: null,
    adblockEnabled: true, migrationApplied: false, migrationTargetInstalled: false,
    proxy: { supported: ["ss"], engine: "Mu", ssVersion: "2022", enabled: false, autoServer: true, id: "" },
    iap: { supported: false, error: "" },
  });
}
async function fetchAddonSig(clientIp) {
  const h = { "user-agent": "okhttp/4.11.0", "accept": "application/json", "content-type": "application/json; charset=utf-8" };
  for (const u of PING_URLS) {
    try {
      const r = await fetch(u, { method: "POST", headers: h, body: buildPingPayload() });
      if (!r.ok) continue;
      const d = await r.json();
      const sig = d?.addonSig || d?.mhub;
      if (sig) return clientIp ? rewriteAddonSigIp(sig, clientIp) : sig;
    } catch {}
  }
  return null;
}
async function fetchAddonSigWithCache(clientIp) {
  if (!clientIp) return fetchAddonSig(clientIp);
  const key = `https://cache.internal/addonSig_${encodeURIComponent(clientIp)}`;
  const cache = caches.default;
  try { const c = await cache.match(key); if (c) return await c.text(); } catch {}
  const sig = await fetchAddonSig(clientIp);
  if (sig) {
    try { await cache.put(key, new Response(sig, { headers: { 'Cache-Control': `s-maxage=${SIG_TTL}, stale-while-revalidate` } })); } catch {}
  }
  return sig;
}

class VavooExtractor {
  _norm(u) { const m = u.match(/\/play\/([^/?#]+)/); if (m) return `https://vavoo.to/vavoo-iptv/play/${m[1]}`; return u; }
  async resolve(vUrl, ip) {
    const n = this._norm(vUrl);
    let sig = await fetchAddonSigWithCache(ip);
    const body = JSON.stringify({ language: VAVOO_LANGUAGE, region: VAVOO_REGION, url: n, clientVersion: "3.0.2" });
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

// --- Playlist proxy (unchanged) ---
async function handlePlaylistProxy(request) {
  const url = new URL(request.url);
  const p = url.searchParams.get('url');
  if (!p) return new Response('Missing url', { status: 400, headers: CORS_HEADERS });
  const urls = p.split(';').filter(x => x.trim());
  let out = '';
  for (const u of urls) {
    try { const r = await fetch(u, { headers: BROWSER_HEADERS }); if (r.ok) out += await r.text() + '\n'; } catch {}
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
  <h1>Stream Extractor v2.3</h1>
  <p><b>Geil play URL:</b> <code>${o}/manifest.m3u8?url=https://geil.to/live/play/ID</code></p>
  <p><b>Direct stream:</b> <code>${o}/manifest.m3u8?url=http://.../index.m3u8</code></p>
  <p><b>Vavoo page:</b> <code>${o}/manifest.m3u8?url=https://vavoo.to/vavoo-iptv/play/ID</code></p>
  <p><a href="${o}/status" style="color:#3b82f6">Status</a></p></body></html>`,
  { headers: { ...CORS_HEADERS, 'Content-Type': 'text/html; charset=utf-8' } });
}

function handleStatus(request) {
  const ip = getClientIP(request);
  return new Response(JSON.stringify({
    status: "operational", version: "2.3", timestamp: new Date().toISOString(),
    client_info: { ip, country: request.headers.get('CF-IPCountry') || 'unknown' },
    supported_services: {
      vavoo: { mode: "proxy+resolve" },
      geil_play_url: { mode: "resolve+proxy", path: "/manifest.m3u8?url=https://geil.to/live/play/ID" },
      direct_hls: { mode: "proxy", path: "/manifest.m3u8?url=http://.../index.m3u8" },
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

      if (url.pathname === '/manifest.m3u8') {
        const targetUrl = url.searchParams.get('url');
        if (!targetUrl) return new Response(JSON.stringify({ error: 'Missing url param' }), { status: 400, headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' } });

        // 1. Geil play URL → resolve on-demand + proxy
        if (targetUrl.includes('/live/play/')) {
          const streamUrl = await resolveGeilPlayUrl(targetUrl);
          if (!streamUrl) return new Response('Geil resolve failed', { status: 502, headers: CORS_HEADERS });
          return await proxyHLS(streamUrl, request, workerOrigin);
        }

        // 2. Vavoo page → extractor (which now proxies)
        if ((targetUrl.includes('vavoo.to') || targetUrl.includes('kool.to')) && !targetUrl.split('?')[0].endsWith('.m3u8')) {
          const ex = new VavooExtractor();
          return await ex.handle(targetUrl, request, workerOrigin);
        }

        // 3. Direct stream / segment / key → proxy
        return await proxyHLS(targetUrl, request, workerOrigin);
      }

      return new Response(JSON.stringify({ error: '404' }), { status: 404, headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' } });
    } catch (e) {
      console.error(e.stack);
      return new Response(JSON.stringify({ error: e.message, type: e.name }), { status: 500, headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' } });
    }
  },
};
