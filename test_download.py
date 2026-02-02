#!/usr/bin/env python3
"""
Simple diagnostic script to test downloading a single Hotmart video.
Run this directly to see exactly what's happening.
"""

import subprocess
import sys
import time
import os

# Test URL - you can replace this with any Hotmart M3U8 URL
TEST_URL = "https://vod-akm.play.hotmart.com/video/4qXdk6WEqv/hls/master-pkg-t-1724261131000.m3u8"
OUTPUT_FILE = "test_video.mp4"

def test_ffmpeg_basic():
    """Test basic FFmpeg download without any special headers."""
    print("=" * 60)
    print("TEST 1: Basic FFmpeg download (no headers)")
    print("=" * 60)

    cmd = [
        'ffmpeg', '-y',
        '-i', TEST_URL,
        '-c', 'copy',
        '-t', '10',  # Only download 10 seconds
        'test_basic.mp4'
    ]

    print(f"Command: {' '.join(cmd[:4])}...")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print("SUCCESS! Basic download works.")
            return True
        else:
            print(f"FAILED: {result.stderr[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        print("TIMEOUT: FFmpeg hung for 30 seconds")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False

def test_ffmpeg_with_headers():
    """Test FFmpeg download with Hotmart headers."""
    print("\n" + "=" * 60)
    print("TEST 2: FFmpeg download with Hotmart headers")
    print("=" * 60)

    headers = [
        'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer: https://player.hotmart.com/',
        'Origin: https://player.hotmart.com',
    ]
    headers_str = '\r\n'.join(headers) + '\r\n'

    cmd = [
        'ffmpeg', '-y',
        '-headers', headers_str,
        '-i', TEST_URL,
        '-c', 'copy',
        '-t', '10',  # Only download 10 seconds
        'test_headers.mp4'
    ]

    print(f"Command: ffmpeg with headers...")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print("SUCCESS! Download with headers works.")
            return True
        else:
            print(f"FAILED: {result.stderr[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        print("TIMEOUT: FFmpeg hung for 30 seconds")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False

def test_curl_m3u8():
    """Test if we can even fetch the M3U8 playlist."""
    print("\n" + "=" * 60)
    print("TEST 3: Fetch M3U8 playlist with curl")
    print("=" * 60)

    cmd = [
        'curl', '-s', '-L',
        '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
        '-H', 'Referer: https://player.hotmart.com/',
        TEST_URL
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and '#EXTM3U' in result.stdout:
            print("SUCCESS! M3U8 playlist is accessible.")
            print(f"First 500 chars:\n{result.stdout[:500]}")
            return True
        else:
            print(f"FAILED: Could not fetch M3U8")
            print(f"Response: {result.stdout[:200]}")
            return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False

def test_ytdlp():
    """Test if yt-dlp can download the video."""
    print("\n" + "=" * 60)
    print("TEST 4: Download with yt-dlp")
    print("=" * 60)

    # Check if yt-dlp is installed
    try:
        subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("yt-dlp not installed. Install with: brew install yt-dlp")
        return None

    cmd = [
        'yt-dlp',
        '--no-check-certificate',
        '-o', 'test_ytdlp.mp4',
        '--downloader', 'ffmpeg',
        '--downloader-args', 'ffmpeg:-t 10',  # Only 10 seconds
        TEST_URL
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print("SUCCESS! yt-dlp can download this video.")
            return True
        else:
            print(f"FAILED: {result.stderr[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        print("TIMEOUT: yt-dlp hung for 60 seconds")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False

def test_ffmpeg_verbose():
    """Test FFmpeg with verbose output to see what's happening."""
    print("\n" + "=" * 60)
    print("TEST 5: FFmpeg verbose mode (shows detailed progress)")
    print("=" * 60)

    headers = [
        'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer: https://player.hotmart.com/',
        'Origin: https://player.hotmart.com',
    ]
    headers_str = '\r\n'.join(headers) + '\r\n'

    cmd = [
        'ffmpeg', '-y',
        '-loglevel', 'verbose',
        '-headers', headers_str,
        '-i', TEST_URL,
        '-c', 'copy',
        '-t', '10',
        'test_verbose.mp4'
    ]

    print("Running FFmpeg in verbose mode (output below)...")
    print("-" * 40)

    try:
        # Run interactively so we can see output in real-time
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        start = time.time()
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                print(line.rstrip())
            if time.time() - start > 30:
                print("\n[TIMEOUT - killing process]")
                process.kill()
                return False

        return process.returncode == 0

    except Exception as e:
        print(f"ERROR: {e}")
        return False

def main():
    print("Hotmart Video Download Diagnostic Tool")
    print(f"Testing URL: {TEST_URL[:60]}...")
    print()

    results = {}

    # Test 1: Basic FFmpeg
    results['basic'] = test_ffmpeg_basic()

    # Test 2: FFmpeg with headers
    results['headers'] = test_ffmpeg_with_headers()

    # Test 3: Curl M3U8
    results['curl'] = test_curl_m3u8()

    # Test 4: yt-dlp
    results['ytdlp'] = test_ytdlp()

    # Test 5: Verbose FFmpeg (only if others failed)
    if not results['headers']:
        results['verbose'] = test_ffmpeg_verbose()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for test, result in results.items():
        status = "PASS" if result else ("SKIP" if result is None else "FAIL")
        print(f"  {test}: {status}")

    # Recommendations
    print("\n" + "=" * 60)
    print("RECOMMENDATIONS")
    print("=" * 60)

    if results.get('ytdlp'):
        print("yt-dlp works! Use yt-dlp instead of FFmpeg directly.")
        print("The downloader should be updated to use yt-dlp.")
    elif results.get('curl'):
        print("M3U8 is accessible but FFmpeg can't download it.")
        print("Try installing yt-dlp: brew install yt-dlp")
    elif not results.get('curl'):
        print("Cannot access the M3U8 URL at all.")
        print("The URL might be expired or require authentication tokens.")

    # Cleanup test files
    for f in ['test_basic.mp4', 'test_headers.mp4', 'test_ytdlp.mp4', 'test_verbose.mp4']:
        if os.path.exists(f):
            os.remove(f)

if __name__ == "__main__":
    main()
