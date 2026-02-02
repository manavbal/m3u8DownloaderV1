#!/usr/bin/env python3
"""
Video Extractor using Playwright.
Supports: Wistia, Hotmart, and direct video URLs.
This runs as a separate process to avoid threading issues with tkinter.

IMPORTANT: For Hotmart, we intercept network requests to get the authenticated URL.

Usage: python3 wistia_extractor.py <url> <cookies_json> [--debug]
Output: JSON with video_url/video_id or error
"""

import sys
import json
import re
import time


def extract_hotmart_video(page, context, iframe_src: str, debug: bool = False) -> dict:
    """Extract video URL from Hotmart player by intercepting network requests."""
    captured_urls = []

    def handle_request(request):
        """Capture M3U8 requests."""
        url = request.url
        if '.m3u8' in url and 'master' in url.lower():
            captured_urls.append(url)
            if debug:
                print(f"DEBUG: Captured M3U8 URL: {url[:100]}...", file=sys.stderr)

    def handle_response(response):
        """Capture M3U8 responses."""
        url = response.url
        if '.m3u8' in url:
            captured_urls.append(url)
            if debug:
                print(f"DEBUG: Captured M3U8 response: {url[:100]}...", file=sys.stderr)

    try:
        # Set up request interception
        page.on('request', handle_request)
        page.on('response', handle_response)

        # Navigate to the Hotmart player page
        if debug:
            print(f"DEBUG: Navigating to iframe: {iframe_src}", file=sys.stderr)

        page.goto(iframe_src, wait_until='networkidle', timeout=45000)

        # Wait for video to potentially start loading
        time.sleep(3)

        # Try to click play button if video hasn't started
        try:
            play_button = page.query_selector('button[aria-label*="Play"], .play-button, .vjs-big-play-button, [class*="play"]')
            if play_button:
                play_button.click()
                time.sleep(3)  # Wait for video to start loading
        except:
            pass

        # Also try clicking on the video element itself
        try:
            video_elem = page.query_selector('video')
            if video_elem:
                video_elem.click()
                time.sleep(2)
        except:
            pass

        # Check if we captured any M3U8 URLs
        if captured_urls:
            # Prefer master playlist URLs
            for url in captured_urls:
                if 'master' in url.lower():
                    return {"success": True, "video_url": url, "type": "hotmart"}
            # Return first captured URL
            return {"success": True, "video_url": captured_urls[0], "type": "hotmart"}

        # Fallback: Look for video source in the player
        video_elem = page.query_selector('video')
        if video_elem:
            video_url = video_elem.get_attribute('src')
            if video_url and ('http' in video_url):
                return {"success": True, "video_url": video_url, "type": "hotmart"}

        # Fallback: Look for M3U8 URLs in page content
        content = page.content()

        m3u8_patterns = [
            r'"(https?://[^"]+\.m3u8\?[^"]+)"',  # M3U8 with query params
            r"'(https?://[^']+\.m3u8\?[^']+)'",
            r'"(https?://[^"]+\.m3u8[^"]*)"',
            r"'(https?://[^']+\.m3u8[^']*)'",
        ]

        for pattern in m3u8_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                # Prefer URLs with query parameters (authenticated)
                if '?' in match and 'Policy' in match:
                    return {"success": True, "video_url": match, "type": "hotmart"}
            for match in matches:
                if '?' in match:
                    return {"success": True, "video_url": match, "type": "hotmart"}

        # Method: Execute JavaScript to get player config
        try:
            player_data = page.evaluate('''() => {
                // Look for HLS.js instance
                if (window.Hls && window.Hls.DefaultConfig) {
                    const videos = document.querySelectorAll('video');
                    for (const video of videos) {
                        if (video.src) return video.src;
                    }
                }

                // Look for video.js player
                if (window.videojs) {
                    const players = window.videojs.getPlayers();
                    for (const id in players) {
                        const player = players[id];
                        if (player && player.src) {
                            const src = player.src();
                            if (src) return src;
                        }
                    }
                }

                // Look for any video source
                const video = document.querySelector('video');
                if (video) {
                    if (video.src) return video.src;
                    const source = video.querySelector('source');
                    if (source && source.src) return source.src;
                }

                // Look in network requests stored in window
                if (window.__PLAYER_CONFIG__) {
                    return JSON.stringify(window.__PLAYER_CONFIG__);
                }

                return null;
            }''')

            if player_data:
                if player_data.startswith('http'):
                    return {"success": True, "video_url": player_data, "type": "hotmart"}
                try:
                    data = json.loads(player_data)
                    data_str = json.dumps(data)
                    for pattern in m3u8_patterns:
                        match = re.search(pattern, data_str)
                        if match:
                            return {"success": True, "video_url": match.group(1), "type": "hotmart"}
                except:
                    pass
        except:
            pass

        if debug:
            print(f"DEBUG: No M3U8 found. Captured URLs: {captured_urls}", file=sys.stderr)

        return {"success": False, "error": "Could not extract Hotmart video URL - no authenticated M3U8 found"}

    except Exception as e:
        return {"success": False, "error": f"Hotmart extraction error: {str(e)}"}


