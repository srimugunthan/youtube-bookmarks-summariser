import pytest
from youtubesynth.extractors.url_validator import (
    extract_video_id,
    normalize_url,
    is_youtube_url,
    make_video_meta,
    VideoMeta,
)


class TestExtractVideoId:
    def test_watch_url(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_youtu_be_url(self):
        assert extract_video_id("https://youtu.be/9bZkp7q19f0") == "9bZkp7q19f0"

    def test_embed_url(self):
        assert extract_video_id("https://www.youtube.com/embed/M7lc1UVf-VE") == "M7lc1UVf-VE"

    def test_shorts_url(self):
        assert extract_video_id("https://www.youtube.com/shorts/jNQXAC9IVRw") == "jNQXAC9IVRw"

    def test_watch_url_with_extra_params(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PLxxx") == "dQw4w9WgXcQ"

    def test_no_www(self):
        assert extract_video_id("https://youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_non_youtube_url_returns_none(self):
        assert extract_video_id("https://vimeo.com/12345678") is None

    def test_empty_string_returns_none(self):
        assert extract_video_id("") is None

    def test_plain_text_returns_none(self):
        assert extract_video_id("not a url at all") is None

    def test_strips_whitespace(self):
        assert extract_video_id("  https://youtu.be/dQw4w9WgXcQ  ") == "dQw4w9WgXcQ"


class TestNormalizeUrl:
    def test_produces_canonical_watch_url(self):
        assert normalize_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class TestIsYoutubeUrl:
    def test_valid_url_returns_true(self):
        assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_invalid_url_returns_false(self):
        assert is_youtube_url("https://example.com") is False


class TestMakeVideoMeta:
    def test_returns_video_meta_for_valid_url(self):
        vm = make_video_meta("https://www.youtube.com/watch?v=dQw4w9WgXcQ", title="Rick Roll")
        assert isinstance(vm, VideoMeta)
        assert vm.video_id == "dQw4w9WgXcQ"
        assert vm.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert vm.title == "Rick Roll"

    def test_returns_none_for_invalid_url(self):
        assert make_video_meta("https://example.com/notaytvideo") is None

    def test_url_is_normalized(self):
        vm = make_video_meta("https://youtu.be/dQw4w9WgXcQ")
        assert vm.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_title_defaults_to_none(self):
        vm = make_video_meta("https://youtu.be/dQw4w9WgXcQ")
        assert vm.title is None
