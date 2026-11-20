import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httplib2
from googleapiclient.errors import HttpError

import youtube_api


class CaptionTrackSelectionTests(unittest.TestCase):
    def test_prefers_requested_language_and_standard_track_over_asr(self):
        tracks = [
            {"id": "spanish", "snippet": {"language": "es", "trackKind": "standard"}},
            {"id": "english-asr", "snippet": {"language": "en", "trackKind": "ASR"}},
            {"id": "english-manual", "snippet": {"language": "en", "trackKind": "standard"}},
        ]

        selected = youtube_api.choose_caption_track(tracks, ["en", "es"])
        self.assertEqual(selected["id"], "english-manual")

    def test_uses_asr_when_it_is_the_available_requested_track(self):
        tracks = [
            {"id": "spanish", "snippet": {"language": "es", "trackKind": "standard"}},
            {"id": "english-asr", "snippet": {"language": "en", "trackKind": "ASR"}},
        ]

        selected = youtube_api.choose_caption_track(tracks, ["en"])
        self.assertEqual(selected["id"], "english-asr")

    def test_ignores_draft_and_failed_tracks(self):
        tracks = [
            {
                "id": "draft",
                "snippet": {"language": "en", "trackKind": "standard", "isDraft": True},
            },
            {
                "id": "failed",
                "snippet": {"language": "en", "trackKind": "standard", "status": "failed"},
            },
        ]

        self.assertIsNone(youtube_api.choose_caption_track(tracks, ["en"]))


class CaptionDownloadTests(unittest.TestCase):
    def test_lists_and_downloads_selected_caption_as_webvtt(self):
        class FakeRequest:
            def execute(self):
                return {
                    "items": [
                        {
                            "id": "track-123",
                            "snippet": {
                                "language": "en",
                                "trackKind": "ASR",
                                "status": "serving",
                            },
                        }
                    ]
                }

        class FakeCaptions:
            def __init__(self):
                self.list_args = None
                self.download_args = None

            def list(self, **kwargs):
                self.list_args = kwargs
                return FakeRequest()

            def download(self, **kwargs):
                self.download_args = kwargs
                return object()

        class FakeService:
            def __init__(self):
                self.resource = FakeCaptions()

            def captions(self):
                return self.resource

        class FakeDownloader:
            def __init__(self, output, request):
                self.output = output
                self.finished = False

            def next_chunk(self):
                if not self.finished:
                    self.output.write(
                        b"WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nA caption.\n"
                    )
                    self.finished = True
                return None, True

        service = FakeService()
        with patch("youtube_api.MediaIoBaseDownload", FakeDownloader):
            result = youtube_api.download_caption_file(
                "abcdefghijk",
                languages=["en"],
                service=service,
            )

        self.assertIn("A caption.", result)
        self.assertEqual(
            service.resource.list_args,
            {"part": "snippet", "videoId": "abcdefghijk"},
        )
        self.assertEqual(
            service.resource.download_args,
            {"id": "track-123", "tfmt": "vtt"},
        )

    def test_no_matching_language_raises_caption_track_unavailable(self):
        class FakeRequest:
            def execute(self):
                return {
                    "items": [
                        {
                            "id": "spanish",
                            "snippet": {"language": "es", "trackKind": "standard"},
                        }
                    ]
                }

        class FakeCaptions:
            def list(self, **kwargs):
                return FakeRequest()

            def download(self, **kwargs):
                raise AssertionError("A non-matching track must not be downloaded")

        class FakeService:
            def captions(self):
                return FakeCaptions()

        with self.assertRaises(youtube_api.CaptionTrackUnavailable):
            youtube_api.download_caption_file(
                "abcdefghijk", languages=["en"], service=FakeService()
            )


class OAuthStateTests(unittest.TestCase):
    def test_missing_client_file_reports_setup_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "client_secret.json"
            with patch("youtube_api.CLIENT_SECRET_PATH", missing):
                status = youtube_api.get_connection_status()

        self.assertFalse(status["configured"])
        self.assertFalse(status["connected"])

    def test_quota_error_is_classified_for_batch_resume(self):
        response = httplib2.Response({"status": "403", "reason": "Forbidden"})
        error = HttpError(
            response,
            b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}',
        )

        with self.assertRaises(youtube_api.YouTubeApiQuotaExceeded):
            youtube_api._raise_api_error(error)


if __name__ == "__main__":
    unittest.main()
