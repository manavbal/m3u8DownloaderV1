# DDS Downloader

A simple desktop application to download course videos and materials from DDS Success for offline viewing.

## Features

- Download entire courses or individual videos
- Automatically maintains folder structure and video order
- Downloads all associated files (PDFs, Word docs, Excel files)
- Choose video quality (1080p, 720p, etc.)
- Progress tracking with pause/resume support
- Auto-retry on network issues
- Skips already downloaded files
- Remembers your last download folder

## Requirements

- **macOS** (Apple Silicon M1/M2 or Intel)
- **Python 3.8+** (you likely already have this)
- **Google Chrome** (for login session)
- **FFmpeg** (for video processing)

## Installation

### Step 1: Install FFmpeg

FFmpeg is required to process video files. Open Terminal and run:

```bash
# If you have Homebrew installed:
brew install ffmpeg

# If you don't have Homebrew, install it first:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install ffmpeg
```

### Step 2: Install Python Dependencies

Open Terminal, navigate to the DDS Downloader folder, and run:

```bash
cd /path/to/m3u8DownloaderV1
pip3 install -r requirements.txt
```

### Step 3: Grant Keychain Access (First Run Only)

The app needs to read your Chrome session. On first run, macOS will ask for permission to access Chrome Safe Storage in Keychain. Click "Allow" or "Always Allow".

## How to Use

### 1. Log into Your Course in Chrome

Open Google Chrome and log into your DDS Success account. Make sure you can access your courses.

### 2. Run DDS Downloader

```bash
cd /path/to/m3u8DownloaderV1
python3 main.py
```

Or double-click `run_app.command` (after making it executable).

### 3. Paste a Course URL

Copy any URL from a course (e.g., a specific video page):
```
https://app.ddssuccess.com/courses/art-of-scheduling-productively/lectures/42201128
```

Paste it into the app and click "Scan Course".

### 4. Select What to Download

The app will show you:
- A checklist of all sections and videos
- Any downloadable files (PDFs, Word docs, etc.)

Check/uncheck items as needed.

### 5. Choose Quality and Folder

- Select video quality (best, 1080p, 720p, etc.)
- Choose where to save the files

### 6. Download

Click "Download Selected" and wait for completion.

## Folder Structure

Downloaded files are organized like this:

```
Your Download Folder/
  Art of Scheduling Productively/
    01 - Introduction.mp4
    01 - Introduction.pdf
    02 - The 5 Basic Rules of Scheduling.mp4
    03 - Setting Production Goals.mp4
    03 - Setting Production Goals.xlsx
    ...
```

## Troubleshooting

### "Could not read Chrome session"

- Make sure Chrome is installed
- Make sure you're logged into the course website in Chrome
- Try logging out and back in on the website

### "Session is not valid"

- Your login may have expired
- Log into the course website again in Chrome
- Try again

### "FFmpeg not found"

- Install FFmpeg using the instructions above
- Restart the app after installing

### Download seems stuck

- Check your internet connection
- Click "Pause" then "Resume" or "Force Resume"
- The app will auto-retry on network issues

### Keychain access denied

If you accidentally clicked "Deny" on the Keychain prompt:
1. Open Keychain Access app
2. Search for "Chrome Safe Storage"
3. Delete the entry
4. Run the app again and click "Allow"

## Technical Notes

- The app reads your Chrome cookies to authenticate with the course website
- No passwords are stored by this app
- Videos are downloaded as MP4 files
- Temporary files are automatically cleaned up
- Settings are saved to `~/Library/Application Support/DDS Downloader/`

## Privacy

This app:
- Only reads Chrome cookies for ddssuccess.com
- Does not store your password
- Does not send data anywhere except to download from the course website
- Saves files only to your chosen folder
