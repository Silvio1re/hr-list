import requests
import re

SOURCE_URL = "https://raw.githubusercontent.com/mr-evil1/VAVOO/refs/heads/main/vavoo_all.m3u"
PROXY_PREFIX = "https://loud-songbird-5966.fromzer00.deno.net/?url="
OUTPUT_FILE = "vavoo_croatia.m3u"

def main():
    # Dohvati glavnu listu
    resp = requests.get(SOURCE_URL, timeout=30)
    resp.raise_for_status()
    lines = resp.text.splitlines()

    output = ["#EXTM3U"]  # zaglavlje
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            # Provjeri je li grupa "Croatia"
            if 'group-title="Croatia"' in line:
                # Pronađi sljedeću liniju koja sadrži URL
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    url_line = lines[j].strip()
                    if url_line.startswith("https://vavoo.to/vavoo-iptv/play/"):
                        # Zadrži #EXTINF liniju
                        output.append(line)
                        # Dodaj proxy prefix ispred URL-a
                        output.append(f"{PROXY_PREFIX}{url_line}")
                        i = j + 1
                        continue
            # Ako nije Croatia, preskoči EXTINF i pripadajući URL
            i += 1
            # preskoči prazne linije
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines) and lines[i].strip().startswith("https://vavoo.to/"):
                i += 1
        else:
            # Preskoči sve ostalo (komentare, prazne linije, itd.)
            i += 1

    # Spremi rezultat
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"✅ Spremljeno {len(output)-1} kanala u {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
