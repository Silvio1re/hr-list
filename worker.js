/**
 * Cloudflare Worker for Vavoo + Geil Stream Proxy
 * Version: 2.2
 */

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS, HEAD',
  'Access-Control-Allow-Headers': 'Content-Type, Range, User-Agent, Accept, Authorization, X-Requested-With',
  'Access-Control-Max-Age': '86400',
  'Access-Control-Expose-Headers': 'Content-Length, Content-Range, Accept-Ranges, Location',
};

const CACHE_NAME = 'vavoo_cache';
const SIG_TTL = 300;

function getClientIP(request) {
  try {
      const url = new URL(request.url);
      const explicitIp = url.searchParams.get('ip');
      if (explicitIp && explicitIp.trim()) return explicitIp.trim();
  } catch {}

  const isPrivate = (ip) => {
      if (!ip) return true;
      const m = ip.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
      if (m) {
          const a = parseInt(m[1], 10);
          if (a === 10 || a === 127) return true;
          if (a === 172 && parseInt(m[2], 10) >= 16 && parseInt(m[2], 10) <= 31) return true;
          if (a === 192 && parseInt(m[2], 10) === 168) return true;
          if (a === 169 && parseInt(m[2], 10) === 254) return true;
          return false;
      }
      const low = ip.toLowerCase();
      if (low === '::1' || low.startsWith('fc') || low.startsWith('fd') || low.startsWith('fe80:')) return true;
      return false;
  };
  const normalize = (raw) => {
      if (!raw) return '';
      let ip = raw.trim();
      if (ip.startsWith('[') && ip.endsWith(']')) ip = ip.slice(1, -1);
      const mapped = ip.match(/::ffff:(\d+\.\d+\.\d+\.\d+)/i);
      if (mapped) ip = mapped[1];
      return ip;
  };
  const pickFirstPublic = (candidates) => {
      for (const raw of candidates) {
          const ip = normalize(raw);
          if (ip && !isPrivate(ip)) return ip;
      }
      for (const raw of candidates) {
          const ip = normalize(raw);
          if (ip) return ip;
      }
      return null;
  };

  const xff = request.headers.get('X-Forwarded-For');
  if (xff) {
      const list = xff.split(',').map(s => s.trim()).filter(Boolean);
      const got = pickFirstPublic(list);
      if (got) return got;
  }
  const directHeaders = ['CF-Connecting-IP', 'True-Client-IP', 'X-Real-IP', 'X-Client-IP', 'Fly-Client-IP', 'Fastly-Client-IP'];
  for (const h of directHeaders) {
      const val = request.headers.get(h);
      if (val) {
          const ip = normalize(val);
          if (ip) return ip;
      }
  }
  return null;
}

class ExtractorError extends Error {
  constructor(message) {
      super(message);
      this.name = 'ExtractorError';
  }
}

// --- HLS Proxy (NOVO) ---

async function proxyHLS(streamUrl, request, workerOrigin) {
    const fetchHeaders = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://geil.to/',
        'Origin': 'https://geil.to',
    };

    // Forward Range header for seeking
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

    // Binary segment / key / init segment → passthrough
    if (!isPlaylist) {
        const headers = { ...CORS_HEADERS };
        const ct = response.headers.get('Content-Type');
        if (ct) headers['Content-Type'] = ct;
        const cr = response.headers.get('Content-Range');
        if (cr) headers['Content-Range'] = cr;
        const cl = response.headers.get('Content-Length');
        if (cl) headers['Content-Length'] = cl;
        const ar = response.headers.get('Accept-Ranges');
        if (ar) headers['Accept-Ranges'] = ar;

        return new Response(response.body, { status: response.status, headers });
    }

    // Parse m3u8 and rewrite all segment URLs through the worker
    const text = await response.text();
    const baseUrl = new URL(streamUrl);
    const lines = text.split('\n');

    const rewritten = lines.map(line => {
        const trimmed = line.trim();
        if (!trimmed) return line;

        // Handle URI="..." attributes (encryption keys, init segments)
        if (trimmed.includes('URI="')) {
            return trimmed.replace(/URI="([^"]*)"/g, (match, uri) => {
                if (!uri) return match;
                const absolute = new URL(uri, baseUrl).href;
                return `URI="${workerOrigin}/manifest.m3u8?url=${encodeURIComponent(absolute)}"`;
            });
        }

        // Keep all other comments and tags as-is
        if (trimmed.startsWith('#')) return line;

        // It's a segment or sub-playlist URL → rewrite
        const absolute = new URL(trimmed, baseUrl).href;
        return `${workerOrigin}/manifest.m3u8?url=${encodeURIComponent(absolute)}`;
    });

    return new Response(rewritten.join('\n'), {
        headers: {
            ...CORS_HEADERS,
            'Content-Type': 'application/vnd.apple.mpegurl; charset=utf-8',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
        },
    });
}

