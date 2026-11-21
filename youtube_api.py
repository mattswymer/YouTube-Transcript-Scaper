"""Authenticated caption retrieval through the official YouTube Data API."""

from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload


APP_DIR = Path(__file__).resolve().parent
CLIENT_SECRET_PATH = APP_DIR / "client_secret.json"
TOKEN_PATH = APP_DIR / "data" / "youtube_token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


class YouTubeApiError(Exception):
    """Base error for YouTube Data API caption retrieval."""


class YouTubeApiAuthenticationRequired(YouTubeApiError):
    """The local app has not been authorized for the YouTube account."""


class YouTubeApiQuotaExceeded(YouTubeApiError):
    """The project's YouTube Data API daily quota has been exhausted."""


class YouTubeApiPermissionDenied(YouTubeApiError):
    """The authorized account cannot access this video's caption track."""


class CaptionTrackUnavailable(YouTubeApiError):
    """No usable caption track exists in the requested languages."""


def _save_credentials(credentials: Credentials) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")


def get_credentials(interactive: bool = False) -> Credentials:
    """Load or refresh the saved OAuth token; optionally start Google consent."""
    if not CLIENT_SECRET_PATH.is_file():
        raise YouTubeApiAuthenticationRequired(
            "Google OAuth setup is incomplete. Place your downloaded Desktop OAuth "
            "JSON file beside run.bat and name it client_secret.json."
        )

    credentials = None
    if TOKEN_PATH.is_file():
        try:
            credentials = Credentials.from_authorized_user_file(
                str(TOKEN_PATH), SCOPES
            )
        except (OSError, ValueError, json.JSONDecodeError):
            credentials = None

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            _save_credentials(credentials)
        except Exception as exc:
            if not interactive:
                raise YouTubeApiAuthenticationRequired(
                    "The saved Google authorization has expired or was revoked. "
                    "Use Connect YouTube account on the app home page to reconnect."
                ) from exc
            credentials = None

    if credentials and credentials.valid:
        return credentials

    if not interactive:
        raise YouTubeApiAuthenticationRequired(
            "Connect your YouTube account from the app home page before retrieving captions."
        )

    raise YouTubeApiAuthenticationRequired(
        "Google authorization must be started from the app home page."
    )


def create_authorization_request(redirect_uri: str):
    """Create a Google consent URL that returns to this app's loopback address."""
    if not CLIENT_SECRET_PATH.is_file():
        raise YouTubeApiAuthenticationRequired(
            "Google OAuth setup is incomplete. Place your downloaded Desktop OAuth "
            "JSON file beside run.bat and name it client_secret.json."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRET_PATH), SCOPES
        )
        # Desktop OAuth clients use a loopback IP redirect URI with no path.
        flow.redirect_uri = redirect_uri
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
        )
        return flow, authorization_url, state
    except YouTubeApiError:
        raise
    except Exception as exc:
        raise YouTubeApiAuthenticationRequired(
            "Google authorization could not be started. Check your OAuth Desktop "
            "client setup and try again."
        ) from exc


def complete_authorization(flow, expected_state: str, authorization_response: str):
    """Validate Google's callback, exchange its code, and save the local token."""
    params = parse_qs(urlparse(authorization_response).query)
    provider_error = params.get("error", [""])[0]
    if provider_error:
        message = (
            "Google authorization was cancelled."
            if provider_error == "access_denied"
            else f"Google authorization failed ({provider_error})."
        )
        raise YouTubeApiAuthenticationRequired(message)

    returned_state = params.get("state", [""])[0]
    if not expected_state or returned_state != expected_state:
        raise YouTubeApiAuthenticationRequired(
            "Google authorization could not be verified. Please connect again."
        )

    try:
        flow.fetch_token(authorization_response=authorization_response)
        credentials = flow.credentials
        _save_credentials(credentials)
        return credentials
    except YouTubeApiError:
        raise
    except Exception as exc:
        raise YouTubeApiAuthenticationRequired(
            "Google did not complete authorization. Check the OAuth Desktop client "
            "configuration and try connecting again."
        ) from exc


def get_youtube_service(interactive: bool = False):
    credentials = get_credentials(interactive=interactive)
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def connect_youtube_account() -> None:
    """Complete OAuth consent and save the refreshable token locally."""
    get_youtube_service(interactive=True)


