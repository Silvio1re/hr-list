# -*- coding: utf-8 -*-
import requests

def main():
    url = "https://www2.vavoo.to/epg?output=xml"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        with open("epg.xml", "w", encoding="utf-8") as f:
            f.write(response.text)
        print("✅ EPG uspješno spremljen kao 'epg.xml'")
    except Exception as e:
        print(f"❌ Greška pri dohvaćanju EPG-a: {e}")

if __name__ == "__main__":
    main()
