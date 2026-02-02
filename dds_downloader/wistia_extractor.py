#!/usr/bin/env python3
"""
Video Extractor using Playwright.
Supports: Wistia, Hotmart, and direct video URLs.
This runs as a separate process to avoid threading issues with tkinter.

Usage: python3 wistia_extractor.py <url> <cookies_json> [--debug]
Output: JSON with video_url/video_id or error
"""

import sys
import json
import re
import time


def extract_hotmart_video(page, iframe_src: str) -> dict:
    """Extract video URL from Hotmart player iframe."""
    try:
        # Navigate to the Hotmart player page directly
        page.goto(iframe_src, wait_until='networkidle', timeout=30000)
        time.sleep(3)

        # Method 1: Look for video source in the player
        video_url = None

        # Try to find the video element
        video_elem = page.query_selector('video')
        if video_elem:
            video_url = video_elem.get_attribute('src')
            if video_url:
                return {"success": True, "video_url": video_url, "type": "hotmart"}

        # Method 2: Look for HLS source in page content
        content = page.content()

        # Look for m3u8 URLs in the page
        m3u8_patterns = [
            r'"(https?://[^"]+\.m3u8[^"]*)"',
            r"'(https?://[^']+\.m3u8[^']*)'",
            r'src:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
            r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
            r'source:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        ]

        for pattern in m3u8_patterns:
            match = re.search(pattern, content)
            if match:
                video_url = match.group(1)
                return {"success": True, "video_url": video_url, "type": "hotmart"}

        # Method 3: Look for MP4 URLs
        mp4_patterns = [
            r'"(https?://[^"]+\.mp4[^"]*)"',
            r"'(https?://[^']+\.mp4[^']*)'",
        ]

        for pattern in mp4_patterns:
            match = re.search(pattern, content)
            if match:
                video_url = match.group(1)
                # Filter out small files (likely thumbnails)
                if 'thumb' not in video_url.lower() and 'preview' not in video_url.lower():
                    return {"success": True, "video_url": video_url, "type": "hotmart_mp4"}

        # Method 4: Execute JavaScript to get player config
        try:
            player_data = page.evaluate('''() => {
                // Look for common video player configurations
                if (window.playerConfig) return JSON.stringify(window.playerConfig);
                if (window.videoConfig) return JSON.stringify(window.videoConfig);
                if (window.player && window.player.getConfig) return JSON.stringify(window.player.getConfig());

                // Look for video sources in the DOM
                const videos = document.querySelectorAll('video source');
                const sources = [];
                videos.forEach(v => sources.push(v.src));
                if (sources.length > 0) return JSON.stringify({sources: sources});

                return null;
            }''')
            if player_data:
                try:
                    data = json.loads(player_data)
                    # Look for URLs in the data
                    data_str = json.dumps(data)
                    for pattern in m3u8_patterns + mp4_patterns:
                        match = re.search(pattern, data_str)
                        if match:
                            return {"success": True, "video_url": match.group(1), "type": "hotmart"}
                except:
                    pass
        except:
            pass

        return {"success": False, "error": "Could not extract Hotmart video URL"}

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
                for domain in ['.ddssuccess.com', 'app.ddssuccess.com']:
                    cookie_list.append({
                        'name': name,
                        'value': value,
                        'domain': domain,
                        'path': '/'
                    })

            if cookie_list:
                context.add_cookies(cookie_list)

            # Open page
            page = context.new_page()
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
                        break
            except:
                pass

            if hotmart_iframe:
                # Found Hotmart player - extract from it
                result = extract_hotmart_video(page, hotmart_iframe)
                browser.close()
                if result.get('success'):
                    return result
                # If Hotmart extraction failed, continue to try other methods

            # Check for Wistia
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
                        // Try finding it in the DOM
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
                        r'wistia_responsive_padding.*?wistia_async_([a-zA-Z0-9]+)',
                        r'medias/([a-zA-Z0-9]+)\.jsonp',
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

            # Debug: save page content if no video found
            if not wistia_id and debug:
                content = page.content()
                with open('/tmp/playwright_debug.html', 'w') as f:
                    f.write(content)
                # Also check what video-related elements exist
                video_info = page.evaluate('''() => {
                    const info = {
                        iframes: [],
                        videos: [],
                        wistiaElems: [],
                        scripts: []
                    };
                    document.querySelectorAll('iframe').forEach(el => {
                        info.iframes.push(el.src || el.getAttribute('data-src') || 'no-src');
                    });
                    document.querySelectorAll('video').forEach(el => {
                        info.videos.push(el.src || 'no-src');
                    });
                    document.querySelectorAll('[class*="wistia"]').forEach(el => {
                        info.wistiaElems.push(el.className);
                    });
                    document.querySelectorAll('script[src*="wistia"]').forEach(el => {
                        info.scripts.push(el.src);
                    });
                    return info;
                }''')
                browser.close()
                return {"success": False, "error": "No video found", "debug": video_info, "debug_file": "/tmp/playwright_debug.html"}

            browser.close()

            if wistia_id:
                return {"success": True, "video_id": wistia_id, "type": "wistia"}
            else:
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
