"""
Course Scraper for DDS Downloader
Parses Teachable course pages to extract structure, videos, and downloadable files.
"""

import re
import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup


@dataclass
class DownloadableFile:
    """Represents a downloadable file (PDF, Word, Excel, etc.)"""
    name: str
    url: str
    file_type: str  # 'pdf', 'docx', 'xlsx', etc.


@dataclass
class Lesson:
    """Represents a single lesson/video in a course."""
    title: str
    url: str
    duration: str = ""
    order: int = 0
    m3u8_url: Optional[str] = None
    available_qualities: List[str] = field(default_factory=list)
    downloadable_files: List[DownloadableFile] = field(default_factory=list)
    is_video: bool = True


@dataclass
class Section:
    """Represents a section/chapter in a course."""
    title: str
    lessons: List[Lesson] = field(default_factory=list)
    order: int = 0


@dataclass
class Course:
    """Represents a complete course."""
    title: str
    url: str
    sections: List[Section] = field(default_factory=list)
    total_videos: int = 0
    total_files: int = 0


class CourseScraper:
    """Scrapes course information from Teachable-based platforms."""

    def __init__(self, cookies: Dict[str, str]):
        """
        Initialize the scraper with session cookies.

        Args:
            cookies: Dictionary of authentication cookies
        """
        self.cookies = cookies
        self.session = requests.Session()
        self.session.cookies.update(cookies)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    def get_course_info(self, url: str, progress_callback: Optional[Callable] = None) -> Optional[Course]:
        """
        Extract complete course information from a course or lecture URL.

        Args:
            url: URL to a course page or any lecture within the course
            progress_callback: Optional callback function for progress updates

        Returns:
            Course object with all sections, lessons, and file info
        """
        try:
            # First, get the course page
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'lxml')

            # Extract course title
            course_title = self._extract_course_title(soup, url)

            # Get the base course URL
            course_base_url = self._get_course_base_url(url)

            # Parse the curriculum/sidebar
            sections = self._parse_curriculum(soup, course_base_url)

            course = Course(
                title=course_title,
                url=course_base_url,
                sections=sections
            )

            # Count totals
            for section in sections:
                for lesson in section.lessons:
                    if lesson.is_video:
                        course.total_videos += 1
                    course.total_files += len(lesson.downloadable_files)

            return course

        except Exception as e:
            print(f"Error getting course info: {e}")
            return None

    def _extract_course_title(self, soup: BeautifulSoup, url: str) -> str:
        """Extract the course title from the page."""
        # Try various selectors that Teachable uses
        selectors = [
            'h1.course-title',
            '.course-sidebar h2',
            'h1',
            '.course-name',
            '[data-course-title]',
        ]

        for selector in selectors:
            element = soup.select_one(selector)
            if element and element.text.strip():
                return element.text.strip()

        # Fallback: extract from URL
        match = re.search(r'/courses/([^/]+)', url)
        if match:
            return match.group(1).replace('-', ' ').title()

        return "Unknown Course"

    def _get_course_base_url(self, url: str) -> str:
        """Get the base course URL from any lecture URL."""
        parsed = urlparse(url)
        match = re.search(r'(/courses/[^/]+)', url)
        if match:
            return f"{parsed.scheme}://{parsed.netloc}{match.group(1)}"
        return url

    def _parse_curriculum(self, soup: BeautifulSoup, base_url: str) -> List[Section]:
        """Parse the course curriculum from the sidebar."""
        sections = []

        # Try to find the curriculum section - Teachable uses various structures
        # Look for section headers and their lessons

        # Method 1: Look for section containers
        section_containers = soup.select('.course-section, .section, [data-section]')

        if section_containers:
            for idx, container in enumerate(section_containers):
                section = self._parse_section_container(container, base_url, idx)
                if section:
                    sections.append(section)

        # Method 2: Look for the sidebar list structure
        if not sections:
            sidebar = soup.select_one('.course-sidebar, .lecture-list, [class*="curriculum"]')
            if sidebar:
                sections = self._parse_sidebar_list(sidebar, base_url)

        # Method 3: Look for individual lecture items and group by section
        if not sections:
            sections = self._parse_flat_lecture_list(soup, base_url)

        return sections

    def _parse_section_container(self, container, base_url: str, section_idx: int) -> Optional[Section]:
        """Parse a section container element."""
        # Get section title
        title_elem = container.select_one('.section-title, .section-header, h3, h4, [class*="section-name"]')
        section_title = title_elem.text.strip() if title_elem else f"Section {section_idx + 1}"

        # Get lessons in this section
        lesson_items = container.select('.section-item, .lecture-item, li a[href*="/lectures/"]')

        lessons = []
        for idx, item in enumerate(lesson_items):
            lesson = self._parse_lesson_item(item, base_url, idx)
            if lesson:
                lessons.append(lesson)

        if lessons:
            return Section(title=section_title, lessons=lessons, order=section_idx)

        return None

    def _parse_sidebar_list(self, sidebar, base_url: str) -> List[Section]:
        """Parse the sidebar list structure."""
        sections = []
        current_section = None
        section_idx = 0
        lesson_idx = 0

        for element in sidebar.children:
            if not hasattr(element, 'name') or element.name is None:
                continue

            # Check if this is a section header
            if element.name in ['h3', 'h4', 'div'] and 'section' in element.get('class', []):
                if current_section and current_section.lessons:
                    sections.append(current_section)

                current_section = Section(
                    title=element.text.strip(),
                    order=section_idx
                )
                section_idx += 1
                lesson_idx = 0

            # Check if this is a lesson item
            elif element.name in ['a', 'li', 'div']:
                link = element if element.name == 'a' else element.select_one('a')
                if link and '/lectures/' in link.get('href', ''):
                    lesson = self._parse_lesson_item(link, base_url, lesson_idx)
                    if lesson:
                        if current_section is None:
                            current_section = Section(title="Main Content", order=0)
                        current_section.lessons.append(lesson)
                        lesson_idx += 1

        if current_section and current_section.lessons:
            sections.append(current_section)

        return sections

    def _parse_flat_lecture_list(self, soup: BeautifulSoup, base_url: str) -> List[Section]:
        """Parse a flat list of lectures without section grouping."""
        lectures = soup.select('a[href*="/lectures/"]')

        # Try to group by section headers that might be nearby
        sections = []
        current_section = Section(title="Course Content", order=0)
        lesson_idx = 0

        for lecture in lectures:
            lesson = self._parse_lesson_item(lecture, base_url, lesson_idx)
            if lesson:
                current_section.lessons.append(lesson)
                lesson_idx += 1

        if current_section.lessons:
            sections.append(current_section)

        return sections

    def _parse_lesson_item(self, item, base_url: str, order: int) -> Optional[Lesson]:
        """Parse a single lesson item."""
        # Get the link element
        if item.name == 'a':
            link = item
        else:
            link = item.select_one('a[href*="/lectures/"]')

        if not link:
            return None

        href = link.get('href', '')
        if not href or '/lectures/' not in href:
            return None

        # Build full URL
        url = urljoin(base_url, href)

        # Get title
        title = link.text.strip()

        # Clean up title - remove duration if embedded
        duration_match = re.search(r'\((\d+:\d+)\)', title)
        duration = ""
        if duration_match:
            duration = duration_match.group(1)
            title = re.sub(r'\s*\(\d+:\d+\)\s*', '', title).strip()

        # Also check for duration in a separate element
        if not duration:
            duration_elem = item.select_one('.duration, .lecture-duration, [class*="time"]')
            if duration_elem:
                duration = duration_elem.text.strip()

        # Check if this is a video or just content
        is_video = True
        icon = item.select_one('.fa-video, .fa-play, [class*="video"], svg')
        if item.select_one('.fa-file-pdf, .fa-file-text, [class*="text"]'):
            is_video = False

        return Lesson(
            title=title,
            url=url,
            duration=duration,
            order=order,
            is_video=is_video
        )

    def get_lesson_details(self, lesson: Lesson, progress_callback: Optional[Callable] = None) -> Lesson:
        """
        Fetch detailed information for a lesson including M3U8 URL and downloadable files.

        Args:
            lesson: Lesson object to populate with details
            progress_callback: Optional callback for progress updates

        Returns:
            Updated Lesson object with M3U8 URL and files
        """
        try:
            response = self.session.get(lesson.url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'lxml')

            # Extract M3U8 URL
            m3u8_url = self._extract_m3u8_url(soup, response.text)
            if m3u8_url:
                lesson.m3u8_url = m3u8_url
                lesson.available_qualities = self._get_available_qualities(m3u8_url)

            # Extract downloadable files
            lesson.downloadable_files = self._extract_downloadable_files(soup, lesson.url)

        except Exception as e:
            print(f"Error getting lesson details for {lesson.title}: {e}")

        return lesson

    def _extract_m3u8_url(self, soup: BeautifulSoup, html_content: str) -> Optional[str]:
        """Extract the M3U8 URL from the page."""
        # Method 1: Look for Wistia embed
        wistia_match = re.search(r'wistia\.com/embed/medias/([a-zA-Z0-9]+)', html_content)
        if wistia_match:
            media_id = wistia_match.group(1)
            return self._get_wistia_m3u8(media_id)

        # Method 2: Look for direct M3U8 URL in the page
        m3u8_match = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', html_content)
        if m3u8_match:
            return m3u8_match.group(1)

        # Method 3: Look for video source in data attributes
        video_elem = soup.select_one('[data-video-url], [data-m3u8], video source[src*=".m3u8"]')
        if video_elem:
            return video_elem.get('data-video-url') or video_elem.get('data-m3u8') or video_elem.get('src')

        # Method 4: Look in script tags for video config
        for script in soup.select('script'):
            if script.string:
                # Look for various patterns
                patterns = [
                    r'"m3u8":\s*"([^"]+)"',
                    r'"hls":\s*"([^"]+)"',
                    r'"src":\s*"([^"]+\.m3u8[^"]*)"',
                    r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                ]
                for pattern in patterns:
                    match = re.search(pattern, script.string)
                    if match:
                        return match.group(1)

        return None

    def _get_wistia_m3u8(self, media_id: str) -> Optional[str]:
        """Get M3U8 URL from Wistia media ID."""
        try:
            # Wistia's embed info endpoint
            info_url = f"https://fast.wistia.com/embed/medias/{media_id}.json"
            response = self.session.get(info_url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                media = data.get('media', {})
                assets = media.get('assets', [])

                # Find the HLS asset
                for asset in assets:
                    if asset.get('type') == 'hls':
                        return asset.get('url')

                    # Also check for m3u8 in the URL
                    url = asset.get('url', '')
                    if '.m3u8' in url:
                        return url

        except Exception as e:
            print(f"Error getting Wistia M3U8: {e}")

        return None

    def _get_available_qualities(self, m3u8_url: str) -> List[str]:
        """Get available quality options from the master M3U8 playlist."""
        qualities = []

        try:
            response = self.session.get(m3u8_url, timeout=10)
            if response.status_code == 200:
                content = response.text

                # Parse resolution information
                resolution_pattern = r'RESOLUTION=(\d+x\d+)'
                bandwidth_pattern = r'BANDWIDTH=(\d+)'

                resolutions = re.findall(resolution_pattern, content)
                bandwidths = re.findall(bandwidth_pattern, content)

                # Create quality labels
                for res in set(resolutions):
                    height = res.split('x')[1]
                    qualities.append(f"{height}p")

                qualities.sort(key=lambda x: int(x.replace('p', '')), reverse=True)

        except Exception as e:
            print(f"Error getting qualities: {e}")

        return qualities if qualities else ['Auto']

    def _extract_downloadable_files(self, soup: BeautifulSoup, base_url: str) -> List[DownloadableFile]:
        """Extract downloadable files from the lesson page."""
        files = []

        # Common patterns for download links
        download_selectors = [
            'a[href*=".pdf"]',
            'a[href*=".docx"]',
            'a[href*=".doc"]',
            'a[href*=".xlsx"]',
            'a[href*=".xls"]',
            'a[href*=".pptx"]',
            'a[href*=".ppt"]',
            'a[download]',
            '.attachment a',
            '.download-link',
            'a[href*="download"]',
        ]

        found_urls = set()

        for selector in download_selectors:
            for link in soup.select(selector):
                href = link.get('href', '')
                if not href or href in found_urls:
                    continue

                # Skip video and image files
                if any(ext in href.lower() for ext in ['.mp4', '.webm', '.jpg', '.png', '.gif', '.m3u8']):
                    continue

                full_url = urljoin(base_url, href)
                found_urls.add(href)

                # Determine file type
                file_type = self._get_file_type(href)
                if not file_type:
                    continue

                # Get file name
                name = link.text.strip() or self._get_filename_from_url(href)

                files.append(DownloadableFile(
                    name=name,
                    url=full_url,
                    file_type=file_type
                ))

        return files

    def _get_file_type(self, url: str) -> Optional[str]:
        """Determine file type from URL."""
        url_lower = url.lower()
        extensions = {
            '.pdf': 'pdf',
            '.docx': 'docx',
            '.doc': 'doc',
            '.xlsx': 'xlsx',
            '.xls': 'xls',
            '.pptx': 'pptx',
            '.ppt': 'ppt',
            '.zip': 'zip',
            '.txt': 'txt',
            '.csv': 'csv',
        }

        for ext, file_type in extensions.items():
            if ext in url_lower:
                return file_type

        return None

    def _get_filename_from_url(self, url: str) -> str:
        """Extract filename from URL."""
        parsed = urlparse(url)
        path = parsed.path
        if '/' in path:
            return path.split('/')[-1]
        return "download"


if __name__ == "__main__":
    # Test the scraper (requires valid cookies)
    from cookie_extractor import get_session_cookies

    cookies = get_session_cookies("https://app.ddssuccess.com")
    if cookies:
        scraper = CourseScraper(cookies)
        course = scraper.get_course_info(
            "https://app.ddssuccess.com/courses/art-of-scheduling-productively/lectures/42201128"
        )
        if course:
            print(f"Course: {course.title}")
            print(f"Sections: {len(course.sections)}")
            for section in course.sections:
                print(f"  {section.title}: {len(section.lessons)} lessons")