// --- Vavoo Extractor (sada proxyja, ne redirecta) ---

const PING_URLS = [
  "https://www.vavoo.tv/api/app/ping",
  "https://www.vypn.net/api/app/ping",
];
const VYPN_PACKAGE = "net.vypn.app";
const VYPN_VERSION = "1.4.1";
const BASE_SITES = ["https://vavoo.to", "https://kool.to"];
const VAVOO_LANGUAGE = "de";
const VAVOO_REGION = "DE";

function base64UrlDecode(str) {
  const pad = str.length % 4;
  const padded = str + (pad ? '='.repeat(4 - pad) : '');
  const bin = atob(padded);
  return decodeURIComponent([...bin].map(c => '%' + c.charCodeAt(0).toString(16).padStart(2, '0')).join(''));
}

function base64UrlEncode(str) {
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function rewriteAddonSigIp(sig, clientIp) {
  try {
      const decoded = base64UrlDecode(sig);
      const sigObj = JSON.parse(decoded);
      if (!sigObj || typeof sigObj !== 'object' || !sigObj.data) return sig;
      const dataObj = JSON.parse(sigObj.data);
      const currentIps = Array.isArray(dataObj.ips) ? dataObj.ips : [];
      dataObj.ips = [clientIp, ...currentIps.filter(ip => ip && ip !== clientIp)];
      if (typeof dataObj.ip === 'string') dataObj.ip = clientIp;
      sigObj.data = JSON.stringify(dataObj);
      return base64UrlEncode(JSON.stringify(sigObj));
  } catch (e) {
      console.warn(`[Vavoo] addonSig IP rewrite failed, keeping original sig: ${e.message}`);
      return sig;
  }
}

function buildPingPayload() {
  const ts = Date.now();
  return JSON.stringify({
      token: "",
      reason: "app-focus",
      locale: VAVOO_LANGUAGE,
      theme: "dark",
      metadata: {
          device: { type: "phone", uniqueId: crypto.randomUUID() },
          os: { name: "android", version: "14", abis: ["arm64-v8a"], host: "android" },
          app: { platform: "android" },
          version: { package: VYPN_PACKAGE, binary: VYPN_VERSION, js: VYPN_VERSION },
      },
      appFocusTime: 0, playerActive: false, playDuration: 0, devMode: false,
      hasAddon: true, castConnected: false,
      package: VYPN_PACKAGE, version: VYPN_VERSION, process: "app",
      firstAppStart: ts - 86400000, lastAppStart: ts, ipLocation: null,
      adblockEnabled: true, migrationApplied: false, migrationTargetInstalled: false,
      proxy: { supported: ["ss"], engine: "Mu", ssVersion: "2022", enabled: false, autoServer: true, id: "" },
      iap: { supported: false, error: "" },
  });
}

async function fetchAddonSigWithCache(clientIp) {
    if (!clientIp) return fetchAddonSig(clientIp);

    const cacheKey = `https://cache.internal/addonSig_${encodeURIComponent(clientIp)}`;
    const cache = caches.default;

    try {
        const cachedResponse = await cache.match(cacheKey);
        if (cachedResponse) {
            return await cachedResponse.text();
        }
    } catch (e) {
        console.warn('[Vavoo] Cache read error:', e.message);
    }

    const sig = await fetchAddonSig(clientIp);
    if (sig) {
        try {
            await cache.put(cacheKey, new Response(sig, {
                headers: { 'Cache-Control': `s-maxage=${SIG_TTL}, stale-while-revalidate` }
            }));
        } catch (e) {
            console.warn('[Vavoo] Failed to cache addonSig:', e.message);
        }
    }
    return sig;
}

async function fetchAddonSig(clientIp) {
  const pingHeaders = {
      "user-agent": "okhttp/4.11.0",
      "accept": "application/json",
      "content-type": "application/json; charset=utf-8",
  };
  for (const url of PING_URLS) {
      try {
          const resp = await fetch(url, {
              method: "POST", headers: pingHeaders, body: buildPingPayload(),
          });
          if (!resp.ok) continue;
          const data = await resp.json();
          const sig = data?.addonSig || data?.mhub;
          if (sig) return clientIp ? rewriteAddonSigIp(sig, clientIp) : sig;
      } catch (e) {
          console.warn(`[Vavoo] Ping ${url} failed: ${e.message}`);
      }
  }
  return null;
}

class VavooExtractor {
  _normalizeUrl(url) {
      if (url.includes('/watch')) {
          const parsed = new URL(url);
          const liveId = parsed.searchParams.get('live');
          if (liveId) return `https://vavoo.to/vavoo-iptv/play/${liveId}`;
      }
      const m = url.match(/\/play\/([^/?#]+)/);
      if (m) return `https://vavoo.to/vavoo-iptv/play/${m[1]}`;
      return url;
  }

  async resolveStream(vavooUrl, clientIp) {
      const normalizedUrl = this._normalizeUrl(vavooUrl);
      let sig = await fetchAddonSigWithCache(clientIp);
      const resolvePayload = {
          language: VAVOO_LANGUAGE, region: VAVOO_REGION,
          url: normalizedUrl, clientVersion: "3.0.2"
      };

      for (let attempt = 0; attempt < 2; attempt++) {
          const resolveHeaders = {
              "Origin": "https://vavoo.to",
              "Referer": "https://vavoo.to/",
              "User-Agent": "MediaHubMX/2",
              "Accept": "*/*",
              "Content-Type": "application/json; charset=utf-8",
              "Accept-Language": VAVOO_LANGUAGE,
          };
          if (sig) resolveHeaders["mediahubmx-signature"] = sig;

          const response = await fetch(`${BASE_SITES[attempt]}/mediahubmx-resolve.json`, {
              method: "POST",
              headers: resolveHeaders,
              body: JSON.stringify(resolvePayload)
          });
          if (response.status === 451 || response.status === 502) {
              if (attempt === 0) {
                  const fresh = await fetchAddonSigWithCache(clientIp);
                  if (fresh) sig = fresh;
                  continue;
              }
          }
          if (!response.ok) throw new ExtractorError(`Resolve API failed: ${response.status}`);
          const result = await response.json();
          let streamUrl;
          if (Array.isArray(result)) {
              const httpsStream = result.find(item => item.url && item.url.startsWith('https://'));
              streamUrl = httpsStream ? httpsStream.url : result[0]?.url;
          } else {
              streamUrl = result?.url;
          }
          if (!streamUrl) throw new ExtractorError('No stream URL in response.');
          return streamUrl;
      }
      throw new ExtractorError('Resolve API failed after retries.');
  }

  // PROMIJENJENO: sada proxyja direktno umjesto da redirecta na HTTP stream
  async handle(url, request, workerOrigin) {
      const clientIp = getClientIP(request);
      const streamUrl = await this.resolveStream(url, clientIp);
      const origin = workerOrigin || new URL(request.url).origin;
      return await proxyHLS(streamUrl, request, origin);
  }
}

// --- M3U Playlist Proxy (nepromijenjeno) ---

async function handlePlaylistProxy(request) {
  const url = new URL(request.url);
  const m3uUrlsParam = url.searchParams.get('url');
  if (!m3uUrlsParam) {
      return new Response('Error: Missing url parameter for playlist.', { status: 400, headers: CORS_HEADERS });
  }

  const m3uUrls = m3uUrlsParam.split(';').filter(u => u.trim() !== '');
  if (m3uUrls.length === 0) {
      return new Response('Error: No valid playlist URLs provided.', { status: 400, headers: CORS_HEADERS });
  }

  let combinedM3U = '';
  for (const m3uUrl of m3uUrls) {
      try {
          const response = await fetch(m3uUrl, { headers: { 'User-Agent': 'Mozilla/5.0' } });
          if (response.ok) {
              combinedM3U += await response.text() + '\n';
          }
      } catch (e) {
          console.error(`Failed to fetch ${m3uUrl}: ${e.message}`);
      }
  }

  const workerDomain = url.origin;
  const modifiedM3U = rewritePlaylistUrls(combinedM3U, workerDomain);

  return new Response(modifiedM3U, {
      headers: {
          ...CORS_HEADERS,
          'Content-Type': 'application/vnd.apple.mpegurl; charset=utf-8',
          'Content-Disposition': 'inline; filename="playlist.m3u"',
          'Cache-Control': 's-maxage=3600, stale-while-revalidate',
      }
  });
}

function rewritePlaylistUrls(m3uContent, workerDomain) {
  const lines = m3uContent.split('\n');
  const processedM3uParts = [];
  let lastExtinf = null;

  if (!lines[0]?.startsWith('#EXTM3U')) processedM3uParts.push('#EXTM3U');

  for (const line of lines) {
      const trimmedLine = line.trim();
      if (!trimmedLine) continue;

      if (trimmedLine.startsWith('#EXTM3U')) {
          if (!processedM3uParts.includes('#EXTM3U')) processedM3uParts.push(trimmedLine);
      } else if (trimmedLine.startsWith('#EXTINF:')) {
          lastExtinf = trimmedLine;
      } else if (trimmedLine.startsWith('#EXTVLCOPT:')) {
          processedM3uParts.push(trimmedLine);
      } else if (trimmedLine.startsWith('http') && lastExtinf) {
          processedM3uParts.push(lastExtinf);
          const newUrl = `${workerDomain}/manifest.m3u8?url=${encodeURIComponent(trimmedLine)}`;
          processedM3uParts.push(newUrl);
          lastExtinf = null;
      }
  }
  return processedM3uParts.join('\n');
}

// --- Info & Status Pages ---

function handleInfoPage(request) {
  const workerDomain = new URL(request.url).origin;
  const htmlContent = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Stream Extractor v2.2</title>
  <style>
    body { font-family: -apple-system, sans-serif; background: #0a0a0b; color: #fff; padding: 2rem; max-width: 900px; margin: auto; }
    h1 { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .card { background: #16181c; border: 1px solid #374151; border-radius: 1rem; padding: 1.5rem; margin: 1rem 0; }
    code { background: #1a1a1d; padding: 0.3rem 0.6rem; border-radius: 0.3rem; color: #3b82f6; word-break: break-all; }
  </style>
</head>
<body>
  <h1>Stream Extractor v2.2</h1>
  <div class="card">
    <h3>HLS Proxy (univerzalno)</h3>
    <p>Proxira bilo koji HLS stream (vavoo, geil, ili direktni stream URL). Prepisuje sve segmente kroz Worker.</p>
    <code>${workerDomain}/manifest.m3u8?url=&lt;STREAM_URL&gt;</code>
  </div>
  <div class="card">
    <h3>Status</h3>
    <code>${workerDomain}/status</code>
  </div>
</body>
</html>`;
  return new Response(htmlContent, { headers: { ...CORS_HEADERS, 'Content-Type': 'text/html; charset=utf-8' } });
}

function handleStatus(request) {
  const clientIP = getClientIP(request);
  const statusInfo = {
      status: "operational",
      version: "2.2",
      timestamp: new Date().toISOString(),
      client_info: {
          ip: clientIP,
          country: request.headers.get('CF-IPCountry') || 'unknown',
          user_agent: request.headers.get('User-Agent') || 'unknown',
          is_ipv6: clientIP ? clientIP.includes(':') : false,
      },
      supported_services: {
          vavoo: { mode: "proxy", path: "/manifest.m3u8?url=https://vavoo.to/..." },
          geil:  { mode: "proxy", path: "/manifest.m3u8?url=<resolved_stream_url>" },
          direct_hls: { mode: "proxy", path: "/manifest.m3u8?url=http://.../index.m3u8" },
      },
      endpoints: {
          info: new URL(request.url).origin + '/',
          status: new URL(request.url).origin + '/status',
          playlist_proxy: new URL(request.url).origin + '/playlist?url=<m3u_url>',
      }
  };
  return new Response(JSON.stringify(statusInfo, null, 2), { headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' } });
}

// --- Main Worker Fetch Handler ---

export default {
  async fetch(request) {
      if (request.method === 'OPTIONS') {
          return new Response(null, { status: 204, headers: CORS_HEADERS });
      }

      const url = new URL(request.url);

      try {
          if (url.pathname === '/' || url.pathname === '') {
              return handleInfoPage(request);
          }
          if (url.pathname === '/status') {
              return handleStatus(request);
          }
          if (url.pathname === '/playlist') {
              return await handlePlaylistProxy(request);
          }
          if (url.pathname === '/manifest.m3u8') {
              if (!url.searchParams.has('url')) {
                  return new Response(JSON.stringify({ error: 'Missing "url" parameter' }), {
                      status: 400, headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' }
                  });
              }

              const targetUrl = url.searchParams.get('url');
              const workerOrigin = url.origin;

              // Detect what kind of URL this is
              const cleanUrl = targetUrl.split('?')[0];
              const isStreamUrl = cleanUrl.endsWith('.m3u8') || cleanUrl.endsWith('.ts') || targetUrl.includes('/hls/');
              const isVavooPage = (targetUrl.includes('vavoo.to') || targetUrl.includes('geil.to') || targetUrl.includes('kool.to')) && !isStreamUrl;

              // 1. Vavoo/Geil page URL → use extractor (which now proxies, not redirects)
              if (isVavooPage) {
                  const extractor = new VavooExtractor();
                  return await extractor.handle(targetUrl, request, workerOrigin);
              }

              // 2. Any other URL (already-resolved stream, direct m3u8, segment) → proxy
              return await proxyHLS(targetUrl, request, workerOrigin);
          }

          return new Response(JSON.stringify({ error: '404 Not Found' }), {
              status: 404, headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' }
          });

      } catch (error) {
          console.error(`Worker Error: ${error.stack}`);
          return new Response(JSON.stringify({ error: error.message, type: error.name }), {
              status: 500, headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' }
          });
      }
  },
};
