from typing import List

from youtubesynth.extractors.url_validator import VideoMeta, normalize_url


def extract_from_playlist(url: str, max_videos: int = 50) -> List[VideoMeta]:
    """
    Extract VideoMeta entries from a YouTube playlist URL using yt-dlp.

    Uses the yt-dlp Python API (no subprocess). Respects `max_videos` cap.
    Does not download any media — metadata only.
    """
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,   # metadata only, no download
        "playlistend": max_videos,
    }

    results: List[VideoMeta] = []

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            return results

        entries = info.get("entries") or []
        for entry in entries[:max_videos]:
            if entry is None:
                continue
            video_id = entry.get("id")
            if not video_id:
                continue
            title = entry.get("title")
            results.append(VideoMeta(
                video_id=video_id,
                url=normalize_url(video_id),
                title=title,
            ))

    return results
