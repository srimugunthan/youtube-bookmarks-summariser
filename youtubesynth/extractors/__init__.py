import re
from typing import List

from youtubesynth.extractors.url_validator import VideoMeta

_PLAYLIST_URL_RE = re.compile(
    r'(?:https?://)?(?:www\.)?youtube\.com/playlist\?'
    r'|(?:https?://)?(?:www\.)?youtube\.com/.*[?&]list='
)


def extract_urls(source: str, max_videos: int = 50) -> List[VideoMeta]:
    """
    Unified dispatcher. Accepts a file path or a YouTube playlist URL.

    Dispatch rules (in order):
      1. If source matches a YouTube playlist URL pattern → playlist_extractor
      2. Else by file extension:
         .xml        → xml_extractor
         .json       → json_extractor
         .txt / .csv → txt_extractor
         (unknown)   → txt_extractor as fallback

    Deduplication: videos with the same video_id are deduplicated;
    first occurrence wins. The result is capped at max_videos.
    """
    if _PLAYLIST_URL_RE.search(source):
        from youtubesynth.extractors.playlist_extractor import extract_from_playlist
        videos = extract_from_playlist(source, max_videos=max_videos)
    else:
        ext = source.rsplit(".", 1)[-1].lower() if "." in source else ""
        if ext == "xml":
            from youtubesynth.extractors.xml_extractor import extract_from_xml
            videos = extract_from_xml(source)
        elif ext == "json":
            from youtubesynth.extractors.json_extractor import extract_from_json
            videos = extract_from_json(source)
        else:
            from youtubesynth.extractors.txt_extractor import extract_from_txt
            videos = extract_from_txt(source)

    # Deduplicate (extractors do their own dedup, but guard at the boundary too)
    seen: set = set()
    unique: List[VideoMeta] = []
    for v in videos:
        if v.video_id not in seen:
            seen.add(v.video_id)
            unique.append(v)

    return unique[:max_videos]
