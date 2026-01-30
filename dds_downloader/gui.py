"""
GUI module for DDS Downloader
Main application interface using tkinter.
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Dict, List, Optional, Set
from pathlib import Path
from dataclasses import dataclass

from .cookie_extractor import get_session_cookies, validate_session
from .course_scraper import CourseScraper, Course, Section, Lesson, DownloadableFile
from .downloader import (
    Downloader, DownloadProgress, DownloadStatus,
    check_ffmpeg_installed, get_ffmpeg_install_instructions
)
from .settings import get_settings


@dataclass
class DownloadItem:
    """Represents an item to be downloaded."""
    item_id: str
    lesson: Lesson
    file: Optional[DownloadableFile] = None
    is_video: bool = True
    selected: bool = True
    status: DownloadStatus = DownloadStatus.PENDING


class DDSDownloaderApp:
    """Main application class."""

    def __init__(self, root: tk.Tk):
        """Initialize the application."""
        self.root = root
        self.root.title("DDS Downloader")

        # Settings
        self.settings = get_settings()

        # State
        self.cookies: Dict[str, str] = {}
        self.course: Optional[Course] = None
        self.download_items: Dict[str, DownloadItem] = {}
        self.checkboxes: Dict[str, tk.BooleanVar] = {}
        self.downloader: Optional[Downloader] = None
        self.is_downloading = False
        self.scraper: Optional[CourseScraper] = None

        # Set window geometry
        width, height, x, y = self.settings.get_window_geometry()
        if x is not None and y is not None:
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        else:
            self.root.geometry(f"{width}x{height}")

        # Setup UI
        self._setup_styles()
        self._create_widgets()

        # Check FFmpeg on startup
        self._check_ffmpeg()

        # Bind window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_styles(self):
        """Setup ttk styles."""
        style = ttk.Style()
        style.theme_use('clam')

        # Custom styles
        style.configure('Title.TLabel', font=('Helvetica', 16, 'bold'))
        style.configure('Section.TLabel', font=('Helvetica', 12, 'bold'))
        style.configure('Status.TLabel', font=('Helvetica', 10))

    def _create_widgets(self):
        """Create all UI widgets."""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(main_frame, text="DDS Downloader", style='Title.TLabel')
        title_label.pack(pady=(0, 10))

        # URL Input Section
        url_frame = ttk.LabelFrame(main_frame, text="Course URL", padding="10")
        url_frame.pack(fill=tk.X, pady=(0, 10))

        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(url_frame, textvariable=self.url_var, width=60)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        self.scan_btn = ttk.Button(url_frame, text="Scan Course", command=self._scan_course)
        self.scan_btn.pack(side=tk.LEFT)

        # Status Label
        self.status_var = tk.StringVar(value="Enter a course URL and click 'Scan Course'")
        self.status_label = ttk.Label(main_frame, textvariable=self.status_var, style='Status.TLabel')
        self.status_label.pack(fill=tk.X, pady=(0, 10))

        # Course Info Frame (initially hidden)
        self.course_frame = ttk.LabelFrame(main_frame, text="Course Content", padding="10")

        # Scrollable checklist
        list_container = ttk.Frame(self.course_frame)
        list_container.pack(fill=tk.BOTH, expand=True)

        # Create canvas with scrollbar
        self.canvas = tk.Canvas(list_container, height=300)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Bind mousewheel scrolling
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # Select All / Deselect All buttons
        btn_frame = ttk.Frame(self.course_frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(btn_frame, text="Select All", command=self._select_all).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Deselect All", command=self._deselect_all).pack(side=tk.LEFT)

        # Quality Selection
        self.quality_frame = ttk.Frame(main_frame)

        ttk.Label(self.quality_frame, text="Video Quality:").pack(side=tk.LEFT)
        self.quality_var = tk.StringVar(value=self.settings.preferred_quality)
        self.quality_combo = ttk.Combobox(
            self.quality_frame,
            textvariable=self.quality_var,
            values=['best', '1080p', '720p', '480p', '360p'],
            state='readonly',
            width=10
        )
        self.quality_combo.pack(side=tk.LEFT, padx=(10, 0))

        # Output Directory Selection
        self.output_frame = ttk.Frame(main_frame)

        ttk.Label(self.output_frame, text="Save to:").pack(side=tk.LEFT)
        self.output_var = tk.StringVar(value=self.settings.last_download_folder)
        self.output_entry = ttk.Entry(self.output_frame, textvariable=self.output_var, width=50)
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 10))
        ttk.Button(self.output_frame, text="Browse...", command=self._browse_output).pack(side=tk.LEFT)

        # Progress Section
        self.progress_frame = ttk.LabelFrame(main_frame, text="Download Progress", padding="10")

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            self.progress_frame,
            variable=self.progress_var,
            maximum=100,
            mode='determinate'
        )
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))

        self.progress_label = ttk.Label(self.progress_frame, text="")
        self.progress_label.pack(fill=tk.X)

        # Action Buttons
        self.action_frame = ttk.Frame(main_frame)

        self.download_btn = ttk.Button(
            self.action_frame,
            text="Download Selected",
            command=self._start_download,
            state=tk.DISABLED
        )
        self.download_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.pause_btn = ttk.Button(
            self.action_frame,
            text="Pause",
            command=self._toggle_pause,
            state=tk.DISABLED
        )
        self.pause_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.cancel_btn = ttk.Button(
            self.action_frame,
            text="Cancel",
            command=self._cancel_download,
            state=tk.DISABLED
        )
        self.cancel_btn.pack(side=tk.LEFT)

        self.force_resume_btn = ttk.Button(
            self.action_frame,
            text="Force Resume",
            command=self._force_resume,
            state=tk.DISABLED
        )
        self.force_resume_btn.pack(side=tk.LEFT, padx=(10, 0))

    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling."""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _check_ffmpeg(self):
        """Check if FFmpeg is installed."""
        if not check_ffmpeg_installed():
            messagebox.showwarning(
                "FFmpeg Required",
                get_ffmpeg_install_instructions()
            )

    def _scan_course(self):
        """Scan the course URL to get content."""
        url = self.url_var.get().strip()

        if not url:
            messagebox.showwarning("Error", "Please enter a course URL")
            return

        if 'ddssuccess.com' not in url and 'teachable' not in url:
            messagebox.showwarning("Error", "Please enter a valid DDS Success course URL")
            return

        # Disable scan button
        self.scan_btn.config(state=tk.DISABLED)
        self.status_var.set("Checking login session...")

        # Run in background thread
        thread = threading.Thread(target=self._scan_course_thread, args=(url,))
        thread.daemon = True
        thread.start()

    def _scan_course_thread(self, url: str):
        """Background thread for scanning course."""
        try:
            # Get cookies from Chrome
            self.root.after(0, lambda: self.status_var.set("Reading Chrome session..."))
            self.cookies = get_session_cookies(url)

            if not self.cookies:
                self.root.after(0, lambda: self._show_error(
                    "Could not read Chrome session.\n\n"
                    "Please make sure you are logged into the course website in Chrome."
                ))
                return

            # Validate session
            self.root.after(0, lambda: self.status_var.set("Validating session..."))
            if not validate_session(self.cookies, url):
                self.root.after(0, lambda: self._show_error(
                    "Session is not valid.\n\n"
                    "Please log into the course website in Chrome and try again."
                ))
                return

            # Create scraper and get course info
            self.root.after(0, lambda: self.status_var.set("Scanning course content..."))
            self.scraper = CourseScraper(self.cookies)
            self.course = self.scraper.get_course_info(url)

            if not self.course:
                self.root.after(0, lambda: self._show_error(
                    "Could not find course content.\n\n"
                    "Please make sure the URL is correct."
                ))
                return

            # Update UI with course info
            self.root.after(0, self._display_course_content)

        except Exception as e:
            self.root.after(0, lambda: self._show_error(f"Error scanning course: {str(e)}"))

        finally:
            self.root.after(0, lambda: self.scan_btn.config(state=tk.NORMAL))

    def _show_error(self, message: str):
        """Show error message and reset status."""
        messagebox.showerror("Error", message)
        self.status_var.set("Enter a course URL and click 'Scan Course'")

    def _display_course_content(self):
        """Display the scanned course content in the UI."""
        if not self.course:
            return

        # Clear existing content
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.download_items.clear()
        self.checkboxes.clear()

        # Update status
        self.status_var.set(
            f"Found: {self.course.title} - "
            f"{len(self.course.sections)} sections, "
            f"{self.course.total_videos} videos, "
            f"{self.course.total_files} files"
        )

        # Create checklist
        item_count = 0
        for section in self.course.sections:
            # Section header
            section_frame = ttk.Frame(self.scrollable_frame)
            section_frame.pack(fill=tk.X, pady=(10, 5))

            section_var = tk.BooleanVar(value=True)
            section_cb = ttk.Checkbutton(
                section_frame,
                text=section.title,
                variable=section_var,
                style='Section.TLabel'
            )
            section_cb.pack(anchor=tk.W)

            # Store section checkbox
            section_id = f"section_{section.order}"
            self.checkboxes[section_id] = section_var

            # Lessons in this section
            for lesson in section.lessons:
                item_count += 1
                lesson_frame = ttk.Frame(self.scrollable_frame)
                lesson_frame.pack(fill=tk.X, padx=(20, 0))

                # Format lesson text
                order_str = f"{item_count:02d}"
                duration_str = f" ({lesson.duration})" if lesson.duration else ""
                file_indicator = ""

                # Create download item for video
                if lesson.is_video:
                    item_id = f"video_{section.order}_{lesson.order}"
                    self.download_items[item_id] = DownloadItem(
                        item_id=item_id,
                        lesson=lesson,
                        is_video=True
                    )

                    var = tk.BooleanVar(value=True)
                    self.checkboxes[item_id] = var

                    cb = ttk.Checkbutton(
                        lesson_frame,
                        text=f"{order_str} - {lesson.title}{duration_str}",
                        variable=var
                    )
                    cb.pack(anchor=tk.W)

                # Create download items for files
                for file_idx, file in enumerate(lesson.downloadable_files):
                    file_item_id = f"file_{section.order}_{lesson.order}_{file_idx}"
                    self.download_items[file_item_id] = DownloadItem(
                        item_id=file_item_id,
                        lesson=lesson,
                        file=file,
                        is_video=False
                    )

                    file_var = tk.BooleanVar(value=True)
                    self.checkboxes[file_item_id] = file_var

                    file_label = f"    - {file.name} [{file.file_type.upper()}]"
                    file_cb = ttk.Checkbutton(
                        lesson_frame,
                        text=file_label,
                        variable=file_var
                    )
                    file_cb.pack(anchor=tk.W)

        # Show all frames
        self.course_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.quality_frame.pack(fill=tk.X, pady=(0, 10))
        self.output_frame.pack(fill=tk.X, pady=(0, 10))
        self.progress_frame.pack(fill=tk.X, pady=(0, 10))
        self.action_frame.pack(fill=tk.X)

        # Enable download button
        self.download_btn.config(state=tk.NORMAL)

        # Now scan each lesson for details (M3U8 URLs and files)
        self._scan_lesson_details()

    def _scan_lesson_details(self):
        """Scan each lesson for M3U8 URLs and downloadable files."""
        if not self.course or not self.scraper:
            return

        def scan_thread():
            total_lessons = sum(len(s.lessons) for s in self.course.sections)
            scanned = 0

            for section in self.course.sections:
                for lesson in section.lessons:
                    if lesson.is_video:
                        self.root.after(0, lambda l=lesson: self.status_var.set(
                            f"Scanning: {l.title}..."
                        ))

                        # Get lesson details (M3U8 URL, files)
                        self.scraper.get_lesson_details(lesson)

                        # Update download items with files found
                        for file_idx, file in enumerate(lesson.downloadable_files):
                            file_item_id = f"file_{section.order}_{lesson.order}_{file_idx}"
                            if file_item_id not in self.download_items:
                                self.download_items[file_item_id] = DownloadItem(
                                    item_id=file_item_id,
                                    lesson=lesson,
                                    file=file,
                                    is_video=False
                                )

                    scanned += 1

            # Update status when done
            file_count = sum(
                len(lesson.downloadable_files)
                for section in self.course.sections
                for lesson in section.lessons
            )

            self.root.after(0, lambda: self.status_var.set(
                f"Ready: {self.course.title} - "
                f"{len(self.course.sections)} sections, "
                f"{self.course.total_videos} videos, "
                f"{file_count} files"
            ))

            # Refresh the display to show newly found files
            self.root.after(0, self._refresh_file_list)

        thread = threading.Thread(target=scan_thread)
        thread.daemon = True
        thread.start()

    def _refresh_file_list(self):
        """Refresh the file list after scanning lesson details."""
        # This could be enhanced to update the UI with newly found files
        pass

    def _select_all(self):
        """Select all items."""
        for var in self.checkboxes.values():
            var.set(True)

    def _deselect_all(self):
        """Deselect all items."""
        for var in self.checkboxes.values():
            var.set(False)

    def _browse_output(self):
        """Browse for output directory."""
        initial_dir = self.output_var.get() or str(Path.home() / "Downloads")
        folder = filedialog.askdirectory(
            initialdir=initial_dir,
            title="Select Download Folder"
        )
        if folder:
            self.output_var.set(folder)
            self.settings.last_download_folder = folder

    def _start_download(self):
        """Start downloading selected items."""
        # Get selected items
        selected_items = [
            item for item_id, item in self.download_items.items()
            if self.checkboxes.get(item_id, tk.BooleanVar(value=False)).get()
        ]

        if not selected_items:
            messagebox.showwarning("No Selection", "Please select items to download")
            return

        # Validate output directory
        output_dir = self.output_var.get()
        if not output_dir:
            messagebox.showwarning("No Folder", "Please select a download folder")
            return

        if not Path(output_dir).exists():
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"Could not create folder: {e}")
                return

        # Save settings
        self.settings.last_download_folder = output_dir
        self.settings.preferred_quality = self.quality_var.get()

        # Update UI
        self.is_downloading = True
        self.download_btn.config(state=tk.DISABLED)
        self.scan_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL)
        self.cancel_btn.config(state=tk.NORMAL)
        self.force_resume_btn.config(state=tk.DISABLED)

        # Start download thread
        thread = threading.Thread(
            target=self._download_thread,
            args=(selected_items, output_dir)
        )
        thread.daemon = True
        thread.start()

    def _download_thread(self, items: List[DownloadItem], output_dir: str):
        """Background thread for downloading."""
        try:
            # Create downloader
            self.downloader = Downloader(self.cookies, output_dir)
            self.downloader.set_progress_callback(self._on_download_progress)

            # Create course folder
            course_folder = Path(output_dir) / self._sanitize_filename(self.course.title)
            course_folder.mkdir(parents=True, exist_ok=True)

            total_items = len(items)
            completed = 0
            successful = 0
            skipped = 0

            for item in items:
                if not self.is_downloading:
                    break

                # Determine output path
                lesson_name = f"{item.lesson.order + 1:02d} - {self._sanitize_filename(item.lesson.title)}"

                if item.is_video:
                    output_path = course_folder / f"{lesson_name}.mp4"

                    # Update status - fetching video info
                    self.root.after(0, lambda n=lesson_name: self.progress_label.config(
                        text=f"Fetching video info: {n}"
                    ))

                    # First, ensure we have the M3U8 URL
                    if not item.lesson.m3u8_url:
                        print(f"Fetching M3U8 URL for: {item.lesson.title}")
                        self.scraper.get_lesson_details(item.lesson)

                    if item.lesson.m3u8_url:
                        print(f"Downloading: {item.lesson.title}")
                        print(f"  M3U8 URL: {item.lesson.m3u8_url[:80]}...")

                        # Update status - downloading
                        self.root.after(0, lambda n=lesson_name: self.progress_label.config(
                            text=f"Downloading: {n}"
                        ))

                        success = self.downloader.download_m3u8_video(
                            item.lesson.m3u8_url,
                            output_path,
                            self.quality_var.get(),
                            item.item_id
                        )
                        if success:
                            successful += 1
                            print(f"  Success: {output_path}")
                        else:
                            print(f"  Failed to download: {item.lesson.title}")
                    else:
                        print(f"No M3U8 URL found for: {item.lesson.title}")
                        skipped += 1
                        self.root.after(0, lambda n=lesson_name: self.progress_label.config(
                            text=f"Skipped (no video found): {n}"
                        ))
                        import time
                        time.sleep(0.5)  # Brief pause so user can see the message
                else:
                    # Download file
                    if item.file:
                        file_ext = item.file.file_type
                        output_path = course_folder / f"{lesson_name}.{file_ext}"

                        self.root.after(0, lambda n=item.file.name: self.progress_label.config(
                            text=f"Downloading: {n}"
                        ))

                        success = self.downloader.download_file(
                            item.file.url,
                            output_path,
                            item.item_id
                        )
                        if success:
                            successful += 1

                completed += 1
                overall_progress = (completed / total_items) * 100
                self.root.after(0, lambda p=overall_progress: self.progress_var.set(p))

            # Done - show summary
            print(f"Download complete: {successful} successful, {skipped} skipped")
            self.root.after(0, lambda: self._download_complete_with_summary(successful, skipped))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.root.after(0, lambda: messagebox.showerror("Error", f"Download error: {e}"))
            self.root.after(0, self._download_complete)

    def _on_download_progress(self, item_id: str, progress: DownloadProgress):
        """Callback for download progress updates."""
        if progress.status == DownloadStatus.DOWNLOADING:
            self.root.after(0, lambda p=progress.progress_percent: self._update_item_progress(item_id, p))

    def _update_item_progress(self, item_id: str, progress: float):
        """Update progress for a specific item."""
        # Could update individual item progress indicators here
        pass

    def _download_complete(self):
        """Called when download is complete."""
        self.is_downloading = False
        self.download_btn.config(state=tk.NORMAL)
        self.scan_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.DISABLED)
        self.force_resume_btn.config(state=tk.DISABLED)

        self.progress_label.config(text="Download complete!")
        messagebox.showinfo("Complete", "Download finished!")

    def _download_complete_with_summary(self, successful: int, skipped: int):
        """Called when download is complete, with summary."""
        self.is_downloading = False
        self.download_btn.config(state=tk.NORMAL)
        self.scan_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.DISABLED)
        self.force_resume_btn.config(state=tk.DISABLED)

        self.progress_label.config(text=f"Complete: {successful} downloaded, {skipped} skipped")

        if skipped > 0:
            messagebox.showinfo(
                "Download Complete",
                f"Downloaded: {successful} files\n"
                f"Skipped: {skipped} files (no video URL found)\n\n"
                "Check Terminal for details on skipped files."
            )
        else:
            messagebox.showinfo("Complete", f"Successfully downloaded {successful} files!")

    def _toggle_pause(self):
        """Toggle pause/resume."""
        if self.downloader:
            if self.pause_btn.cget('text') == 'Pause':
                self.downloader.pause_downloads()
                self.pause_btn.config(text='Resume')
                self.force_resume_btn.config(state=tk.NORMAL)
                self.progress_label.config(text="Paused")
            else:
                self.downloader.resume_downloads()
                self.pause_btn.config(text='Pause')
                self.force_resume_btn.config(state=tk.DISABLED)

    def _cancel_download(self):
        """Cancel the download."""
        if self.downloader:
            self.downloader.cancel_downloads()
            self.is_downloading = False

    def _force_resume(self):
        """Force resume downloads after network issues."""
        if self.downloader:
            self.downloader.resume_downloads()
            self.pause_btn.config(text='Pause')
            self.force_resume_btn.config(state=tk.DISABLED)
            self.progress_label.config(text="Resuming...")

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize filename for filesystem."""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name.strip(' .')[:200]

    def _on_close(self):
        """Handle window close."""
        # Save window geometry
        self.settings.save_window_geometry(
            self.root.winfo_width(),
            self.root.winfo_height(),
            self.root.winfo_x(),
            self.root.winfo_y()
        )

        # Cancel any ongoing downloads
        if self.is_downloading and self.downloader:
            self.downloader.cancel_downloads()

        self.root.destroy()


def main():
    """Main entry point."""
    root = tk.Tk()
    app = DDSDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
