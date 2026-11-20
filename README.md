# D&D Session Transcript Scraper

A local web app that downloads YouTube transcripts into one combined text file. It supports individual links and playlist-based selection.

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
- The app reads the playlist title and video list without downloading video files.
- Search the titles or video IDs to narrow the list.
- Use **Select all** to select all currently visible search results, or **Clear selection** to uncheck everything.
- Select up to **200 videos per transcript batch**. Playlists can contain up to 500 entries in the selector; larger playlists are limited to the first 500 entries.
- The app retrieves transcripts sequentially and combines them in playlist order. If YouTube temporarily blocks transcript requests, it stops the batch and marks the remaining videos as skipped.

Public and unlisted playlists are supported when YouTube makes their playlist data available. Private playlists and private videos require account access; this app does not sign in to YouTube.

## Individual video links

The original individual-link workflow is still available. Paste up to 10 YouTube links, one per line. Standard watch links, youtu.be links, Shorts, live links, embed links, and 11-character video IDs are accepted.

## Options

- **Languages:** Enter language codes in preference order, separated by commas (for example, en, es). English is the default.
- **Timestamps:** Include a timestamp approximately every 60 seconds in each transcript.

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

- A video needs captions or an available transcript.
- Unlisted videos are supported when captions are available.
- YouTube can change how playlist data is exposed. If a playlist will not load, update the packages by running the app again; the launcher checks requirements each time.
- This is a local app. It listens only on your computer (127.0.0.1); it is not a public website.
