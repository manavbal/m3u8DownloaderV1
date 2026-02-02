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


def extract_hotmart_video_via_network(page, context, iframe_src: str, debug: bool = False) -> dict:
    """Extract video URL from Hotmart player by intercepting network requests during playback."""
    captured_m3u8_urls = []
    captured_segment_urls = []

    def handle_request(request):
        """Capture video-related requests."""
        url = request.url
        if '.m3u8' in url:
            captured_m3u8_urls.append(url)
            if debug:
                print(f"DEBUG: [REQUEST] M3U8: {url[:120]}...", file=sys.stderr)
        elif '.ts' in url or '.mp4' in url:
            captured_segment_urls.append(url)
            if debug and len(captured_segment_urls) <= 3:
                print(f"DEBUG: [REQUEST] Segment: {url[:80]}...", file=sys.stderr)

    def handle_response(response):
        """Capture video-related responses."""
        url = response.url
        status = response.status
        if '.m3u8' in url:
            if debug:
                print(f"DEBUG: [RESPONSE] M3U8 (status={status}): {url[:120]}...", file=sys.stderr)
            if status == 200:
                captured_m3u8_urls.append(url)

    try:
        # Create a new page for the iframe to avoid conflicts
        iframe_page = context.new_page()

        # Set up request/response interception BEFORE navigation
        iframe_page.on('request', handle_request)
        iframe_page.on('response', handle_response)

        if debug:
            print(f"DEBUG: Navigating to Hotmart player iframe...", file=sys.stderr)

        # Navigate to the Hotmart player
        iframe_page.goto(iframe_src, wait_until='domcontentloaded', timeout=30000)

        # Wait for initial load
        time.sleep(2)

        if debug:
            print(f"DEBUG: Page loaded, attempting to trigger playback...", file=sys.stderr)

        # Try multiple methods to trigger video playback
        playback_triggered = False

        # Method 1: Click the big play button
        try:
            play_selectors = [
                'button.vjs-big-play-button',
                '.vjs-big-play-button',
                'button[aria-label="Play"]',
                'button[aria-label="Play Video"]',
                '.play-button',
                '[class*="play-button"]',
                '[class*="PlayButton"]',
                'button[class*="play"]',
                '.video-js .vjs-control-bar button',
            ]
            for selector in play_selectors:
                try:
                    elem = iframe_page.query_selector(selector)
                    if elem and elem.is_visible():
                        if debug:
                            print(f"DEBUG: Found play button: {selector}", file=sys.stderr)
                        elem.click()
                        playback_triggered = True
                        time.sleep(3)
                        break
                except:
                    continue
        except Exception as e:
            if debug:
                print(f"DEBUG: Play button click failed: {e}", file=sys.stderr)

        # Method 2: Click on the video element
        if not playback_triggered or not captured_m3u8_urls:
            try:
                video = iframe_page.query_selector('video')
                if video:
                    if debug:
                        print(f"DEBUG: Clicking video element...", file=sys.stderr)
                    video.click()
                    time.sleep(3)
            except:
                pass

        # Method 3: Use JavaScript to play
        if not captured_m3u8_urls:
            try:
                if debug:
                    print(f"DEBUG: Trying JavaScript play()...", file=sys.stderr)
                iframe_page.evaluate('''() => {
                    const video = document.querySelector('video');
                    if (video) {
                        video.muted = true;
                        video.play().catch(() => {});
                    }
                }''')
                time.sleep(3)
            except:
                pass

        # Method 4: Try to extract HLS source from video.js player
        if not captured_m3u8_urls:
            try:
                if debug:
                    print(f"DEBUG: Trying to get URL from player...", file=sys.stderr)
                player_src = iframe_page.evaluate('''() => {
                    // Try video.js
                    if (window.videojs) {
                        const players = videojs.getPlayers();
                        for (const id in players) {
                            const p = players[id];
                            if (p && p.tech_ && p.tech_.hls && p.tech_.hls.playlists) {
                                const master = p.tech_.hls.playlists.master;
                                if (master && master.uri) return master.uri;
                            }
                            if (p && p.currentSrc) {
                                const src = p.currentSrc();
                                if (src && src.includes('.m3u8')) return src;
                            }
                        }
                    }
                    // Try HLS.js
                    if (window.Hls) {
                        const videos = document.querySelectorAll('video');
                        for (const v of videos) {
                            if (v._hls && v._hls.url) return v._hls.url;
                        }
                    }
                    // Try video src directly
                    const video = document.querySelector('video');
                    if (video && video.src && video.src.includes('.m3u8')) {
                        return video.src;
                    }
                    return null;
                }''')
                if player_src:
                    if debug:
                        print(f"DEBUG: Got URL from player: {player_src[:80]}...", file=sys.stderr)
                    captured_m3u8_urls.append(player_src)
            except Exception as e:
                if debug:
                    print(f"DEBUG: Player source extraction failed: {e}", file=sys.stderr)

        # Method 5: Parse page content for M3U8 URLs with tokens
        if not captured_m3u8_urls:
            try:
                content = iframe_page.content()
                # Look for M3U8 URLs with authentication tokens
                patterns = [
                    r'"(https?://[^"]+\.m3u8\?[^"]+)"',
                    r"'(https?://[^']+\.m3u8\?[^']+)'",
                    r'src["\s]*[:=]["\s]*["\']?(https?://[^"\'>\s]+\.m3u8[^"\'>\s]*)',
                ]
                for pattern in patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        if 'master' in match.lower() or 'hdnts' in match or '?' in match:
                            if debug:
                                print(f"DEBUG: Found M3U8 in content: {match[:80]}...", file=sys.stderr)
                            captured_m3u8_urls.append(match)
            except:
                pass

        iframe_page.close()

        # Analyze captured URLs
        if debug:
            print(f"DEBUG: Total captured M3U8 URLs: {len(captured_m3u8_urls)}", file=sys.stderr)
            print(f"DEBUG: Total captured segments: {len(captured_segment_urls)}", file=sys.stderr)

        if captured_m3u8_urls:
            # Prefer URLs with authentication tokens
            for url in captured_m3u8_urls:
                if 'hdnts=' in url or 'token=' in url or 'Policy=' in url or 'Signature=' in url:
                    if debug:
                        print(f"DEBUG: Selected authenticated URL", file=sys.stderr)
                    return {"success": True, "video_url": url, "type": "hotmart"}

            # Prefer master playlist
            for url in captured_m3u8_urls:
                if 'master' in url.lower():
                    return {"success": True, "video_url": url, "type": "hotmart"}

            # Return first URL
            return {"success": True, "video_url": captured_m3u8_urls[0], "type": "hotmart"}

        return {"success": False, "error": "Could not capture video URL from network requests"}

    except Exception as e:
        if debug:
            print(f"DEBUG: Exception in hotmart extraction: {e}", file=sys.stderr)
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

            # Add cookies
            cookie_list = []
            for name, value in cookies.items():
                for domain in ['.ddssuccess.com', 'app.ddssuccess.com', '.hotmart.com', 'player.hotmart.com']:
                    cookie_list.append({
                        'name': name,
                        'value': value,
                        'domain': domain,
                        'path': '/'
                    })

            if cookie_list:
                context.add_cookies(cookie_list)

            # Open main page
            page = context.new_page()

            if debug:
                print(f"DEBUG: Loading main page: {url}", file=sys.stderr)

            page.goto(url, wait_until='networkidle', timeout=30000)
            time.sleep(3)

            # Find Hotmart iframe
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
                # Use network interception method for Hotmart
                result = extract_hotmart_video_via_network(page, context, hotmart_iframe, debug=debug)
                browser.close()
                if result.get('success'):
                    return result

            # Fall back to Wistia detection
            wistia_id = None

            # Check for Wistia in page
            try:
                content = page.content()
                patterns = [
                    r'wistia_async_([a-zA-Z0-9]+)',
                    r'wistia\.com/embed/medias/([a-zA-Z0-9]+)',
                    r'"hashedId"\s*:\s*"([a-zA-Z0-9]+)"',
                ]
                for pattern in patterns:
                    match = re.search(pattern, content)
                    if match:
                        wistia_id = match.group(1)
                        break
            except:
                pass

            browser.close()

            if wistia_id:
                return {"success": True, "video_id": wistia_id, "type": "wistia"}

            return {"success": False, "error": "No video found"}

    except Exception as e:
        if debug:
            print(f"DEBUG: Exception: {e}", file=sys.stderr)
        return {"success": False, "error": str(e)}


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
