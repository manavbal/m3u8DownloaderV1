#!/usr/bin/env python3
"""
Hotmart video extraction - interact with iframe INSIDE parent page.
The key is to NOT navigate to the iframe URL separately.

Usage: python3 test_hotmart_iframe.py
"""

import json
import time
import sys
import subprocess
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def get_cookies():
    from dds_downloader.cookie_extractor import get_session_cookies
    return get_session_cookies("https://app.ddssuccess.com")

def extract_video(lesson_url: str, cookies: dict):
    """Extract video URL by interacting with iframe INSIDE the parent page."""
    from playwright.sync_api import sync_playwright

    captured_urls = []

    print("\n[1] Starting browser...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # Visible for debugging
            slow_mo=300
        )

        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        # Add cookies for all relevant domains
        cookie_list = []
        for name, value in cookies.items():
            for domain in ['.ddssuccess.com', 'app.ddssuccess.com', '.hotmart.com', 'player.hotmart.com', '.play.hotmart.com']:
                cookie_list.append({'name': name, 'value': value, 'domain': domain, 'path': '/'})
        context.add_cookies(cookie_list)

        # Set up network interception on the context level (catches all pages/frames)
        def on_request(request):
            url = request.url
            if '.m3u8' in url:
                print(f"    [NETWORK] M3U8 REQUEST: {url[:100]}...")
                captured_urls.append(('request', url))

        def on_response(response):
            url = response.url
            if '.m3u8' in url:
                status = response.status
                print(f"    [NETWORK] M3U8 RESPONSE ({status}): {url[:100]}...")
                if status == 200:
                    captured_urls.append(('response', url))

        page = context.new_page()
        page.on('request', on_request)
        page.on('response', on_response)

        print(f"[2] Loading course page: {lesson_url[:60]}...")
        page.goto(lesson_url, wait_until='networkidle', timeout=60000)

        print("[3] Waiting for page to fully load...")
        time.sleep(3)

        # Find the Hotmart iframe and interact with it IN CONTEXT
        print("[4] Looking for Hotmart player iframe...")

        # Get all frames
        frames = page.frames
        print(f"    Found {len(frames)} frames")

        hotmart_frame = None
        for frame in frames:
            frame_url = frame.url
            if 'player.hotmart.com' in frame_url:
                hotmart_frame = frame
                print(f"    Found Hotmart frame: {frame_url[:80]}...")
                break

        if not hotmart_frame:
            print("    No Hotmart frame found!")
            # Try to find iframe element and get its frame
            iframe_elem = page.query_selector('iframe[src*="player.hotmart.com"]')
            if iframe_elem:
                hotmart_frame = iframe_elem.content_frame()
                print(f"    Got frame from iframe element")

        if not hotmart_frame:
            print("    ERROR: Could not access Hotmart frame!")
            input("Press Enter to close...")
            browser.close()
            return None

        print("[5] Inspecting Hotmart frame content...")
        time.sleep(2)

        # Check frame content
        try:
            frame_content = hotmart_frame.evaluate('''() => {
                return {
                    title: document.title,
                    body: document.body ? document.body.innerText.slice(0, 500) : 'no body',
                    videoCount: document.querySelectorAll('video').length,
                    buttonCount: document.querySelectorAll('button').length,
                    hasError: document.body ? document.body.innerText.includes('went wrong') : false
                };
            }''')
            print(f"    Frame title: {frame_content['title']}")
            print(f"    Videos: {frame_content['videoCount']}, Buttons: {frame_content['buttonCount']}")
            print(f"    Has error: {frame_content['hasError']}")
            if frame_content['hasError']:
                print(f"    Body text: {frame_content['body'][:200]}...")
        except Exception as e:
            print(f"    Error inspecting frame: {e}")

        print("[6] Waiting for video player to initialize...")
        time.sleep(3)

        # Try to find and click play button in the frame
        print("[7] Looking for play button in frame...")

        try:
            # Wait for video element
            hotmart_frame.wait_for_selector('video', timeout=10000)
            print("    Video element found!")

            # Get video info
            video_info = hotmart_frame.evaluate('''() => {
                const v = document.querySelector('video');
                return v ? {
                    src: v.src,
                    currentSrc: v.currentSrc,
                    paused: v.paused,
                    readyState: v.readyState
                } : null;
            }''')
            print(f"    Video info: {video_info}")

            # Try to click play
            play_btn = hotmart_frame.query_selector('.vjs-big-play-button, [class*="play-button"], button[aria-label*="Play"]')
            if play_btn:
                print("    Clicking play button...")
                play_btn.click()
                time.sleep(5)

        except Exception as e:
            print(f"    Error: {e}")

        # Try JavaScript play
        print("[8] Trying JavaScript play...")
        try:
            result = hotmart_frame.evaluate('''() => {
                const video = document.querySelector('video');
                if (video) {
                    video.muted = true;
                    video.play();
                    return 'play called';
                }
                return 'no video';
            }''')
            print(f"    Result: {result}")
            time.sleep(5)
        except Exception as e:
            print(f"    Error: {e}")

        print(f"\n[9] Captured URLs: {len(captured_urls)}")
        for source, url in captured_urls:
            print(f"    [{source}] {url[:100]}...")

        # If no URLs captured, check video src directly
        if not captured_urls:
            print("\n[10] Checking video src directly...")
            try:
                video_src = hotmart_frame.evaluate('''() => {
                    const v = document.querySelector('video');
                    return v ? (v.src || v.currentSrc) : null;
                }''')
                if video_src and '.m3u8' in str(video_src):
                    print(f"    Found video src: {video_src[:100]}...")
                    captured_urls.append(('direct', video_src))
                else:
                    print(f"    Video src: {video_src}")
            except Exception as e:
                print(f"    Error: {e}")

        print("\n" + "=" * 60)
        if captured_urls:
            best_url = None
            for source, url in captured_urls:
                if 'hdnts=' in url or source == 'response':
                    best_url = url
                    break
            if not best_url:
                best_url = captured_urls[0][1]

            print(f" SUCCESS! Captured URL:")
            print(f" {best_url}")
        else:
            print(" No URLs captured.")
            print(" The video might not be loading at all.")

        input("\nPress Enter to close browser...")
        browser.close()

        if captured_urls:
            return captured_urls[0][1]
        return None

def main():
    print("=" * 60)
    print(" Hotmart In-Frame Video Extraction Test")
    print("=" * 60)

    TEST_URL = "https://app.ddssuccess.com/courses/art-of-scheduling-productively/lectures/42201128"

    cookies = get_cookies()
    if not cookies:
        print("ERROR: Could not get cookies")
        return

    print(f"Got {len(cookies)} cookies")

    video_url = extract_video(TEST_URL, cookies)

    if video_url:
        print(f"\n\nExtracted URL: {video_url[:100]}...")

        # Quick test
        print("\nTesting URL...")
        cmd = ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}',
               '-H', 'Referer: https://player.hotmart.com/', video_url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        print(f"HTTP Status: {result.stdout}")

if __name__ == "__main__":
    main()
