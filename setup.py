#!/usr/bin/env python3
"""
Setup script for DDS Downloader
"""

from setuptools import setup, find_packages

setup(
    name="dds-downloader",
    version="1.0.0",
    description="Download course videos from DDS Success",
    author="DDS Downloader",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "requests>=2.31.0",
        "beautifulsoup4>=4.12.2",
        "lxml>=4.9.3",
        "m3u8>=4.0.0",
        "browser-cookie3>=0.19.1",
        "pycryptodome>=3.19.0",
        "appdirs>=1.4.4",
    ],
    entry_points={
        "console_scripts": [
            "dds-downloader=dds_downloader:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "Operating System :: MacOS :: MacOS X",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
