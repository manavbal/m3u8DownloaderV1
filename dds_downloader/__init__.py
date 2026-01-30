"""
DDS Downloader - Download course videos from DDS Success
"""

__version__ = "1.0.0"
__author__ = "DDS Downloader"

from .gui import DDSDownloaderApp, main
from .cookie_extractor import get_session_cookies
from .course_scraper import CourseScraper, Course, Section, Lesson
from .downloader import Downloader, check_ffmpeg_installed
from .settings import get_settings

__all__ = [
    'DDSDownloaderApp',
    'main',
    'get_session_cookies',
    'CourseScraper',
    'Course',
    'Section',
    'Lesson',
    'Downloader',
    'check_ffmpeg_installed',
    'get_settings',
]
