import html
import json
import os
import re
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from flask import Flask, Response, jsonify, render_template_string, request, redirect, url_for
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from youtube_api import (
    CaptionTrackUnavailable,
    YouTubeApiAuthenticationRequired,
    YouTubeApiError,
    YouTubeApiPermissionDenied,
    YouTubeApiQuotaExceeded,
    create_authorization_request,
    complete_authorization,
    download_caption_file,
    get_connection_status,
)

app = Flask(__name__)

MAX_VIDEOS = 10
MAX_PLAYLIST_ENTRIES = 500
MAX_SELECTED_VIDEOS = 200
SUPPORTED_BROWSER_CHOICES = {"", "chrome", "edge", "firefox"}
REQUEST_DELAY_SECONDS = 2.5
SUBTITLE_REQUEST_SLEEP_SECONDS = 2.0
DATA_DIR = Path(__file__).resolve().parent / "data"
BATCH_STATE_PATH = DATA_DIR / "last_batch.json"
BATCH_WORKER_LOCK = threading.Lock()
OAUTH_LOCK = threading.Lock()
OAUTH_FLOW = None
OAUTH_STATE = None
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
LANGUAGE_CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#18181b">
    <title>D&D Session Transcript Scraper</title>
    <style>
        :root { color-scheme: dark; }
        body {
            font-family: system-ui, -apple-system, sans-serif;
            max-width: 900px;
            margin: 36px auto;
            padding: 0 20px;
            background: #18181b;
            color: #f4f4f5;
        }
        h1 { color: #e4e4e7; margin-bottom: 8px; }
        h2 { font-size: 19px; margin: 0 0 12px; }
        p.subtitle { color: #a1a1aa; margin-top: 0; margin-bottom: 26px; }
        textarea, input[type="text"], input[type="url"], input[type="search"] {
            width: 100%;
            box-sizing: border-box;
            background: #27272a;
            color: #f4f4f5;
            border: 1px solid #52525b;
            border-radius: 8px;
            padding: 12px;
            font: 14px ui-monospace, monospace;
        }
        textarea { min-height: 150px; resize: vertical; }
        input[type="text"], input[type="url"], input[type="search"] { margin-top: 8px; }
        textarea:focus, input:focus {
            outline: 2px solid #a78bfa;
            outline-offset: 2px;
        }
        label { color: #d4d4d8; }
        .section {
            margin-top: 24px;
            padding: 20px;
            border: 1px solid #3f3f46;
            border-radius: 10px;
            background: #202024;
        }
        .section-heading { display: flex; align-items: baseline; gap: 10px; margin-bottom: 14px; }
        .step { color: #a78bfa; font-size: 13px; font-weight: 700; }
        .field { margin-top: 16px; }
        .help { color: #a1a1aa; font-size: 13px; margin: 6px 0 0; }
        .controls {
            margin: 16px 0 20px;
            display: flex;
            flex-wrap: wrap;
            gap: 18px;
            align-items: center;
        }
        .checkbox-label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
        button {
            background: #7c3aed;
            color: white;
            border: none;
            padding: 11px 18px;
            font-size: 15px;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
        }
        button:hover { background: #6d28d9; }
        button:focus-visible { outline: 2px solid white; outline-offset: 3px; }
        a.primary-link {
            display: inline-block;
            box-sizing: border-box;
            background: #7c3aed;
            color: white;
            border: none;
            padding: 11px 18px;
            font-size: 15px;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
            text-decoration: none;
        }
        a.primary-link:hover { background: #6d28d9; }
        a.primary-link:focus-visible { outline: 2px solid white; outline-offset: 3px; }
        button.secondary {
            background: #3f3f46;
            color: #f4f4f5;
            font-size: 13px;
            padding: 8px 12px;
        }
        button.secondary:hover { background: #52525b; }
        .error, .warning, .note {
            padding: 12px 16px;
            border-radius: 7px;
            margin: 14px 0;
            font-size: 13px;
            line-height: 1.5;
        }
        .error { background: #450a0a; color: #fecaca; }
        .warning { background: #422006; color: #fde68a; }
        .note {
            color: #a1a1aa;
            background: #27272a;
            border-left: 3px solid #7c3aed;
        }
        .playlist-toolbar {
            display: grid;
            grid-template-columns: minmax(180px, 1fr) auto auto;
            gap: 10px;
            align-items: end;
            margin: 16px 0 12px;
        }
        .playlist-toolbar input { margin-top: 0; }
        .selection-summary { color: #c4b5fd; font-size: 13px; margin: 10px 0; }
        .video-list {
            max-height: 520px;
            overflow-y: auto;
            border: 1px solid #3f3f46;
            border-radius: 8px;
            background: #18181b;
        }
        .video-row {
            display: grid;
            grid-template-columns: 22px 34px minmax(0, 1fr) auto;
            gap: 10px;
            align-items: center;
            padding: 10px 12px;
            border-bottom: 1px solid #303036;
            cursor: pointer;
        }
        .video-row:last-child { border-bottom: 0; }
        .video-row:hover { background: #27272a; }
        .video-row input { margin: 0; }
        .video-index { color: #71717a; font-size: 12px; text-align: right; }
        .video-title { font-size: 13px; line-height: 1.4; overflow-wrap: anywhere; }
        .video-duration { color: #a1a1aa; font-size: 12px; white-space: nowrap; }
        .playlist-submit { margin-top: 16px; width: 100%; }
        .hidden { display: none !important; }
        @media (max-width: 640px) {
            body { margin: 22px auto; padding: 0 14px; }
            .section { padding: 15px; }
            .playlist-toolbar { grid-template-columns: 1fr 1fr; }
            .playlist-toolbar .search-wrap { grid-column: 1 / -1; }
            .video-row { grid-template-columns: 22px 26px minmax(0, 1fr); gap: 8px; }
            .video-duration { grid-column: 3; margin-top: -4px; }
            button { min-height: 42px; }
        }
    </style>
</head>
<body>
    <h1>D&D Session Transcript Scraper</h1>
    <p class="subtitle">
        Pull transcripts from individual videos or choose specific videos from a YouTube playlist.
        Everything is combined into one downloadable text file.
    </p>

    <section class="section">
        <div class="section-heading">
            <span class="step">YOUTUBE API</span>
            <h2>YouTube account access</h2>
        </div>
        {% if youtube_status.connected %}
        <p class="selection-summary">Connected. Captions are retrieved through the official YouTube Data API.</p>
        {% else %}
            {% if not youtube_status.configured %}
            <div class="note">
                <strong>One-time setup:</strong> In Google Cloud, enable YouTube Data API v3 and create an OAuth client with application type <strong>Desktop app</strong>. Save the downloaded JSON file beside run.bat as <code>client_secret.json</code>, then reload this page.
            </div>
            {% else %}
            <div class="warning">{{ youtube_status.message }}</div>
            {% endif %}
            {% if youtube_status.configured %}
            <a class="primary-link" href="{{ url_for('connect_youtube') }}">Connect YouTube account</a>
            {% else %}
            <button type="button" disabled>Connect YouTube account</button>
            {% endif %}
        {% endif %}
        <p class="help">Use the Google account that owns the videos or has permission to edit them. The authorization token stays in this app's local data folder.</p>
    </section>

    {% if error %}
    <div class="error" role="alert">{{ error }}</div>
    {% endif %}

    {% if batch_summary %}
    <section class="section">
        <div class="section-heading">
            <span class="step">SAVED BATCH</span>
            <h2>{{ batch_summary.playlist_title }}</h2>
        </div>
        <p class="help">
            {{ batch_summary.completed }} transcripts saved;
            {{ batch_summary.no_transcript }} videos have no available captions;
            {{ batch_summary.pending }} still need processing.
        </p>
        {% if batch_summary.block_reason %}
        <div class="warning">{{ batch_summary.block_reason }}</div>
        {% endif %}
        {% if batch_summary.pending %}
        <form method="POST" action="/resume-last">
            <button type="submit">Resume remaining videos ({{ batch_summary.pending }})</button>
        </form>
        {% else %}
        <p class="selection-summary">This batch has no remaining videos to process.</p>
        {% endif %}
        <div class="controls">
            <form method="POST" action="/download-last">
                <button class="secondary" type="submit">Download saved combined transcripts</button>
            </form>
            <form method="POST" action="/clear-last-batch">
                <button class="secondary" type="submit">Clear saved batch</button>
            </form>
        </div>
        <p class="help">Progress and transcript text are saved locally in the app's data folder, not uploaded anywhere.</p>
    </section>
    {% endif %}

    <section class="section">
        <div class="section-heading">
            <span class="step">OPTION 1</span>
            <h2>Choose videos from a playlist</h2>
        </div>
        <form method="POST" action="/load-playlist">
            <label for="playlist_url">YouTube playlist link</label>
            <input id="playlist_url" name="playlist_url" type="url"
                   value="{{ playlist_url }}" placeholder="https://www.youtube.com/playlist?list=..." required>

            <div class="field">
                <label for="playlist_languages">Preferred transcript languages</label>
                <input id="playlist_languages" name="languages" type="text"
                       value="{{ languages }}" placeholder="en, es">
                <p class="help">Comma-separated language codes, in preference order. English is the default.</p>
            </div>

            <div class="field">
                <label for="playlist_browser">YouTube browser session (optional)</label>
                <select id="playlist_browser" name="browser">
                    <option value="">No browser cookies</option>
                    <option value="chrome" {% if browser == "chrome" %}selected{% endif %}>Chrome</option>
                    <option value="edge" {% if browser == "edge" %}selected{% endif %}>Microsoft Edge</option>
                    <option value="firefox" {% if browser == "firefox" %}selected{% endif %}>Firefox</option>
                </select>
                <p class="help">Optional: use a signed-in browser session when loading private playlist metadata. Caption downloads use the connected Google account.</p>
            </div>

            <div class="controls">
                <label class="checkbox-label">
                    <input type="checkbox" name="timestamps" {% if include_timestamps %}checked{% endif %}>
                    Include timestamps approximately every 60 seconds
                </label>
            </div>

            <button type="submit">Load playlist videos</button>
        </form>
    </section>

    {% if playlist_entries %}
    <section class="section">
        <div class="section-heading">
            <span class="step">OPTION 2</span>
            <h2>Select videos to download</h2>
        </div>
        <div><strong>{{ playlist_title }}</strong></div>
        <p class="help">{{ playlist_entries|length }} videos found. Select the videos you want included.</p>
        {% if playlist_warning %}
        <div class="warning">{{ playlist_warning }}</div>
        {% endif %}

        <form method="POST" action="/download-playlist" id="playlistSelectionForm">
            <input type="hidden" name="playlist_title" value="{{ playlist_title }}">
            <input type="hidden" name="playlist_url" value="{{ playlist_url }}">
            <input type="hidden" name="languages" value="{{ languages }}">
            <input type="hidden" name="browser" value="{{ browser }}">
            {% if include_timestamps %}
            <input type="hidden" name="timestamps" value="on">
            {% endif %}

            {% for video in playlist_entries %}
            <input type="hidden" name="playlist_video_ids" value="{{ video.video_id }}">
            <input type="hidden" name="title__{{ video.video_id }}" value="{{ video.title }}">
            <input type="hidden" name="duration__{{ video.video_id }}" value="{{ video.duration_display }}">
            {% endfor %}

            <div class="playlist-toolbar">
                <div class="search-wrap">
                    <label for="videoSearch">Filter videos</label>
                    <input id="videoSearch" type="search" placeholder="Search titles or video IDs">
                </div>
                <button type="button" class="secondary" id="selectAll">Select visible</button>
                <button type="button" class="secondary" id="clearAll">Clear selection</button>
            </div>

            <div class="selection-summary" id="selectionCount" aria-live="polite">0 selected</div>

            <div class="video-list" id="videoList">
                {% for video in playlist_entries %}
                <label class="video-row" data-search="{{ (video.title ~ ' ' ~ video.video_id)|lower }}">
                    <input class="video-checkbox" type="checkbox" name="selected_video_ids" value="{{ video.video_id }}" {% if video.video_id in selected_ids %}checked{% endif %}>
                    <span class="video-index">{{ video.playlist_index }}</span>
                    <span class="video-title">{{ video.title }}</span>
                    <span class="video-duration">{{ video.duration_display }}</span>
                </label>
                {% endfor %}
            </div>

            <button type="submit" class="playlist-submit">Download selected transcripts</button>
            <p class="help">You can select up to 200 videos at once. Requests run sequentially to reduce the chance of YouTube temporarily blocking them.</p>
        </form>
    </section>
    {% endif %}

    <section class="section">
        <div class="section-heading">
            <span class="step">OPTION 3</span>
            <h2>Paste individual video links</h2>
        </div>
        <form method="POST" action="/">
            <label for="urls">YouTube links, one per line (up to 10)</label>
            <textarea id="urls" name="urls" placeholder="https://www.youtube.com/watch?v=...&#10;https://youtu.be/..." required>{{ urls }}</textarea>

            <div class="field">
                <label for="single_languages">Preferred transcript languages</label>
                <input id="single_languages" name="languages" type="text"
                       value="{{ languages }}" placeholder="en, es">
            </div>

            <div class="controls">
                <label class="checkbox-label">
                    <input type="checkbox" name="timestamps" {% if include_timestamps %}checked{% endif %}>
                    Include timestamps approximately every 60 seconds
                </label>
            </div>

            <button type="submit">Download combined transcripts</button>
        </form>
    </section>

    <div class="note">
        <strong>Notes:</strong> The app retrieves uploader-provided or automatically generated caption tracks through YouTube's official API. The connected Google account must have permission to edit each video. Playlist metadata can still use a local browser session when needed. If the API daily quota is reached, progress is saved and the remaining videos can be resumed after the quota resets.
    </div>

    <script>
    (function () {
        const list = document.getElementById("videoList");
        if (!list) return;

        const rows = Array.from(list.querySelectorAll(".video-row"));
        const checks = rows.map(row => row.querySelector(".video-checkbox"));
        const search = document.getElementById("videoSearch");
        const count = document.getElementById("selectionCount");

        function updateCount() {
            const selected = checks.filter(input => input.checked).length;
            count.textContent = selected + " of " + checks.length + " selected";
        }

        function filterRows() {
            const term = search.value.trim().toLowerCase();
            rows.forEach(row => {
                row.classList.toggle("hidden", term && !row.dataset.search.includes(term));
            });
        }

        checks.forEach(input => input.addEventListener("change", updateCount));
        search.addEventListener("input", filterRows);

        document.getElementById("selectAll").addEventListener("click", function () {
            rows.forEach((row, index) => {
                if (!row.classList.contains("hidden")) checks[index].checked = true;
            });
            updateCount();
        });

        document.getElementById("clearAll").addEventListener("click", function () {
            checks.forEach(input => { input.checked = false; });
            updateCount();
        });

        updateCount();
    })();
    </script>
</body>
</html>
"""



PROGRESS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#18181b">
    <title>Transcript Download Progress</title>
    <style>
        :root { color-scheme: dark; }
        body {
            font-family: system-ui, -apple-system, sans-serif;
            max-width: 760px;
            margin: 40px auto;
            padding: 0 20px;
            background: #18181b;
            color: #f4f4f5;
        }
        h1 { margin-bottom: 8px; font-size: 25px; }
        h2 { margin: 0 0 8px; font-size: 17px; }
        .subtitle, .muted { color: #a1a1aa; }
        .panel {
            margin-top: 22px;
            padding: 20px;
            border: 1px solid #3f3f46;
            border-radius: 10px;
            background: #202024;
        }
        .progress-heading {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: baseline;
            margin-bottom: 9px;
        }
        .progress-value { color: #c4b5fd; font-size: 13px; white-space: nowrap; }
        .track {
            width: 100%;
            height: 15px;
            overflow: hidden;
            border-radius: 99px;
            background: #3f3f46;
        }
        .fill {
            width: 0%;
            height: 100%;
            border-radius: inherit;
            background: #8b5cf6;
            transition: width .25s ease;
        }
        .fill.current.indeterminate {
            width: 35%;
            animation: slide 1.4s ease-in-out infinite alternate;
        }
        @keyframes slide {
            from { transform: translateX(-15%); }
            to { transform: translateX(205%); }
        }
        .status { margin-top: 9px; color: #d4d4d8; font-size: 14px; }
        .detail { margin-top: 5px; color: #a1a1aa; font-size: 13px; overflow-wrap: anywhere; }
        .summary {
            display: flex;
            flex-wrap: wrap;
            gap: 8px 18px;
            margin-top: 18px;
            color: #a1a1aa;
            font-size: 13px;
        }
        .summary strong { color: #f4f4f5; }
        .notice {
            margin-top: 16px;
            padding: 12px 14px;
            border-radius: 7px;
            background: #422006;
            color: #fde68a;
            font-size: 13px;
            line-height: 1.5;
        }
        .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }
        button, a.button {
            display: inline-block;
            border: 0;
            border-radius: 8px;
            padding: 11px 16px;
            font-size: 14px;
            font-weight: 600;
            color: white;
            background: #7c3aed;
            text-decoration: none;
            cursor: pointer;
        }
        a.secondary, button.secondary { background: #3f3f46; color: #f4f4f5; }
        @media (max-width: 520px) {
            body { margin: 24px auto; padding: 0 14px; }
            .panel { padding: 16px; }
            .actions > * { flex: 1 1 100%; text-align: center; }
        }
    </style>
</head>
<body>
    <h1>Downloading transcripts</h1>
    <p class="subtitle" id="playlistTitle">{{ playlist_title }}</p>

    <section class="panel">
        <div class="progress-heading">
            <h2>Current video</h2>
            <span class="progress-value" id="currentPosition">Preparing…</span>
        </div>
        <div class="track" role="progressbar" aria-label="Current video progress">
            <div class="fill current indeterminate" id="currentBar"></div>
        </div>
        <div class="status" id="currentStatus">Starting transcript retrieval…</div>
        <div class="detail" id="currentTitle"></div>

        <div style="height:26px"></div>

        <div class="progress-heading">
            <h2>All selected videos</h2>
            <span class="progress-value" id="overallPercent">0%</span>
        </div>
        <div class="track" role="progressbar" aria-label="Overall batch progress">
            <div class="fill" id="overallBar"></div>
        </div>
        <div class="status" id="overallStatus">0 of 0 videos processed</div>

        <div class="summary">
            <span>Transcripts: <strong id="successCount">0</strong></span>
            <span>No captions: <strong id="noCaptionCount">0</strong></span>
            <span>Unavailable: <strong id="unavailableCount">0</strong></span>
            <span>Errors: <strong id="failedCount">0</strong></span>
        </div>

        <div class="notice" id="blockNotice" hidden></div>

        <div class="actions">
            <form id="downloadForm" method="POST" action="/download-last" hidden>
                <button class="button" id="downloadButton" type="submit">Download combined transcripts</button>
            </form>
            <form id="resumeForm" method="POST" action="/resume-last" hidden>
                <button type="submit">Resume remaining videos</button>
            </form>
            <a class="button secondary" href="/">Back to scraper</a>
        </div>
        <p class="muted" style="font-size:12px;margin-bottom:0">
            This page updates automatically. You can leave it open while the batch runs.
        </p>
    </section>

    <script>
    (function () {
        const currentBar = document.getElementById("currentBar");
        const currentPosition = document.getElementById("currentPosition");
        const currentStatus = document.getElementById("currentStatus");
        const currentTitle = document.getElementById("currentTitle");
        const overallBar = document.getElementById("overallBar");
        const overallPercent = document.getElementById("overallPercent");
        const overallStatus = document.getElementById("overallStatus");
        const successCount = document.getElementById("successCount");
        const noCaptionCount = document.getElementById("noCaptionCount");
        const unavailableCount = document.getElementById("unavailableCount");
        const failedCount = document.getElementById("failedCount");
        const blockNotice = document.getElementById("blockNotice");
        const downloadForm = document.getElementById("downloadForm");
        const resumeForm = document.getElementById("resumeForm");

        async function refreshProgress() {
            try {
                const response = await fetch("/api/batch-progress", {cache: "no-store"});
                if (!response.ok) throw new Error("Progress request failed");
                const data = await response.json();

                const percent = Math.max(0, Math.min(100, data.percent || 0));
                overallBar.style.width = percent + "%";
                overallPercent.textContent = Math.round(percent) + "%";
                overallStatus.textContent = data.processed + " of " + data.total + " videos processed";

                currentPosition.textContent = data.current_index && data.total
                    ? "Video " + data.current_index + " of " + data.total
                    : (data.processing ? "Preparing…" : "Batch complete");
                currentStatus.textContent = data.current_status || "Waiting";
                currentTitle.textContent = data.current_title || "";

                currentBar.classList.toggle("indeterminate", Boolean(data.processing));
                if (!data.processing) {
                    currentBar.style.width = (data.current_progress || 0) + "%";
                } else {
                    currentBar.style.width = "35%";
                }

                successCount.textContent = data.successful;
                noCaptionCount.textContent = data.no_transcript;
                unavailableCount.textContent = data.unavailable;
                failedCount.textContent = data.failed;

                blockNotice.hidden = !data.block_reason;
                blockNotice.textContent = data.block_reason || "";

                downloadForm.hidden = data.processing || data.total === 0;
                resumeForm.hidden = data.processing || data.retryable === 0;

                if (!data.processing && data.pending === 0) {
                    currentStatus.textContent = data.failed
                        ? "Finished, with some videos that can be retried."
                        : "All selected videos have been processed.";
                }
                window.setTimeout(refreshProgress, data.processing ? 1000 : 5000);
            } catch (error) {
                currentStatus.textContent = "Connection interrupted. Checking again…";
                window.setTimeout(refreshProgress, 2000);
            }
        }

        refreshProgress();
    })();
    </script>
</body>
</html>
"""

def render_page(
    error=None,
    urls="",
    languages="en",
    include_timestamps=True,
    status=200,
    playlist_entries=None,
    playlist_title="",
    playlist_url="",
    playlist_warning="",
    selected_ids=None,
    browser="",
    batch_summary=None,
    youtube_status=None,
):
    if batch_summary is None:
        batch_summary = get_batch_summary()
    if youtube_status is None:
        youtube_status = get_connection_status()

    page = render_template_string(
        HTML_TEMPLATE,
        error=error,
        urls=urls,
        languages=languages,
        include_timestamps=include_timestamps,
        playlist_entries=playlist_entries or [],
        playlist_title=playlist_title,
        playlist_url=playlist_url,
        playlist_warning=playlist_warning,
        selected_ids=set(selected_ids or []),
        browser=browser if browser in SUPPORTED_BROWSER_CHOICES else "",
        batch_summary=batch_summary,
        youtube_status=youtube_status,
    )
    return page, status


def extract_video_id(value: str):
    """Extract and validate an 11-character ID from common YouTube URL formats."""
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if VIDEO_ID_RE.fullmatch(candidate):
        return candidate

    if not candidate:
        return None

    # Allow users to paste youtube.com/watch?... without typing the scheme.
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", candidate):
        candidate = "https://" + candidate

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None

    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        return None

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname not in YOUTUBE_HOSTS:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]

    if hostname in ("youtu.be", "www.youtu.be"):
        video_id = path_parts[0] if path_parts else None
    elif parsed.path.rstrip("/") == "/watch":
        video_id = parse_qs(parsed.query).get("v", [None])[0]
    elif path_parts and path_parts[0] in ("embed", "shorts", "live", "v"):
        video_id = path_parts[1] if len(path_parts) > 1 else None
    else:
        video_id = None

    return video_id if video_id and VIDEO_ID_RE.fullmatch(video_id) else None


def parse_languages(value: str):
    """Parse comma-, semicolon-, or space-separated YouTube language codes."""
    requested = [part for part in re.split(r"[,;\s]+", (value or "").strip()) if part]
    if not requested:
        return ["en"]

    invalid = [code for code in requested if not LANGUAGE_CODE_RE.fullmatch(code)]
    if invalid:
        raise ValueError(
            "Language codes should look like 'en' or 'en, es'. "
            f"Check: {', '.join(invalid)}"
        )

    # Preserve user priority while avoiding redundant requests.
    return list(dict.fromkeys(requested))


def format_seconds(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def extract_playlist_id(value: str):
    """Accept only YouTube playlist URLs containing a list identifier."""
    if not isinstance(value, str) or not value.strip():
        return None

    candidate = value.strip()
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", candidate):
        candidate = "https://" + candidate

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None

    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        return None

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname not in YOUTUBE_HOSTS:
        return None

    playlist_id = parse_qs(parsed.query).get("list", [None])[0]
    if not playlist_id or not re.fullmatch(r"[A-Za-z0-9_-]{2,128}", playlist_id):
        return None

    return playlist_id


def format_duration(seconds):
    if seconds is None:
        return "Duration unavailable"
    try:
        return format_seconds(float(seconds))
    except (TypeError, ValueError):
        return "Duration unavailable"


def normalize_browser(value):
    browser = (value or "").strip().lower()
    if browser not in SUPPORTED_BROWSER_CHOICES:
        return ""
    return browser


def apply_browser_cookies(options, browser):
    browser = normalize_browser(browser)
    if browser:
        # yt-dlp reads the chosen browser cookie store directly for this run.
        options["cookiesfrombrowser"] = (browser, None, None, None)
    return options


def fetch_playlist_entries(playlist_url: str, browser=None):
    """Read playlist metadata without downloading any video or audio."""
    if not extract_playlist_id(playlist_url):
        raise ValueError("Paste a valid YouTube playlist link containing a playlist ID.")

    options = {
        "quiet": True,
        "no_warnings": True,
        "no_color": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "playlistend": MAX_PLAYLIST_ENTRIES,
    }
    apply_browser_cookies(options, browser)

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(playlist_url, download=False)

    if not info or not info.get("entries"):
        raise ValueError(
            "No playlist videos were found. Check that the playlist is public or unlisted "
            "and that its link is correct."
        )

    entries = []
    seen_ids = set()
    skipped = 0

    for position, raw_entry in enumerate(info.get("entries") or [], start=1):
        if not raw_entry:
            skipped += 1
            continue

        video_id = raw_entry.get("id")
        if not video_id or not VIDEO_ID_RE.fullmatch(str(video_id)):
            fallback_url = raw_entry.get("webpage_url") or raw_entry.get("url") or ""
            video_id = extract_video_id(fallback_url)

        if not video_id or not VIDEO_ID_RE.fullmatch(str(video_id)):
            skipped += 1
            continue

        video_id = str(video_id)
        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)

        title = re.sub(r"\s+", " ", str(raw_entry.get("title") or "Untitled video")).strip()
        duration_display = format_duration(raw_entry.get("duration"))
        playlist_index = raw_entry.get("playlist_index") or position

        entries.append({
            "video_id": video_id,
            "title": title[:300],
            "duration_display": duration_display,
            "playlist_index": playlist_index,
        })

    if not entries:
        raise ValueError(
            "YouTube returned playlist entries, but none had a usable video ID. "
            "Some videos may be deleted or unavailable."
        )

    total_count = info.get("playlist_count") or info.get("n_entries")
    warning_parts = []

    if skipped:
        warning_parts.append(
            f"{skipped} unavailable or unrecognized playlist entr{'y' if skipped == 1 else 'ies'} "
            f"could not be selected."
        )

    if total_count and int(total_count) > len(info.get("entries") or []):
        warning_parts.append(
            f"Only the first {MAX_PLAYLIST_ENTRIES} playlist entries were loaded."
        )

    if len(info.get("entries") or []) >= MAX_PLAYLIST_ENTRIES and not total_count:
        warning_parts.append(
            f"The list reached the {MAX_PLAYLIST_ENTRIES}-video loading limit."
        )

    return {
        "title": str(info.get("title") or "YouTube Playlist")[:300],
        "entries": entries,
        "warning": " ".join(warning_parts),
    }


def entries_from_selection_form():
    """Rebuild the displayed playlist list from submitted, validated form fields."""
    entries = []
    seen_ids = set()

    for position, video_id in enumerate(request.form.getlist("playlist_video_ids"), start=1):
        if not VIDEO_ID_RE.fullmatch(video_id) or video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        title = re.sub(
            r"\s+",
            " ",
            request.form.get(f"title__{video_id}", "Untitled video"),
        ).strip()[:300]
        entries.append({
            "video_id": video_id,
            "title": title or "Untitled video",
            "duration_display": request.form.get(
                f"duration__{video_id}", "Duration unavailable"
            )[:40],
            "playlist_index": position,
        })

    return entries


class NoTranscriptAvailable(Exception):
    """The video has no subtitle track matching the requested languages."""


class TranscriptBlocked(Exception):
    """YouTube temporarily blocked subtitle retrieval."""


class TranscriptUnavailable(Exception):
    """The video cannot be accessed with the current session."""


def parse_subtitle_timestamp(value):
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    elif len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        seconds = float(parts[1])
    else:
        raise ValueError("Invalid subtitle timestamp")
    return hours * 3600 + minutes * 60 + seconds


def parse_subtitle_file(content, include_timestamps=True):
    """Convert VTT/SRT cues into readable paragraphs, removing rolling-caption overlap."""
    cues = []
    current_start = None
    current_end = None
    current_text = []

    def normalized_words(value):
        return [
            re.sub(r"[^\w’']", "", word.casefold())
            for word in value.split()
        ]

    def flush():
        nonlocal current_start, current_end, current_text
        text = " ".join(current_text).strip()
        if text and current_start is not None:
            text = html.unescape(re.sub(r"<[^>]*>", "", text))
            text = re.sub(r"\{\\[^}]*\}", "", text)
            text = re.sub(r"\s+", " ", text).strip()

            if text:
                # YouTube can send successive rolling captions containing an
                # expanded version of words already present in the previous cue.
                if cues and current_start <= cues[-1][1] + 0.75:
                    previous_start, previous_end, previous_text = cues[-1]
                    previous_words = normalized_words(previous_text)
                    current_words = normalized_words(text)

                    if previous_words and current_words:
                        if (
                            len(previous_words) <= len(current_words)
                            and current_words[:len(previous_words)] == previous_words
                        ):
                            cues[-1] = (
                                previous_start,
                                max(previous_end, current_end or current_start),
                                text,
                            )
                            current_start = current_end = None
                            current_text = []
                            return

                        if (
                            len(current_words) <= len(previous_words)
                            and previous_words[:len(current_words)] == current_words
                        ):
                            cues[-1] = (
                                previous_start,
                                max(previous_end, current_end or current_start),
                                previous_text,
                            )
                            current_start = current_end = None
                            current_text = []
                            return

                        max_overlap = min(len(previous_words), len(current_words))
                        for overlap in range(max_overlap, 0, -1):
                            overlap_words = previous_words[-overlap:]
                            if (
                                overlap_words == current_words[:overlap]
                                and all(len(word) >= 2 for word in overlap_words)
                            ):
                                merged_text = " ".join(
                                    previous_text.split() + text.split()[overlap:]
                                )
                                cues[-1] = (
                                    previous_start,
                                    max(previous_end, current_end or current_start),
                                    merged_text,
                                )
                                current_start = current_end = None
                                current_text = []
                                return

                cues.append((current_start, current_end or current_start, text))

        current_start = current_end = None
        current_text = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue

        if "-->" in line:
            flush()
            try:
                timing = line.split("-->", 1)
                current_start = parse_subtitle_timestamp(timing[0])
                current_end = parse_subtitle_timestamp(timing[1].strip().split()[0])
            except (IndexError, TypeError, ValueError):
                current_start = current_end = None
            continue

        if (
            line == "WEBVTT"
            or line.startswith(("NOTE", "STYLE", "REGION", "Kind:", "Language:"))
            or re.fullmatch(r"\d+", line)
        ):
            continue

        if current_start is not None:
            current_text.append(line)

    flush()

    if not cues:
        raise NoTranscriptAvailable("No readable caption cues were found.")

    output = []
    paragraph = []
    last_timestamp = -60.0

    for start, _end, text in cues:
        if include_timestamps and start - last_timestamp >= 60:
            if paragraph:
                output.append(" ".join(paragraph))
                paragraph = []
            output.append(f"[{format_seconds(start)}]")
            last_timestamp = start
        paragraph.append(text)

    if paragraph:
        output.append(" ".join(paragraph))

    return "\n".join(output)

def classify_ytdlp_error(exc):
    message = str(exc)
    lowered = message.lower()

    blocked_markers = (
        "http error 429",
        "too many requests",
        "requestblocked",
        "ipblocked",
        "temporarily blocked",
        "sign in to confirm you're not a bot",
        "sign in to confirm you’re not a bot",
        "confirm you're not a bot",
        "confirm you’re not a bot",
        "rate limit",
        "http error 403",
    )
    unavailable_markers = (
        "private video",
        "video unavailable",
        "has been removed",
        "this video is unavailable",
        "members-only",
        "members only",
    )

    if any(marker in lowered for marker in blocked_markers):
        return TranscriptBlocked(
            "YouTube temporarily blocked subtitle retrieval. The batch has been saved; "
            "wait before resuming, or try your signed-in browser session."
        )
    if any(marker in lowered for marker in unavailable_markers):
        return TranscriptUnavailable(
            "The video is private, removed, members-only, or unavailable to the selected session."
        )
    return RuntimeError(f"yt-dlp could not retrieve subtitles ({type(exc).__name__}).")


def fetch_single_transcript(
    video_id: str,
    include_timestamps: bool,
    languages=None,
    browser=None,
) -> str:
    """Retrieve one caption track through the official YouTube Data API."""
    try:
        caption_file = download_caption_file(
            video_id,
            languages=languages or ["en"],
        )
    except YouTubeApiAuthenticationRequired as exc:
        raise TranscriptBlocked(str(exc)) from exc
    except YouTubeApiQuotaExceeded as exc:
        raise TranscriptBlocked(str(exc)) from exc
    except CaptionTrackUnavailable as exc:
        raise NoTranscriptAvailable(str(exc)) from exc
    except YouTubeApiPermissionDenied as exc:
        raise TranscriptUnavailable(str(exc)) from exc
    except YouTubeApiError as exc:
        raise TranscriptUnavailable(str(exc)) from exc

    return parse_subtitle_file(
        caption_file,
        include_timestamps=include_timestamps,
    )

def describe_transcript_error(exc: Exception) -> str:
    if isinstance(exc, TranscriptBlocked):
        return str(exc)
    if isinstance(exc, NoTranscriptAvailable):
        return "Captions and transcripts are disabled or unavailable in the requested language(s)."
    if isinstance(exc, TranscriptUnavailable):
        return str(exc)
    if isinstance(exc, YouTubeApiError):
        return str(exc)
    if isinstance(exc, DownloadError):
        return str(classify_ytdlp_error(exc))
    return f"An unexpected error occurred ({type(exc).__name__})."


def make_text_download(content, filename=None):
    now = datetime.now().astimezone()
    filename = filename or f"dnd_transcripts_{now.strftime('%Y%m%d_%H%M%S')}.txt"
    return Response(
        content,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def create_transcript_response(video_items, include_timestamps, languages, playlist_title=None, browser=None):
    """Fetch a small individual-link batch sequentially."""
    now = datetime.now().astimezone()
    heading = "D&D CAMPAIGN SESSION TRANSCRIPTS"
    if playlist_title:
        heading += f"\nPlaylist: {playlist_title}"

    output_sections = [
        heading,
        f"Exported: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Videos selected: {len(video_items)}",
        "=" * 60,
        "",
    ]

    for index, item in enumerate(video_items, start=1):
        video_id = item["video_id"]
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()[:300]
        url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""

        if not video_id:
            output_sections.append(
                f"=== VIDEO {index}: INVALID YOUTUBE URL ===\n"
                f"Input: {title}\n"
                "[Error: Paste a valid YouTube video link or 11-character video ID.]\n"
            )
            continue

        try:
            body = fetch_single_transcript(
                video_id, include_timestamps, languages, browser=browser
            )
            label = f" | {title}" if title else ""
            output_sections.append(
                f"=== VIDEO {index} | Video ID: {video_id}{label} | {url} ===\n\n"
                f"{body}\n"
            )
        except Exception as exc:
            message = describe_transcript_error(exc)
            label = f" | {title}" if title else ""
            output_sections.append(
                f"=== VIDEO {index} | Video ID: {video_id}{label} | {url} ===\n"
                f"[Error: {message}]\n"
            )
            if isinstance(exc, TranscriptBlocked):
                for skipped_index, skipped_item in enumerate(video_items[index:], start=index + 1):
                    output_sections.append(
                        f"=== VIDEO {skipped_index} | Video ID: {skipped_item['video_id']} ===\n"
                        "[Skipped because YouTube blocked an earlier request.]\n"
                    )
                break

        if index < len(video_items):
            time.sleep(REQUEST_DELAY_SECONDS)

    content = "\n\n".join(output_sections).rstrip() + "\n"
    return make_text_download(content)


def save_batch_state(state):
    BATCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = BATCH_STATE_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, BATCH_STATE_PATH)


def load_batch_state():
    try:
        return json.loads(BATCH_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def clear_batch_state():
    try:
        BATCH_STATE_PATH.unlink()
    except FileNotFoundError:
        pass


def get_batch_summary():
    state = load_batch_state()
    if not state:
        return None

    videos = state.get("videos") or []
    statuses = [item.get("status", "pending") for item in videos]
    return {
        "playlist_title": state.get("playlist_title") or "Last playlist batch",
        "total": len(videos),
        "completed": statuses.count("complete"),
        "no_transcript": statuses.count("no_transcript"),
        "unavailable": statuses.count("unavailable"),
        "pending": statuses.count("pending") + statuses.count("failed"),
        "browser": state.get("browser", ""),
        "block_reason": state.get("block_reason", ""),
    }


def build_batch_export(state):
    now = datetime.now().astimezone()
    videos = state.get("videos") or []
    sections = [
        "D&D CAMPAIGN SESSION TRANSCRIPTS",
        f"Playlist: {state.get('playlist_title', 'YouTube Playlist')}",
        f"Exported: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Videos selected: {len(videos)}",
        "=" * 60,
        "",
    ]

    for index, item in enumerate(videos, start=1):
        video_id = item.get("video_id", "")
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()[:300]
        url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
        label = f" | {title}" if title else ""
        status = item.get("status", "pending")

        if status == "complete":
            sections.append(
                f"=== VIDEO {index} | Video ID: {video_id}{label} | {url} ===\n\n"
                f"{item.get('transcript', '')}\n"
            )
        elif status == "no_transcript":
            sections.append(
                f"=== VIDEO {index} | Video ID: {video_id}{label} | {url} ===\n"
                "[No captions or transcripts were available in the requested language(s).]\n"
            )
        elif status == "unavailable":
            sections.append(
                f"=== VIDEO {index} | Video ID: {video_id}{label} | {url} ===\n"
                f"[Unavailable: {item.get('error', 'Video unavailable.') }]\n"
            )
        elif status == "failed":
            sections.append(
                f"=== VIDEO {index} | Video ID: {video_id}{label} | {url} ===\n"
                f"[Error: {item.get('error', 'Transcript retrieval failed.') }]\n"
            )
        else:
            sections.append(
                f"=== VIDEO {index} | Video ID: {video_id}{label} | {url} ===\n"
                "[Pending: this video has not been processed yet. Use Resume remaining videos.]\n"
            )

    return "\n\n".join(sections).rstrip() + "\n"


def process_saved_batch(state, browser=None):
    browser = normalize_browser(browser if browser is not None else state.get("browser"))
    state["browser"] = browser
    state["block_reason"] = ""
    state["is_processing"] = True
    state.setdefault("current_video_index", 0)
    state.setdefault("current_video_title", "")
    state.setdefault("current_video_status", "Starting batch")
    state.setdefault("current_video_progress", 0)
    save_batch_state(state)

    videos = state.get("videos") or []
    for index, item in enumerate(videos):
        if item.get("status") not in ("pending", "failed"):
            continue

        state["current_video_index"] = index + 1
        state["current_video_title"] = item.get("title") or item.get("video_id")
        state["current_video_status"] = "Requesting captions from YouTube…"
        state["current_video_progress"] = 15
        item["status"] = "pending"
        save_batch_state(state)

        try:
            state["current_video_status"] = "Retrieving and formatting captions…"
            state["current_video_progress"] = 45
            save_batch_state(state)

            transcript = fetch_single_transcript(
                item["video_id"],
                bool(state.get("include_timestamps", True)),
                state.get("languages") or ["en"],
                browser=browser,
            )
            state["current_video_status"] = "Saving transcript…"
            state["current_video_progress"] = 90
            save_batch_state(state)

            item["status"] = "complete"
            item["transcript"] = transcript
            item["error"] = ""
            state["current_video_progress"] = 100
            state["current_video_status"] = "Transcript saved"
        except NoTranscriptAvailable as exc:
            item["status"] = "no_transcript"
            item["error"] = str(exc)
            state["current_video_progress"] = 100
            state["current_video_status"] = "No captions available"
        except TranscriptUnavailable as exc:
            item["status"] = "unavailable"
            item["error"] = str(exc)
            state["current_video_progress"] = 100
            state["current_video_status"] = "Video unavailable"
        except TranscriptBlocked as exc:
            item["status"] = "pending"
            item["error"] = str(exc)
            state["block_reason"] = str(exc)
            state["current_video_status"] = "Paused — YouTube blocked the request"
            state["is_processing"] = False
            save_batch_state(state)
            break
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = describe_transcript_error(exc)
            state["current_video_progress"] = 100
            state["current_video_status"] = "This video failed; continuing to the next"

        save_batch_state(state)

        if index < len(videos) - 1:
            time.sleep(REQUEST_DELAY_SECONDS)

    state["updated_at"] = datetime.now().astimezone().isoformat()
    state["is_processing"] = False
    if not state.get("block_reason"):
        state["current_video_status"] = "Batch finished"
        state["current_video_progress"] = 100
    save_batch_state(state)

    filename = f"dnd_transcripts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    return make_text_download(build_batch_export(state), filename)


def batch_progress_snapshot():
    state = load_batch_state()
    if not state:
        return {
            "exists": False,
            "processing": False,
            "total": 0,
            "processed": 0,
            "pending": 0,
            "retryable": 0,
            "percent": 0,
            "successful": 0,
            "no_transcript": 0,
            "unavailable": 0,
            "failed": 0,
            "current_index": 0,
            "current_title": "",
            "current_status": "No batch loaded",
            "current_progress": 0,
            "block_reason": "",
        }

    videos = state.get("videos") or []
    statuses = [item.get("status", "pending") for item in videos]
    total = len(videos)
    pending = statuses.count("pending")
    successful = statuses.count("complete")
    no_transcript = statuses.count("no_transcript")
    unavailable = statuses.count("unavailable")
    failed = statuses.count("failed")
    processed = total - pending
    percent = round(processed * 100 / total) if total else 0

    return {
        "exists": True,
        "playlist_title": state.get("playlist_title", "YouTube Playlist"),
        "processing": bool(state.get("is_processing")),
        "total": total,
        "processed": processed,
        "pending": pending,
        "retryable": pending + failed,
        "percent": percent,
        "successful": successful,
        "no_transcript": no_transcript,
        "unavailable": unavailable,
        "failed": failed,
        "current_index": state.get("current_video_index", 0),
        "current_title": state.get("current_video_title", ""),
        "current_status": state.get("current_video_status", ""),
        "current_progress": state.get("current_video_progress", 0),
        "block_reason": state.get("block_reason", ""),
    }


def _run_batch_worker(browser=None):
    try:
        state = load_batch_state()
        if state:
            process_saved_batch(state, browser=browser)
    except Exception as exc:
        state = load_batch_state()
        if state:
            state["is_processing"] = False
            state["current_video_status"] = f"Batch stopped unexpectedly ({type(exc).__name__})"
            state["block_reason"] = str(exc)
            save_batch_state(state)
    finally:
        BATCH_WORKER_LOCK.release()


def start_batch_worker(browser=None):
    """Run the long playlist batch outside the request so the page can poll progress."""
    if not BATCH_WORKER_LOCK.acquire(blocking=False):
        return False

    try:
        state = load_batch_state()
        if not state:
            BATCH_WORKER_LOCK.release()
            return False

        state["is_processing"] = True
        state["browser"] = normalize_browser(browser if browser is not None else state.get("browser"))
        state["current_video_status"] = "Starting batch…"
        save_batch_state(state)

        worker = threading.Thread(
            target=_run_batch_worker,
            args=(state["browser"],),
            daemon=True,
            name="transcript-batch-worker",
        )
        worker.start()
        return True
    except Exception:
        BATCH_WORKER_LOCK.release()
        raise


@app.route("/connect-youtube", methods=["GET", "POST"])
def connect_youtube():
    global OAUTH_FLOW, OAUTH_STATE
    try:
        flow, authorization_url, state = create_authorization_request(
            request.url_root.rstrip("/")
        )
        with OAUTH_LOCK:
            OAUTH_FLOW = flow
            OAUTH_STATE = state
        # Navigate this tab to Google; no form submission or popup is required.
        return redirect(authorization_url)
    except YouTubeApiError as exc:
        return render_page(str(exc), status=400)
    except Exception as exc:
        return render_page(
            f"Google authorization could not start ({type(exc).__name__}). Check your OAuth Desktop client setup and try again.",
            status=400,
        )


@app.route("/", methods=["GET", "POST"])
def index():
    global OAUTH_FLOW, OAUTH_STATE
    if request.method == "GET":
        if "code" in request.args or "error" in request.args:
            with OAUTH_LOCK:
                flow = OAUTH_FLOW
                expected_state = OAUTH_STATE

            if flow is None:
                return render_page(
                    "There is no pending Google authorization. Click Connect YouTube account and try again.",
                    status=400,
                )

            try:
                complete_authorization(flow, expected_state or "", request.url)
            except YouTubeApiError as exc:
                with OAUTH_LOCK:
                    OAUTH_FLOW = None
                    OAUTH_STATE = None
                return render_page(str(exc), status=400)
            except Exception as exc:
                with OAUTH_LOCK:
                    OAUTH_FLOW = None
                    OAUTH_STATE = None
                return render_page(
                    f"Google authorization failed ({type(exc).__name__}). Please try connecting again.",
                    status=400,
                )

            with OAUTH_LOCK:
                OAUTH_FLOW = None
                OAUTH_STATE = None
            return redirect(url_for("index"))

        return render_page()

    raw_urls = request.form.get("urls", "")
    include_timestamps = "timestamps" in request.form
    urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
    raw_languages = request.form.get("languages", "en")
    browser = normalize_browser(request.form.get("browser", ""))

    if not urls:
        return render_page(
            "Please paste at least one YouTube link.",
            raw_urls,
            raw_languages,
            include_timestamps,
            400,
        )

    if len(urls) > MAX_VIDEOS:
        return render_page(
            f"Please limit individual-link batches to {MAX_VIDEOS} videos. "
            "Use playlist selection for larger batches.",
            raw_urls,
            raw_languages,
            include_timestamps,
            400,
        )

    try:
        languages = parse_languages(raw_languages)
    except ValueError as exc:
        return render_page(str(exc), raw_urls, raw_languages, include_timestamps, 400)

    connection = get_connection_status()
    if not connection["connected"]:
        return render_page(
            connection["message"] + " Connect your YouTube account before downloading transcripts.",
            raw_urls,
            raw_languages,
            include_timestamps,
            400,
        )

    video_items = []
    for url in urls:
        video_id = extract_video_id(url)
        video_items.append({"video_id": video_id or "", "title": url})

    return create_transcript_response(
        video_items, include_timestamps, languages, browser=browser
    )


@app.route("/load-playlist", methods=["POST"])
def load_playlist():
    playlist_url = request.form.get("playlist_url", "").strip()
    raw_languages = request.form.get("languages", "en")
    include_timestamps = "timestamps" in request.form
    browser = normalize_browser(request.form.get("browser", ""))

    if not extract_playlist_id(playlist_url):
        return render_page(
            "Paste a valid YouTube playlist link containing a playlist ID.",
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_url=playlist_url,
            status=400,
        )

    try:
        languages = parse_languages(raw_languages)
        playlist = fetch_playlist_entries(playlist_url, browser=browser)
    except ValueError as exc:
        return render_page(
            str(exc),
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_url=playlist_url,
            browser=browser,
            status=400,
        )
    except DownloadError:
        return render_page(
            "YouTube could not read this playlist. Check the link and confirm the playlist "
            "is public or unlisted. YouTube may also be temporarily limiting playlist requests.",
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_url=playlist_url,
            browser=browser,
            status=400,
        )
    except Exception as exc:
        return render_page(
            f"Unable to load the playlist ({type(exc).__name__}). Check the link and try again.",
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_url=playlist_url,
            browser=browser,
            status=400,
        )

    return render_page(
        languages=", ".join(languages),
        browser=browser,
        include_timestamps=include_timestamps,
        playlist_entries=playlist["entries"],
        playlist_title=playlist["title"],
        playlist_url=playlist_url,
        playlist_warning=playlist["warning"],
    )


@app.route("/download-playlist", methods=["POST"])
def download_playlist():
    playlist_entries = entries_from_selection_form()
    selected_ids = set(request.form.getlist("selected_video_ids"))
    selected_entries = [
        entry for entry in playlist_entries if entry["video_id"] in selected_ids
    ]
    playlist_title = re.sub(
        r"\s+", " ", request.form.get("playlist_title", "YouTube Playlist")
    ).strip()[:300]
    playlist_url = request.form.get("playlist_url", "")
    raw_languages = request.form.get("languages", "en")
    include_timestamps = "timestamps" in request.form
    browser = normalize_browser(request.form.get("browser", ""))

    if not selected_entries:
        return render_page(
            "Select at least one video from the playlist.",
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_entries=playlist_entries,
            playlist_title=playlist_title,
            playlist_url=playlist_url,
            selected_ids=selected_ids,
            status=400,
        )

    if len(selected_entries) > MAX_SELECTED_VIDEOS:
        return render_page(
            f"Please select no more than {MAX_SELECTED_VIDEOS} videos in one batch.",
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_entries=playlist_entries,
            playlist_title=playlist_title,
            playlist_url=playlist_url,
            selected_ids=selected_ids,
            status=400,
        )

    connection = get_connection_status()
    if not connection["connected"]:
        return render_page(
            connection["message"] + " Connect your YouTube account before downloading transcripts.",
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_entries=playlist_entries,
            playlist_title=playlist_title,
            playlist_url=playlist_url,
            selected_ids=selected_ids,
            status=400,
        )

    try:
        languages = parse_languages(raw_languages)
    except ValueError as exc:
        return render_page(
            str(exc),
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_entries=playlist_entries,
            playlist_title=playlist_title,
            playlist_url=playlist_url,
            status=400,
        )

    state = {
        "playlist_title": playlist_title,
        "playlist_url": playlist_url,
        "languages": languages,
        "include_timestamps": include_timestamps,
        "browser": browser,
        "created_at": datetime.now().astimezone().isoformat(),
        "block_reason": "",
        "is_processing": False,
        "current_video_index": 0,
        "current_video_title": "",
        "current_video_status": "Queued",
        "current_video_progress": 0,
        "videos": [
            {
                **entry,
                "status": "pending",
                "transcript": "",
                "error": "",
            }
            for entry in selected_entries
        ],
    }
    save_batch_state(state)
    if not start_batch_worker(browser=browser):
        return render_page("Another transcript batch is already running.", status=409)
    return redirect(url_for("batch_progress_page"))


@app.route("/resume-last", methods=["POST"])
def resume_last_batch():
    state = load_batch_state()
    if not state:
        return render_page("There is no saved batch to resume.", status=400)

    connection = get_connection_status()
    if not connection["connected"]:
        return render_page(
            connection["message"] + " Connect your YouTube account before resuming this batch.",
            status=400,
        )

    if not start_batch_worker(browser=""):
        return render_page("Another transcript batch is already running.", status=409)
    return redirect(url_for("batch_progress_page"))


@app.route("/batch-progress")
def batch_progress_page():
    state = load_batch_state()
    if not state:
        return redirect(url_for("index"))
    page = render_template_string(
        PROGRESS_TEMPLATE,
        playlist_title=state.get("playlist_title", "YouTube Playlist"),
    )
    return page


@app.route("/api/batch-progress")
def batch_progress_api():
    return jsonify(batch_progress_snapshot())


@app.route("/download-last", methods=["POST"])
def download_last_batch():
    state = load_batch_state()
    if not state:
        return render_page("There is no saved batch to download.", status=400)
    filename = f"dnd_transcripts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    return make_text_download(build_batch_export(state), filename)


@app.route("/clear-last-batch", methods=["POST"])
def clear_last_batch():
    clear_batch_state()
    return redirect(url_for("index"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    url = f"http://127.0.0.1:{port}"
    print(f"Starting D&D Transcript Scraper at {url}", flush=True)
    print("The browser will open automatically. Press Ctrl+C to stop the app.", flush=True)

    threading.Timer(1.0, lambda: webbrowser.open_new_tab(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
