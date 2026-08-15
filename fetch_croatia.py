import requests
import json
import time
import os

API_URL = "https://vavoo.to/vto-cluster/mediahubmx-catalog.json"
PROXY_PREFIX = "https://loud-songbird-5966.fromzer00.deno.net/?url="
OUTPUT_FILE = "vavoo_croatia_direct.m3u"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "MediaHubMX/2"
}

def fetch_catalog(group="Croatia"):
    """Dohvati sve kanale iz Vavoo kataloga za zadanu grupu."""
    items = []
    cursor = None
    page = 0
    max_pages = 50

    while True:
        page += 1
        payload = {
            "language": "de",
            "region": "AT",
            "catalogId": "iptv",
            "filter": {"group": group} if group else {},
            "cursor": cursor
        }

        try:
            resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"Greška pri dohvaćanju: {e}")
            break

        new_items = data.get("items", [])
        items.extend(new_items)
        cursor = data.get("nextCursor")
        print(f"Stranica {page}: {len(new_items)} kanala, nextCursor={cursor}")

        if cursor is None or page >= max_pages:
            break

        time.sleep(0.5)

    return items

def generate_m3u(items):
    """Generira M3U listu s proxy prefixom."""
    lines = ["#EXTM3U"]
    for item in items:
        name = item.get("name", "Nepoznato")
        vavoo_id = item.get("ids", {}).get("id")
        if not vavoo_id:
            continue
        group = item.get("group", "Diğer")
        logo = item.get("logo", "")
        stream_url = f"{PROXY_PREFIX}https://vavoo.to/vavoo-iptv/play/{vavoo_id}"
        lines.append(f'#EXTINF:-1 tvg-id="{vavoo_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="{group}",{name}')
        lines.append(stream_url)
    return "\n".join(lines)

def main():
    print("Dohvaćam Vavoo katalog...")
    items = fetch_catalog("Croatia")
    print(f"Ukupno kanala: {len(items)}")

    if not items:
        print("Nema kanala za grupu 'Croatia'.")
        # Ako nema kanala, ne želimo prepisati postojeću listu
        return

    m3u = generate_m3u(items)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(m3u)

    print(f"Spremljeno {len(items)} kanala u {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
