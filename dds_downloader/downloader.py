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
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Optional, Callable, List
from enum import Enum
from urllib.parse import urljoin, urlparse
import requests


def format_bytes(size: int) -> str:
    """Format bytes into human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_time(seconds: float) -> str:
    """Format seconds into human readable time."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


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

    def _get_stream_duration(self, stream_url: str) -> Optional[float]:
        """Get the duration of the stream using ffprobe."""
        try:
            # Build headers for ffprobe too
            cookie_header = '; '.join([f'{k}={v}' for k, v in self.cookies.items()])
            headers = [
                f'Cookie: {cookie_header}',
                'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Referer: https://player.hotmart.com/',
                'Origin: https://player.hotmart.com',
            ]
            headers_str = '\r\n'.join(headers) + '\r\n'

            cmd = [
                'ffprobe',
                '-headers', headers_str,
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                stream_url
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0 and result.stdout.strip():
                duration = float(result.stdout.strip())
                if duration > 0:
                    return duration
        except Exception as e:
            print(f"  Could not get duration: {e}")

        return None

    def _print_progress(self, filename: str, progress: float, speed: str = "", eta: str = "", downloaded: int = 0, total: int = 0):
        """Print a progress bar to the terminal."""
        bar_width = 30
        filled = int(bar_width * progress / 100)
        bar = '=' * filled + '-' * (bar_width - filled)

        if total > 0:
            size_info = f" {format_bytes(downloaded)}/{format_bytes(total)}"
        elif downloaded > 0:
            size_info = f" {format_bytes(downloaded)}"
        else:
            size_info = ""

        speed_info = f" {speed}" if speed else ""
        eta_info = f" ETA: {eta}" if eta else ""

        # Truncate filename if too long
        max_name_len = 25
        if len(filename) > max_name_len:
            filename = filename[:max_name_len-3] + "..."

        line = f"\r  [{bar}] {progress:5.1f}%{size_info}{speed_info}{eta_info}  "

        # Print to terminal
        sys.stdout.write(line)
        sys.stdout.flush()

    def _run_ffmpeg_download(self, stream_url: str, output_path: Path, item_id: str) -> bool:
        """Run FFmpeg to download the stream."""
        # Prepare cookies header for FFmpeg
        cookie_header = '; '.join([f'{k}={v}' for k, v in self.cookies.items()])

        # Use a temporary file to avoid partial downloads
        temp_output = output_path.with_suffix('.tmp.mp4')

        # Build headers string for FFmpeg
        # Hotmart requires specific headers to allow downloads
        headers = [
            f'Cookie: {cookie_header}',
            'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer: https://player.hotmart.com/',
            'Origin: https://player.hotmart.com',
        ]
        headers_str = '\r\n'.join(headers) + '\r\n'

        # Get duration first for progress tracking
        print(f"  Getting video duration...")
        duration = self._get_stream_duration(stream_url)
        if duration:
            print(f"  Duration: {format_time(duration)}")
        else:
            print(f"  Duration unknown - will show time-based progress")

        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output
            '-headers', headers_str,
            '-i', stream_url,
            '-c', 'copy',  # Copy streams without re-encoding
            '-bsf:a', 'aac_adtstoasc',  # Fix audio for MP4
            '-movflags', '+faststart',  # Enable streaming
            '-progress', 'pipe:1',  # Output progress to stdout
            '-stats_period', '1',  # Update stats every 1 second
            str(temp_output)
        ]

        print(f"  Starting download...")

        # Timeout settings - abort if no progress for this long
        STUCK_TIMEOUT = 60  # seconds - if no data progress for 60s, consider stuck
        MAX_DOWNLOAD_TIME = 30 * 60  # 30 minutes max per video

        try:
            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1  # Line buffered
            )

            # Read progress from FFmpeg
            current_time = 0
            total_size = 0
            speed = ""
            start_time = time.time()
            last_update_time = start_time
            last_size = 0
            last_progress_time = start_time  # Track when we last saw progress

            filename = output_path.name

            while True:
                if self._cancel_flag or self._pause_flag:
                    self._current_process.terminate()
                    print("\n  Download cancelled")
                    if temp_output.exists():
                        temp_output.unlink()
                    return False

                # Check for stuck download
                now = time.time()
                if now - last_progress_time > STUCK_TIMEOUT:
                    print(f"\n  Download appears stuck (no progress for {STUCK_TIMEOUT}s)")
                    self._current_process.terminate()
                    if temp_output.exists():
                        temp_output.unlink()
                    return False

                # Check for max download time
                if now - start_time > MAX_DOWNLOAD_TIME:
                    print(f"\n  Download timeout (exceeded {MAX_DOWNLOAD_TIME/60:.0f} minutes)")
                    self._current_process.terminate()
                    if temp_output.exists():
                        temp_output.unlink()
                    return False

                # Use select-like approach with timeout to prevent blocking
                try:
                    line = self._current_process.stdout.readline()
                except:
                    line = ""

                if not line:
                    # Check if process has ended
                    if self._current_process.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue

                # We got a line - that's progress
                last_progress_time = time.time()

                # Parse progress info from FFmpeg
                if 'out_time_ms=' in line:
                    match = re.search(r'out_time_ms=(\d+)', line)
                    if match:
                        current_time = int(match.group(1)) / 1000000  # Convert to seconds

                elif 'total_size=' in line:
                    match = re.search(r'total_size=(\d+)', line)
                    if match:
                        total_size = int(match.group(1))

                elif 'speed=' in line:
                    match = re.search(r'speed=\s*([0-9.]+)x', line)
                    if match:
                        speed = f"{match.group(1)}x"

                elif 'progress=' in line:
                    if 'end' in line:
                        # Final progress
                        self._print_progress(filename, 100.0, downloaded=total_size)
                        print()  # New line after progress
                        break

                # Update progress display
                now = time.time()
                if now - last_update_time >= 0.5:  # Update every 0.5 seconds
                    last_update_time = now

                    # Calculate progress percentage
                    if duration and duration > 0:
                        progress = min(99.9, (current_time / duration) * 100)
                        # Estimate ETA
                        if progress > 0:
                            elapsed = now - start_time
                            total_estimated = elapsed / (progress / 100)
                            eta = format_time(total_estimated - elapsed)
                        else:
                            eta = ""
                    else:
                        # No duration - show time-based progress
                        progress = 0
                        eta = ""

                    self._print_progress(
                        filename,
                        progress,
                        speed=speed,
                        eta=eta,
                        downloaded=total_size
                    )

                    # Also update callback for GUI
                    self._update_progress(item_id, DownloadProgress(
                        status=DownloadStatus.DOWNLOADING,
                        progress_percent=progress,
                        downloaded_bytes=total_size,
                        speed=speed,
                        eta=eta
                    ))

            self._current_process.wait()

            if self._current_process.returncode == 0 and temp_output.exists():
                file_size = temp_output.stat().st_size
                print(f"  Download complete: {format_bytes(file_size)}")
                # Move temp file to final location
                shutil.move(str(temp_output), str(output_path))
                return True

            # Check stderr for errors
            stderr = self._current_process.stderr.read()
            if stderr:
                # Print only the most relevant error lines
                error_lines = stderr.strip().split('\n')
                relevant_errors = [l for l in error_lines if 'error' in l.lower() or 'failed' in l.lower() or 'denied' in l.lower()]
                if relevant_errors:
                    print(f"\n  FFmpeg error: {relevant_errors[-1]}")
                else:
                    # Print last few lines
                    print(f"\n  FFmpeg failed. Last output: {error_lines[-1] if error_lines else 'unknown error'}")

            return False

        except FileNotFoundError:
            print("\n  FFmpeg not found. Please install FFmpeg.")
            self._update_progress(item_id, DownloadProgress(
                status=DownloadStatus.FAILED,
                error_message="FFmpeg not found. Please install FFmpeg."
            ))
            return False

        except Exception as e:
            print(f"\n  Download error: {e}")
            return False

        finally:
            self._current_process = None
            # Clean up temp file if it exists and download failed
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
