import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from youtubesynth.extractors.txt_extractor import extract_from_txt
from youtubesynth.extractors.json_extractor import extract_from_json
from youtubesynth.extractors.xml_extractor import extract_from_xml
from youtubesynth.extractors import extract_urls

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestTxtExtractor:
    def test_extracts_unique_videos(self):
        videos = extract_from_txt(str(FIXTURES / "sample_videos.txt"))
        # All extracted URLs must be unique YouTube video IDs
        ids = [v.video_id for v in videos]
        assert len(ids) == len(set(ids))
        assert len(videos) == 12

    def test_skips_comments(self):
        videos = extract_from_txt(str(FIXTURES / "sample_videos.txt"))
        for v in videos:
            assert not v.url.startswith("#")

    def test_deduplicates(self):
        videos = extract_from_txt(str(FIXTURES / "sample_videos.txt"))
        ids = [v.video_id for v in videos]
        assert len(ids) == len(set(ids))

    def test_filters_non_youtube(self):
        videos = extract_from_txt(str(FIXTURES / "sample_videos.txt"))
        for v in videos:
            assert "youtube.com" in v.url


class TestJsonExtractor:
    def test_extracts_five_videos(self):
        videos = extract_from_json(str(FIXTURES / "sample_videos.json"))
        assert len(videos) == 5

    def test_preserves_titles(self):
        videos = extract_from_json(str(FIXTURES / "sample_videos.json"))
        assert videos[0].title == "Rick Astley - Never Gonna Give You Up"

    def test_array_of_strings(self, tmp_path):
        f = tmp_path / "urls.json"
        f.write_text(json.dumps([
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/9bZkp7q19f0",
        ]))
        videos = extract_from_json(str(f))
        assert len(videos) == 2

    def test_google_takeout_format(self, tmp_path):
        f = tmp_path / "takeout.json"
        f.write_text(json.dumps([
            {"contentDetails": {"videoId": "dQw4w9WgXcQ", "note": "Rick Roll"}},
            {"contentDetails": {"videoId": "9bZkp7q19f0", "note": ""}},
        ]))
        videos = extract_from_json(str(f))
        assert len(videos) == 2
        assert videos[0].video_id == "dQw4w9WgXcQ"


class TestXmlExtractor:
    def test_extracts_five_youtube_videos(self):
        videos = extract_from_xml(str(FIXTURES / "sample_videos.xml"))
        assert len(videos) == 5

    def test_filters_non_youtube(self):
        videos = extract_from_xml(str(FIXTURES / "sample_videos.xml"))
        for v in videos:
            assert "youtube.com" in v.url

    def test_invalid_xml_falls_back_to_bs4(self, tmp_path):
        # Malformed XML that ET cannot parse
        f = tmp_path / "broken.xml"
        f.write_text(
            '<bookmarks><A HREF="https://www.youtube.com/watch?v=dQw4w9WgXcQ">Rick Roll</A>'
            '<A HREF="https://vimeo.com/123">not youtube</A></bookmarks>'
        )
        videos = extract_from_xml(str(f))
        assert len(videos) == 1
        assert videos[0].video_id == "dQw4w9WgXcQ"


class TestDispatcher:
    def test_dispatches_txt_by_extension(self):
        videos = extract_urls(str(FIXTURES / "sample_videos.txt"), max_videos=50)
        assert len(videos) > 0

    def test_dispatches_json_by_extension(self):
        videos = extract_urls(str(FIXTURES / "sample_videos.json"), max_videos=50)
        assert len(videos) == 5

    def test_dispatches_xml_by_extension(self):
        videos = extract_urls(str(FIXTURES / "sample_videos.xml"), max_videos=50)
        assert len(videos) == 5

    def test_max_videos_cap_is_respected(self):
        videos = extract_urls(str(FIXTURES / "sample_videos.json"), max_videos=2)
        assert len(videos) == 2

    def test_dispatcher_deduplicates(self):
        videos = extract_urls(str(FIXTURES / "sample_videos.txt"), max_videos=50)
        ids = [v.video_id for v in videos]
        assert len(ids) == len(set(ids))

    def test_playlist_url_dispatches_to_playlist_extractor(self):
        playlist_url = "https://www.youtube.com/playlist?list=PLtest123"
        mock_videos = [
            MagicMock(video_id="aaaaaaaaa01", url="https://www.youtube.com/watch?v=aaaaaaaaa01", title="V1"),
        ]
        with patch("youtubesynth.extractors.playlist_extractor.extract_from_playlist", return_value=mock_videos) as mock:
            result = extract_urls(playlist_url, max_videos=10)
            mock.assert_called_once_with(playlist_url, max_videos=10)
            assert len(result) == 1
