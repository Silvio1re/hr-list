#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geil.to M3U Generator - v3.0
- Katalog: GET /live/catalog/live/channels.json
- Stream: play URL se šalje Workeru, Worker resolva on-demand
- Prednost: brzo (10s umjesto 3min), svježi tokeni, nema 403
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

# Grupe koje pokušavamo dohvatiti (redom)
TARGET_GROUPS = ["Croatia", "Hrvatska", "HR", "CRO", "Croatian"]
# Ako želiš SAMO hrvatske kanale, isprazni ovu listu: FALLBACK_GROUPS = []
FALLBACK_GROUPS = ["Balkans"]

REGION = "US"
LANGUAGE = "en"
SORT = "trending"

# Geil.to API rute (otkrivene iz Network taba)
GEIL_CATALOG_URL = "https://geil.to/live/catalog/live/channels.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) Gecko/20100101 Firefox/153.0",
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

def build_proxy_url(channel_id):
    """Gradi URL na Worker koji će sam resolvati play URL u stream."""
    play_url = f"https://geil.to/live/play/{channel_id}"
    encoded = quote(play_url, safe='')
    return f"{WORKER_BASE}{PROXY_PATH}?url={encoded}"

def main():
    epg_data = fetch_epg_data()

    all_channels = []
    groups_with_results = []

    # Prvo probaj ciljne grupe
    for group in TARGET_GROUPS:
        print(f"📡 Dohvaćam kanale za grupu: {group}...", file=sys.stderr)
        items = fetch_channels_for_group(group)
        if items:
            print(f"   ✅ Pronađeno {len(items)} kanala u grupi '{group}'", file=sys.stderr)
            for item in items:
                ch_id = extract_channel_id(item)
                if ch_id:
                    all_channels.append({
                        "id": ch_id,
                        "name": extract_channel_name(item),
                        "group": extract_channel_group(item, group),
                    })
            groups_with_results.append(group)
        else:
            print(f"   ⚠️ Nema kanala za '{group}'", file=sys.stderr)
        time.sleep(0.3)

    # Ako ništa nije pronađeno, probaj fallback grupe
    if not all_channels and FALLBACK_GROUPS:
        print("⚠️ Nema kanala u ciljnim grupama, pokušavam fallback...", file=sys.stderr)
        for group in FALLBACK_GROUPS:
            print(f"📡 Dohvaćam kanale za grupu: {group}...", file=sys.stderr)
            items = fetch_channels_for_group(group)
            if items:
                print(f"   ✅ Pronađeno {len(items)} kanala u grupi '{group}'", file=sys.stderr)
                for item in items:
                    ch_id = extract_channel_id(item)
                    if ch_id:
                        all_channels.append({
                            "id": ch_id,
                            "name": extract_channel_name(item),
                            "group": extract_channel_group(item, group),
                        })
                groups_with_results.append(group)
            time.sleep(0.3)

    if not all_channels:
        print("❌ Nema pronađenih kanala.", file=sys.stderr)
        sys.exit(1)

    # Ukloni duplikate po ID-u
    seen = set()
    unique_channels = [ch for ch in all_channels if not (ch["id"] in seen or seen.add(ch["id"]))]

    print(f"\n✅ Ukupno jedinstvenih kanala: {len(unique_channels)}", file=sys.stderr)
    print(f"   Grupe: {', '.join(groups_with_results)}", file=sys.stderr)

    # ---- GENERIRANJE M3U ----
    print("\n📝 Generiram playlistu (Worker će resolvati on-demand)...", file=sys.stderr)
    lines = ["#EXTM3U"]
    for ch in unique_channels:
        final_url = build_proxy_url(ch["id"])
        epg_id = get_epg_id(ch["name"], epg_data) or ""
        tvg_id = f"{ch['name']}.hr"

        tvg_id_attr = f' tvg-id="{tvg_id or epg_id}"' if (tvg_id or epg_id) else ' tvg-id=""'
        tvg_name_attr = f' tvg-name="{ch["name"]}"'
        group_attr = f' group-title="{ch["group"]}"'

        lines.append(f'#EXTINF:-1{tvg_id_attr}{tvg_name_attr}{group_attr},{ch["name"]}')
        lines.append(final_url)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n🎉 Gotovo! {len(unique_channels)} kanala u playlisti.", file=sys.stderr)
    print(f"💾 Spremljeno u: {OUTPUT_FILE}", file=sys.stderr)

if __name__ == "__main__":
    main()
