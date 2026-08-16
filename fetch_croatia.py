#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch Vavoo channels directly from Vavoo catalog API.
Generates M3U playlist with EPG IDs and logos (from IPTV-org).
"""

import requests
import json
import sys
import re
import xml.etree.ElementTree as ET
from difflib import get_close_matches
from urllib.parse import urlparse, parse_qs

# ---------- Konfiguracija ----------
WORKER_BASE = "https://hr-list.hallgrunt.workers.dev"
PROXY_PATH = "/manifest.m3u8"
OUTPUT_FILE = "vavoo_croatia.m3u"
EPG_URL = "https://iptv-epg.org/files/epg-hr.xml"

TARGET_GROUPS = ["Croatia"]
FALLBACK_GROUPS = ["Balkans", "Ex-YU", "Hrvatska", "Balkan"]

HEADERS = {
    "User-Agent": "MediaHubMX/2",
    "Accept": "application/json",
    "Content-Type": "application/json; charset=utf-8",
}

# ---------- Ručno mapiranje logotipa (za kanale koje IPTV-org nema) ----------
MANUAL_LOGOS = {
    # Dodaj ovdje kanale koji nemaju logo u IPTV-org bazi
    # "ARENA SPORT 1": "https://i.imgur.com/xxxxx.png",
    # "ARENA SPORT 2": "https://i.imgur.com/yyyyy.png",
}

# -----------------------------------


def fetch_groups():
    """Dohvati dostupne grupe s Vavoo-a."""
    for url in ["https://www2.vavoo.to/live2/index?output=json", "https://www.vavoo.to/live2/index?output=json"]:
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                groups = list(set([c.get("group") for c in data if c.get("group")]))
                return sorted(groups)
        except:
            continue
    return []


def fetch_channels_for_group(group, session):
    """Dohvati sve kanale za zadanu grupu (uz paginaciju)."""
    channels = []
    cursor = 0

    while True:
        payload = {
            "language": "de",
            "region": "DE",
            "catalogId": "vto-iptv",
            "id": "vto-iptv",
            "adult": False,
            "search": "",
            "sort": "name",
            "filter": {"group": group},
            "cursor": cursor,
            "clientVersion": "3.0.2"
        }

        try:
            resp = session.post(
                "https://vavoo.to/vto-cluster/mediahubmx-catalog.json",
                data=json.dumps(payload),
                timeout=30,
                headers={"Referer": "https://vavoo.tv"}
            )

            if resp.status_code != 200:
                break

            data = resp.json()
            items = data.get("items", [])
            if not items:
                break

            for item in items:
                name = item.get("name", "Unknown")
                clean_name = re.sub(r"\s*\.\w+$", "", name).strip()
                url = item.get("url", "")

                stream_id = extract_stream_id(url)
                if stream_id:
                    channels.append({
                        "name": clean_name,
                        "id": stream_id,
                        "url": url,
                        "logo": item.get("logo", ""),
                        "group": group
                    })

            cursor = data.get("nextCursor")
            if not cursor:
                break

        except Exception as e:
            print(f"  Greška: {e}", file=sys.stderr)
            break

    return channels


def extract_stream_id(url):
    """Izvadi stream ID iz Vavoo URL-a."""
    if not url:
        return None

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    if 'stream' in query_params:
        return query_params['stream'][0]

    match = re.search(r'/live/([^/]+)', parsed.path)
    if match:
        return match.group(1)

    return url.split('/')[-1].split('.')[0]


def fetch_epg_data():
    """Dohvati i parsiraj EPG XML s iptv-epg.org."""
    try:
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
                no_space = re.sub(r"\s+", "", name)
                if no_space != name:
                    epg_channels[no_space] = chan_id
                    epg_channels[no_space.lower()] = chan_id
        print(f"Učitano {len(epg_channels)} EPG mapiranja.", file=sys.stderr)
        return epg_channels
    except Exception as e:
        print(f"Greška pri dohvaćanju EPG-a: {e}", file=sys.stderr)
        return {}


def fetch_iptv_logos():
    """
    Dohvati logotipe s IPTV-org API-ja (channels.json).
    Vraća rječnik {naziv_kanala: logo_url}.
    """
    try:
        resp = requests.get("https://iptv-org.github.io/api/channels.json", timeout=15)
        if resp.status_code != 200:
            print("IPTV-org API nije dostupan.", file=sys.stderr)
            return {}

        channels = resp.json()
        logo_map = {}
        for ch in channels:
            name = ch.get("name", "")
            logo = ch.get("logo", "")
            if name and logo:
                # Spremi više varijanti naziva
                logo_map[name] = logo
                logo_map[name.lower()] = logo
                # Bez razmaka
                no_space = name.lower().replace(" ", "")
                logo_map[no_space] = logo
                # Za hrvatske kanale dodaj i s prefiksom
                if ch.get("country") == "HR":
                    logo_map[f"HR_{name}"] = logo
                    logo_map[f"hr_{name}"] = logo
        print(f"Učitano {len(logo_map)} logotipa iz IPTV-org.", file=sys.stderr)
        return logo_map
    except Exception as e:
        print(f"Greška pri dohvaćanju IPTV-org logotipa: {e}", file=sys.stderr)
        return {}


def get_epg_id(channel_name, epg_data):
    """Pronađi EPG ID za naziv kanala (fuzzy matching)."""
    if not epg_data or not channel_name:
        return None
    clean_name = re.sub(r"\s*\(.*?\)\s*", "", channel_name).strip()
    if clean_name in epg_data:
        return epg_data[clean_name]
    name_lower = clean_name.lower()
    if name_lower in epg_data:
        return epg_data[name_lower]
    no_space = re.sub(r"\s+", "", clean_name)
    if no_space in epg_data:
        return epg_data[no_space]
    if no_space.lower() in epg_data:
        return epg_data[no_space.lower()]
    if len(name_lower) >= 3:
        matches = get_close_matches(name_lower, epg_data.keys(), n=1, cutoff=0.7)
        if matches:
            return epg_data[matches[0]]
    return None


def get_logo_url(channel_name, vavoo_logo, iptv_logo_map):
    """
    Dohvati URL logotipa.
    Prioritet: Ručno mapiranje → IPTV-org → Vavoo (ako nije logo.huhu.to) → prazno.
    """
    # 1. Ručno mapiranje (za kanale koje IPTV-org nema)
    if channel_name in MANUAL_LOGOS:
        return MANUAL_LOGOS[channel_name]

    # 2. IPTV-org (najpouzdaniji)
    if channel_name in iptv_logo_map:
        return iptv_logo_map[channel_name]
    no_space = channel_name.lower().replace(" ", "")
    if no_space in iptv_logo_map:
        return iptv_logo_map[no_space]
    # Probaj i s prefiksom HR_ (ako je kanal hrvatski)
    hr_key = f"HR_{channel_name}"
    if hr_key in iptv_logo_map:
        return iptv_logo_map[hr_key]

    # 3. Vavoo logo (preskoči logo.huhu.to)
    if vavoo_logo and vavoo_logo.startswith("http"):
        if "logo.huhu.to" not in vavoo_logo:
            return vavoo_logo

    # 4. Prazno (bez logotipa)
    return ""


def build_proxy_url(stream_id):
    """Izgradi proxy URL s tvojim Cloudflare Workerom."""
    return f"{WORKER_BASE}{PROXY_PATH}?url=https://vavoo.to/vavoo-iptv/play/{stream_id}"


def generate_m3u(channels, epg_data, iptv_logo_map, group_name):
    """Generiraj M3U sadržaj s EPG ID-ovima i logotipima."""
    lines = ["#EXTM3U"]
    for ch in channels:
        name = ch["name"]
        stream_id = ch["id"]
        vavoo_logo = ch.get("logo", "")

        epg_id = get_epg_id(name, epg_data) or ""
        logo_url = get_logo_url(name, vavoo_logo, iptv_logo_map) or ""
        stream_url = build_proxy_url(stream_id)

        tvg_id_attr = f' tvg-id="{epg_id}"' if epg_id else ' tvg-id=""'
        tvg_logo_attr = f' tvg-logo="{logo_url}"' if logo_url else ' tvg-logo=""'
        tvg_name_attr = f' tvg-name="{name}"'
        group_attr = f' group-title="{group_name}"'

        extinf = f'#EXTINF:-1{tvg_id_attr}{tvg_name_attr}{tvg_logo_attr}{group_attr},{name}'

        lines.append(extinf)
        lines.append(stream_url)

    return "\n".join(lines)


def main():
    print("Dohvaćanje grupa s Vavoo-a...", file=sys.stderr)
    groups = fetch_groups()
    if not groups:
        print("Nema dostupnih grupa.", file=sys.stderr)
        sys.exit(1)

    print(f"Dostupne grupe: {groups}", file=sys.stderr)

    target_groups = [g for g in groups if g in TARGET_GROUPS]
    if not target_groups:
        print("Grupa 'Croatia' nije pronađena, tražim zamjenske...", file=sys.stderr)
        target_groups = [g for g in groups if g in FALLBACK_GROUPS]

    if not target_groups:
        print("Nema odgovarajuće grupe.", file=sys.stderr)
        sys.exit(1)

    print("Dohvaćanje EPG podataka...", file=sys.stderr)
    epg_data = fetch_epg_data()

    print("Dohvaćanje IPTV-org logotipa...", file=sys.stderr)
    iptv_logo_map = fetch_iptv_logos()

    session = requests.Session()
    session.headers.update(HEADERS)

    all_channels = []
    for group in target_groups:
        print(f"Dohvaćanje kanala za grupu: {group}...", file=sys.stderr)
        channels = fetch_channels_for_group(group, session)
        print(f"  Pronađeno {len(channels)} kanala.", file=sys.stderr)
        all_channels.extend(channels)

    if not all_channels:
        print("Nema kanala.", file=sys.stderr)
        sys.exit(1)

    print(f"Ukupno kanala: {len(all_channels)}", file=sys.stderr)

    group_name = target_groups[0]
    m3u_content = generate_m3u(all_channels, epg_data, iptv_logo_map, group_name)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(m3u_content)

    print(f"Playlista spremljena u {OUTPUT_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
