import os
import re
import threading
import time
import webbrowser
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from flask import Flask, Response, render_template_string, request
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
REQUEST_DELAY_SECONDS = 1.0
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
            max-width: 760px;
            margin: 40px auto;
            padding: 0 20px;
            background: #18181b;
            color: #f4f4f5;
        }
        h1 { color: #e4e4e7; margin-bottom: 8px; }
        p.subtitle { color: #a1a1aa; margin-top: 0; margin-bottom: 24px; }
        textarea, input[type="text"] {
            width: 100%;
            box-sizing: border-box;
            background: #27272a;
            color: #f4f4f5;
            border: 1px solid #52525b;
            border-radius: 8px;
            padding: 12px;
            font: 14px ui-monospace, monospace;
        }
        textarea { min-height: 190px; resize: vertical; }
        input[type="text"] { margin-top: 8px; }
        textarea:focus, input[type="text"]:focus {
            outline: 2px solid #a78bfa;
            outline-offset: 2px;
        }
        .controls {
            margin: 18px 0 24px;
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            align-items: center;
        }
        label { color: #d4d4d8; }
        .checkbox-label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
        button {
            background: #7c3aed;
            color: white;
            border: none;
            padding: 12px 24px;
            font-size: 16px;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
        }
        button:hover { background: #6d28d9; }
        button:focus-visible { outline: 2px solid white; outline-offset: 3px; }
        .field { margin-top: 18px; }
        .help { color: #a1a1aa; font-size: 13px; margin: 6px 0 0; }
        .note {
            font-size: 13px;
            line-height: 1.5;
            color: #a1a1aa;
            background: #27272a;
            padding: 12px 16px;
            border-radius: 6px;
            border-left: 3px solid #7c3aed;
            margin-top: 28px;
        }
        .error {
            background: #450a0a;
            color: #fecaca;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 16px;
        }
        @media (max-width: 520px) {
            body { margin: 24px auto; }
            button { width: 100%; }
        }
    </style>
</head>
<body>
    <h1>D&D Session Transcript Scraper</h1>
    <p class="subtitle">
        Paste up to 10 public or unlisted YouTube links below, one per line.
        The app combines their transcripts into one downloadable text file.
    </p>

    {% if error %}
    <div class="error" role="alert">{{ error }}</div>
    {% endif %}

    <form method="POST">
        <label for="urls">YouTube links</label>
        <textarea id="urls" name="urls" placeholder="https://www.youtube.com/watch?v=...&#10;https://youtu.be/..." required>{{ urls }}</textarea>

        <div class="field">
            <label for="languages">Preferred transcript languages</label>
            <input id="languages" name="languages" type="text" value="{{ languages }}" placeholder="en, es">
            <p class="help">Comma-separated language codes, in preference order. Defaults to English.</p>
        </div>

        <div class="controls">
            <label class="checkbox-label">
                <input type="checkbox" name="timestamps" {% if include_timestamps %}checked{% endif %}>
                Include timestamps approximately every 60 seconds
            </label>
        </div>

        <button type="submit">Download Combined Transcripts (.txt)</button>
    </form>

    <div class="note">
        <strong>Notes:</strong> Unlisted videos work when captions are available.
        Private videos and videos without captions cannot be retrieved. YouTube may
        temporarily block transcript requests after too many requests; the app will
        stop the batch rather than keep sending requests after a block.
    </div>
</body>
</html>
"""


def render_page(error=None, urls="", languages="en", include_timestamps=True, status=200):
    page = render_template_string(
        HTML_TEMPLATE,
        error=error,
        urls=urls,
        languages=languages,
        include_timestamps=include_timestamps,
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
            f"Please limit each batch to {MAX_VIDEOS} links.",
            raw_urls,
            raw_languages,
            include_timestamps,
            400,
        )

    try:
        languages = parse_languages(raw_languages)
    except ValueError as exc:
        return render_page(str(exc), raw_urls, raw_languages, include_timestamps, 400)

    api = YouTubeTranscriptApi()
    now = datetime.now().astimezone()
    output_sections = [
        "D&D CAMPAIGN SESSION TRANSCRIPTS",
        f"Exported: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "=" * 60,
        "",
    ]

    for index, url in enumerate(urls, start=1):
        video_id = extract_video_id(url)
        if not video_id:
            output_sections.append(
                f"=== SESSION {index}: INVALID YOUTUBE URL ===\n"
                f"Input: {url}\n"
                "[Error: Paste a valid YouTube video link or 11-character video ID.]\n"
            )
            continue

        try:
            body = fetch_single_transcript(api, video_id, include_timestamps, languages)
            if not body:
                body = "[No transcript text was returned for this video.]"
            output_sections.append(
                f"=== SESSION {index} | Video ID: {video_id} | {url} ===\n\n"
                f"{body}\n"
            )
        except Exception as exc:
            message = describe_transcript_error(exc)
            output_sections.append(
                f"=== SESSION {index} | Video ID: {video_id} | {url} ===\n"
                f"[Error: {message}]\n"
            )

            if isinstance(exc, RequestBlocked):
                for skipped_index, skipped_url in enumerate(urls[index:], start=index + 1):
                    output_sections.append(
                        f"=== SESSION {skipped_index} | SKIPPED ===\n"
                        "[Skipped because YouTube blocked an earlier request.]\n"
                    )
                break

        if index < len(urls):
            time.sleep(REQUEST_DELAY_SECONDS)

    combined_text = "\n\n".join(output_sections).rstrip() + "\n"
    filename = f"dnd_transcripts_{now.strftime('%Y%m%d_%H%M%S')}.txt"

    return Response(
        combined_text,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    url = f"http://127.0.0.1:{port}"
    print(f"Starting D&D Transcript Scraper at {url}", flush=True)
    print("The browser will open automatically. Press Ctrl+C to stop the app.", flush=True)

    threading.Timer(1.0, lambda: webbrowser.open_new_tab(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
