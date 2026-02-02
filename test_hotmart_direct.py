#!/usr/bin/env python3
"""
Direct Hotmart video URL extraction test.
This script opens the player, starts playback, and captures the authenticated M3U8 URL.

Usage: python3 test_hotmart_direct.py
"""

import json
import time
import sys
import subprocess
import os

# Add dds_downloader to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def get_cookies():
    """Get cookies from Chrome."""
    from dds_downloader.cookie_extractor import get_session_cookies
    return get_session_cookies("https://app.ddssuccess.com")

def extract_video_url(lesson_url: str, cookies: dict):
    """Extract authenticated video URL using Playwright with proper network capture."""
    from playwright.sync_api import sync_playwright

    captured_urls = []

    print("\n[1] Starting Playwright browser...")

    with sync_playwright() as p:
        # Launch browser (try headed mode to see what's happening)
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )

        # Add cookies
        cookie_list = []
        for name, value in cookies.items():
            for domain in ['.ddssuccess.com', 'app.ddssuccess.com', '.hotmart.com', 'player.hotmart.com']:
                cookie_list.append({'name': name, 'value': value, 'domain': domain, 'path': '/'})
        context.add_cookies(cookie_list)

        print("[2] Loading course page...")
        page = context.new_page()
        page.goto(lesson_url, wait_until='networkidle', timeout=30000)
        time.sleep(2)

        # Find Hotmart iframe
        print("[3] Looking for Hotmart player iframe...")
        iframe_src = None
        iframes = page.query_selector_all('iframe')
        for iframe in iframes:
            src = iframe.get_attribute('src') or ''
            if 'player.hotmart.com' in src:
                iframe_src = src
                print(f"    Found iframe: {src[:80]}...")
                break

        if not iframe_src:
            print("    ERROR: No Hotmart iframe found!")
            browser.close()
            return None

        # Create new page for iframe with network interception
        print("[4] Setting up network interception...")
        iframe_page = context.new_page()

        def on_request(request):
            url = request.url
            if '.m3u8' in url:
                print(f"    [NETWORK] M3U8 request: {url[:100]}...")
                captured_urls.append(('request', url))

        def on_response(response):
            url = response.url
            status = response.status
            if '.m3u8' in url:
                print(f"    [NETWORK] M3U8 response (status={status}): {url[:100]}...")
                if status == 200:
                    captured_urls.append(('response_ok', url))
                else:
                    captured_urls.append(('response_fail', url))

        iframe_page.on('request', on_request)
        iframe_page.on('response', on_response)

        print("[5] Navigating to Hotmart player...")
        iframe_page.goto(iframe_src, wait_until='domcontentloaded', timeout=30000)
        time.sleep(3)

        print("[6] Attempting to trigger video playback...")

        # Method 1: Click play button
        play_clicked = False
        play_selectors = [
            '.vjs-big-play-button',
            'button.vjs-big-play-button',
            '[class*="play-button"]',
            'button[aria-label*="Play"]',
        ]
        for selector in play_selectors:
            try:
                btn = iframe_page.query_selector(selector)
                if btn and btn.is_visible():
                    print(f"    Clicking: {selector}")
                    btn.click()
                    play_clicked = True
                    time.sleep(4)
                    break
            except Exception as e:
                pass

        if not play_clicked:
            print("    No play button found, trying video click...")
            try:
                video = iframe_page.query_selector('video')
                if video:
                    video.click()
                    time.sleep(3)
            except:
                pass

        # Method 2: JavaScript play
        if not captured_urls:
            print("    Trying JavaScript play()...")
            try:
                iframe_page.evaluate('''() => {
                    const video = document.querySelector('video');
                    if (video) {
                        video.muted = true;
                        video.play();
                    }
                }''')
                time.sleep(4)
            except:
                pass

        # Method 3: Get URL from player object
        print("[7] Checking for captured URLs and player state...")

        try:
            player_info = iframe_page.evaluate('''() => {
                const info = { sources: [], videoSrc: null, hlsUrl: null };

                // Check video element
                const video = document.querySelector('video');
                if (video) {
                    info.videoSrc = video.src || video.currentSrc;

                    // Check for HLS.js attached to video
                    if (video.hls) info.hlsUrl = video.hls.url;
                    if (video._hls) info.hlsUrl = video._hls.url;
                }

                // Check video.js player
                if (window.videojs) {
                    try {
                        const players = videojs.getPlayers();
                        for (const id in players) {
                            const p = players[id];
                            if (p) {
                                if (p.currentSrc) info.sources.push(p.currentSrc());
                                if (p.tech_ && p.tech_.vhs) {
                                    const vhs = p.tech_.vhs;
                                    if (vhs.playlists && vhs.playlists.master) {
                                        info.hlsUrl = vhs.playlists.master.uri;
                                    }
                                }
                            }
                        }
                    } catch(e) {}
                }

                return info;
            }''')
            print(f"    Player info: {player_info}")

            if player_info.get('hlsUrl'):
                captured_urls.append(('player', player_info['hlsUrl']))
            if player_info.get('videoSrc') and '.m3u8' in str(player_info.get('videoSrc', '')):
                captured_urls.append(('video_src', player_info['videoSrc']))

        except Exception as e:
            print(f"    Error getting player info: {e}")

        # Wait a bit more for any delayed requests
        print("[8] Waiting for additional network activity...")
        time.sleep(3)

        iframe_page.close()
        browser.close()

    print(f"\n[9] Analysis of captured URLs:")
    print(f"    Total captured: {len(captured_urls)}")

    if not captured_urls:
        print("    ERROR: No M3U8 URLs were captured!")
        print("    The video player might not be loading or playback didn't trigger.")
        return None

    # Find best URL (prefer response_ok, then request with auth tokens)
    best_url = None
    for source, url in captured_urls:
        print(f"    - [{source}] {url[:80]}...")
        if source == 'response_ok':
            best_url = url
            break
        elif 'hdnts=' in url and not best_url:
            best_url = url

    if not best_url and captured_urls:
        best_url = captured_urls[0][1]

    return best_url

