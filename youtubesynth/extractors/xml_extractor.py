import xml.etree.ElementTree as ET
from typing import List

from youtubesynth.extractors.url_validator import VideoMeta, make_video_meta


def extract_from_xml(path: str) -> List[VideoMeta]:
    """
    Extract YouTube VideoMeta entries from an XML bookmark file.

    Tries stdlib ElementTree first; falls back to BeautifulSoup for
    malformed/HTML-style XML (e.g. Netscape bookmark format).
    Non-YouTube URLs are silently filtered out.
    """
    try:
        return _parse_with_et(path)
    except ET.ParseError:
        return _parse_with_bs4(path)


def _parse_with_et(path: str) -> List[VideoMeta]:
    tree = ET.parse(path)
    root = tree.getroot()
    results: List[VideoMeta] = []
    for elem in root.iter():
        url = elem.get("HREF") or elem.get("href") or elem.get("url") or elem.text or ""
        title = elem.get("title") or elem.get("ADD_DATE") and None or None
        # Also try to get title from the element's own text if it's an <A> tag
        if elem.tag in ("A", "a") and elem.text:
            title = elem.text.strip() or None
            url = elem.get("HREF") or elem.get("href") or ""
        vm = make_video_meta(url.strip(), title)
        if vm:
            results.append(vm)
    return results


def _parse_with_bs4(path: str) -> List[VideoMeta]:
    from bs4 import BeautifulSoup

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    results: List[VideoMeta] = []
    for tag in soup.find_all(True):
        url = tag.get("href") or tag.get("url") or ""
        title = tag.get_text(strip=True) or None
        vm = make_video_meta(url.strip(), title)
        if vm:
            results.append(vm)
    return results
