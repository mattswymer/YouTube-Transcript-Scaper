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

    def test_home_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"D&amp;D Session Transcript Scraper", response.data)

    def test_rejects_more_than_ten_links(self):
        response = self.client.post("/", data={"urls": "\n".join(["abcdefghijk"] * 11)})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"limit each batch to 10", response.data)

    def test_invalid_url_is_explained_in_download(self):
        response = self.client.post("/", data={"urls": "https://example.com/not-a-video"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"INVALID YOUTUBE URL", response.data)
        self.assertIn(b"valid YouTube video link", response.data)

    def test_successful_transcript_download(self):
        snippets = [SimpleNamespace(start=0, text="A transcript line.")]

        class FakeApi:
            def fetch(self, video_id, languages):
                self.asserted_video_id = video_id
                self.asserted_languages = languages
                return snippets

        fake_api = FakeApi()
        with patch("app.YouTubeTranscriptApi", return_value=fake_api):
            with patch("app.time.sleep"):
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
