# D&D Session Transcript Scraper

A local web app that downloads YouTube transcripts into one combined text file. It supports individual links and playlist-based selection, with resumable playlist batches.

## Easiest setup (Windows)

1. Install **Python 3.11 or newer** from https://www.python.org/downloads/. During installation, enable **Add Python to PATH**.
2. Download this repository as a ZIP and extract the folder.
3. Double-click **run.bat**.
4. On the first run, the launcher creates a local Python environment and installs the required packages. It then starts the app and opens your browser.
5. Paste a playlist link and click **Load playlist videos**. Search the list, select the videos you want, and click **Download selected transcripts**.

The first launch needs an internet connection to install the packages. The yt-dlp installation includes its recommended JavaScript support and Deno runtime; you do not need to install those separately.

To stop the app, close its command window or press **Ctrl+C** in that window.

## Playlist selection

- Paste a standard YouTube playlist URL, including a playlist ID in the URL.
- The app reads the playlist title and video list without downloading video or audio.
- Search the titles or video IDs to narrow the list.
- Use **Select visible** to select all currently visible search results, or **Clear selection** to uncheck everything.
- Select up to **200 videos per transcript batch**. Playlists can contain up to 500 entries in the selector; larger playlists are limited to the first 500 entries.
- Transcripts are retrieved sequentially and combined in playlist order.
- During a download, a live progress page shows the current video's status and overall batch completion.

## YouTube account setup

Transcript retrieval uses the official YouTube Data API. This is the reliable path for videos you own or have permission to edit. The app can retrieve uploader-provided captions and automatically generated speech-recognition captions when YouTube exposes those tracks.

Complete this one-time setup:

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. Enable **YouTube Data API v3** for the project.
3. Open **Google Auth Platform** while signed in to the same Google account that owns or manages your YouTube channel. For a personal, single-account installation, choose **Personal** audience mode when creating the app. This authorizes only that exact Google account, but avoids the seven-day test-token expiration and the unverified-app warning. Personal mode is permanent for that project; you cannot later switch it to External or Internal. Choose External instead if you need different Google accounts to authorize the app.
4. Under **Data Access**, make sure the YouTube scope `https://www.googleapis.com/auth/youtube.force-ssl` is available.
5. Create an OAuth client with application type **Desktop app** and download its JSON file.
6. Rename the downloaded file to **client_secret.json** and place it in the same folder as **run.bat**.
7. Start the app and click **Connect YouTube account**. Sign in with the Google account that owns the videos, or has permission to edit them.

The app saves its refreshable authorization token in **data/youtube_token.json**. Both the token and OAuth client JSON stay on your computer; neither belongs in GitHub or in a shared ZIP. The app uses the OAuth scope Google requires for caption retrieval. That scope is broader than the app's read-only behavior and can permit editing or deleting YouTube content at the Google API permission level; this app only calls the caption-list and caption-download methods.

If you configure the project as an **External** app and leave its publishing status at **Testing**, Google expires the authorization after seven days for this YouTube scope. You will need to reconnect periodically. Personal mode is the simpler choice when the same Google account will always use the app.

## Caption retrieval, quota, and resume

- The app calls `captions.list` to find the available tracks, prefers a standard track, and uses an `ASR` automatically generated track when that is the available match.
- It calls `captions.download` for one selected language track and converts the returned WebVTT into the existing combined text export.
- The current documented quota costs are 50 units for `captions.list` and 200 units for `captions.download`, or about **250 units per video** when one track is downloaded. With the default 10,000-unit daily allowance, that is approximately **40 videos per day**.
- If the daily quota is exhausted, the batch pauses. Every completed transcript remains saved locally; use **Resume remaining videos** after the quota resets. Completed videos are not requested again.
- No video or audio is downloaded.

## Individual video links

The individual-link workflow remains available. Paste up to 10 YouTube links, one per line. Standard watch links, youtu.be links, Shorts, live links, embed links, and 11-character video IDs are accepted.

## Options

- **Languages:** Enter language codes in preference order, separated by commas (for example, en, es). English is the default.
- **Timestamps:** Include a timestamp approximately every 60 seconds in each transcript.
- **Playlist browser session:** Optional Chrome, Edge, or Firefox cookies for loading private playlist metadata. Caption retrieval itself uses the connected Google account.

## Manual setup

Python 3.11 or newer is required.

Create and activate a virtual environment:

~~~bash
python -m venv .venv
~~~

Windows:

~~~powershell
.venv\Scripts\activate
~~~

macOS / Linux:

~~~bash
source .venv/bin/activate
~~~

Install and start the app:

~~~bash
python -m pip install -r requirements.txt
python app.py
~~~

Open the address printed in the terminal (normally http://127.0.0.1:5000).

## Run the tests

With the environment activated:

~~~bash
python -m unittest discover -v
~~~

## Important notes

- A video needs a caption track that the connected Google account can access. If YouTube has no caption track, the app cannot create a verbatim transcript.
- Unlisted playlists and videos are supported when YouTube makes their data/captions available.
- The YouTube Data API enforces daily quota. The saved-batch/resume feature is designed to pause cleanly when the quota is exhausted without losing completed transcripts.
- This is a local app. It listens only on your computer (127.0.0.1); it is not a public website.
