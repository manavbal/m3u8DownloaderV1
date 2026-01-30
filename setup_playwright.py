#!/usr/bin/env python3
"""
Setup script to install Playwright browser for DDS Downloader.
Run this once before using the app.
"""

import subprocess
import sys

def main():
    print("Installing Playwright browser (Chromium)...")
    print("This may take a moment on first run.\n")

    try:
        # Install playwright browsers
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            print("✓ Playwright browser installed successfully!")
            print("\nYou can now run the app with: python3 main.py")
        else:
            print("Error installing Playwright browser:")
            print(result.stderr)
            print("\nTry running manually:")
            print("  python3 -m playwright install chromium")

    except Exception as e:
        print(f"Error: {e}")
        print("\nTry running manually:")
        print("  python3 -m playwright install chromium")

if __name__ == "__main__":
    main()
