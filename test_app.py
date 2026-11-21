import json
import tempfile
import unittest
from pathlib import Path
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
            ("https://www.youtube.com/playlist?list=WL", "WL"),
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
            "https://youtube.com/playlist?list=s",
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
        self.assertEqual(
            [item["video_id"] for item in result["entries"]],
            ["abcdefghijk", "lmnopqrstuv"],
        )
        self.assertEqual(result["entries"][0]["duration_display"], "01:01:01")
        self.assertEqual(result["entries"][1]["playlist_index"], 3)
        self.assertIn("1 unavailable", result["warning"])
        self.assertTrue(FakeYoutubeDL.options["skip_download"])
        self.assertEqual(FakeYoutubeDL.options["extract_flat"], "in_playlist")
        self.assertEqual(FakeYoutubeDL.options["playlistend"], app.MAX_PLAYLIST_ENTRIES)

    def test_browser_cookies_are_added_only_when_requested(self):
        options = {"quiet": True}
        app.apply_browser_cookies(options, "chrome")
        self.assertEqual(options["cookiesfrombrowser"], ("chrome", None, None, None))

        options = {"quiet": True}
        app.apply_browser_cookies(options, "")
        self.assertNotIn("cookiesfrombrowser", options)

    def test_invalid_playlist_link_does_not_call_ytdlp(self):
        with patch("app.YoutubeDL") as ytdlp:
            with self.assertRaises(ValueError):
                app.fetch_playlist_entries("https://example.com/playlist?list=PLabcdefghij")
        ytdlp.assert_not_called()


class SubtitleParsingTests(unittest.TestCase):
    def test_vtt_parser_adds_approximately_minute_timestamps(self):
        content = """WEBVTT

00:00:00.000 --> 00:00:05.000 align:start
First line

00:00:20.000 --> 00:00:25.000
second <c>line</c>

00:01:01.000 --> 00:01:04.000
third &amp; final

"""
        result = app.parse_subtitle_file(content, include_timestamps=True)
        self.assertEqual(
            result,
            "[00:00:00]\nFirst line second line\n[00:01:01]\nthird & final",
        )

    def test_vtt_parser_can_omit_timestamps(self):
        content = """WEBVTT

00:00:00.000 --> 00:00:02.000
First

00:00:05.000 --> 00:00:07.000
Second
"""
        self.assertEqual(
            app.parse_subtitle_file(content, include_timestamps=False),
            "First Second",
        )

    def test_empty_subtitle_file_is_reported_as_unavailable(self):
        with self.assertRaises(app.NoTranscriptAvailable):
            app.parse_subtitle_file("WEBVTT\n\n")

    def test_http_429_is_classified_as_blocked(self):
        exc = app.classify_ytdlp_error(Exception("HTTP Error 429: Too Many Requests"))
        self.assertIsInstance(exc, app.TranscriptBlocked)


class TranscriptRetrievalTests(unittest.TestCase):
    def test_official_youtube_api_caption_is_formatted_into_transcript(self):
        caption_file = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.000\n"
            "A transcript line.\n"
        )
        with patch("app.download_caption_file", return_value=caption_file) as api:
            transcript = app.fetch_single_transcript(
                "abcdefghijk",
                include_timestamps=True,
                languages=["en"],
                browser="edge",
            )

        self.assertEqual(transcript, "[00:00:00]\nA transcript line.")
        api.assert_called_once_with("abcdefghijk", languages=["en"])

    def test_blocked_download_message_suggests_local_browser_session(self):
        message = str(
            app.classify_ytdlp_error(
                Exception("Sign in to confirm you're not a bot")
            )
        ).lower()
        self.assertIn("browser session", message)


class BatchResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "last_batch.json"
        self.path_patcher = patch("app.BATCH_STATE_PATH", self.state_path)
        self.path_patcher.start()
        self.delay_patcher = patch("app.time.sleep")
        self.delay_patcher.start()

    def tearDown(self):
        self.delay_patcher.stop()
        self.path_patcher.stop()
        self.temp_dir.cleanup()

    def make_state(self):
        return {
            "playlist_title": "Monday Campaign",
            "playlist_url": "https://www.youtube.com/playlist?list=PLabcdefghij",
            "languages": ["en"],
            "include_timestamps": True,
            "browser": "",
            "videos": [
                {
                    "video_id": "abcdefghijk",
                    "title": "Session One",
                    "status": "pending",
                    "transcript": "",
                    "error": "",
                },
                {
                    "video_id": "lmnopqrstuv",
                    "title": "Session Two",
                    "status": "pending",
                    "transcript": "",
                    "error": "",
                },
                {
                    "video_id": "zyxwvutsrqp",
                    "title": "Session Three",
                    "status": "pending",
                    "transcript": "",
                    "error": "",
                },
            ],
        }

    def test_blocked_batch_saves_completed_transcripts_and_resume_only_retries_pending(self):
        state = self.make_state()
        app.save_batch_state(state)

        with patch(
            "app.fetch_single_transcript",
            side_effect=[
                "Transcript one",
                app.TranscriptBlocked("YouTube temporarily blocked this request."),
                "Transcript two",
                "Transcript three",
            ],
        ) as fetch:
            app.process_saved_batch(state, browser="")
            saved = app.load_batch_state()

            self.assertEqual(saved["videos"][0]["status"], "complete")
            self.assertEqual(saved["videos"][0]["transcript"], "Transcript one")
            self.assertEqual(saved["videos"][1]["status"], "pending")
            self.assertEqual(saved["videos"][2]["status"], "pending")
            self.assertEqual(fetch.call_count, 2)

            app.process_saved_batch(saved, browser="chrome")
            completed = app.load_batch_state()

        self.assertEqual(fetch.call_count, 4)
        self.assertEqual([item["status"] for item in completed["videos"]], [
            "complete", "complete", "complete"
        ])
        self.assertEqual(completed["videos"][0]["transcript"], "Transcript one")
        self.assertEqual(completed["videos"][1]["transcript"], "Transcript two")
        self.assertEqual(completed["videos"][2]["transcript"], "Transcript three")

    def test_export_contains_success_no_caption_and_pending_sections(self):
        state = self.make_state()
        state["videos"][0].update(status="complete", transcript="A transcript.")
        state["videos"][1].update(status="no_transcript")
        content = app.build_batch_export(state)
        self.assertIn("A transcript.", content)
        self.assertIn("No captions or transcripts", content)
        self.assertIn("Pending:", content)


class FlaskRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "last_batch.json"
        self.path_patcher = patch("app.BATCH_STATE_PATH", self.state_path)
        self.path_patcher.start()

    def tearDown(self):
        self.path_patcher.stop()
        self.temp_dir.cleanup()

    def test_connect_youtube_redirects_to_google_and_callback_saves_token(self):
        fake_flow = object()
        authorization_url = "https://accounts.google.com/authorize?client=test"
        app.OAUTH_FLOW = None
        app.OAUTH_STATE = None

        with patch(
            "app.create_authorization_request",
            return_value=(fake_flow, authorization_url, "state-123"),
        ) as start_auth:
            response = self.client.post("/connect-youtube")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], authorization_url)
        start_auth.assert_called_once()

        with patch("app.complete_authorization") as finish_auth:
            callback = self.client.get("/?code=auth-code&state=state-123")

        self.assertEqual(callback.status_code, 302)
        self.assertEqual(callback.headers["Location"], "/")
        finish_auth.assert_called_once_with(
            fake_flow,
            "state-123",
            "http://localhost/?code=auth-code&state=state-123",
        )
        self.assertIsNone(app.OAUTH_FLOW)
        self.assertIsNone(app.OAUTH_STATE)

    def test_home_page_loads_with_playlist_and_individual_options(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"D&D Session Transcript Scraper", response.data)
        self.assertIn(b"Load playlist videos", response.data)
        self.assertIn(b"Paste individual video links", response.data)
        self.assertIn(b"Chrome", response.data)
        self.assertIn(b"YouTube account access", response.data)

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
                    "browser": "chrome",
                    "timestamps": "on",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Monday Campaign", response.data)
        self.assertIn(b"Session One", response.data)
        self.assertIn(b"Session Two", response.data)
        self.assertIn(b"Select visible", response.data)
        self.assertIn(b'value="chrome"', response.data)

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
        with patch("app.get_connection_status", return_value={"connected": True}), \
             patch("app.start_batch_worker", return_value=True) as start_worker:
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

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/batch-progress"))
        start_worker.assert_called_once_with(browser="")
        saved = app.load_batch_state()
        self.assertEqual([item["status"] for item in saved["videos"]], [
            "pending", "pending"
        ])
        self.assertEqual([item["title"] for item in saved["videos"]], [
            "Session One", "Session Two"
        ])

    def test_progress_page_has_separate_current_and_overall_bars(self):
        state = {
            "playlist_title": "Monday Campaign",
            "is_processing": True,
            "videos": [
                {"video_id": "abcdefghijk", "title": "Session One", "status": "pending"},
            ],
        }
        app.save_batch_state(state)

        response = self.client.get("/batch-progress")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Current video", response.data)
        self.assertIn(b"All selected videos", response.data)
        self.assertIn(b"/api/batch-progress", response.data)

    def test_progress_api_reports_file_and_batch_counts(self):
        state = {
            "playlist_title": "Monday Campaign",
            "is_processing": True,
            "current_video_index": 3,
            "current_video_title": "Session Three",
            "current_video_status": "Retrieving captions",
            "current_video_progress": 45,
            "videos": [
                {"video_id": "abcdefghijk", "status": "complete"},
                {"video_id": "lmnopqrstuv", "status": "no_transcript"},
                {"video_id": "zyxwvutsrqp", "status": "pending"},
                {"video_id": "zyxwvutsrqq", "status": "pending"},
            ],
        }
        app.save_batch_state(state)

        response = self.client.get("/api/batch-progress")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["processing"])
        self.assertEqual(data["total"], 4)
        self.assertEqual(data["processed"], 2)
        self.assertEqual(data["percent"], 50)
        self.assertEqual(data["current_index"], 3)
        self.assertEqual(data["current_title"], "Session Three")
        self.assertEqual(data["current_progress"], 45)
        self.assertEqual(data["successful"], 1)
        self.assertEqual(data["no_transcript"], 1)
        self.assertEqual(data["pending"], 2)

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

    def test_home_page_shows_resume_button_for_saved_pending_batch(self):
        state = self.make_state_for_route()
        app.save_batch_state(state)
        response = self.client.get("/")
        self.assertIn(b"Resume remaining videos (1)", response.data)

    def make_state_for_route(self):
        return {
            "playlist_title": "Saved Campaign",
            "videos": [
                {"video_id": "abcdefghijk", "title": "Done", "status": "complete"},
                {"video_id": "lmnopqrstuv", "title": "Pending", "status": "pending"},
            ],
            "browser": "",
            "block_reason": "YouTube blocked the last request.",
        }

    def test_resume_route_starts_worker_and_returns_to_progress_page(self):
        state = self.make_state_for_route()
        app.save_batch_state(state)

        with patch("app.get_connection_status", return_value={"connected": True}), \
             patch("app.start_batch_worker", return_value=True) as start_worker:
            response = self.client.post(
                "/resume-last",
                data={"browser": "firefox"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/batch-progress"))
        start_worker.assert_called_once_with(browser="")
        self.assertEqual(app.load_batch_state()["videos"][1]["status"], "pending")

    def test_download_last_batch_exports_saved_text_without_requests(self):
        state = self.make_state_for_route()
        state["videos"][0]["transcript"] = "Already saved"
        app.save_batch_state(state)

        with patch("app.fetch_single_transcript") as fetch:
            response = self.client.post("/download-last")
        fetch.assert_not_called()
        self.assertIn(b"Already saved", response.data)

    def test_successful_individual_transcript_download(self):
        with patch("app.get_connection_status", return_value={"connected": True}), \
             patch(
                "app.fetch_single_transcript",
                return_value="A transcript line.",
            ) as fetch:
            response = self.client.post(
                "/",
                data={
                    "urls": "https://youtu.be/abcdefghijk",
                    "languages": "en, es",
                    "timestamps": "on",
                    "browser": "edge",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertIn(b"A transcript line.", response.data)
        self.assertEqual(fetch.call_args.kwargs["browser"], "edge")


if __name__ == "__main__":
    unittest.main()
