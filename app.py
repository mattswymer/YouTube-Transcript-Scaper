import re
import time
import urllib.parse
from datetime import datetime
from flask import Flask, render_template_string, request, Response
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound, VideoUnavailable

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>D&D Session Transcript Scraper</title>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 20px; background: #18181b; color: #f4f4f5; }
        h1 { color: #e4e4e7; margin-bottom: 8px; }
        p.subtitle { color: #a1a1aa; margin-top: 0; margin-bottom: 24px; }
        textarea { width: 100%; height: 180px; background: #27272a; color: #f4f4f5; border: 1px solid #3f3f46; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 14px; box-sizing: border-box; }
        .controls { margin: 16px 0 24px; display: flex; flex-wrap: wrap; gap: 20px; align-items: center; }
        label { display: flex; align-items: center; gap: 8px; cursor: pointer; color: #d4d4d8; }
        button { background: #7c3aed; color: white; border: none; padding: 12px 24px; font-size: 16px; font-weight: 600; border-radius: 8px; cursor: pointer; }
        button:hover { background: #6d28d9; }
        .note { font-size: 13px; color: #a1a1aa; background: #27272a; padding: 12px 16px; border-radius: 6px; border-left: 3px solid #7c3aed; }
        .error { background: #450a0a; color: #fca5a5; padding: 12px; border-radius: 6px; margin-bottom: 16px; }
    </style>
</head>
<body>
    <h1>D&D Session Transcript Scraper</h1>
    <p class="subtitle">Paste up to 10 unlisted or public YouTube links below (one per line) to download a single combined .txt file.</p>
    
    {% if error %}
    <div class="error">{{ error }}</div>
    {% endif %}

    <form method="POST">
        <textarea name="urls" placeholder="https://www.youtube.com/watch?v=...&#10;https://youtu.be/..." required></textarea>
        
        <div class="controls">
            <label>
                <input type="checkbox" name="timestamps" checked>
                Include timestamps every ~60 seconds
            </label>
        </div>
        
        <button type="submit">Download Combined Transcripts (.txt)</button>
    </form>

    <div class="note" style="margin-top: 28px;">
        <strong>Tips:</strong> Unlisted links work automatically as long as captions/auto-captions are available on the video. Keep batches to 10 or fewer links at a time so YouTube doesn't rate-limit your IP.
    </div>
</body>
</html>
"""

def extract_video_id(url: str):
    url = url.strip()
    if not url:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname in ("youtu.be", "www.youtu.be"):
        return parsed.path.lstrip("/").split("/")[0]
    if parsed.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            qs = urllib.parse.parse_qs(parsed.query)
            return qs.get("v", [None])[0]
        if parsed.path.startswith(("/embed/", "/v/", "/live/", "/shorts/")):
            return parsed.path.split("/")[2]
    return None

def format_seconds(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def fetch_single_transcript(api: YouTubeTranscriptApi, video_id: str, include_timestamps: bool) -> str:
    transcript = api.fetch(video_id)
    lines = []
    last_stamp = -60
    current_paragraph = []

    for snippet in transcript:
        start = snippet.start
        text = snippet.text.replace("\n", " ").strip()
        if not text:
            continue

        if include_timestamps and (start - last_stamp >= 60):
            if current_paragraph:
                lines.append(" ".join(current_paragraph))
                current_paragraph = []
            lines.append(f"[{format_seconds(start)}]")
            last_stamp = start

        current_paragraph.append(text)

    if current_paragraph:
        lines.append(" ".join(current_paragraph))

    return "\n".join(lines)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template_string(HTML_TEMPLATE)

    raw_urls = request.form.get("urls", "")
    include_timestamps = "timestamps" in request.form
    lines = [line.strip() for line in raw_urls.splitlines() if line.strip()]

    if not lines:
        return render_template_string(HTML_TEMPLATE, error="Please paste at least one YouTube link.")

    if len(lines) > 10:
        return render_template_string(HTML_TEMPLATE, error="Please limit batches to 10 links at a time to avoid YouTube rate limits.")

    api = YouTubeTranscriptApi()
    output_sections = [
        f"D&D CAMPAIGN SESSION TRANSCRIPTS",
        f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60 + "\n"
    ]

    for idx, line in enumerate(lines, start=1):
        video_id = extract_video_id(line)
        if not video_id:
            output_sections.append(f"=== SESSION {idx}: INVALID URL ({line}) ===\n")
            continue

        try:
            body = fetch_single_transcript(api, video_id, include_timestamps)
            output_sections.append(f"=== SESSION {idx} | Video ID: {video_id} | {line} ===\n\n{body}\n\n")
        except (TranscriptsDisabled, NoTranscriptFound):
            output_sections.append(f"=== SESSION {idx} | Video ID: {video_id} ===\n[Error: No captions/transcript found for this video.]\n\n")
        except VideoUnavailable:
            output_sections.append(f"=== SESSION {idx} | Video ID: {video_id} ===\n[Error: Video is unavailable or private (note: Unlisted works, Private does not).]\n\n")
        except Exception as exc:
            output_sections.append(f"=== SESSION {idx} | Video ID: {video_id} ===\n[Error: {exc}]\n\n")

        if idx < len(lines):
            time.sleep(1.5)  # Polite pause between requests

    combined_text = "\n".join(output_sections)
    filename = f"dnd_transcripts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    return Response(
        combined_text,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

if __name__ == "__main__":
    print("Starting D&D Transcript Scraper at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
