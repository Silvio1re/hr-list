#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geil.to M3U Generator (ispravljene rute)
"""

import requests
import sys
import re
import time
import uuid
import xml.etree.ElementTree as ET
from difflib import get_close_matches
from urllib.parse import quote

# ---------- KONFIGURACIJA ----------
WORKER_BASE = "https://hr-list.hallgrunt.workers.dev"
PROXY_PATH = "/manifest.m3u8"

OUTPUT_FILE = "geil_croatia.m3u"
EPG_URL = "https://iptv-epg.org/files/epg-hr.xml"

TARGET_GROUPS = ["Croatia", "Hrvatska"]
FALLBACK_GROUPS = ["Balkans", "Ex-YU", "Balkan"]

# --- ISPRAVLJENE RUTE ---
# Umjesto samo https://geil.to/mediahubmx-catalog.json, dodali smo /vto-cluster/
GEIL_CATALOG_URL = "https://geil.to/vto-cluster/mediahubmx-catalog.json"
GEIL_RESOLVE_URL = "https://geil.to/vto-cluster/mediahubmx-resolve.json"

# Ako gornje ne radi, isprobaj ovo (obriši # ispred i zakomentiraj gornje):
# GEIL_CATALOG_URL = "https://geil.to/live2/mediahubmx-catalog.json"
# GEIL_RESOLVE_URL = "https://geil.to/live2/mediahubmx-resolve.json"

PING_URL = "https://www.vavoo.tv/api/app/ping"
PING_URL2 = "https://www.vypn.net/api/app/ping"

HEADERS = {
    "User-Agent": "MediaHubMX/2",
    "Accept": "*/*",
    "Accept-Language": "hr",
    "Accept-Encoding": "gzip, deflate"
}

# -----------------------------------

def get_addon_sig(session):
    print("🔑 Dohvaćam addonSig token...", file=sys.stderr)
    unique_id = str(uuid.uuid4())
    current_timestamp = int(time.time() * 1000)

    payload = {
        "token": "",
        "reason": "app-focus",
        "locale": "hr",
        "theme": "dark",
        "metadata": {
            "device": {"type": "phone", "uniqueId": unique_id},
            "os": {"name": "android", "version": "14", "abis": ["arm64-v8a"], "host": "android"},
            "app": {"platform": "android"},
            "version": {"package": "net.vypn.app", "binary": "1.4.1", "js": "1.4.1"}
        },
        "appFocusTime": 0,
        "playerActive": False,
        "playDuration": 0,
        "devMode": False,
        "hasAddon": True,
        "castConnected": False,
        "package": "net.vypn.app",
        "version": "1.4.1",
        "process": "app",
        "firstAppStart": current_timestamp - 86400000,
        "lastAppStart": current_timestamp,
        "ipLocation": None,
        "adblockEnabled": True,
        "proxy": {"supported": ["ss"], "engine": "Mu", "ssVersion": "2022", "enabled": False, "autoServer": True, "id": ""},
        "iap": {"supported": False, "error": ""}
    }

    headers = {
        "user-agent": "okhttp/4.11.0",
        "accept": "application/json",
        "content-type": "application/json; charset=utf-8",
    }

    for url in [PING_URL, PING_URL2]:
        try:
            r = session.post(url, json=payload, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                sig = data.get("addonSig") or data.get("mhub")
                if sig:
                    print("✅ Token uspješno dohvaćen.", file=sys.stderr)
                    return sig
        except Exception as e:
            pass
    
    print("❌ Nije moguće dohvatiti token.", file=sys.stderr)
    return None

def resolve_stream_url(channel_url, session, sig):
    if not channel_url:
        return None
        
    headers = {
        "content-type": "application/json; charset=utf-8",
        "mediahubmx-signature": sig,
        "user-agent": "MediaHubMX/2"
    }
    payload = {
        "language": "hr", 
        "region": "HR",
        "url": channel_url,
        "clientVersion": "3.0.2"
    }
    
    try:
        r = session.post(GEIL_RESOLVE_URL, json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            result = r.json()
            if isinstance(result, list) and result:
                return result[0].get("url")
            elif isinstance(result, dict):
                return result.get("url")
    except Exception:
        pass
    return None

def fetch_channels(session, sig):
    print("📡 Dohvaćam katalog kanala s geil.to...", file=sys.stderr)
    all_channels = []
    cursor = None
    page = 1

    headers = {
        "content-type": "application/json; charset=utf-8",
        "mediahubmx-signature": sig,
        "user-agent": "MediaHubMX/2"
    }

    while page <= 50:
        payload = {
            "language": "hr",
            "region": "HR",
            "catalogId": "iptv", # Enigma2 skripta koristi "iptv"
            "id": "iptv",
            "adult": False,
            "search": "",
            "sort": "name",
            "filter": {},
            "cursor": cursor,
            "clientVersion": "3.0.2"
        }

        try:
            r = session.post(GEIL_CATALOG_URL, json=payload, headers=headers, timeout=30)
            if r.status_code != 200:
                print(f"⚠️ Greška pri dohvatu stranice {page}: HTTP {r.status_code}", file=sys.stderr)
                break

            data = r.json()
            items = data.get("items", [])
            if not items:
                break

            for item in items:
                if item.get("type") == "iptv":
                    name = item.get("name", "Unknown")
                    group = item.get("group", "")
                    
                    base_country = group
                    for sep in ["➾", "⟾", "->", "→", "»", "›"]:
                        if sep in base_country:
                            base_country = base_country.split(sep)[0].strip()
                            break
                    
                    if base_country in TARGET_GROUPS or base_country in FALLBACK_GROUPS:
                        clean_name = re.sub(r"\s*\.\w+$", "", name).strip()
                        all_channels.append({
                            "name": clean_name,
                            "url": item.get("url", ""),
                            "group": base_country
                        })

            cursor = data.get("nextCursor")
            if not cursor:
                break
            page += 1
            time.sleep(0.5)

        except Exception as e:
            print(f"❌ Greška pri dohvatu kataloga: {e}", file=sys.stderr)
            break

    print(f"✅ Pronađeno {len(all_channels)} ciljanih kanala.", file=sys.stderr)
    return all_channels

def fetch_epg_data():
    try:
        print("📅 Dohvaćam EPG podatke...", file=sys.stderr)
        resp = requests.get(EPG_URL, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        epg_channels = {}
        for channel in root.findall("channel"):
            chan_id = channel.get("id")
            display_name = channel.find("display-name")
            if chan_id is not None and display_name is not None and display_name.text:
                name = display_name.text.strip()
                epg_channels[name] = chan_id
                epg_channels[name.lower()] = chan_id
        print(f"✅ Učitano {len(epg_channels)} EPG mapiranja.", file=sys.stderr)
        return epg_channels
    except Exception as e:
        print(f"❌ Greška pri dohvaćanju EPG-a: {e}", file=sys.stderr)
        return {}

def get_epg_id(channel_name, epg_data):
    if not epg_data or not channel_name:
        return None
    clean_name = re.sub(r"\s*\(.*?\)\s*", "", channel_name).strip()
    if clean_name in epg_data:
        return epg_data[clean_name]
    name_lower = clean_name.lower()
    if name_lower in epg_data:
        return epg_data[name_lower]
    if len(name_lower) >= 3:
        matches = get_close_matches(name_lower, epg_data.keys(), n=1, cutoff=0.7)
        if matches:
            return epg_data[matches[0]]
    return None

def build_proxy_url(real_stream_url):
    if not real_stream_url:
        return ""
    encoded = quote(real_stream_url, safe='')
    return f"{WORKER_BASE}{PROXY_PATH}?url={encoded}"

def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    sig = get_addon_sig(session)
    if not sig:
        print("❌ Prekidam rad jer nemam token.", file=sys.stderr)
        sys.exit(1)

    epg_data = fetch_epg_data()

    channels = fetch_channels(session, sig)
    if not channels:
        print("❌ Nema pronađenih kanala. Prekidam.", file=sys.stderr)
        sys.exit(1)

    lines = ["#EXTM3U"]
    processed_count = 0

    print("⚙️ Resolvam streamove i generiram playlistu...", file=sys.stderr)
    for ch in channels:
        print(f"   -> {ch['name']}", file=sys.stderr)
        
        real_url = resolve_stream_url(ch["url"], session, sig)
        if not real_url:
            print(f"      ⚠️ Nije moguće resolveati, preskačem.", file=sys.stderr)
            continue

        final_url = build_proxy_url(real_url)
        
        epg_id = get_epg_id(ch["name"], epg_data) or ""
        tvg_id = f"{ch['name']}.hr"

        tvg_id_attr = f' tvg-id="{tvg_id or epg_id}"' if (tvg_id or epg_id) else ' tvg-id=""'
        tvg_name_attr = f' tvg-name="{ch["name"]}"'
        group_attr = f' group-title="{ch["group"]}"'

        extinf = f'#EXTINF:-1{tvg_id_attr}{tvg_name_attr}{group_attr},{ch["name"]}'
        
        lines.append(extinf)
        lines.append(final_url)
        processed_count += 1
        
        time.sleep(0.2)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n🎉 Gotovo! Uspješno obrađeno {processed_count} kanala.", file=sys.stderr)
    print(f"💾 Playlista spremljena u: {OUTPUT_FILE}", file=sys.stderr)

if __name__ == "__main__":
    main()
