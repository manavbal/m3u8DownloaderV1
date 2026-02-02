#!/usr/bin/env python3
"""
Hotmart video extraction with VISIBLE browser.
This lets us see exactly what's happening.

Usage: python3 test_hotmart_visible.py
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

def extract_with_visible_browser(lesson_url: str, cookies: dict):
    """Extract video URL with visible browser to debug."""
    from playwright.sync_api import sync_playwright

    captured_urls = []

    print("\n[1] Starting VISIBLE browser (you should see a Chrome window)...")

    with sync_playwright() as p:
        # Launch browser in HEADED mode (visible)
        browser = p.chromium.launch(
            headless=False,  # VISIBLE!
            slow_mo=500  # Slow down actions so we can see them
        )

        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        # Add cookies
        cookie_list = []
        for name, value in cookies.items():
            for domain in ['.ddssuccess.com', 'app.ddssuccess.com', '.hotmart.com', 'player.hotmart.com']:
                cookie_list.append({'name': name, 'value': value, 'domain': domain, 'path': '/'})
        context.add_cookies(cookie_list)

        print("[2] Loading course page (watch the browser)...")
        page = context.new_page()
        page.goto(lesson_url, wait_until='networkidle', timeout=60000)

        print("[3] Page loaded. Looking for Hotmart iframe...")
        time.sleep(2)

        # Find iframe
        iframe_src = None
        iframes = page.query_selector_all('iframe')
        print(f"    Found {len(iframes)} iframes on page")

        for i, iframe in enumerate(iframes):
            src = iframe.get_attribute('src') or ''
            print(f"    iframe[{i}]: {src[:80]}...")
            if 'player.hotmart.com' in src:
                iframe_src = src
                print(f"    ^ This is the Hotmart player!")

        if not iframe_src:
            print("    ERROR: No Hotmart iframe found!")
            input("Press Enter to close browser...")
            browser.close()
            return None

        print(f"\n[4] Creating new page for iframe with network capture...")

        # Set up network interception on new page
        iframe_page = context.new_page()

        def on_request(request):
            url = request.url
            if '.m3u8' in url:
                print(f"    >>> CAPTURED M3U8: {url[:100]}...")
                captured_urls.append(url)
            elif '.ts' in url and len(captured_urls) < 3:
                print(f"    >>> CAPTURED segment: {url[:60]}...")

        def on_response(response):
            if '.m3u8' in response.url:
                print(f"    <<< M3U8 RESPONSE (status={response.status}): {response.url[:80]}...")
                if response.status == 200:
                    captured_urls.append(response.url)

        iframe_page.on('request', on_request)
        iframe_page.on('response', on_response)

        print(f"[5] Navigating to Hotmart player iframe...")
        iframe_page.goto(iframe_src, wait_until='networkidle', timeout=60000)

        print("[6] Iframe loaded. Inspecting page structure...")
        time.sleep(2)

        # Dump page structure
        page_info = iframe_page.evaluate('''() => {
            const info = {
                title: document.title,
                videos: [],
                buttons: [],
                divs_with_play: []
            };

            // Find all video elements
            document.querySelectorAll('video').forEach((v, i) => {
                info.videos.push({
                    index: i,
                    src: v.src || 'none',
                    currentSrc: v.currentSrc || 'none',
                    paused: v.paused,
                    readyState: v.readyState
                });
            });

            // Find all buttons
            document.querySelectorAll('button').forEach((b, i) => {
                info.buttons.push({
                    index: i,
                    className: b.className,
                    ariaLabel: b.getAttribute('aria-label'),
                    text: b.textContent.slice(0, 50)
                });
            });

            // Find divs with 'play' in class
            document.querySelectorAll('[class*="play"]').forEach((el, i) => {
                info.divs_with_play.push({
                    tag: el.tagName,
                    className: el.className,
                    visible: el.offsetParent !== null
                });
            });

            return info;
        }''')

        print(f"\n    Page title: {page_info['title']}")
        print(f"    Videos found: {len(page_info['videos'])}")
        for v in page_info['videos']:
            print(f"      - Video {v['index']}: src={v['src'][:50] if v['src'] else 'none'}... paused={v['paused']}")

        print(f"    Buttons found: {len(page_info['buttons'])}")
        for b in page_info['buttons'][:5]:  # First 5
            print(f"      - {b['className'][:40]} | aria={b['ariaLabel']}")

        print(f"    Elements with 'play' class: {len(page_info['divs_with_play'])}")
        for p in page_info['divs_with_play'][:5]:
            print(f"      - <{p['tag']}> class='{p['className'][:40]}' visible={p['visible']}")

        print("\n[7] Attempting to click play button...")

        # Try to click on video or play button
        clicked = False

        # First try: vjs-big-play-button (video.js)
        try:
            btn = iframe_page.query_selector('.vjs-big-play-button')
            if btn:
                print("    Found .vjs-big-play-button, clicking...")
                btn.click()
                clicked = True
                time.sleep(3)
        except Exception as e:
            print(f"    vjs-big-play-button error: {e}")

        # Second try: any visible play element
        if not clicked:
            for elem_info in page_info['divs_with_play']:
                if elem_info['visible']:
                    try:
                        elem = iframe_page.query_selector(f".{elem_info['className'].split()[0]}")
                        if elem:
                            print(f"    Clicking {elem_info['className'][:30]}...")
                            elem.click()
                            clicked = True
                            time.sleep(3)
                            break
                    except:
                        pass

        # Third try: click video element
        if not clicked:
            try:
                video = iframe_page.query_selector('video')
                if video:
                    print("    Clicking video element...")
                    video.click()
                    time.sleep(3)
            except:
                pass

        # Fourth try: JavaScript play
        print("[8] Trying JavaScript play()...")
        try:
            iframe_page.evaluate('''() => {
                const video = document.querySelector('video');
                if (video) {
                    video.muted = true;
                    return video.play().then(() => 'playing').catch(e => e.message);
                }
                return 'no video';
            }''')
            time.sleep(5)
        except Exception as e:
            print(f"    JS play error: {e}")

        print("\n[9] Checking player state after interactions...")
        time.sleep(2)

        final_info = iframe_page.evaluate('''() => {
            const video = document.querySelector('video');
            if (!video) return { hasVideo: false };

            return {
                hasVideo: true,
                src: video.src,
                currentSrc: video.currentSrc,
                paused: video.paused,
                currentTime: video.currentTime,
                duration: video.duration,
                readyState: video.readyState,
                networkState: video.networkState
            };
        }''')

        print(f"    Final video state: {json.dumps(final_info, indent=2)}")

        print(f"\n[10] Total captured M3U8 URLs: {len(captured_urls)}")
        for url in captured_urls:
            print(f"    - {url[:100]}...")

        # Keep browser open so user can see
        print("\n" + "=" * 60)
        if captured_urls:
            print(" URLs were captured! Check above for the M3U8 URL.")
            best_url = captured_urls[0]
            print(f"\n Best URL: {best_url}")
        else:
            print(" No URLs captured. The video might need manual interaction.")
            print(" Try clicking the play button manually in the browser.")

        input("\nPress Enter to close browser and continue...")

        # If user manually played, check again
        if not captured_urls:
            final_urls = iframe_page.evaluate('''() => {
                const video = document.querySelector('video');
                return video ? (video.src || video.currentSrc) : null;
            }''')
            if final_urls and '.m3u8' in str(final_urls):
                captured_urls.append(final_urls)
                print(f"Found URL after manual play: {final_urls[:80]}...")

        iframe_page.close()
        browser.close()

        return captured_urls[0] if captured_urls else None

def main():
    print("=" * 60)
    print(" Hotmart VISIBLE Browser Test")
    print(" (A Chrome window will open - watch what happens)")
    print("=" * 60)

    TEST_URL = "https://app.ddssuccess.com/courses/art-of-scheduling-productively/lectures/42201128"

    cookies = get_cookies()
    if not cookies:
        print("ERROR: Could not get cookies")
        return

    print(f"Got {len(cookies)} cookies")

    video_url = extract_with_visible_browser(TEST_URL, cookies)

    if video_url:
        print(f"\n\nFinal URL: {video_url}")

        # Test the URL
        print("\nTesting URL accessibility...")
        cookie_str = '; '.join([f'{k}={v}' for k, v in cookies.items()])
        cmd = ['curl', '-s', '-I', '-w', '%{http_code}',
               '-H', f'Cookie: {cookie_str}',
               '-H', 'Referer: https://player.hotmart.com/',
               video_url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        status = result.stdout.strip().split('\n')[-1]
        print(f"HTTP Status: {status}")

        if status == '200':
            print("\n SUCCESS! URL is accessible!")
            print(f"\nTo download, run:")
            print(f'ffmpeg -headers "Referer: https://player.hotmart.com/\\r\\n" -i "{video_url}" -c copy test_video.mp4')
    else:
        print("\n\nFailed to get video URL")

if __name__ == "__main__":
    main()
