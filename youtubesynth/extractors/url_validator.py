import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, parse_qs

# Matches all supported YouTube URL patterns.
# (?<![a-zA-Z0-9]) ensures we don't match domains like "notyoutube.com"
# where "youtube.com" is a suffix of a different hostname.
_PATTERNS = [
    # https://www.youtube.com/watch?v=VIDEO_ID
    re.compile(r'(?:https?://)?(?:www\.)?(?<![a-zA-Z0-9])youtube\.com/watch\?.*?v=([A-Za-z0-9_-]{11})'),
    # https://youtu.be/VIDEO_ID
    re.compile(r'(?:https?://)?(?<![a-zA-Z0-9])youtu\.be/([A-Za-z0-9_-]{11})'),
    # https://www.youtube.com/embed/VIDEO_ID
    re.compile(r'(?:https?://)?(?:www\.)?(?<![a-zA-Z0-9])youtube\.com/embed/([A-Za-z0-9_-]{11})'),
    # https://www.youtube.com/shorts/VIDEO_ID
    re.compile(r'(?:https?://)?(?:www\.)?(?<![a-zA-Z0-9])youtube\.com/shorts/([A-Za-z0-9_-]{11})'),
]

_VIDEO_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')


@dataclass
class VideoMeta:
    video_id: str
    url: str
    title: Optional[str] = None
    extra: dict = field(default_factory=dict)


def extract_video_id(url: str) -> Optional[str]:
    """Return the 11-char video ID from any supported YouTube URL, or None."""
    url = url.strip()
    for pattern in _PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def normalize_url(video_id: str) -> str:
    """Return the canonical watch URL for a video ID."""
    return f"https://www.youtube.com/watch?v={video_id}"


def is_youtube_url(url: str) -> bool:
    """Return True if the URL points to a YouTube video."""
    return extract_video_id(url) is not None


def make_video_meta(url: str, title: Optional[str] = None) -> Optional[VideoMeta]:
    """Parse a URL and return a VideoMeta, or None if not a valid YouTube URL."""
    video_id = extract_video_id(url)
    if video_id is None:
        return None
    return VideoMeta(
        video_id=video_id,
        url=normalize_url(video_id),
        title=title,
    )
