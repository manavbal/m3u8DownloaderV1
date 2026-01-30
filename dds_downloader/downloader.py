"""
Downloader module for DDS Downloader
Handles M3U8 video downloads and file downloads with retry logic.
"""

import os
import re
import json
import time
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Optional, Callable, List
from enum import Enum
from urllib.parse import urljoin, urlparse
import requests


class DownloadStatus(Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class DownloadProgress:
    """Tracks progress for a download."""
    status: DownloadStatus = DownloadStatus.PENDING
    progress_percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: str = ""
    eta: str = ""
    error_message: str = ""


class Downloader:
    """Handles downloading of M3U8 videos and files."""

    def __init__(self, cookies: Dict[str, str], output_dir: str):
        """
        Initialize the downloader.

        Args:
            cookies: Session cookies for authentication
            output_dir: Base output directory for downloads
        """
        self.cookies = cookies
        self.output_dir = Path(output_dir)
        self.session = requests.Session()
        self.session.cookies.update(cookies)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

        self._cancel_flag = False
        self._pause_flag = False
        self._current_process: Optional[subprocess.Popen] = None

        # Progress tracking
        self.progress_callback: Optional[Callable[[str, DownloadProgress], None]] = None

        # Retry settings
        self.max_retries = 5
        self.retry_delay = 2  # seconds, will be exponentially increased

        # Resume state file
        self.state_file = self.output_dir / '.download_state.json'

    def set_progress_callback(self, callback: Callable[[str, DownloadProgress], None]):
        """Set callback for progress updates."""
        self.progress_callback = callback

    def _update_progress(self, item_id: str, progress: DownloadProgress):
        """Update progress via callback if set."""
        if self.progress_callback:
            self.progress_callback(item_id, progress)

    def cancel_downloads(self):
        """Cancel all ongoing downloads."""
        self._cancel_flag = True
        if self._current_process:
            self._current_process.terminate()

    def pause_downloads(self):
        """Pause ongoing downloads."""
        self._pause_flag = True
        if self._current_process:
            self._current_process.terminate()

    def resume_downloads(self):
        """Resume paused downloads."""
        self._pause_flag = False
        self._cancel_flag = False

    def _should_skip_file(self, output_path: Path) -> bool:
        """Check if file already exists and should be skipped."""
        return output_path.exists() and output_path.stat().st_size > 0

    def _ensure_directory(self, path: Path):
        """Ensure directory exists."""
        path.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize filename for filesystem."""
        # Remove or replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')

        # Remove leading/trailing spaces and dots
        name = name.strip(' .')

        # Limit length
        if len(name) > 200:
            name = name[:200]

        return name

    def download_m3u8_video(
        self,
        m3u8_url: str,
        output_path: Path,
        quality: str = "best",
        item_id: str = ""
    ) -> bool:
        """
        Download M3U8 video using FFmpeg.

        Args:
            m3u8_url: URL to the M3U8 playlist
            output_path: Path to save the output MP4 file
            quality: Desired quality (e.g., '1080p', '720p', 'best')
            item_id: Identifier for progress tracking

        Returns:
            True if successful, False otherwise
        """
        if self._should_skip_file(output_path):
            self._update_progress(item_id, DownloadProgress(
                status=DownloadStatus.SKIPPED,
                progress_percent=100.0
            ))
            return True

        self._ensure_directory(output_path.parent)

        # Get quality-specific URL if needed
        stream_url = self._get_quality_stream_url(m3u8_url, quality)

        retry_count = 0
        while retry_count < self.max_retries:
            if self._cancel_flag:
                return False

            if self._pause_flag:
                self._update_progress(item_id, DownloadProgress(
                    status=DownloadStatus.PAUSED
                ))
                while self._pause_flag and not self._cancel_flag:
                    time.sleep(0.5)
                if self._cancel_flag:
                    return False

            try:
                self._update_progress(item_id, DownloadProgress(
                    status=DownloadStatus.DOWNLOADING,
                    progress_percent=0.0
                ))

                success = self._run_ffmpeg_download(stream_url, output_path, item_id)

                if success:
                    self._update_progress(item_id, DownloadProgress(
                        status=DownloadStatus.COMPLETED,
                        progress_percent=100.0
                    ))
                    return True

            except Exception as e:
                print(f"Download error (attempt {retry_count + 1}): {e}")

            retry_count += 1
            if retry_count < self.max_retries:
                delay = self.retry_delay * (2 ** retry_count)
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)

        self._update_progress(item_id, DownloadProgress(
            status=DownloadStatus.FAILED,
            error_message=f"Failed after {self.max_retries} attempts"
        ))
        return False

    def _get_quality_stream_url(self, m3u8_url: str, quality: str) -> str:
        """Get the stream URL for a specific quality."""
        if quality.lower() == 'best' or quality.lower() == 'auto':
            return m3u8_url

        try:
            response = self.session.get(m3u8_url, timeout=10)
            if response.status_code != 200:
                return m3u8_url

            content = response.text
            lines = content.strip().split('\n')

            # Parse the master playlist
            target_height = int(quality.replace('p', ''))
            best_match = None
            best_match_url = None

            for i, line in enumerate(lines):
                if line.startswith('#EXT-X-STREAM-INF'):
                    # Extract resolution
                    res_match = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
                    if res_match:
                        height = int(res_match.group(2))
                        if height == target_height:
                            # Next line is the URL
                            if i + 1 < len(lines):
                                url = lines[i + 1].strip()
                                if not url.startswith('#'):
                                    return urljoin(m3u8_url, url)

                        # Track closest match
                        if best_match is None or abs(height - target_height) < abs(best_match - target_height):
                            best_match = height
                            if i + 1 < len(lines):
                                best_match_url = lines[i + 1].strip()

            if best_match_url and not best_match_url.startswith('#'):
                return urljoin(m3u8_url, best_match_url)

        except Exception as e:
            print(f"Error getting quality stream: {e}")

        return m3u8_url

    def _run_ffmpeg_download(self, stream_url: str, output_path: Path, item_id: str) -> bool:
        """Run FFmpeg to download the stream."""
        # Prepare cookies header for FFmpeg
        cookie_header = '; '.join([f'{k}={v}' for k, v in self.cookies.items()])

        # Use a temporary file to avoid partial downloads
        temp_output = output_path.with_suffix('.tmp.mp4')

        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output
            '-headers', f'Cookie: {cookie_header}\r\n',
            '-i', stream_url,
            '-c', 'copy',  # Copy streams without re-encoding
            '-bsf:a', 'aac_adtstoasc',  # Fix audio for MP4
            '-movflags', '+faststart',  # Enable streaming
            '-progress', 'pipe:1',  # Output progress to stdout
            str(temp_output)
        ]

        try:
            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Read progress from FFmpeg
            duration = None
            current_time = 0

            while True:
                if self._cancel_flag or self._pause_flag:
                    self._current_process.terminate()
                    if temp_output.exists():
                        temp_output.unlink()
                    return False

                line = self._current_process.stdout.readline()
                if not line:
                    break

                # Parse progress info
                if 'out_time_ms=' in line:
                    match = re.search(r'out_time_ms=(\d+)', line)
                    if match:
                        current_time = int(match.group(1)) / 1000000  # Convert to seconds

                if 'progress=' in line:
                    if 'end' in line:
                        break

                # Update progress (estimate based on time if we know duration)
                if duration and duration > 0:
                    progress = min(99, (current_time / duration) * 100)
                    self._update_progress(item_id, DownloadProgress(
                        status=DownloadStatus.DOWNLOADING,
                        progress_percent=progress
                    ))

            self._current_process.wait()

            if self._current_process.returncode == 0 and temp_output.exists():
                # Move temp file to final location
                shutil.move(str(temp_output), str(output_path))
                return True

            # Check stderr for errors
            stderr = self._current_process.stderr.read()
            if stderr:
                print(f"FFmpeg error: {stderr}")

            return False

        except FileNotFoundError:
            print("FFmpeg not found. Please install FFmpeg.")
            self._update_progress(item_id, DownloadProgress(
                status=DownloadStatus.FAILED,
                error_message="FFmpeg not found. Please install FFmpeg."
            ))
            return False

        finally:
            self._current_process = None
            # Clean up temp file if it exists
            if temp_output.exists():
                try:
                    temp_output.unlink()
                except:
                    pass

    def download_file(
        self,
        url: str,
        output_path: Path,
        item_id: str = ""
    ) -> bool:
        """
        Download a file (PDF, Word, etc.).

        Args:
            url: URL to download from
            output_path: Path to save the file
            item_id: Identifier for progress tracking

        Returns:
            True if successful, False otherwise
        """
        if self._should_skip_file(output_path):
            self._update_progress(item_id, DownloadProgress(
                status=DownloadStatus.SKIPPED,
                progress_percent=100.0
            ))
            return True

        self._ensure_directory(output_path.parent)

        retry_count = 0
        while retry_count < self.max_retries:
            if self._cancel_flag:
                return False

            if self._pause_flag:
                self._update_progress(item_id, DownloadProgress(
                    status=DownloadStatus.PAUSED
                ))
                while self._pause_flag and not self._cancel_flag:
                    time.sleep(0.5)
                if self._cancel_flag:
                    return False

            try:
                self._update_progress(item_id, DownloadProgress(
                    status=DownloadStatus.DOWNLOADING,
                    progress_percent=0.0
                ))

                response = self.session.get(url, stream=True, timeout=30)
                response.raise_for_status()

                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0

                temp_output = output_path.with_suffix(output_path.suffix + '.tmp')

                with open(temp_output, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._cancel_flag or self._pause_flag:
                            f.close()
                            temp_output.unlink()
                            return False

                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            self._update_progress(item_id, DownloadProgress(
                                status=DownloadStatus.DOWNLOADING,
                                progress_percent=progress,
                                downloaded_bytes=downloaded,
                                total_bytes=total_size
                            ))

                # Move temp file to final location
                shutil.move(str(temp_output), str(output_path))

                self._update_progress(item_id, DownloadProgress(
                    status=DownloadStatus.COMPLETED,
                    progress_percent=100.0
                ))
                return True

            except Exception as e:
                print(f"Download error (attempt {retry_count + 1}): {e}")

            retry_count += 1
            if retry_count < self.max_retries:
                delay = self.retry_delay * (2 ** retry_count)
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)

        self._update_progress(item_id, DownloadProgress(
            status=DownloadStatus.FAILED,
            error_message=f"Failed after {self.max_retries} attempts"
        ))
        return False

    def save_state(self, state: Dict):
        """Save download state for resume capability."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"Error saving state: {e}")

    def load_state(self) -> Optional[Dict]:
        """Load saved download state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading state: {e}")
        return None

    def clear_state(self):
        """Clear saved download state."""
        if self.state_file.exists():
            try:
                self.state_file.unlink()
            except:
                pass


def check_ffmpeg_installed() -> bool:
    """Check if FFmpeg is installed and accessible."""
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_ffmpeg_install_instructions() -> str:
    """Get FFmpeg installation instructions for macOS."""
    return """
FFmpeg is required for video downloads.

To install FFmpeg on macOS, run one of these commands:

Using Homebrew (recommended):
    brew install ffmpeg

Using MacPorts:
    sudo port install ffmpeg

After installation, restart DDS Downloader.
"""


if __name__ == "__main__":
    # Test FFmpeg availability
    if check_ffmpeg_installed():
        print("FFmpeg is installed")
    else:
        print("FFmpeg is NOT installed")
        print(get_ffmpeg_install_instructions())
