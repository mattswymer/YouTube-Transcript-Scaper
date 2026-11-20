import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app


class VideoIdTests(unittest.TestCase):
    def test_supported_youtube_url_formats(self):
        cases = [
            ("https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk"),
            ("https://youtu.be/abcdefghijk?t=90", "abcdefghijk"),
            ("youtube.com/watch?feature=share&v=abcdefghijk", "abcdefghijk"),
            ("https://www.youtube.com/shorts/abcdefghijk", "abcdefghijk"),
            ("https://www.youtube.com/live/abcdefghijk", "abcdefghijk"),
            ("https://www.youtube.com/embed/abcdefghijk", "abcdefghijk"),
            ("abcdefghijk", "abcdefghijk"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(app.extract_video_id(value), expected)

    def test_rejects_invalid_ids_and_untrusted_hosts(self):
        cases = [
            "",
            "not a URL",
            "https://youtube.com.example.org/watch?v=abcdefghijk",
            "https://example.com/watch?v=abcdefghijk",
            "https://www.youtube.com/watch?v=too-short",
            "https://www.youtube.com/channel/abcdefghijk",
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertIsNone(app.extract_video_id(value))


class PlaylistUrlTests(unittest.TestCase):
    def test_extracts_playlist_id_from_playlist_and_watch_urls(self):
        cases = [
            ("https://www.youtube.com/playlist?list=PLabcdefghij", "PLabcdefghij"),
            (
                "https://www.youtube.com/watch?v=abcdefghijk&list=PLabcdefghij",
                "PLabcdefghij",
            ),
            ("youtube.com/playlist?list=PLabcdefghij", "PLabcdefghij"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(app.extract_playlist_id(value), expected)

    def test_rejects_urls_without_a_valid_playlist_id(self):
        cases = [
            "",
            "https://example.com/playlist?list=PLabcdefghij",
            "https://youtube.com/playlist?list=short",
            "https://youtube.com/watch?v=abcdefghijk",
            "https://youtube.com.evil.example/playlist?list=PLabcdefghij",
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertIsNone(app.extract_playlist_id(value))

    def test_playlist_metadata_is_read_flat_without_downloading(self):
        playlist_info = {
            "title": "Monday Campaign",
            "playlist_count": 3,
            "entries": [
                {
                    "id": "abcdefghijk",
                    "title": "Session One",
                    "duration": 3661,
                    "playlist_index": 1,
                },
                None,
                {
                    "id": "lmnopqrstuv",
                    "title": "Session Two",
                    "duration": 61,
                    "playlist_index": 3,
                },
            ],
        }

        class FakeYoutubeDL:
            options = None

            def __init__(self, options):
                FakeYoutubeDL.options = options

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download):
                self.url = url
                self.download = download
                return playlist_info

        with patch("app.YoutubeDL", FakeYoutubeDL):
            result = app.fetch_playlist_entries(
                "https://www.youtube.com/playlist?list=PLabcdefghij"
            )

        self.assertEqual(result["title"], "Monday Campaign")
        self.assertEqual([item["video_id"] for item in result["entries"]], [
            "abcdefghijk", "lmnopqrstuv"
        ])
        self.assertEqual(result["entries"][0]["duration_display"], "01:01:01")
        self.assertEqual(result["entries"][1]["playlist_index"], 3)
        self.assertIn("1 unavailable", result["warning"])
        self.assertTrue(FakeYoutubeDL.options["skip_download"])
        self.assertEqual(FakeYoutubeDL.options["extract_flat"], "in_playlist")
        self.assertEqual(FakeYoutubeDL.options["playlistend"], app.MAX_PLAYLIST_ENTRIES)

    def test_invalid_playlist_link_does_not_call_ytdlp(self):
        with patch("app.YoutubeDL") as ytdlp:
            with self.assertRaises(ValueError):
                app.fetch_playlist_entries("https://example.com/playlist?list=PLabcdefghij")
        ytdlp.assert_not_called()


class LanguageTests(unittest.TestCase):
    def test_default_language(self):
        self.assertEqual(app.parse_languages(""), ["en"])
        self.assertEqual(app.parse_languages("   "), ["en"])

    def test_parses_priority_and_removes_duplicates(self):
        self.assertEqual(app.parse_languages("en, es;en fr"), ["en", "es", "fr"])

    def test_rejects_malformed_language_codes(self):
        with self.assertRaises(ValueError):
            app.parse_languages("english, @@")


class TranscriptFormattingTests(unittest.TestCase):
    def setUp(self):
        self.snippets = [
            SimpleNamespace(start=0, text="First line"),
            SimpleNamespace(start=20, text="second\nline"),
            SimpleNamespace(start=61, text="third"),
            SimpleNamespace(start=122, text="fourth"),
        ]

    def test_timestamps_are_added_at_roughly_one_minute_intervals(self):
        snippets = self.snippets

        class FakeApi:
            def fetch(self, video_id, languages):
                self.video_id = video_id
                self.languages = languages
                return snippets

        api = FakeApi()
        result = app.fetch_single_transcript(api, "abcdefghijk", True, ["en", "es"])

        self.assertEqual(api.video_id, "abcdefghijk")
        self.assertEqual(api.languages, ["en", "es"])
        self.assertEqual(
            result,
            "[00:00:00]\nFirst line second line\n[00:01:01]\nthird\n[00:02:02]\nfourth",
        )

    def test_timestamps_can_be_disabled(self):
        snippets = self.snippets

        class FakeApi:
            def fetch(self, video_id, languages):
                return snippets

        result = app.fetch_single_transcript(FakeApi(), "abcdefghijk", False)
        self.assertEqual(result, "First line second line third fourth")


class FlaskRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_home_page_loads_with_playlist_and_individual_options(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"D&amp;D Session Transcript Scraper", response.data)
        self.assertIn(b"Load playlist videos", response.data)
        self.assertIn(b"Paste individual video links", response.data)

    def test_rejects_more_than_ten_individual_links(self):
        response = self.client.post("/", data={"urls": "\n".join(["abcdefghijk"] * 11)})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"limit individual-link batches to 10", response.data)

    def test_load_playlist_shows_video_selection(self):
        playlist = {
            "title": "Monday Campaign",
            "entries": [
                {
                    "video_id": "abcdefghijk",
                    "title": "Session One",
                    "duration_display": "01:00:00",
                    "playlist_index": 1,
                },
                {
                    "video_id": "lmnopqrstuv",
                    "title": "Session Two",
                    "duration_display": "00:45:00",
                    "playlist_index": 2,
                },
            ],
            "warning": "",
        }
        with patch("app.fetch_playlist_entries", return_value=playlist):
            response = self.client.post(
                "/load-playlist",
                data={
                    "playlist_url": "https://www.youtube.com/playlist?list=PLabcdefghij",
                    "languages": "en",
                    "timestamps": "on",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Monday Campaign", response.data)
        self.assertIn(b"Session One", response.data)
        self.assertIn(b"Session Two", response.data)
        self.assertIn(b"Select all", response.data)

    def test_rejects_invalid_playlist_before_extraction(self):
        with patch("app.fetch_playlist_entries") as fetch:
            response = self.client.post(
                "/load-playlist",
                data={"playlist_url": "https://example.com/playlist?list=PLabcdefghij"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"valid YouTube playlist link", response.data)
        fetch.assert_not_called()

    def test_downloads_only_selected_playlist_videos_in_playlist_order(self):
        snippets = [SimpleNamespace(start=0, text="Transcript text.")]

        class FakeApi:
            def fetch(self, video_id, languages):
                return snippets

        with patch("app.YouTubeTranscriptApi", return_value=FakeApi()):
            with patch("app.time.sleep"):
                response = self.client.post(
                    "/download-playlist",
                    data={
                        "playlist_title": "Monday Campaign",
                        "playlist_url": "https://www.youtube.com/playlist?list=PLabcdefghij",
                        "languages": "en",
                        "timestamps": "on",
                        "playlist_video_ids": ["abcdefghijk", "lmnopqrstuv"],
                        "selected_video_ids": ["lmnopqrstuv", "abcdefghijk"],
                        "title__abcdefghijk": "Session One",
                        "title__lmnopqrstuv": "Session Two",
                        "duration__abcdefghijk": "01:00:00",
                        "duration__lmnopqrstuv": "00:45:00",
                    },
                )

        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertIn("Playlist: Monday Campaign", content)
        self.assertIn("Session One", content)
        self.assertIn("Session Two", content)
        self.assertLess(content.index("Session One"), content.index("Session Two"))
        self.assertEqual(response.mimetype, "text/plain")

    def test_playlist_download_requires_a_selection(self):
        response = self.client.post(
            "/download-playlist",
            data={
                "playlist_title": "Monday Campaign",
                "playlist_video_ids": ["abcdefghijk"],
                "selected_video_ids": [],
                "title__abcdefghijk": "Session One",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Select at least one video", response.data)

    def test_successful_individual_transcript_download(self):
        snippets = [SimpleNamespace(start=0, text="A transcript line.")]

        class FakeApi:
            def fetch(self, video_id, languages):
                self.asserted_video_id = video_id
                self.asserted_languages = languages
                return snippets

        fake_api = FakeApi()
        with patch("app.YouTubeTranscriptApi", return_value=fake_api):
            response = self.client.post(
                "/",
                data={
                    "urls": "https://youtu.be/abcdefghijk",
                    "languages": "en, es",
                    "timestamps": "on",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertIn(b"A transcript line.", response.data)
        self.assertIn(b"[00:00:00]", response.data)
        self.assertEqual(fake_api.asserted_languages, ["en", "es"])


if __name__ == "__main__":
    unittest.main()
