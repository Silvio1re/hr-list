#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch Vavoo channels directly from Vavoo catalog API.
Generates M3U playlist with EPG IDs and logos (from GitHub).
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
LOGOS_URL = "https://raw.githubusercontent.com/Silvio1re/hr-list/main/logos.json"

TARGET_GROUPS = ["Croatia"]
FALLBACK_GROUPS = ["Balkans", "Ex-YU", "Hrvatska", "Balkan"]

HEADERS = {
    "User-Agent": "MediaHubMX/2",
    "Accept": "application/json",
    "Content-Type": "application/json; charset=utf-8",
}

# -----------------------------------

def normalize_key(key):
    """
    Normalizira ključ za pretraživanje:
    - ukloni sufiks (.hr, .rs, .si, .ba, .me, .mk, .al, .it, .de, itd.)
    - ukloni sve razmake
    - pretvori u mala slova
    """
    if not key:
        return key
    # Ukloni .hr, .rs, .si, itd. na kraju (2-3 slova)
    cleaned = re.sub(r'\.(hr|rs|si|ba|me|mk|al|it|de|at|ch|hu|ro|bg|gr|tr|ru|pl|cz|sk|fr|es|pt|nl|be|no|se|dk|fi|ie|gb|us|ca|au|nz|za|il|sa|ae|in|cn|jp|kr|tw|hk|sg|my|id|ph|th|vn|pk|bd|eg|ma|tn|dz|ng|ke|gh|za|br|ar|cl|co|pe|mx|uy|py|bo|ec|ve|pa|cr|gt|hn|sv|ni|do|pr|jm|tt|bb|bs|bm|ky|vg|tc|ai|ag|gd|kn|lc|vc|dm|ms|mp|gu|as|pw|fm|mh|vu|sb|fj|to|ws|pg|tl|kh|la|mm|np|lk|mv|bt|mn|kg|uz|tm|az|ge|am|ir|iq|sy|lb|jo|kw|qa|bh|om|ye|ps)$', '', key, flags=re.IGNORECASE)
    # Ukloni sve razmake i pretvori u mala slova
    return re.sub(r'\s+', '', cleaned).lower()


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
                        "group": group,
                        "tvg_id": f"{clean_name}.hr"
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


def fetch_local_logos():
    """Učitaj logotipe iz lokalnog logos.json i normaliziraj ključeve."""
    try:
        with open('logos.json', 'r', encoding='utf-8') as f:
            raw = json.load(f)
        # Normaliziraj sve ključeve i dodaj ih u mapu
        normalized = {}
        for key, value in raw.items():
            normalized[key] = value  # zadrži originalni ključ
            norm_key = normalize_key(key)
            if norm_key and norm_key not in normalized:
                normalized[norm_key] = value
        print(f"Učitano {len(normalized)} logotipa iz logos.json.", file=sys.stderr)
        return normalized
    except FileNotFoundError:
        print("logos.json nije pronađen.", file=sys.stderr)
        return {}


def get_epg_id(channel_name, epg_data):
    """Pronađi EPG ID za naziv kanala."""
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


def get_logo_url(tvg_id, channel_name, vavoo_logo, logo_map):
    """
    Dohvati URL logotipa.
    Prioritet: Normalizirani tvg-id → Normalizirani naziv kanala → Vavoo logo
    """
    # 1. Probaj po tvg-id (normaliziranom)
    if tvg_id:
        norm_tvg = normalize_key(tvg_id)
        if norm_tvg in logo_map:
            return logo_map[norm_tvg]
        # Probaj i originalni tvg-id (ako je točan)
        if tvg_id in logo_map:
            return logo_map[tvg_id]
    
    # 2. Probaj po nazivu kanala (normaliziranom)
    if channel_name:
        norm_name = normalize_key(channel_name)
        if norm_name in logo_map:
            return logo_map[norm_name]
        if channel_name in logo_map:
            return logo_map[channel_name]
    
    # 3. Vavoo logo (preskoči logo.huhu.to)
    if vavoo_logo and "logo.huhu.to" not in vavoo_logo:
        return vavoo_logo
    
    return ""


def build_proxy_url(stream_id):
    """Izgradi proxy URL s tvojim Cloudflare Workerom."""
    return f"{WORKER_BASE}{PROXY_PATH}?url=https://vavoo.to/vavoo-iptv/play/{stream_id}"


def generate_m3u(channels, epg_data, logo_map, group_name):
    """Generiraj M3U sadržaj s EPG ID-ovima i logotipima."""
    lines = ["#EXTM3U"]
    for ch in channels:
        name = ch["name"]
        stream_id = ch["id"]
        tvg_id = ch.get("tvg_id", "")
        vavoo_logo = ch.get("logo", "")

        epg_id = get_epg_id(name, epg_data) or ""
        logo_url = get_logo_url(tvg_id, name, vavoo_logo, logo_map) or ""
        stream_url = build_proxy_url(stream_id)

        tvg_id_attr = f' tvg-id="{tvg_id or epg_id}"' if (tvg_id or epg_id) else ' tvg-id=""'
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

    print("Dohvaćanje logotipa...", file=sys.stderr)
    logo_map = fetch_local_logos()

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
    m3u_content = generate_m3u(all_channels, epg_data, logo_map, group_name)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(m3u_content)

    print(f"Playlista spremljena u {OUTPUT_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
