#!/usr/bin/env python3
"""
Comprehensive test script for Hotmart video downloading.
Tests each step of the process and shows detailed output.

Run with: python3 test_full_flow.py <course_page_url>
Example: python3 test_full_flow.py "https://app.ddssuccess.com/courses/art-of-scheduling-productively/lectures/42201128"
"""

import sys
import os
import json
import subprocess
import time
import re

# Add the dds_downloader directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

def print_header(title):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)

def print_step(step_num, description):
    print(f"\n[Step {step_num}] {description}")
    print("-" * 50)

def test_cookies():
    """Test cookie extraction."""
    print_step(1, "Extracting cookies from Chrome")

    try:
        from dds_downloader.cookie_extractor import get_session_cookies

        cookies = get_session_cookies("https://app.ddssuccess.com")

        if cookies:
            print(f"✓ Found {len(cookies)} cookies")
            # Show some cookie names (not values for security)
            cookie_names = list(cookies.keys())[:5]
            print(f"  Sample cookie names: {cookie_names}")
            return cookies
        else:
            print("✗ No cookies found")
            print("  Make sure you're logged into the course website in Chrome")
            return None
    except Exception as e:
        print(f"✗ Error: {e}")
        return None

def test_playwright_extractor(url, cookies):
    """Test the Playwright video extractor with debug output."""
    print_step(2, "Running Playwright extractor (with debug)")

    extractor_path = os.path.join(script_dir, 'dds_downloader', 'wistia_extractor.py')

    if not os.path.exists(extractor_path):
        print(f"✗ Extractor not found: {extractor_path}")
        return None

    cookies_json = json.dumps(cookies)

    print(f"  Running: python3 wistia_extractor.py <url> <cookies> --debug")
    print(f"  URL: {url[:60]}...")

    try:
        result = subprocess.run(
            [sys.executable, extractor_path, url, cookies_json, '--debug'],
            capture_output=True,
            text=True,
            timeout=120
        )

        # Show stderr (debug output)
        if result.stderr:
            print("\n  Debug output:")
            for line in result.stderr.strip().split('\n')[-20:]:  # Last 20 lines
                print(f"    {line}")

        # Parse result
        if result.returncode == 0 and result.stdout:
            try:
                data = json.loads(result.stdout.strip())
                if data.get('success'):
                    video_url = data.get('video_url', data.get('video_id', 'N/A'))
                    video_type = data.get('type', 'unknown')
                    print(f"\n✓ Extraction successful!")
                    print(f"  Type: {video_type}")
                    print(f"  URL/ID: {video_url[:100]}..." if len(str(video_url)) > 100 else f"  URL/ID: {video_url}")

                    # Check if URL has authentication tokens
                    if '?' in str(video_url):
                        params = video_url.split('?')[1] if '?' in video_url else ''
                        print(f"  Has query params: Yes")
                        if 'Policy' in params or 'Signature' in params or 'Key-Pair-Id' in params:
                            print(f"  Has auth tokens: Yes (Policy/Signature found)")
                        else:
                            print(f"  Has auth tokens: Unknown (no Policy/Signature)")
                    else:
                        print(f"  Has query params: No - THIS MAY CAUSE 403 ERRORS")

                    return data
                else:
                    print(f"\n✗ Extraction failed: {data.get('error', 'Unknown error')}")
                    return None
            except json.JSONDecodeError as e:
                print(f"\n✗ Invalid JSON response: {e}")
                print(f"  Raw output: {result.stdout[:200]}")
                return None
        else:
            print(f"\n✗ Extractor failed with code {result.returncode}")
            if result.stderr:
                print(f"  Error: {result.stderr[-300:]}")
            return None

    except subprocess.TimeoutExpired:
        print("✗ Extractor timed out (120s)")
        return None
    except Exception as e:
        print(f"✗ Error running extractor: {e}")
        return None

def test_url_accessibility(video_url, cookies):
    """Test if the video URL is accessible."""
    print_step(3, "Testing URL accessibility")

    print(f"  Testing URL: {video_url[:80]}...")

    # Test with curl
    headers = [
        '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        '-H', 'Referer: https://player.hotmart.com/',
        '-H', 'Origin: https://player.hotmart.com',
    ]

    # Add cookies
    cookie_str = '; '.join([f'{k}={v}' for k, v in cookies.items()])
    headers.extend(['-H', f'Cookie: {cookie_str}'])

    cmd = ['curl', '-s', '-L', '-I', '-w', '%{http_code}'] + headers + [video_url]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        # Get HTTP status code (last line)
        output_lines = result.stdout.strip().split('\n')
        status_code = output_lines[-1] if output_lines else 'unknown'

        print(f"  HTTP Status: {status_code}")

        if status_code == '200':
            print("✓ URL is accessible!")

            # Try to fetch and verify it's an M3U8
            cmd2 = ['curl', '-s', '-L'] + headers + [video_url]
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=15)

            if '#EXTM3U' in result2.stdout:
                print("✓ Confirmed: Valid M3U8 playlist")
                # Show first few lines
                lines = result2.stdout.split('\n')[:10]
                print("  First lines of playlist:")
                for line in lines:
                    print(f"    {line[:80]}")
                return True
            else:
                print(f"  Warning: Response doesn't look like M3U8")
                print(f"  First 200 chars: {result2.stdout[:200]}")
                return False
        else:
            print(f"✗ URL returned {status_code}")
            # Show response headers for debugging
            for line in output_lines[:10]:
                if line.strip():
                    print(f"    {line[:80]}")
            return False

    except Exception as e:
        print(f"✗ Error testing URL: {e}")
        return False

