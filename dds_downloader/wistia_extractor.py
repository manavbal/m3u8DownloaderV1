#!/usr/bin/env python3
"""
Wistia Video ID Extractor using Playwright.
This runs as a separate process to avoid threading issues with tkinter.

Usage: python3 wistia_extractor.py <url> <cookies_json>
Output: JSON with video_id or error
"""

import sys
import json
import re
import time


def extract_wistia_id(url: str, cookies: dict, debug: bool = False) -> dict:
    """Extract Wistia video ID from a page using Playwright."""
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

            # Wait longer for Wistia to load - it can be slow
            time.sleep(5)

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
                return {"success": False, "error": "No Wistia video found", "debug": video_info, "debug_file": "/tmp/playwright_debug.html"}

            browser.close()

            if wistia_id:
                return {"success": True, "video_id": wistia_id}
            else:
                return {"success": False, "error": "No Wistia video found"}

    except Exception as e:
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

    result = extract_wistia_id(url, cookies, debug=debug)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