def extract_video(url: str, cookies: dict, debug: bool = False) -> dict:
    """Extract video URL from a page using Playwright."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # Create context with cookies
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            # Add cookies - need to handle multiple domains
            cookie_list = []
            for name, value in cookies.items():
                # Add for both domains
                for domain in ['.ddssuccess.com', 'app.ddssuccess.com', '.hotmart.com', 'player.hotmart.com']:
                    cookie_list.append({
                        'name': name,
                        'value': value,
                        'domain': domain,
                        'path': '/'
                    })

            if cookie_list:
                context.add_cookies(cookie_list)

            # Set up request interception for the main page too
            captured_m3u8_urls = []

            def capture_request(request):
                if '.m3u8' in request.url:
                    captured_m3u8_urls.append(request.url)
                    if debug:
                        print(f"DEBUG: Main page captured: {request.url[:80]}...", file=sys.stderr)

            # Open page
            page = context.new_page()
            page.on('request', capture_request)

            if debug:
                print(f"DEBUG: Loading main page: {url}", file=sys.stderr)

            page.goto(url, wait_until='networkidle', timeout=30000)

            # Wait for video players to load
            time.sleep(5)

            # First, check for Hotmart player (this is what DDS Success uses)
            hotmart_iframe = None
            try:
                iframes = page.query_selector_all('iframe')
                for iframe in iframes:
                    src = iframe.get_attribute('src') or ''
                    if 'player.hotmart.com' in src:
                        hotmart_iframe = src
                        if debug:
                            print(f"DEBUG: Found Hotmart iframe: {src[:80]}...", file=sys.stderr)
                        break
            except:
                pass

            if hotmart_iframe:
                # Found Hotmart player - extract from it with network interception
                result = extract_hotmart_video(page, context, hotmart_iframe, debug=debug)
                browser.close()
                if result.get('success'):
                    return result
                # If Hotmart extraction failed, check if we captured URLs on main page
                if captured_m3u8_urls:
                    for url in captured_m3u8_urls:
                        if 'master' in url.lower() or '?' in url:
                            return {"success": True, "video_url": url, "type": "hotmart"}
                    return {"success": True, "video_url": captured_m3u8_urls[0], "type": "hotmart"}

            # Check for Wistia (keep existing Wistia logic)
            wistia_id = None

            # Method 1: Look for wistia_async_ class in the DOM
            try:
                wistia_elem = page.query_selector('[class*="wistia_async_"]')
                if wistia_elem:
                    class_attr = wistia_elem.get_attribute('class')
                    match = re.search(r'wistia_async_([a-zA-Z0-9]+)', class_attr)
                    if match:
                        wistia_id = match.group(1)
            except:
                pass

            # Method 2: Look for Wistia embed divs
            if not wistia_id:
                try:
                    wistia_embed = page.query_selector('[class*="wistia_embed"]')
                    if wistia_embed:
                        wistia_id_attr = wistia_embed.get_attribute('id')
                        if wistia_id_attr:
                            match = re.search(r'wistia_([a-zA-Z0-9]+)', wistia_id_attr)
                            if match:
                                wistia_id = match.group(1)
                        if not wistia_id:
                            class_attr = wistia_embed.get_attribute('class')
                            if class_attr:
                                match = re.search(r'wistia_async_([a-zA-Z0-9]+)', class_attr)
                                if match:
                                    wistia_id = match.group(1)
                except:
                    pass

            # Method 3: Look for data attributes
            if not wistia_id:
                try:
                    data_elem = page.query_selector('[data-wistia-id]')
                    if data_elem:
                        wistia_id = data_elem.get_attribute('data-wistia-id')
                except:
                    pass

            # Method 4: Execute JavaScript to get Wistia video data
            if not wistia_id:
                try:
                    wistia_id = page.evaluate('''() => {
                        if (window.Wistia && window.Wistia.api) {
                            const videos = window.Wistia.api.all();
                            if (videos && videos.length > 0) {
                                return videos[0].hashedId();
                            }
                        }
                        const elem = document.querySelector('[class*="wistia_async_"]');
                        if (elem) {
                            const match = elem.className.match(/wistia_async_([a-zA-Z0-9]+)/);
                            if (match) return match[1];
                        }
                        return null;
                    }''')
                except:
                    pass

            # Method 5: Check page content for Wistia patterns
            if not wistia_id:
                try:
                    content = page.content()
                    patterns = [
                        r'wistia_async_([a-zA-Z0-9]+)',
                        r'wistia\.com/embed/medias/([a-zA-Z0-9]+)',
                        r'"hashedId"\s*:\s*"([a-zA-Z0-9]+)"',
                        r'Wistia\.embed\(["\']([a-zA-Z0-9]+)["\']',
                    ]
                    for pattern in patterns:
                        match = re.search(pattern, content)
                        if match:
                            wistia_id = match.group(1)
                            break
                except:
                    pass

            # Method 6: Check for iframe with Wistia embed
            if not wistia_id:
                try:
                    iframes = page.query_selector_all('iframe')
                    for iframe in iframes:
                        src = iframe.get_attribute('src') or ''
                        if 'wistia' in src:
                            match = re.search(r'/medias/([a-zA-Z0-9]+)', src)
                            if match:
                                wistia_id = match.group(1)
                                break
                except:
                    pass

            browser.close()

            if wistia_id:
                return {"success": True, "video_id": wistia_id, "type": "wistia"}

            # Check captured URLs from main page
            if captured_m3u8_urls:
                for url in captured_m3u8_urls:
                    if 'master' in url.lower() or '?' in url:
                        return {"success": True, "video_url": url, "type": "hotmart"}
                return {"success": True, "video_url": captured_m3u8_urls[0], "type": "unknown"}

            return {"success": False, "error": "No video found"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# Keep old function name for backwards compatibility
def extract_wistia_id(url: str, cookies: dict, debug: bool = False) -> dict:
    """Backwards compatible wrapper."""
    return extract_video(url, cookies, debug)


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"success": False, "error": "Usage: wistia_extractor.py <url> <cookies_json> [--debug]"}))
        sys.exit(1)

    url = sys.argv[1]
    cookies_json = sys.argv[2]
    debug = "--debug" in sys.argv

    try:
        cookies = json.loads(cookies_json)
    except json.JSONDecodeError as e:
        print(json.dumps({"success": False, "error": f"Invalid cookies JSON: {e}"}))
        sys.exit(1)

    result = extract_video(url, cookies, debug=debug)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
