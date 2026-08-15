import requests
import json
import time

API_URL = "https://vavoo.to/vto-cluster/mediahubmx-catalog.json"
PROXY_PREFIX = "https://loud-songbird-5966.fromzer00.deno.net/?url="
OUTPUT_FILE = "vavoo_croatia.m3u"
HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "User-Agent": "MediaHubMX/2",
    "Accept": "application/json"
}

def fetch_catalog(group="Croatia"):
    items = []
    cursor = 0  # mr-evil1 uses 0, not None!
    page = 0
    max_pages = 50

    while True:
        page += 1
        payload = {
            "language": "de",
            "region": "AT",
            "catalogId": "vto-iptv",      # <-- KEY FIX
            "id": "vto-iptv",             # <-- KEY FIX
            "adult": False,
            "search": "",
            "sort": "name",
            "filter": {"group": group},
            "cursor": cursor,
            "clientVersion": "3.0.2"      # <-- KEY FIX
        }

        try:
            resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"❌ Greška na stranici {page}: {e}")
            break

        new_items = data.get("items", [])
        items.extend(new_items)
        cursor = data.get("nextCursor")
        print(f"Stranica {page}: {len(new_items)} kanala, nextCursor={cursor}")

        if cursor is None or page >= max_pages:
            break

        time.sleep(0.05)  # mr-evil1 uses 0.05

    return items

def generate_m3u(items):
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
    print("🔄 Dohvaćam kanale za 'Croatia'...")
    items = fetch_catalog("Croatia")
    print(f"✅ Pronađeno {len(items)} kanala.")

    if not items:
        print("⚠️ Pokušavam s 'Balkans'...")
        items = fetch_catalog("Balkans")
        print(f"✅ Pronađeno {len(items)} kanala za 'Balkans'.")

    if not items:
        print("❌ Nema kanala. Provjeri API.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n# No channels found")
        return

    m3u = generate_m3u(items)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(m3u)

    print(f"✅ Spremljeno {len(items)} kanala u {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
