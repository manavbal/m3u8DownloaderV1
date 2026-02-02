#!/usr/bin/env python3
"""
DDS Downloader - Main Entry Point
Download course videos from DDS Success (Teachable-based platforms)
"""

import sys
import os

# Add the project directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dds_downloader import main

if __name__ == "__main__":
    main()
