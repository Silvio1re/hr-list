#!/usr/bin/env python3
"""
Fetch Vavoo channels from a remote M3U list, filter for Croatia,
and generate an M3U playlist with EPG IDs and logos.
"""

import requests
import sys
import re
import xml.etree.ElementTree as ET
from difflib import get_close_matches
from urllib.parse import quote

# Configuration
SOURCE_M3U = "https://raw.githubusercontent.com/mr-evil1/VAVOO/main/vavoo_all.m3u"
WORKER_BASE = "https://hr-list.hallgrunt.workers.dev"
PROXY_PATH = "/manifest.m3u8"
OUTPUT_FILE = "vavoo_croatia.m3u"
EPG_URL = "https://iptv-epg.org/files/epg-hr.xml"

# Filter: only channels with group-title="Croatia"
TARGET_GROUP = "Croatia"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def fetch_m3u():
    """Download the remote M3U playlist."""
    try:
        resp = requests.get(SOURCE_M3U, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching M3U: {e}", file=sys.stderr)
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


def extract_group_title(extinf):
    """Extract group-title from EXTINF line."""
    match = re.search(r'group-title="([^"]+)"', extinf)
    return match.group(1) if match else None


def extract_tvg_id(extinf):
    """Extract tvg-id from EXTINF line."""
    match = re.search(r'tvg-id="([^"]+)"', extinf)
    return match.group(1) if match else None


def extract_tvg_logo(extinf):
    """Extract tvg-logo from EXTINF line."""
    match = re.search(r'tvg-logo="([^"]+)"', extinf)
    return match.group(1) if match else None


def extract_channel_name(extinf):
    """Extract channel name from EXTINF line (after the last comma)."""
    parts = extinf.split(",")
    return parts[-1].strip() if parts else "Unknown"


def parse_m3u(content):
    """Parse M3U and return list of (extinf, url) tuples."""
    entries = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF:"):
            extinf = line
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines) and lines[i].strip().startswith("http"):
                url = lines[i].strip()
                entries.append((extinf, url))
        i += 1
    return entries


def build_proxy_url(original_url):
    """Replace Vavoo URL with Cloudflare Worker proxy URL."""
    return f"{WORKER_BASE}{PROXY_PATH}?url={original_url}"


def get_epg_id(channel_name, epg_data):
    """Find EPG ID for a channel name using fuzzy matching."""
    if not epg_data or not channel_name:
        return None
    clean_name = re.sub(r"\s*\(.*?\)\s*", "", channel_name).strip()
    name_lower = clean_name.lower()
    if name_lower in epg_data:
        return epg_data[name_lower]
    name_clean = re.sub(r"[^\w\s]", "", clean_name).lower()
    if name_clean in epg_data:
        return epg_data[name_clean]
    if len(name_clean) >= 3:
        matches = get_close_matches(name_clean, epg_data.keys(), n=1, cutoff=0.7)
        if matches:
            return epg_data[matches[0]]
    return None


def get_logo_url(channel_name, existing_logo):
    """Get logo URL from multiple sources."""
    if existing_logo and existing_logo.startswith("http"):
        return existing_logo
    clean_name = re.sub(r"[^a-zA-Z0-9]", "", channel_name).lower()
    if clean_name:
        return f"https://iptv-org.github.io/iptv-org/logos/{clean_name}.png"
    encoded_name = quote(channel_name)
    return f"https://www.tvprofil.net/img/channels/{encoded_name}.png"


def generate_m3u(entries, epg_data):
    """Generate M3U content from filtered entries."""
    lines = ["#EXTM3U"]
    for extinf, url in entries:
        group = extract_group_title(extinf)
        # Only include channels with group-title="Croatia" (case-insensitive)
        if not group or group.lower() != "croatia":
            continue

        name = extract_channel_name(extinf)
        tvg_id = extract_tvg_id(extinf)
        logo = extract_tvg_logo(extinf)

        # If no tvg-id, try to find it from EPG
        if not tvg_id:
            tvg_id = get_epg_id(name, epg_data)

        # If no logo, try to find one
        if not logo:
            logo = get_logo_url(name, "")

        # Replace URL with worker proxy
        new_url = build_proxy_url(url)

        # Build new EXTINF line
        tvg_id_attr = f' tvg-id="{tvg_id}"' if tvg_id else ""
        tvg_logo_attr = f' tvg-logo="{logo}"' if logo else ""
        new_extinf = f'#EXTINF:-1{tvg_id_attr}{tvg_logo_attr} group-title="Croatia",{name}'

        lines.append(new_extinf)
        lines.append(new_url)

    return "\n".join(lines)


def main():
    print(f"Fetching M3U from {SOURCE_M3U}...", file=sys.stderr)
    content = fetch_m3u()
    if not content:
        sys.exit(1)

    print("Parsing entries...", file=sys.stderr)
    all_entries = parse_m3u(content)
    print(f"Total entries: {len(all_entries)}", file=sys.stderr)

    print(f"Fetching EPG data from {EPG_URL}...", file=sys.stderr)
    epg_data = fetch_epg_data()

    m3u_content = generate_m3u(all_entries, epg_data)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(m3u_content)

    print(f"Playlist written to {OUTPUT_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
