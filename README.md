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

## If YouTube blocks a batch

The app now uses yt-dlp to retrieve caption files rather than the separate transcript API. It can use captions created by the uploader or automatically generated captions.

You can optionally select **Chrome**, **Edge**, or **Firefox** as the browser session. Use this when you are signed in to YouTube in that browser and the videos are available to your account. The app reads the browser cookies locally for that run; it does not save or upload them. If yt-dlp cannot read a browser's cookie database, completely close that browser and try again.

Every completed transcript is saved locally as the batch runs. If YouTube blocks a request, the current and remaining videos stay pending. Return to the app home page and select **Resume remaining videos** after waiting, optionally choosing a signed-in browser session. Videos already completed or confirmed to have no captions are not requested again.

The last batch and its downloaded transcript text are kept in the local **data** folder so it can be resumed after closing the app. Use **Clear saved batch** on the home page to remove it. The data folder is excluded from Git.

## Individual video links

The individual-link workflow remains available. Paste up to 10 YouTube links, one per line. Standard watch links, youtu.be links, Shorts, live links, embed links, and 11-character video IDs are accepted.

## Options

- **Languages:** Enter language codes in preference order, separated by commas (for example, en, es). English is the default.
- **Timestamps:** Include a timestamp approximately every 60 seconds in each transcript.
- **Browser session:** Optional Chrome, Edge, or Firefox cookies. This is useful for videos that require your own YouTube account access.

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

- A video needs captions or an available transcript. If YouTube has no caption track, the app cannot create a verbatim transcript.
- Unlisted playlists and videos are supported when YouTube makes their data/captions available.
- YouTube may still limit requests, even with slower downloads or browser cookies. The saved-batch/resume feature is designed to avoid losing work when that happens.
- This is a local app. It listens only on your computer (127.0.0.1); it is not a public website.
