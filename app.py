import os
import re
import threading
import time
import webbrowser
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from flask import Flask, Response, render_template_string, request
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from youtube_transcript_api import (
    AgeRestricted,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)

app = Flask(__name__)

MAX_VIDEOS = 10
MAX_PLAYLIST_ENTRIES = 500
MAX_SELECTED_VIDEOS = 200
REQUEST_DELAY_SECONDS = 1.5
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

    {% if error %}
    <div class="error" role="alert">{{ error }}</div>
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
                <button type="button" class="secondary" id="selectAll">Select all</button>
                <button type="button" class="secondary" id="clearAll">Clear selection</button>
            </div>

            <div class="selection-summary" id="selectionCount" aria-live="polite">0 selected</div>

            <div class="video-list" id="videoList">
                {% for video in playlist_entries %}
                <label class="video-row" data-search="{{ (video.title ~ ' ' ~ video.video_id)|lower }}">
                    <input class="video-checkbox" type="checkbox" name="selected_video_ids" value="{{ video.video_id }}">
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
        <strong>Notes:</strong> Public and unlisted playlists can be read when YouTube makes their playlist data available.
        Private playlists and private videos require access the app does not have. A video must have captions or an available transcript.
        YouTube may temporarily block transcript requests; the app stops the batch if that happens.
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
):
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
    if not playlist_id or not re.fullmatch(r"[A-Za-z0-9_-]{10,128}", playlist_id):
        return None

    return playlist_id


def format_duration(seconds):
    if seconds is None:
        return "Duration unavailable"
    try:
        return format_seconds(float(seconds))
    except (TypeError, ValueError):
        return "Duration unavailable"


def fetch_playlist_entries(playlist_url: str):
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


def create_transcript_response(video_items, include_timestamps, languages, playlist_title=None):
    """Fetch selected transcripts sequentially and return one combined text file."""
    api = YouTubeTranscriptApi()
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
        url = f"https://www.youtube.com/watch?v={video_id}"
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()[:300]

        if not video_id:
            output_sections.append(
                f"=== VIDEO {index}: INVALID YOUTUBE URL ===\n"
                f"Input: {title}\n"
                "[Error: Paste a valid YouTube video link or 11-character video ID.]\n"
            )
            continue

        try:
            body = fetch_single_transcript(api, video_id, include_timestamps, languages)
            if not body:
                body = "[No transcript text was returned for this video.]"

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

            if isinstance(exc, RequestBlocked):
                for skipped_index, skipped_item in enumerate(video_items[index:], start=index + 1):
                    output_sections.append(
                        f"=== VIDEO {skipped_index} | Video ID: {skipped_item['video_id']} ===\n"
                        "[Skipped because YouTube blocked an earlier request.]\n"
                    )
                break

        if index < len(video_items):
            time.sleep(REQUEST_DELAY_SECONDS)

    combined_text = "\n\n".join(output_sections).rstrip() + "\n"
    filename = f"dnd_transcripts_{now.strftime('%Y%m%d_%H%M%S')}.txt"

    return Response(
        combined_text,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def fetch_single_transcript(
    api: YouTubeTranscriptApi,
    video_id: str,
    include_timestamps: bool,
    languages=None,
) -> str:
    transcript = api.fetch(video_id, languages=languages or ["en"])
    lines = []
    current_paragraph = []
    last_timestamp = -60.0

    for snippet in transcript:
        start = float(snippet.start or 0)
        text = re.sub(r"\s+", " ", (snippet.text or "")).strip()
        if not text:
            continue

        if include_timestamps and start - last_timestamp >= 60:
            if current_paragraph:
                lines.append(" ".join(current_paragraph))
                current_paragraph = []
            lines.append(f"[{format_seconds(start)}]")
            last_timestamp = start

        current_paragraph.append(text)

    if current_paragraph:
        lines.append(" ".join(current_paragraph))

    return "\n".join(lines)


def describe_transcript_error(exc: Exception) -> str:
    """Convert known API failures into messages a user can act on."""
    if isinstance(exc, RequestBlocked):
        return (
            "YouTube is temporarily blocking transcript requests from this network. "
            "The batch was stopped to avoid sending more requests. Try again later."
        )
    if isinstance(exc, AgeRestricted):
        return "YouTube marked this video as age-restricted, so its transcript could not be retrieved."
    if isinstance(exc, TranscriptsDisabled):
        return "Captions and transcripts are disabled for this video."
    if isinstance(exc, NoTranscriptFound):
        return "No transcript was found in the requested language(s). Try another language code."
    if isinstance(exc, VideoUnavailable):
        return "The video is unavailable or private. Unlisted videos are supported."
    if isinstance(exc, YouTubeTranscriptApiException):
        return f"The transcript service could not retrieve this video ({type(exc).__name__})."
    return f"An unexpected error occurred ({type(exc).__name__})."


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_page()

    raw_urls = request.form.get("urls", "")
    include_timestamps = "timestamps" in request.form
    urls = [line.strip() for line in raw_urls.splitlines() if line.strip()]
    raw_languages = request.form.get("languages", "en")

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

    video_items = []
    for url in urls:
        video_id = extract_video_id(url)
        video_items.append({"video_id": video_id or "", "title": url})

    return create_transcript_response(video_items, include_timestamps, languages)


@app.route("/load-playlist", methods=["POST"])
def load_playlist():
    playlist_url = request.form.get("playlist_url", "").strip()
    raw_languages = request.form.get("languages", "en")
    include_timestamps = "timestamps" in request.form

    try:
        languages = parse_languages(raw_languages)
        playlist = fetch_playlist_entries(playlist_url)
    except ValueError as exc:
        return render_page(
            str(exc),
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_url=playlist_url,
            status=400,
        )
    except DownloadError:
        return render_page(
            "YouTube could not read this playlist. Check the link and confirm the playlist "
            "is public or unlisted. YouTube may also be temporarily limiting playlist requests.",
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_url=playlist_url,
            status=400,
        )
    except Exception as exc:
        return render_page(
            f"Unable to load the playlist ({type(exc).__name__}). Check the link and try again.",
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_url=playlist_url,
            status=400,
        )

    return render_page(
        languages=", ".join(languages),
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

    if not selected_entries:
        return render_page(
            "Select at least one video from the playlist.",
            languages=raw_languages,
            include_timestamps=include_timestamps,
            playlist_entries=playlist_entries,
            playlist_title=playlist_title,
            playlist_url=playlist_url,
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

    return create_transcript_response(
        selected_entries,
        include_timestamps,
        languages,
        playlist_title=playlist_title,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    url = f"http://127.0.0.1:{port}"
    print(f"Starting D&D Transcript Scraper at {url}", flush=True)
    print("The browser will open automatically. Press Ctrl+C to stop the app.", flush=True)

    threading.Timer(1.0, lambda: webbrowser.open_new_tab(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
