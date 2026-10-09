# YT Downloader

Download YouTube videos and playlists as **MP3** or **MP4**: from a Mac or Windows app, from your browser (a local server on your own computer), or from the terminal.

> ⚠️ **Only download content you own or have explicit permission to download** (for example, videos under a Creative Commons licence). See the [legal notice](#legal-notice).

![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Built with](https://img.shields.io/badge/built%20with-yt--dlp-red)

## Features

- **MP3** (320 / 192 / 128 kbps, with cover art and tags) or **MP4** (best / 1080p / 720p / 480p / 360p, H.264 + AAC, so it plays in QuickTime and Windows Media Player)
- **Playlists**: tick exactly the videos you want (filter, select all / none). They're saved in a folder named after the playlist, and files keep their playlist number (`Official Blender Open Movies/03 - Title.mp4`) even if you only take some of them
- Pick where to save with your system's normal folder picker (in the app *and* the browser version)
- A link to a video *inside* a playlist preselects just that video, and you can still pick more
- Live progress, speed and time left; **Stop** works mid-video and cleans up partial files
- If one video fails (private, removed, region-blocked), the rest carry on and you get a summary at the end
- Videos already in the folder are skipped, so re-running a playlist only fetches what's new

## Three ways to use it

| | What it is | Start it |
|---|---|---|
| **Desktop app** | A normal Mac/Windows app window | Double-click `YT Downloader.app` / `.exe` ([build it](#building-the-desktop-app)) or run `ytdl-app` |
| **Web (local)** | The same screen in your browser. Runs only on your computer | `ytdl-web` → opens http://127.0.0.1:8765 |
| **CLI** | Step-by-step questions, or flags for scripting | `ytdl` |

The desktop app and the web version share the same screen, so they look and behave the same.

## Install (from source)

You need **Python 3.10+** and **ffmpeg**. A JavaScript runtime (**deno**, or Node.js) is recommended: YouTube needs one to unlock all qualities.

```bash
# macOS
brew install ffmpeg deno
# Windows
winget install Gyan.FFmpeg
winget install DenoLand.Deno
```

Then, from the repo folder:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[desktop]"        # drop [desktop] if you only want the CLI + web
```

That gives you three commands: `ytdl`, `ytdl-web` and `ytdl-app`.

## CLI

Run `ytdl` with no arguments and it walks you through everything: link → pick videos → format → quality → folder.

```bash
ytdl                                         # guided mode
ytdl "https://youtu.be/VIDEO_ID"             # asks only the remaining questions
ytdl "PLAYLIST_URL" --list                   # just show what's in a playlist
ytdl "PLAYLIST_URL" -s 1,3,5-8 -f mp4 -q 720p
ytdl "PLAYLIST_URL" -s -4 -f mp3 -y          # everything except #4, no questions
ytdl "URL" -o '$music/YouTube'               # use single quotes around $shorthands
```

| Flag | Meaning |
|---|---|
| `-f`, `--format` | `mp3` or `mp4` |
| `-q`, `--quality` | MP3: `320` `192` `128` · MP4: `best` `1080p` `720p` `480p` `360p` |
| `-s`, `--select` | Playlist videos: `all`, `1,3,5`, `2-8`, `1-3,7`, `-4` (all except 4) |
| `-o`, `--out` | Output folder (default `~/Downloads/YT Downloads`) |
| `-y`, `--yes` | Don't ask anything; use defaults for whatever you didn't pass |

In the CLI you can type any folder, including the shorthands `$desktop` `$downloads` `$documents` `$music` `$videos` `$home` `~`, relative paths and environment variables. Downloading two or more videos from a playlist creates a subfolder named after the playlist inside that folder.

## Web (local server)

```bash
ytdl-web                 # or: python -m ytdl.web   (options: --port 8800, --no-browser)
```

The server only listens on `127.0.0.1` and rejects requests from other sites or hosts, so other devices and web pages can't use it. Files go straight into the folder you choose with **Choose…**, which opens your system's folder picker. (This works because the server runs on your own computer.) When it's done, you can also save each file through the browser.

## Building the desktop app

Builds a standalone app that needs no Python. ffmpeg is bundled from your machine.

**macOS**: `./packaging/build_mac.sh` → `dist/YT Downloader.app` and `dist/YT Downloader-macOS.zip`
**Windows**: double-click `packaging\build_windows.bat` → `dist\YT Downloader.exe`

Notes:
- The build script creates its own virtual environment in `build/venv`. Your system Python isn't touched.
- ffmpeg is taken from `packaging/bin/` if you put it there, otherwise from your PATH.
- To make the app independent of a JavaScript runtime on the user's machine, bundle deno: on macOS run `BUNDLE_DENO=1 ./packaging/build_mac.sh`; on Windows put `deno.exe` in `packaging\bin\`. This adds about 100 MB.
- A Mac build runs on the same kind of Mac it was built on (Apple Silicon or Intel).
- The Windows app uses Microsoft Edge WebView2, which Windows 10 and 11 already include.
- The apps aren't code-signed. On a Mac: right-click → **Open** the first time. If macOS says the app is "damaged", run `xattr -cr "/Applications/YT Downloader.app"`. On Windows: SmartScreen → **More info** → **Run anyway**.

## How it's organised

Everything inherits from **`ytdl/core/`**. The frontends only display things and contain no download logic.

```
ytdl/
├── core/                  ← all the logic
│   ├── fetch.py           look up a video/playlist (titles, durations, availability)
│   ├── job.py             DownloadJob: the one download loop (progress, stop, retries, results)
│   ├── formats.py         formats, qualities, yt-dlp options
│   ├── selection.py       "1,3,5-8" parsing
│   ├── paths.py           output folders and $shorthands (CLI)
│   ├── system.py          native folder picker, open in Finder/Explorer
│   └── legal.py           the legal notice text every frontend shows
├── cli.py                 terminal frontend            → `ytdl`
├── web/
│   ├── server.py          local server + JSON API      → `ytdl-web`
│   └── static/            the UI (HTML/CSS/JS), shared by web and desktop
└── desktop.py             native window around the UI  → `ytdl-app`
packaging/                 build scripts for the .app / .exe
tests/                     `pytest`
```

To add a feature (say, a new quality), change `ytdl/core/`. The CLI, app and web version all pick it up.

## Troubleshooting

- **"ffmpeg isn't installed"**: install it (see above). It's needed for MP3 and for HD video.
- **"No supported JavaScript runtime" warning, or fewer qualities than expected**: install deno (`brew install deno` / `winget install DenoLand.Deno`) or Node.js.
- **Downloads suddenly fail for everything**: YouTube changes often. Update yt-dlp with `pip install -U "yt-dlp[default]"`, or rebuild the app.
- **"HTTP Error 403"**: this is usually temporary. The app already retries once automatically, so try again a bit later.
- **A playlist video was skipped**: private, members-only, age-restricted and region-blocked videos can't be downloaded. The rest of the playlist still downloads.
- **Port already in use** (web): `ytdl-web --port 8800`.

## Legal notice

> This project is for personal, educational and research use.

- It isn't affiliated with or endorsed by YouTube or Google LLC.
- Downloading YouTube content may violate [YouTube's Terms of Service](https://www.youtube.com/t/terms) unless YouTube or the rights holder allows it.
- **Only download content you have permission to download**: your own uploads, or content explicitly licensed for download.
- Downloading copyrighted media without authorisation may break copyright law. You're responsible for how you use this tool. The authors aren't liable for misuse.

## License

MIT. See [LICENSE](LICENSE). The licence covers this code only. It grants no rights to YouTube content or third-party services.
