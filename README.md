# D&D Session Transcript Scraper

A lightweight local web app that takes up to 10 unlisted or public YouTube links and downloads a single combined `.txt` transcript file.

## Setup in PyCharm

1. Unzip this folder and open it in **PyCharm** (`File -> Open`).
2. Open the **Terminal** tab at the bottom of PyCharm and install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run `app.py` (right-click `app.py` -> **Run 'app'**).
4. Open the local link printed in the console (`http://127.0.0.1:5000`) in your browser, paste your unlisted YouTube links, and download your combined `.txt` file.

## Notes
- **Unlisted videos** work automatically as long as captions/auto-captions are enabled on YouTube. **Private** videos will not work because they require login authentication.
- Batches are capped at **10 links** with a short pause between videos to prevent YouTube from rate-limiting your IP address.
