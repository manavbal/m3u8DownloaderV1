"""
Course Scraper for DDS Downloader
Parses Teachable course pages to extract structure, videos, and downloadable files.
"""

import re
import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Set
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
        # Track seen URLs to avoid duplicates
        self._seen_urls: Set[str] = set()

    def get_course_info(self, url: str, progress_callback: Optional[Callable] = None) -> Optional[Course]:
        """
        Extract complete course information from a course or lecture URL.
        """
        try:
            # Reset seen URLs for new course scan
            self._seen_urls = set()

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
            '.course-name',
            '[data-course-title]',
        ]

        for selector in selectors:
            element = soup.select_one(selector)
            if element and element.text.strip():
                title = element.text.strip()
                # Clean up the title
                title = re.sub(r'\s+', ' ', title)
                return title

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

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        # Remove trailing slashes and query params for comparison
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip('/')

    def _parse_curriculum(self, soup: BeautifulSoup, base_url: str) -> List[Section]:
        """Parse the course curriculum from the sidebar."""
        sections = []
        self._seen_urls = set()

        # Look for the course sidebar/curriculum structure
        # Teachable typically uses a specific structure

        # Find all section headers
        section_headers = soup.select('.course-section .section-title, .section-header, [class*="section-title"]')

        if section_headers:
            # Parse structured sections
            current_section_elem = None
            for header in section_headers:
                # Find the parent section container
                section_container = header.find_parent(class_=lambda x: x and ('section' in x.lower() if x else False))
                if section_container:
                    section = self._parse_section_container(section_container, base_url, len(sections))
                    if section and section.lessons:
                        sections.append(section)

        # If no structured sections found, try flat list
        if not sections:
            sections = self._parse_flat_lecture_list(soup, base_url)

        return sections

    def _parse_section_container(self, container, base_url: str, section_idx: int) -> Optional[Section]:
        """Parse a section container element."""
        # Get section title
        title_elem = container.select_one('.section-title, .section-header, h3, h4')
        section_title = title_elem.text.strip() if title_elem else f"Section {section_idx + 1}"

        # Clean up section title
        section_title = re.sub(r'\s+', ' ', section_title).strip()

        # Get lessons in this section - look for lecture links
        lesson_links = container.select('a[href*="/lectures/"]')

        lessons = []
        for link in lesson_links:
            lesson = self._parse_lesson_item(link, base_url, len(lessons))
            if lesson:
                lessons.append(lesson)

        if lessons:
            return Section(title=section_title, lessons=lessons, order=section_idx)

        return None

    def _parse_flat_lecture_list(self, soup: BeautifulSoup, base_url: str) -> List[Section]:
        """Parse a flat list of lectures, grouping by section headers."""
        sections = []
        current_section = None

        # Find all lecture links
        all_links = soup.select('a[href*="/lectures/"]')

        for link in all_links:
            # Check if there's a section header before this link
            parent = link.find_parent(['li', 'div'])
            if parent:
                # Look for a preceding section header
                prev_siblings = list(parent.find_previous_siblings(['h3', 'h4', 'div']))
                for sib in prev_siblings:
                    if 'section' in ' '.join(sib.get('class', [])).lower():
                        section_title = sib.get_text(strip=True)
                        if current_section is None or current_section.title != section_title:
                            if current_section and current_section.lessons:
                                sections.append(current_section)
                            current_section = Section(title=section_title, order=len(sections))
                        break

            if current_section is None:
                current_section = Section(title="Course Content", order=0)

            lesson = self._parse_lesson_item(link, base_url, len(current_section.lessons))
            if lesson:
                current_section.lessons.append(lesson)

        if current_section and current_section.lessons:
            sections.append(current_section)

        # If still no sections, create one with all lessons
        if not sections:
            all_lessons = []
            for link in all_links:
                lesson = self._parse_lesson_item(link, base_url, len(all_lessons))
                if lesson:
                    all_lessons.append(lesson)
            if all_lessons:
                sections.append(Section(title="Course Content", lessons=all_lessons, order=0))

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

        # Normalize and check for duplicates
        normalized_url = self._normalize_url(url)
        if normalized_url in self._seen_urls:
            return None  # Skip duplicate
        self._seen_urls.add(normalized_url)

        # Get title - try multiple approaches
        title = ""

        # Method 1: Direct link text
        title = link.get_text(strip=True)

        # Method 2: Look for title in child elements
        if not title or len(title) < 3:
            title_elem = link.select_one('.lecture-name, .item-title, span')
            if title_elem:
                title = title_elem.get_text(strip=True)

        # Clean up title - remove duration if embedded
        duration = ""
        duration_match = re.search(r'\((\d+:\d+)\)', title)
        if duration_match:
            duration = duration_match.group(1)
            title = re.sub(r'\s*\(\d+:\d+\)\s*', '', title).strip()

        # Also look for duration in nearby elements
        if not duration:
            parent = link.find_parent(['li', 'div'])
            if parent:
                duration_elem = parent.select_one('.duration, .lecture-duration, [class*="time"]')
                if duration_elem:
                    dur_text = duration_elem.get_text(strip=True)
                    dur_match = re.search(r'(\d+:\d+)', dur_text)
                    if dur_match:
                        duration = dur_match.group(1)

        # Clean up title
        title = re.sub(r'\s+', ' ', title).strip()

        if not title:
            # Extract from URL as fallback
            match = re.search(r'/lectures/(\d+)', url)
            if match:
                title = f"Lecture {match.group(1)}"
            else:
                title = f"Lesson {order + 1}"

        return Lesson(
            title=title,
            url=url,
            duration=duration,
            order=order,
            is_video=True  # Assume video by default
        )

    def get_lesson_details(self, lesson: Lesson, progress_callback: Optional[Callable] = None) -> Lesson:
        """
        Fetch detailed information for a lesson including M3U8 URL and downloadable files.
        """
        try:
            print(f"Fetching details for: {lesson.title}")
            response = self.session.get(lesson.url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'lxml')
            html_content = response.text

            # Extract M3U8 URL
            m3u8_url = self._extract_m3u8_url(soup, html_content)
            if m3u8_url:
                print(f"  Found M3U8: {m3u8_url[:80]}...")
                lesson.m3u8_url = m3u8_url
                lesson.available_qualities = self._get_available_qualities(m3u8_url)
            else:
                print(f"  No M3U8 found for: {lesson.title}")

            # Extract downloadable files
            lesson.downloadable_files = self._extract_downloadable_files(soup, lesson.url)
            if lesson.downloadable_files:
                print(f"  Found {len(lesson.downloadable_files)} downloadable files")

        except Exception as e:
            print(f"Error getting lesson details for {lesson.title}: {e}")

        return lesson

    def _extract_m3u8_url(self, soup: BeautifulSoup, html_content: str) -> Optional[str]:
        """Extract the M3U8 URL from the page."""

        # Method 1: Look for Wistia embed (most common on Teachable)
        # Pattern 1: wistia_async_XXXXX class
        wistia_class_match = re.search(r'wistia_async_([a-zA-Z0-9]+)', html_content)
        if wistia_class_match:
            media_id = wistia_class_match.group(1)
            print(f"  Found Wistia ID (class): {media_id}")
            m3u8 = self._get_wistia_m3u8(media_id)
            if m3u8:
                return m3u8

        # Pattern 2: wistia.com/embed/medias/XXXXX
        wistia_embed_match = re.search(r'wistia\.com/embed/medias/([a-zA-Z0-9]+)', html_content)
        if wistia_embed_match:
            media_id = wistia_embed_match.group(1)
            print(f"  Found Wistia ID (embed): {media_id}")
            m3u8 = self._get_wistia_m3u8(media_id)
            if m3u8:
                return m3u8

        # Pattern 3: Wistia JSON config
        wistia_json_match = re.search(r'"hashedId"\s*:\s*"([a-zA-Z0-9]+)"', html_content)
        if wistia_json_match:
            media_id = wistia_json_match.group(1)
            print(f"  Found Wistia ID (JSON): {media_id}")
            m3u8 = self._get_wistia_m3u8(media_id)
            if m3u8:
                return m3u8

        # Method 2: Look for direct M3U8 URL in the page
        m3u8_patterns = [
            r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
            r'"file"\s*:\s*"([^"]+\.m3u8[^"]*)"',
            r'"src"\s*:\s*"([^"]+\.m3u8[^"]*)"',
            r'"hls"\s*:\s*"([^"]+)"',
            r'"m3u8"\s*:\s*"([^"]+)"',
        ]

        for pattern in m3u8_patterns:
            match = re.search(pattern, html_content)
            if match:
                url = match.group(1)
                if '.m3u8' in url or 'hls' in url.lower():
                    print(f"  Found direct M3U8: {url[:60]}...")
                    return url

        # Method 3: Look for video data attributes
        video_elem = soup.select_one('[data-video-url], [data-m3u8], video source[src*=".m3u8"]')
        if video_elem:
            url = video_elem.get('data-video-url') or video_elem.get('data-m3u8') or video_elem.get('src')
            if url:
                print(f"  Found video data attr: {url[:60]}...")
                return url

        # Method 4: Look in script tags for video config
        for script in soup.select('script'):
            if script.string:
                script_text = script.string

                # Look for Wistia media ID in script
                wistia_script_match = re.search(r'Wistia\.embed\(["\']([a-zA-Z0-9]+)["\']', script_text)
                if wistia_script_match:
                    media_id = wistia_script_match.group(1)
                    print(f"  Found Wistia ID (script): {media_id}")
                    m3u8 = self._get_wistia_m3u8(media_id)
                    if m3u8:
                        return m3u8

        return None

    def _get_wistia_m3u8(self, media_id: str) -> Optional[str]:
        """Get M3U8 URL from Wistia media ID."""
        try:
            # Wistia's embed info endpoint
            info_url = f"https://fast.wistia.com/embed/medias/{media_id}.json"
            print(f"  Fetching Wistia info: {info_url}")

            response = self.session.get(info_url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                media = data.get('media', {})
                assets = media.get('assets', [])

                # Find the HLS/M3U8 asset
                for asset in assets:
                    asset_type = asset.get('type', '')
                    url = asset.get('url', '')

                    if asset_type == 'hls' or asset_type == 'm3u8':
                        print(f"  Found HLS asset: {url[:60]}...")
                        return url

                    if '.m3u8' in url:
                        print(f"  Found M3U8 in asset: {url[:60]}...")
                        return url

                # If no HLS found, look for original or mp4
                print(f"  Available asset types: {[a.get('type') for a in assets]}")

                # Try to construct HLS URL from other assets
                for asset in assets:
                    if asset.get('type') == 'original':
                        # Wistia HLS URL pattern
                        hls_url = f"https://fast.wistia.com/embed/medias/{media_id}.m3u8"
                        return hls_url

            else:
                print(f"  Wistia API returned status: {response.status_code}")

        except Exception as e:
            print(f"  Error getting Wistia M3U8: {e}")

        return None

    def _get_available_qualities(self, m3u8_url: str) -> List[str]:
        """Get available quality options from the master M3U8 playlist."""
        qualities = []

        try:
            response = self.session.get(m3u8_url, timeout=10)
            if response.status_code == 200:
                content = response.text

                # Parse resolution information
                resolution_pattern = r'RESOLUTION=(\d+)x(\d+)'
                matches = re.findall(resolution_pattern, content)

                for width, height in matches:
                    qualities.append(f"{height}p")

                # Remove duplicates and sort
                qualities = list(set(qualities))
                qualities.sort(key=lambda x: int(x.replace('p', '')), reverse=True)

        except Exception as e:
            print(f"Error getting qualities: {e}")

        return qualities if qualities else ['Auto']

    def _extract_downloadable_files(self, soup: BeautifulSoup, base_url: str) -> List[DownloadableFile]:
        """Extract downloadable files from the lesson page."""
        files = []
        found_urls = set()

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
        ]

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
                name = link.get_text(strip=True) or self._get_filename_from_url(href)

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
                for lesson in section.lessons:
                    print(f"    - {lesson.title} ({lesson.duration})")
