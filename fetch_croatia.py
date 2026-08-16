#!/usr/bin/env python3
"""
Fetch Vavoo channels from a remote M3U list and filter for Croatian channels.
The resulting playlist uses the Cloudflare Worker as a proxy.
"""

import requests
import sys
import re
import argparse
from urllib.parse import urlparse

# Default remote M3U source
DEFAULT_SOURCE = "https://raw.githubusercontent.com/mr-evil1/VAVOO/main/vavoo_all.m3u"

# Cloudflare Worker endpoint
WORKER_BASE = "https://hr-list.hallgrunt.workers.dev"
PROXY_PATH = "/manifest.m3u8"

# Output filename
OUTPUT_FILE = "vavoo_croatia.m3u"

# Keywords for fallback filtering (if group-title is not exactly "Croatia")
FALLBACK_KEYWORDS = ["croatia", "hrvatska", "hr "]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def fetch_remote_m3u(url):
    """Download M3U content from the given URL."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching remote M3U: {e}", file=sys.stderr)
        return None


def parse_m3u(content):
    """
    Parse M3U content and return a list of tuples (extinf, url).
    Handles multiline EXTINF and ignores comments.
    """
    entries = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF:"):
            extinf = line
            i += 1
            # Skip empty lines
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                url = lines[i].strip()
                # Only take valid HTTP URLs
                if url.startswith("http"):
                    entries.append((extinf, url))
        i += 1
    return entries


def extract_group_title(extinf):
    """Extract group-title attribute from EXTINF line, or return None."""
    match = re.search(r'group-title="([^"]+)"', extinf, re.IGNORECASE)
    return match.group(1) if match else None


def is_croatian_channel(extinf, url):
    """
    Determine if a channel is Croatian.
    Priority: exact group-title match (case-insensitive) for "Croatia".
    If not, fallback to checking channel name and URL for keywords.
    """
    group = extract_group_title(extinf)
    if group and group.lower() == "croatia":
        return True

    # Fallback: search in EXTINF line and URL
    combined = (extinf + " " + url).lower()
    for kw in FALLBACK_KEYWORDS:
        if kw in combined:
            return True
    return False


def rewrite_url(url):
    """Replace the Vavoo stream URL with the Cloudflare Worker proxy URL."""
    # If it's already a worker URL, return as is
    if WORKER_BASE in url:
        return url
    return f"{WORKER_BASE}{PROXY_PATH}?url={url}"


def generate_m3u(entries):
    """Generate M3U content from filtered entries, removing duplicates."""
    seen_urls = set()
    lines = ["#EXTM3U"]
    for extinf, url in entries:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        new_url = rewrite_url(url)
        lines.append(extinf)
        lines.append(new_url)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate Croatian Vavoo M3U playlist using Cloudflare Worker proxy.")
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help="URL of the source M3U playlist (default: mr-evil1's list)")
    parser.add_argument("--output", "-o", default=OUTPUT_FILE,
                        help="Output file name (default: vavoo_croatia.m3u)")
    args = parser.parse_args()

    print(f"Fetching M3U from: {args.source}", file=sys.stderr)
    content = fetch_remote_m3u(args.source)
    if not content:
        sys.exit(1)

    print("Parsing entries...", file=sys.stderr)
    all_entries = parse_m3u(content)
    print(f"Total entries: {len(all_entries)}", file=sys.stderr)

    # Filter Croatian channels
    cro_entries = [e for e in all_entries if is_croatian_channel(e[0], e[1])]
    print(f"Croatian channels found: {len(cro_entries)}", file=sys.stderr)

    if not cro_entries:
        print("No Croatian channels found. Please check the source or adjust keywords.", file=sys.stderr)
        # Show sample groups for debugging
        groups = set()
        for extinf, _ in all_entries[:200]:
            g = extract_group_title(extinf)
            if g:
                groups.add(g)
        if groups:
            print("Sample group titles found in source:", file=sys.stderr)
            for g in sorted(groups)[:15]:
                print(f"  - {g}", file=sys.stderr)
        sys.exit(1)

    m3u_content = generate_m3u(cro_entries)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(m3u_content)

    print(f"Playlist written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
