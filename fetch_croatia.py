#!/usr/bin/env python3
"""
Fetch Vavoo channels for the 'Croatia' group and generate an M3U playlist
with EPG IDs and logos from multiple sources.
"""

import json
import requests
import sys
import re
import xml.etree.ElementTree as ET
from difflib import get_close_matches
from urllib.parse import quote

# Configuration
VAVOO_API = "https://www.vavoo.tv/api/channels"
WORKER_BASE = "https://hr-list.hallgrunt.workers.dev"
PROXY_PATH = "/manifest.m3u8"
OUTPUT_FILE = "vavoo_croatia.m3u"
EPG_URL = "https://iptv-epg.org/files/epg-hr.xml"

# Group to fetch
TARGET_GROUP = "Croatia"
FALLBACK_GROUPS = ["Balkans", "Ex-YU", "Hrvatska", "Balkan"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_channels():
    """Fetch all channels from Vavoo API."""
    try:
        resp = requests.get(VAVOO_API, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching channels: {e}", file=sys.stderr)
        return None


def fetch_epg_data():
    """Fetch and parse EPG XML from iptv-epg.org."""
    try:
        resp = requests.get(EPG_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        
        epg_channels = {}
        for channel in root.findall("channel"):
            chan_id = channel.get("id")
            display_name = channel.find("display-name")
            if chan_id is not None and display_name is not None and display_name.text:
                name = display_name.text.strip()
                # Store multiple variants for matching
                epg_channels[name] = chan_id
                epg_channels[name.lower()] = chan_id
                no_space = re.sub(r"\s+", "", name)
                if no_space != name:
                    epg_channels[no_space] = chan_id
                    epg_channels[no_space.lower()] = chan_id
        
        print(f"Loaded {len(epg_channels)} EPG channel mappings.", file=sys.stderr)
        return epg_channels
    except Exception as e:
        print(f"Error fetching EPG: {e}", file=sys.stderr)
        return {}


def find_group_id(channels, group_name):
    """Find the group ID for a given group name."""
    for group in channels.get("groups", []):
        if group.get("name") == group_name:
            return group.get("id")
    for group in channels.get("groups", []):
        if group.get("name", "").lower() == group_name.lower():
            return group.get("id")
    return None


def find_group_id_fallback(channels):
    """Try fallback groups in order."""
    for grp in FALLBACK_GROUPS:
        gid = find_group_id(channels, grp)
        if gid is not None:
            return gid, grp
    return None, None


def get_channels_for_group(channels, group_id):
    """Return list of channel objects for the given group ID."""
    if not group_id:
        return []
    return [ch for ch in channels.get("channels", []) if ch.get("group") == group_id]


def build_proxy_url(channel_id):
    """Build the full proxy URL for a channel."""
    play_url = f"https://vavoo.to/vavoo-iptv/play/{channel_id}"
    return f"{WORKER_BASE}{PROXY_PATH}?url={play_url}"


def get_epg_id(channel_name, epg_data):
    """
    Find EPG ID for a channel name using fuzzy matching.
    Returns epg_id or None.
    """
    if not epg_data or not channel_name:
        return None
    
    # Clean channel name
    clean_name = re.sub(r"\s*\(.*?\)\s*", "", channel_name).strip()
    
    # Try exact match (case-insensitive)
    name_lower = clean_name.lower()
    if name_lower in epg_data:
        return epg_data[name_lower]
    
    # Try without special characters
    name_clean = re.sub(r"[^\w\s]", "", clean_name).lower()
    if name_clean in epg_data:
        return epg_data[name_clean]
    
    # Try fuzzy matching
    if len(name_clean) >= 3:
        matches = get_close_matches(name_clean, epg_data.keys(), n=1, cutoff=0.7)
        if matches:
            return epg_data[matches[0]]
    
    return None


def get_logo_url(channel_name, vavoo_logo):
    """
    Get logo URL from multiple sources.
    Priority: Vavoo > iptv-org > tvprofil
    """
    # 1. If Vavoo has a logo, use it (it's already a full URL)
    if vavoo_logo and vavoo_logo.startswith("http"):
        return vavoo_logo
    
    # 2. Try iptv-org (most reliable)
    clean_name = re.sub(r"[^a-zA-Z0-9]", "", channel_name).lower()
    if clean_name:
        iptv_url = f"https://iptv-org.github.io/iptv-org/logos/{clean_name}.png"
        # Note: We can't verify if it exists without making a request,
        # so we'll just return it and let the player handle it.
        return iptv_url
    
    # 3. Try tvprofil.net (fallback)
    encoded_name = quote(channel_name)
    return f"https://www.tvprofil.net/img/channels/{encoded_name}.png"


def generate_m3u(channels, group_name, epg_data):
    """Generate M3U playlist content with EPG IDs and logos."""
    lines = ["#EXTM3U"]
    for ch in channels:
        name = ch.get("name", "Unknown")
        vavoo_logo = ch.get("logo", "")
        ch_id = ch.get("id")
        if not ch_id:
            continue
        
        # Get EPG ID
        epg_id = get_epg_id(name, epg_data)
        
        # Get logo URL (from Vavoo or fallback)
        logo_url = get_logo_url(name, vavoo_logo)
        
        stream_url = build_proxy_url(ch_id)
        
        # Build EXTINF line
        tvg_id_attr = f' tvg-id="{epg_id}"' if epg_id else ""
        tvg_logo_attr = f' tvg-logo="{logo_url}"' if logo_url else ""
        extinf = f'#EXTINF:-1{tvg_id_attr}{tvg_logo_attr} group-title="{group_name}",{name}'
        
        lines.append(extinf)
        lines.append(stream_url)
    
    return "\n".join(lines)


def main():
    print(f"Fetching channels from Vavoo...", file=sys.stderr)
    data = fetch_channels()
    if not data:
        sys.exit(1)

    print(f"Fetching EPG data from {EPG_URL}...", file=sys.stderr)
    epg_data = fetch_epg_data()

    group_id = find_group_id(data, TARGET_GROUP)
    group_name = TARGET_GROUP
    if group_id is None:
        print(f"Group '{TARGET_GROUP}' not found, trying fallbacks...", file=sys.stderr)
        group_id, found_name = find_group_id_fallback(data)
        if group_id is None:
            print("No suitable group found. Available groups:", file=sys.stderr)
            for g in data.get("groups", []):
                print(f"  {g.get('name')}", file=sys.stderr)
            sys.exit(1)
        else:
            group_name = found_name
            print(f"Using fallback group: {group_name}", file=sys.stderr)

    print(f"Using group '{group_name}' (ID: {group_id})", file=sys.stderr)
    channel_list = get_channels_for_group(data, group_id)
    print(f"Found {len(channel_list)} channels.", file=sys.stderr)

    if not channel_list:
        print("No channels in this group.", file=sys.stderr)
        sys.exit(1)

    m3u_content = generate_m3u(channel_list, group_name, epg_data)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(m3u_content)

    print(f"Playlist written to {OUTPUT_FILE}", file=sys.stderr)
    print(f"  - Channels: {len(channel_list)}", file=sys.stderr)
    print(f"  - EPG mappings: {len(epg_data)}", file=sys.stderr)


if __name__ == "__main__":
    main()