def test_url_with_curl(url: str, cookies: dict):
    """Test if URL is accessible."""
    print(f"\n[10] Testing URL with curl...")

    cookie_str = '; '.join([f'{k}={v}' for k, v in cookies.items()])

    cmd = [
        'curl', '-s', '-I', '-w', '%{http_code}',
        '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        '-H', 'Referer: https://player.hotmart.com/',
        '-H', 'Origin: https://player.hotmart.com',
        '-H', f'Cookie: {cookie_str}',
        url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    status = result.stdout.strip().split('\n')[-1]

    print(f"    HTTP Status: {status}")
    return status == '200'

def download_with_ffmpeg(url: str, cookies: dict, output: str = "test_video.mp4"):
    """Try to download with FFmpeg."""
    print(f"\n[11] Attempting FFmpeg download (10 seconds)...")

    cookie_str = '; '.join([f'{k}={v}' for k, v in cookies.items()])

    headers = '\r\n'.join([
        f'Cookie: {cookie_str}',
        'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer: https://player.hotmart.com/',
        'Origin: https://player.hotmart.com',
    ]) + '\r\n'

    cmd = [
        'ffmpeg', '-y',
        '-headers', headers,
        '-i', url,
        '-c', 'copy',
        '-t', '10',
        output
    ]

    print(f"    Running FFmpeg...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode == 0 and os.path.exists(output):
        size = os.path.getsize(output)
        print(f"    SUCCESS! Downloaded {size/1024:.1f} KB")
        return True
    else:
        print(f"    FAILED!")
        # Show error
        if result.stderr:
            for line in result.stderr.split('\n')[-5:]:
                if line.strip():
                    print(f"      {line}")
        return False

def main():
    print("=" * 60)
    print(" Hotmart Direct Video Download Test")
    print("=" * 60)

    TEST_URL = "https://app.ddssuccess.com/courses/art-of-scheduling-productively/lectures/42201128"

    # Get cookies
    print("\nGetting cookies from Chrome...")
    cookies = get_cookies()
    if not cookies:
        print("ERROR: Could not get cookies. Make sure you're logged in.")
        return
    print(f"Got {len(cookies)} cookies")

    # Extract video URL
    video_url = extract_video_url(TEST_URL, cookies)

    if not video_url:
        print("\n" + "=" * 60)
        print(" FAILED: Could not extract video URL")
        print("=" * 60)
        return

    print(f"\n    Best URL found: {video_url[:100]}...")

    # Test accessibility
    accessible = test_url_with_curl(video_url, cookies)

    if not accessible:
        print("\n" + "=" * 60)
        print(" FAILED: URL is not accessible (403)")
        print(" The Akamai token might be expired or IP-bound")
        print("=" * 60)
        return

    # Try download
    success = download_with_ffmpeg(video_url, cookies)

    if success:
        print("\n" + "=" * 60)
        print(" SUCCESS! Video download works!")
        print(" Output: test_video.mp4")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print(" FAILED: FFmpeg could not download")
        print("=" * 60)

if __name__ == "__main__":
    main()
