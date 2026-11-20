# D&D Session Transcript Scraper

A small local web app that takes up to 10 public or unlisted YouTube video links and downloads their transcripts as one combined text file.

## Easiest setup (Windows)

1. Install **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/). During installation, enable **Add Python to PATH**.
2. Download this repository as a ZIP and extract the folder.
3. Double-click **run.bat**.
4. On the first run, the launcher creates a local Python environment and installs the required packages. It then starts the app and opens your browser.
5. Paste your YouTube links, one per line, and select **Download Combined Transcripts (.txt)**.

The first launch needs an internet connection to install the packages. Later launches verify the installed requirements and only install or update packages when needed.

To stop the app, close its command window or press **Ctrl+C** in that window.

## Options

- **Links:** Up to 10 links per batch. Standard watch links, youtu.be links, Shorts, live links, embed links, and 11-character video IDs are accepted.
- **Languages:** Enter language codes in preference order, separated by commas (for example, en, es). English is the default.
- **Timestamps:** Include a timestamp approximately every 60 seconds.

## Manual setup

You can also run it from a terminal:

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

Then install and start the app:

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

- **Unlisted videos** are supported when YouTube makes captions available.
- **Private videos** cannot be retrieved. This app does not sign in to YouTube or access private account content.
- A video needs captions or an available transcript. The app reports when captions are disabled or the requested language is unavailable.
- YouTube can temporarily block transcript requests from a network. The app reports this and stops the batch instead of continuing to send requests.
- This is a local app. It listens only on your computer (127.0.0.1); it is not a public website.