def get_connection_status() -> dict:
    """Return local setup state without prompting the user or making API calls."""
    configured = CLIENT_SECRET_PATH.is_file()
    if not configured:
        return {
            "configured": False,
            "connected": False,
            "message": "Add your Google OAuth Desktop credentials to enable the YouTube API.",
        }

    try:
        get_credentials(interactive=False)
    except YouTubeApiAuthenticationRequired as exc:
        return {
            "configured": True,
            "connected": False,
            "message": str(exc),
        }

    return {
        "configured": True,
        "connected": True,
        "message": "Connected. Captions will be retrieved through the official YouTube Data API.",
    }


def _api_error_reason(exc: HttpError) -> str:
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        errors = payload.get("error", {}).get("errors", [])
        if errors:
            return str(errors[0].get("reason") or "")
        return str(payload.get("error", {}).get("status") or "")
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return ""


def _raise_api_error(exc: HttpError) -> None:
    status = getattr(exc.resp, "status", None)
    reason = _api_error_reason(exc)
    normalized_reason = reason.lower()

    if status == 429 or normalized_reason in {
        "quotaexceeded",
        "dailylimitexceeded",
        "ratelimitexceeded",
        "userratelimitexceeded",
    }:
        raise YouTubeApiQuotaExceeded(
            "The YouTube Data API daily quota has been reached. Your saved transcripts "
            "are safe; wait for the quota reset and resume the batch."
        ) from exc

    if status in (401, 403) and normalized_reason in {
        "autherror",
        "invalidcredentials",
        "insufficientpermissions",
    }:
        raise YouTubeApiAuthenticationRequired(
            "Google authorization is no longer valid. Reconnect your YouTube account "
            "from the app home page."
        ) from exc

    if status == 404:
        raise CaptionTrackUnavailable(
            "YouTube could not find a caption track for this video."
        ) from exc

    if status == 403:
        raise YouTubeApiPermissionDenied(
            "YouTube denied access to this video's captions. Confirm that the Google "
            "account you connected owns the video or has permission to edit it."
        ) from exc

    raise YouTubeApiError(
        f"YouTube Data API returned an HTTP {status or 'error'} response "
        f"({reason or 'unspecified reason'})."
    ) from exc


def _language_match(track_language: str, requested_language: str) -> int | None:
    track = (track_language or "").lower()
    requested = (requested_language or "").lower()
    if not track or not requested:
        return None
    if track == requested:
        return 0
    if track.startswith(requested + "-"):
        return 1
    if requested.startswith(track + "-"):
        return 2
    return None


def choose_caption_track(tracks: list[dict], languages: list[str]) -> dict | None:
    """Choose the best track by requested language, preferring standard over ASR."""
    usable = []
    for track in tracks or []:
        snippet = track.get("snippet") or {}
        if snippet.get("isDraft"):
            continue
        if str(snippet.get("status", "")).lower() == "failed":
            continue
        kind = str(snippet.get("trackKind") or "standard").upper()
        kind_priority = {"STANDARD": 0, "ASR": 1, "FORCED": 2}.get(kind, 3)
        usable.append((track, snippet, kind_priority))

    for language in languages or ["en"]:
        matches = []
        for track, snippet, kind_priority in usable:
            language_priority = _language_match(
                str(snippet.get("language") or ""), language
            )
            if language_priority is not None:
                matches.append((language_priority, kind_priority, track))
        if matches:
            matches.sort(key=lambda item: (item[0], item[1]))
            return matches[0][2]
    return None


def download_caption_file(
    video_id: str,
    languages: list[str] | None = None,
    service=None,
) -> str:
    """List and download one preferred caption track as WebVTT, without media."""
    youtube = service or get_youtube_service(interactive=False)
    requested_languages = languages or ["en"]

    try:
        response = youtube.captions().list(
            part="snippet",
            videoId=video_id,
        ).execute()
        track = choose_caption_track(response.get("items", []), requested_languages)
        if not track:
            raise CaptionTrackUnavailable(
                "No usable caption track was found in the requested language(s)."
            )

        request = youtube.captions().download(
            id=track["id"],
            tfmt="vtt",
        )
        output = io.BytesIO()
        downloader = MediaIoBaseDownload(output, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        content = output.getvalue().decode("utf-8-sig", errors="replace")
        if not content.strip():
            raise CaptionTrackUnavailable(
                "YouTube returned an empty caption file for this video."
            )
        return content
    except HttpError as exc:
        _raise_api_error(exc)
