# Web Interface

A browser-based frontend for yt-downloader, intended for local/self-hosted use.

## How it works

The web interface runs a small Flask server on your machine. The server calls the same
`core/downloader.py` logic used by the desktop apps. Your browser connects to
`http://localhost:5000`, sends requests to the server, and the server does the actual
downloading. Files are saved to a temporary folder and served back to your browser as
direct downloads.

Because the server runs locally, no data leaves your machine. This is not a hosted service.

## Requirements

- Python 3.10+
- ffmpeg installed and on PATH

**Install ffmpeg:**
- macOS: `brew install ffmpeg`
- Windows: [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/)
- Linux: `sudo apt install ffmpeg`

## Setup

Run these commands from the **repo root** (not from inside `web/`):

```bash
pip install -r web/requirements.txt
python web/app.py
```

Then open [http://localhost:5000](http://localhost:5000) in your browser.

Press `Ctrl+C` in the terminal to stop the server.

## Notes

- The server only accepts connections from your own machine (`127.0.0.1`). It is not
  accessible to other devices on your network unless you change the host in `app.py`.
- Downloaded files are stored in a system temp directory and cleaned up when you click
  "Start over" or restart the server.
- For playlist downloads, each file appears individually in the browser once processing
  is complete. Click "Download" next to each one to save it.
