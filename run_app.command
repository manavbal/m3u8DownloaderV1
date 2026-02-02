#!/bin/bash
# DDS Downloader - Launch Script for macOS
# Double-click this file to run the app

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Change to the app directory
cd "$DIR"

# Run the app
python3 main.py
