import json
from typing import Any, List, Optional

from youtubesynth.extractors.url_validator import VideoMeta, make_video_meta


def extract_from_json(path: str) -> List[VideoMeta]:
    """
    Extract YouTube VideoMeta entries from a JSON file.

    Handles these schemas:
      - Array of strings:           ["url1", "url2", ...]
      - Array of objects:           [{"url": "...", "title": "..."}, ...]
      - Top-level "videos" key:     {"videos": [...]}
      - Google Takeout format:      [{"contentDetails": {"videoId": "...", "note": "..."}}]
      - Any nested structure:       recursively walks the tree looking for YouTube URLs
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results: List[VideoMeta] = []
    seen: set = set()

    def add(vm: Optional[VideoMeta]) -> None:
        if vm and vm.video_id not in seen:
            seen.add(vm.video_id)
            results.append(vm)

    def walk(node: Any) -> None:
        if isinstance(node, str):
            add(make_video_meta(node))
        elif isinstance(node, dict):
            # Google Takeout: {"contentDetails": {"videoId": "..."}}
            content = node.get("contentDetails")
            if isinstance(content, dict) and "videoId" in content:
                video_id = content["videoId"]
                note = content.get("note") or node.get("title")
                add(make_video_meta(f"https://www.youtube.com/watch?v={video_id}", note))
                return

            # Explicit url/link field
            url = node.get("url") or node.get("link") or node.get("href") or ""
            title = node.get("title") or node.get("name")
            if url:
                add(make_video_meta(url, title))
            else:
                for v in node.values():
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    # Unwrap common top-level wrappers
    if isinstance(data, dict) and "videos" in data:
        walk(data["videos"])
    else:
        walk(data)

    return results
