from typing import List

from youtubesynth.extractors.url_validator import VideoMeta, make_video_meta


def extract_from_txt(path: str) -> List[VideoMeta]:
    """
    Extract YouTube VideoMeta entries from a plain-text file.

    Rules:
      - Lines starting with '#' are comments and are skipped.
      - Blank lines are skipped.
      - Duplicates (same video_id) are deduplicated; first occurrence wins.
      - Non-YouTube URLs are silently filtered out.
    """
    seen: set = set()
    results: List[VideoMeta] = []
    prev_line: str = ""

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            vm = make_video_meta(line)
            if vm:
                if vm.video_id not in seen:
                    title = prev_line.removesuffix(" - YouTube").strip() or None
                    vm = make_video_meta(line, title=title)
                    seen.add(vm.video_id)
                    results.append(vm)
                prev_line = ""
            else:
                prev_line = line

    return results
