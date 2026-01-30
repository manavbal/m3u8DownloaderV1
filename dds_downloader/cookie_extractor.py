"""
Chrome Cookie Extractor for DDS Downloader
Extracts session cookies from Chrome browser for authentication.
"""

import os
import json
import sqlite3
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Optional
import subprocess


def get_session_cookies(base_url: str) -> Dict[str, str]:
    """
    Get all relevant session cookies for a given URL.
    Uses browser_cookie3 library for reliable cookie extraction.

    Args:
        base_url: The base URL (e.g., 'https://app.ddssuccess.com')

    Returns:
        Dictionary of cookies needed for authentication
    """
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    domain = parsed.netloc

    # Extract the root domain (e.g., 'ddssuccess.com' from 'app.ddssuccess.com')
    parts = domain.split('.')
    if len(parts) > 2:
        root_domain = '.'.join(parts[-2:])
    else:
        root_domain = domain

    cookies = {}

    # Method 1: Try browser_cookie3 (most reliable)
    try:
        import browser_cookie3

        # Get Chrome cookies
        chrome_cookies = browser_cookie3.chrome(domain_name=root_domain)

        for cookie in chrome_cookies:
            if root_domain in cookie.domain:
                cookies[cookie.name] = cookie.value

        if cookies:
            print(f"Successfully extracted {len(cookies)} cookies using browser_cookie3")
            return cookies

    except Exception as e:
        print(f"browser_cookie3 method failed: {e}")

    # Method 2: Fallback to manual extraction with updated decryption
    try:
        cookies = extract_cookies_manual(root_domain)
        if cookies:
            return cookies
    except Exception as e:
        print(f"Manual extraction failed: {e}")

    return cookies


def extract_cookies_manual(domain: str) -> Dict[str, str]:
    """
    Manually extract cookies from Chrome database.
    Fallback method if browser_cookie3 doesn't work.
    """
    cookies = {}

    home = Path.home()
    cookie_path = home / "Library" / "Application Support" / "Google" / "Chrome" / "Default" / "Cookies"

    if not cookie_path.exists():
        print(f"Chrome cookies database not found at {cookie_path}")
        return cookies

    # Copy the database to a temp file (Chrome may have it locked)
    temp_dir = tempfile.mkdtemp()
    temp_db = os.path.join(temp_dir, 'Cookies')

    try:
        shutil.copy2(cookie_path, temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Get encryption key
        encryption_key = get_encryption_key()
        if not encryption_key:
            print("Could not get encryption key")
            return cookies

        # Query cookies for the domain
        cursor.execute(
            """
            SELECT name, encrypted_value, host_key
            FROM cookies
            WHERE host_key LIKE ?
            """,
            (f'%{domain}%',)
        )

        for row in cursor.fetchall():
            name, encrypted_value, host = row

            if encrypted_value and encryption_key:
                value = decrypt_cookie_value(encrypted_value, encryption_key)
                if value:
                    cookies[name] = value

        conn.close()

    except Exception as e:
        print(f"Error extracting cookies: {e}")
    finally:
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

    return cookies


def get_encryption_key() -> Optional[bytes]:
    """
    Get the Chrome encryption key from macOS Keychain.
    """
    try:
        result = subprocess.run(
            [
                'security', 'find-generic-password',
                '-s', 'Chrome Safe Storage',
                '-w'
            ],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            password = result.stdout.strip()
            import hashlib
            key = hashlib.pbkdf2_hmac(
                'sha1',
                password.encode('utf-8'),
                b'saltysalt',
                1003,
                dklen=16
            )
            return key
    except Exception as e:
        print(f"Error getting encryption key: {e}")
    return None


def decrypt_cookie_value(encrypted_value: bytes, key: bytes) -> str:
    """Decrypt a Chrome cookie value using AES-CBC."""
    try:
        from Crypto.Cipher import AES

        # Check for version prefix
        if encrypted_value[:3] == b'v10':
            encrypted_value = encrypted_value[3:]

            # Ensure the data length is a multiple of 16 (AES block size)
            if len(encrypted_value) % 16 != 0:
                # Pad if necessary
                padding_needed = 16 - (len(encrypted_value) % 16)
                encrypted_value = encrypted_value + (b'\x00' * padding_needed)

            # IV is 16 bytes of space characters for Chrome on macOS
            iv = b' ' * 16
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(encrypted_value)

            # Remove PKCS7 padding
            try:
                padding_len = decrypted[-1]
                if isinstance(padding_len, int) and 0 < padding_len <= 16:
                    # Verify padding is valid
                    if all(b == padding_len for b in decrypted[-padding_len:]):
                        decrypted = decrypted[:-padding_len]
            except:
                pass

            # Try to decode, stripping any null bytes
            try:
                return decrypted.rstrip(b'\x00').decode('utf-8')
            except UnicodeDecodeError:
                # Try latin-1 as fallback
                try:
                    return decrypted.rstrip(b'\x00').decode('latin-1')
                except:
                    pass

    except Exception as e:
        # Silently fail for individual cookies
        pass
    return ""


def format_cookies_for_requests(cookies: Dict[str, str]) -> str:
    """Format cookies as a string for HTTP headers."""
    return '; '.join([f'{name}={value}' for name, value in cookies.items()])


def validate_session(cookies: Dict[str, str], test_url: str) -> bool:
    """
    Validate that the cookies provide a valid logged-in session.

    Args:
        cookies: Dictionary of cookies
        test_url: URL to test authentication against

    Returns:
        True if session is valid, False otherwise
    """
    import requests

    try:
        response = requests.get(
            test_url,
            cookies=cookies,
            allow_redirects=False,
            timeout=10
        )

        # If we get redirected to login, session is invalid
        if response.status_code in [301, 302, 303, 307, 308]:
            location = response.headers.get('Location', '')
            if 'login' in location.lower() or 'sign_in' in location.lower():
                return False

        # If we get a 200 and the page contains course content, we're good
        if response.status_code == 200:
            return True

    except Exception as e:
        print(f"Session validation error: {e}")

    return False


if __name__ == "__main__":
    # Test the cookie extraction
    cookies = get_session_cookies("https://app.ddssuccess.com")
    print(f"Found {len(cookies)} cookies")
    for name in cookies:
        print(f"  - {name}")
