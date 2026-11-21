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
    def test_authorization_request_returns_google_url_and_state(self):
        class FakeFlow:
            redirect_uri = None

            def authorization_url(self, **kwargs):
                self.authorization_args = kwargs
                return "https://accounts.google.com/authorize?client=test", "state-123"

        fake_flow = FakeFlow()
        with tempfile.TemporaryDirectory() as temp_dir:
            client_file = Path(temp_dir) / "client_secret.json"
            client_file.write_text("{}", encoding="utf-8")
            with patch("youtube_api.CLIENT_SECRET_PATH", client_file), patch(
                "youtube_api.InstalledAppFlow.from_client_secrets_file",
                return_value=fake_flow,
            ) as from_file:
                flow, authorization_url, state = youtube_api.create_authorization_request(
                    "http://127.0.0.1:5000"
                )

        self.assertIs(flow, fake_flow)
        self.assertEqual(authorization_url, "https://accounts.google.com/authorize?client=test")
        self.assertEqual(state, "state-123")
        self.assertEqual(fake_flow.redirect_uri, "http://127.0.0.1:5000")
        self.assertEqual(fake_flow.authorization_args["access_type"], "offline")
        self.assertEqual(fake_flow.authorization_args["prompt"], "consent")
        from_file.assert_called_once_with(str(client_file), youtube_api.SCOPES)

    def test_callback_checks_state_and_saves_credentials(self):
        class FakeFlow:
            credentials = object()

            def fetch_token(self, **kwargs):
                self.authorization_response = kwargs["authorization_response"]

        fake_flow = FakeFlow()
        callback = "http://127.0.0.1:5000/?code=abc&state=state-123"
        with patch("youtube_api._save_credentials") as save:
            credentials = youtube_api.complete_authorization(
                fake_flow, "state-123", callback
            )

        self.assertIs(credentials, fake_flow.credentials)
        self.assertEqual(fake_flow.authorization_response, callback)
        save.assert_called_once_with(fake_flow.credentials)

    def test_callback_rejects_wrong_state(self):
        with self.assertRaises(youtube_api.YouTubeApiAuthenticationRequired):
            youtube_api.complete_authorization(
                object(),
                "expected",
                "http://127.0.0.1:5000/?code=abc&state=wrong",
            )

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
