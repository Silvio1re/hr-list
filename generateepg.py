# -*- coding: utf-8 -*-
import requests

def main():
    # Dohvati EPG s Vavoo API-ja (XML format)
    url = "https://www2.vavoo.to/epg?output=xml"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Provjeri je li zahtjev uspio
        
        with open("epg.xml", "w", encoding="utf-8") as f:
            f.write(response.text)
        
        print("✅ EPG uspješno spremljen kao 'epg.xml'")
    except Exception as e:
        print(f"❌ Greška pri dohvaćanju EPG-a: {e}")
        # Čak i ako ne uspije, ne prekidamo izvršavanje – ostavit ćemo stari EPG ako postoji

if __name__ == "__main__":
    main()
