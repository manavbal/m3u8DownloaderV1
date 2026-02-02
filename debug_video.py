#!/usr/bin/env python3
"""
Debug script to see what Playwright finds on a lesson page.
Run this to diagnose video detection issues.
"""

import sys
import json
sys.path.insert(0, '.')

from dds_downloader.cookie_extractor import get_session_cookies

def main():
    # Get a lesson URL from user or use default
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = input("Enter a lesson URL to debug: ").strip()

    if not url:
        print("No URL provided")
        return

    print(f"\nDebug URL: {url}")
    print("-" * 60)

    # Get cookies
    print("Getting Chrome cookies...")
    cookies = get_session_cookies(url)
    if not cookies:
        print("ERROR: Could not get cookies from Chrome")
        return

    print(f"Got {len(cookies)} cookies")

    # Run the extractor with debug mode
    print("\nRunning Playwright to load the page...")
    print("(This may take 10-15 seconds)\n")

    from dds_downloader.wistia_extractor import extract_wistia_id
    result = extract_wistia_id(url, cookies, debug=True)

    print("=" * 60)
    print("RESULT:")
    print(json.dumps(result, indent=2))

    if result.get('debug'):
        debug_info = result['debug']
        print("\n" + "=" * 60)
        print("DEBUG INFO:")
        print(f"  Iframes found: {len(debug_info.get('iframes', []))}")
        for iframe in debug_info.get('iframes', []):
            print(f"    - {iframe[:100]}")
        print(f"  Video elements: {len(debug_info.get('videos', []))}")
        for vid in debug_info.get('videos', []):
            print(f"    - {vid[:100]}")
        print(f"  Wistia elements: {len(debug_info.get('wistiaElems', []))}")
        for elem in debug_info.get('wistiaElems', []):
            print(f"    - {elem}")
        print(f"  Wistia scripts: {len(debug_info.get('scripts', []))}")
        for script in debug_info.get('scripts', []):
            print(f"    - {script}")

    if result.get('debug_file'):
        print(f"\nFull HTML saved to: {result['debug_file']}")
        print("You can open this file to inspect what Playwright saw")

if __name__ == "__main__":
    main()