def test_ffmpeg_download(video_url, cookies):
    """Test downloading with FFmpeg."""
    print_step(4, "Testing FFmpeg download (10 seconds only)")

    cookie_header = '; '.join([f'{k}={v}' for k, v in cookies.items()])

    headers = [
        f'Cookie: {cookie_header}',
        'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer: https://player.hotmart.com/',
        'Origin: https://player.hotmart.com',
    ]
    headers_str = '\r\n'.join(headers) + '\r\n'

    output_file = '/tmp/test_download.mp4'

    cmd = [
        'ffmpeg', '-y',
        '-headers', headers_str,
        '-i', video_url,
        '-c', 'copy',
        '-t', '10',  # Only 10 seconds
        output_file
    ]

    print(f"  Running FFmpeg (downloading first 10 seconds)...")

    try:
        start = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        elapsed = time.time() - start

        if result.returncode == 0 and os.path.exists(output_file):
            size = os.path.getsize(output_file)
            print(f"✓ Download successful!")
            print(f"  File size: {size / 1024:.1f} KB")
            print(f"  Time: {elapsed:.1f}s")

            # Clean up
            os.remove(output_file)
            return True
        else:
            print(f"✗ FFmpeg failed")
            # Extract error from stderr
            if result.stderr:
                error_lines = result.stderr.strip().split('\n')
                for line in error_lines[-10:]:
                    if 'error' in line.lower() or 'denied' in line.lower() or 'failed' in line.lower():
                        print(f"  Error: {line}")
            return False

    except subprocess.TimeoutExpired:
        print("✗ FFmpeg timed out (60s)")
        return False
    except FileNotFoundError:
        print("✗ FFmpeg not installed")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def main():
    print_header("Hotmart Video Download - Full Flow Test")

    # Get URL from command line or use default
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
    else:
        # Default test URL - user should replace this
        test_url = input("Enter a course lecture URL: ").strip()
        if not test_url:
            print("No URL provided. Exiting.")
            sys.exit(1)

    print(f"\nTest URL: {test_url}")

    # Step 1: Get cookies
    cookies = test_cookies()
    if not cookies:
        print("\n❌ FAILED at Step 1: Could not get cookies")
        print("   Fix: Log into the course website in Chrome")
        sys.exit(1)

    # Step 2: Extract video URL
    video_data = test_playwright_extractor(test_url, cookies)
    if not video_data:
        print("\n❌ FAILED at Step 2: Could not extract video URL")
        print("   The Playwright extractor couldn't find the video")
        sys.exit(1)

    # Get the video URL
    video_url = video_data.get('video_url')
    if not video_url:
        # It's a Wistia ID, need to convert
        wistia_id = video_data.get('video_id')
        if wistia_id:
            print(f"\n  Converting Wistia ID to M3U8 URL...")
            video_url = f"https://fast.wistia.com/embed/medias/{wistia_id}.m3u8"
        else:
            print("\n❌ No video URL or ID found")
            sys.exit(1)

    # Step 3: Test URL accessibility
    accessible = test_url_accessibility(video_url, cookies)
    if not accessible:
        print("\n❌ FAILED at Step 3: Video URL is not accessible")
        print("   The URL might be missing authentication tokens")
        print("   or the tokens might have expired")
        sys.exit(1)

    # Step 4: Test FFmpeg download
    success = test_ffmpeg_download(video_url, cookies)
    if not success:
        print("\n❌ FAILED at Step 4: FFmpeg could not download")
        print("   FFmpeg might need different headers or the stream format is unsupported")
        sys.exit(1)

    # All tests passed!
    print_header("ALL TESTS PASSED!")
    print("""
✓ Cookies extracted successfully
✓ Video URL extracted with authentication tokens
✓ URL is accessible (HTTP 200)
✓ FFmpeg can download the video

The downloader should work. If the GUI is still having issues,
the problem is likely in the download loop or progress tracking,
not in the video extraction.
""")

if __name__ == "__main__":
    main()
