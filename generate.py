# -*- coding: utf-8 -*-
import requests
import json
import re
import urllib.parse

def extract_stream_id(url):
    parsed = urllib.parse.urlparse(url)
    query_params = urllib.parse.parse_qs(parsed.query)
    if 'stream' in query_params:
        return query_params['stream'][0]
    match = re.search(r'/live/([^/]+)', parsed.path)
    if match:
        return match.group(1)
    return url.split('/')[-1].split('.')[0]

def main():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'MediaHubMX/2',
        'Accept': 'application/json',
        'Content-Type': 'application/json; charset=utf-8'
    })
    
    try:
        try:
            group_res = session.get("https://www2.vavoo.to/live2/index?output=json", timeout=20).json()
        except:
            group_res = session.get("https://www.vavoo.to/live2/index?output=json", timeout=20).json()
            
        countries = sorted(list(set([c.get("group") for c in group_res if c.get("group")])))
        print(f"✅ Pronađene grupe: {countries}")
        
    except Exception as e:
        print(f"❌ Greška pri dohvaćanju grupa: {e}")
        return

    m3u_lines = ["#EXTM3U"]
    
    target_groups = ["Balkans", "Ex-YU", "Croatia", "Serbia", "Slovenia", "Bosnia", "Ex-Yugoslavia"]
    groups_to_fetch = [g for g in countries if g in target_groups]
    
    if not groups_to_fetch:
        print("⚠️ Nema balkanskih grupa, uzimam sve grupe...")
        groups_to_fetch = countries

    for group in groups_to_fetch:
        cursor = 0
        print(f"📡 Učitavam: {group}...", end="", flush=True)
        count = 0
        
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
                r = session.post(
                    "https://vavoo.to/vto-cluster/mediahubmx-catalog.json",
                    data=json.dumps(payload),
                    timeout=30,
                    headers={"User-Agent": "MediaHubMX/2", "Referer": "https://vavoo.tv"}
                )
                
                if r.status_code == 200:
                    data = r.json()
                    items = data.get("items", [])
                    
                    for item in items:
                        name = item.get("name", "Nepoznato")
                        clean_name = name.split(".")[0].strip()
                        url = item.get("url", "")
                        
                        if url:
                            stream_id = extract_stream_id(url)
                            proxy_url = f"https://vavoo-iptv-proxy.vavoo-iptv.workers.dev/play/{stream_id}"
                            
                            # XTeVe-friendly format: tvg-name umjesto tvg-id, bez EXTVLCOPT
                            m3u_lines.append(f'#EXTINF:-1 tvg-name="{clean_name}" group-title="{group}",{clean_name}')
                            m3u_lines.append(proxy_url)
                            count += 1
                    
                    cursor = data.get("nextCursor")
                    if not cursor:
                        break
                else:
                    print(f" HTTP {r.status_code}", end="")
                    break
            except Exception as e:
                print(f" Greška: {e}", end="")
                break
        
        print(f" ✅ {count} kanala")

    with open("vavoo_hrvatska_lista.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines))
        
    print(f"\n✅ GOTOVO! Ukupno {len(m3u_lines)-1} kanala spremljeno kao 'vavoo_hrvatska_lista.m3u'")

if __name__ == "__main__":
    main()
