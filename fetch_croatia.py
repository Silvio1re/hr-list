import requests
import json
import time
import os

API_URL = "https://vavoo.to/vto-cluster/mediahubmx-catalog.json"
PROXY_PREFIX = "https://loud-songbird-5966.fromzer00.deno.net/?url="
OUTPUT_FILE = "vavoo_croatia.m3u"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "MediaHubMX/2"
}

def fetch_catalog(group=None):
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
            print(f"❌ Greška na stranici {page}: {e}")
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
    # Prvo probaj s "Croatia"
    print("🔄 Dohvaćam kanale za grupu 'Croatia'...")
    items = fetch_catalog("Croatia")
    print(f"✅ Pronađeno {len(items)} kanala za 'Croatia'.")

    # Ako nema, probaj s "Balkans"
    if not items:
        print("⚠️ Nema kanala za 'Croatia', pokušavam s 'Balkans'...")
        items = fetch_catalog("Balkans")
        print(f"✅ Pronađeno {len(items)} kanala za 'Balkans'.")

    # Ako i dalje nema, dohvati sve i prikaži dostupne grupe
    if not items:
        print("⚠️ Nema kanala ni za 'Balkans', dohvaćam sve grupe...")
        all_items = fetch_catalog(None)
        groups = sorted(set(item.get("group") for item in all_items if item.get("group")))
        print("📋 Dostupne grupe:", groups)
        # Uzmi prvu grupu koja nije prazna
        for g in groups:
            if g:
                print(f"🔄 Pokušavam s grupom '{g}'...")
                items = fetch_catalog(g)
                if items:
                    print(f"✅ Pronađeno {len(items)} kanala za '{g}'.")
                    break

    if not items:
        print("❌ Nema dostupnih kanala. Provjeri API ili internet vezu.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n# No channels found")
        return

    m3u = generate_m3u(items)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(m3u)

    print(f"✅ Spremljeno {len(items)} kanala u {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
