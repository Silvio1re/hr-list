#!/usr/bin/env python3
"""
Fetch Vavoo channels for the 'Croatia' group and generate an M3U playlist
using the Cloudflare Worker as a proxy.
"""

import json
import requests
import sys

# Configuration
VAVOO_API = "https://www.vavoo.tv/api/channels"
WORKER_BASE = "https://hr-list.hallgrunt.workers.dev"
PROXY_PATH = "/manifest.m3u8"
OUTPUT_FILE = "vavoo_croatia.m3u"

# Group to fetch
TARGET_GROUP = "Croatia"
FALLBACK_GROUPS = ["Balkans", "Ex-YU", "Hrvatska", "Balkan"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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


def find_group_id(channels, group_name):
    """Find the group ID for a given group name (exact or case-insensitive)."""
    # Exact match first
    for group in channels.get("groups", []):
        if group.get("name") == group_name:
            return group.get("id")
    # Case-insensitive
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


def generate_m3u(channels, group_name):
    """Generate M3U playlist content."""
    lines = ["#EXTM3U"]
    for ch in channels:
        name = ch.get("name", "Unknown")
        logo = ch.get("logo", "")
        ch_id = ch.get("id")
        if not ch_id:
            continue
        stream_url = build_proxy_url(ch_id)
        extinf = f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group_name}",{name}'
        lines.append(extinf)
        lines.append(stream_url)
    return "\n".join(lines)


def main():
    print(f"Fetching channels from Vavoo...", file=sys.stderr)
    data = fetch_channels()
    if not data:
        sys.exit(1)

    # Try to find the target group
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

    m3u_content = generate_m3u(channel_list, group_name)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(m3u_content)

    print(f"Playlist written to {OUTPUT_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
