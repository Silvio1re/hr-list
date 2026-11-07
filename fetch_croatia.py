#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geil.to M3U Generator - konačna verzija s otkrivenim API rutama
"""

import requests
import sys
import re
import time
import xml.etree.ElementTree as ET
from difflib import get_close_matches
from urllib.parse import quote

# ---------- KONFIGURACIJA ----------
WORKER_BASE = "https://hr-list.hallgrunt.workers.dev"
PROXY_PATH = "/manifest.m3u8"

OUTPUT_FILE = "vavoo_croatia.m3u"
EPG_URL = "https://iptv-epg.org/files/epg-hr.xml"

# Grupe za koje pokušavamo dohvatiti kanale
TARGET_GROUPS = ["Croatia", "Hrvatska", "HR", "CRO", "Croatian"]
FALLBACK_GROUPS = ["Balkans", "Ex-YU", "Balkan", "Regional", "Europe"]

REGION = "US"
LANGUAGE = "en"
SORT = "trending"

# --- OTKRIVENE PRAVE RUTE ---
GEIL_CATALOG_URL = "https://geil.to/live/catalog/live/channels.json"
GEIL_RESOLVE_URL = "https://geil.to/live/resolve"

HEADERS = {
    "User-Agent": "MediaHubMX/2",
    "Accept": "*/*",
    "Accept-Language": "en",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://geil.to/",
    "Origin": "https://geil.to",
}

session = requests.Session()
session.headers.update(HEADERS)

# -----------------------------------

def fetch_channels_for_group(group):
    """Dohvaća kanale za zadanu grupu preko GET zahtjeva."""
    params = {
        "region": REGION,
        "language": LANGUAGE,
        "sort": SORT,
        "filter[group]": group,
    }
    try:
        r = session.get(GEIL_CATALOG_URL, params=params, timeout=30)
        if r.status_code != 200:
            print(f"   ⚠️ HTTP {r.status_code} za grupu '{group}'", file=sys.stderr)
            return []
        data = r.json()
        if isinstance(data, dict):
            return data.get("items") or data.get("channels") or []
        elif isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"   ⚠️ Greška za grupu '{group}': {e}", file=sys.stderr)
        return []

def extract_channel_id(item):
    """Izvlači ID kanala iz raznih mogućih struktura."""
    if "id" in item:
        return str(item["id"])
    if "ids" in item and isinstance(item["ids"], dict) and "id" in item["ids"]:
        return str(item["ids"]["id"])
    url = item.get("url", "")
    if "/play/" in url:
        return url.split("/play/")[-1].split("?")[0].split("/")[0]
    return None

def extract_channel_name(item):
    return item.get("name") or item.get("title") or item.get("channel_name") or "Unknown"

def extract_channel_group(item, default):
    return item.get("group") or item.get("group_name") or item.get("groupName") or default

def resolve_stream_url(channel_id):
    """Pretvara ID kanala u pravi .m3u8 link preko GET resolve rute."""
    params = {
        "region": REGION,
        "language": LANGUAGE,
        "url": f"https://geil.to/live/play/{channel_id}"
    }
    try:
        r = session.get(GEIL_RESOLVE_URL, params=params, timeout=15)
        if r.status_code == 200:
            result = r.json()
            if isinstance(result, dict):
                return result.get("url") or result.get("stream_url") or result.get("streamUrl")
            elif isinstance(result, list) and result:
                return result[0].get("url") or result[0].get("stream_url") or result[0].get("streamUrl")
    except Exception:
        pass
    return None

def fetch_epg_data():
    """Dohvati i parsiraj EPG XML."""
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
    """Pretvara pravi HTTP stream u HTTPS preko Cloudflare Workera."""
    if not real_stream_url:
        return ""
    encoded = quote(real_stream_url, safe='')
    return f"{WORKER_BASE}{PROXY_PATH}?url={encoded}"

def main():
    epg_data = fetch_epg_data()

    all_channels = []
    groups_with_results = []

    # Isprobavamo redom sve grupe
    for group in TARGET_GROUPS + FALLBACK_GROUPS:
        print(f"📡 Dohvaćam kanale za grupu: {group}...", file=sys.stderr)
        items = fetch_channels_for_group(group)
        if items:
            print(f"   ✅ Pronađeno {len(items)} kanala u grupi '{group}'", file=sys.stderr)
            # Ispis prvog itema za debug (ako struktura nije očekivana)
            if len(all_channels) == 0 and items:
                first = items[0]
                print(f"   🔍 Debug - ključevi prvog kanala: {list(first.keys())[:15]}", file=sys.stderr)

            for item in items:
                ch_id = extract_channel_id(item)
                if not ch_id:
                    continue
                all_channels.append({
                    "id": ch_id,
                    "name": extract_channel_name(item),
                    "group": extract_channel_group(item, group),
                })
            groups_with_results.append(group)
        else:
            print(f"   ⚠️ Nema kanala za '{group}'", file=sys.stderr)
        time.sleep(0.5)

    if not all_channels:
        print("❌ Nema pronađenih kanala ni u jednoj grupi.", file=sys.stderr)
        sys.exit(1)

    # Ukloni duplikate po ID-u
    seen = set()
    unique_channels = []
    for ch in all_channels:
        if ch["id"] not in seen:
            seen.add(ch["id"])
            unique_channels.append(ch)

    print(f"\n✅ Ukupno jedinstvenih kanala: {len(unique_channels)}", file=sys.stderr)
    print(f"   Grupe s rezultatima: {', '.join(groups_with_results)}", file=sys.stderr)

    lines = ["#EXTM3U"]
    processed = 0

    print("\n⚙️ Resolvam streamove i generiram playlistu...", file=sys.stderr)
    for ch in unique_channels:
        print(f"   → {ch['name']} ({ch['id']})", file=sys.stderr)
        real_url = resolve_stream_url(ch["id"])
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
        processed += 1
        time.sleep(0.3)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n🎉 Gotovo! Uspješno obrađeno {processed} kanala.", file=sys.stderr)
    print(f"💾 Playlista spremljena u: {OUTPUT_FILE}", file=sys.stderr)

if __name__ == "__main__":
    main()
