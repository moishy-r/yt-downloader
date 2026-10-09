"""Fast tests for ytdl.core (no network)."""

import os
from pathlib import Path

import pytest

from ytdl.core import (
    DownloadJob, Entry, FetchError, SelectionError, normalize_url, parse_selection,
    resolve_path, validate,
)
from ytdl.core.job import output_template

AVAIL = list(range(1, 11))


@pytest.mark.parametrize("text, expected", [
    ("", AVAIL),
    ("all", AVAIL),
    ("1,3,5", [1, 3, 5]),
    ("2-4", [2, 3, 4]),
    ("4-2", [2, 3, 4]),
    ("1-3, 7 ,9-10", [1, 2, 3, 7, 9, 10]),
    ("-4", [1, 2, 3, 5, 6, 7, 8, 9, 10]),
    ("1-5,-3", [1, 2, 4, 5]),
    ("8-20", [8, 9, 10]),
])
def test_parse_selection(text, expected):
    assert parse_selection(text, AVAIL) == expected


@pytest.mark.parametrize("text", ["abc", "50", "1-x"])
def test_parse_selection_errors(text):
    with pytest.raises(SelectionError):
        parse_selection(text, AVAIL)


def test_validate():
    assert validate("MP4", None) == ("mp4", "best")
    assert validate("mp4", "720") == ("mp4", "720p")
    assert validate("mp3", "192k") == ("mp3", "192")
    with pytest.raises(ValueError):
        validate("mp3", "1080p")
    with pytest.raises(ValueError):
        validate("wav", None)


def test_normalize_url():
    assert normalize_url("youtu.be/abc") == "https://youtu.be/abc"
    assert normalize_url(" https://music.youtube.com/watch?v=x ").startswith("https://music.")
    for bad in ("", "https://vimeo.com/1", "https://notyoutube.com/watch?v=1"):
        with pytest.raises(FetchError):
            normalize_url(bad)


def test_resolve_path(tmp_path, monkeypatch):
    home = str(Path.home())
    assert resolve_path("$downloads/Music") == str(Path(home, "Downloads", "Music").resolve())
    assert resolve_path("$HOME_X") .endswith("$HOME_X")   # unknown shorthands stay literal
    assert resolve_path("~") == str(Path(home).resolve())
    monkeypatch.chdir(tmp_path)
    assert resolve_path("sub") == str((tmp_path / "sub").resolve())
    assert "YT Downloads" in resolve_path("")


def test_output_template():
    e = Entry(index=7, title="t", url="u")
    assert output_template("/x", e, False) == os.path.join("/x", "%(title)s.%(ext)s")
    assert output_template("/x", e, True).endswith("07 - %(title)s.%(ext)s")
    assert output_template("/x", e, True, width=3).endswith("007 - %(title)s.%(ext)s")


def test_job_reports_failures_without_crashing(tmp_path, monkeypatch):
    """A failing video is reported and the job carries on to the next one."""
    import ytdl.core.job as jobmod

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def extract_info(self, url, download=False):
            if "bad" in url:
                raise RuntimeError("ERROR: [youtube] bad: Video unavailable")
            vid = url.rsplit("/", 1)[-1]
            return {"id": vid, "title": vid, "ext": "mp3"}
        def prepare_filename(self, info):
            return str(tmp_path / f"{info['title']}.webm")
        def process_ie_result(self, info, download=True):
            out = tmp_path / f"{info['title']}.mp3"
            out.write_text("x")
            return {**info, "requested_downloads": [{"filepath": str(out)}]}

    monkeypatch.setattr(jobmod.yt_dlp, "YoutubeDL", FakeYDL)
    events = []
    entries = [Entry(1, "Good", "https://youtu.be/good"), Entry(2, "Bad", "https://youtu.be/bad"),
               Entry(3, "Good2", "https://youtu.be/good2")]
    job = DownloadJob(entries, "mp3", "320", str(tmp_path), on_event=events.append)
    result = job.run()

    assert len(result["files"]) == 2
    assert result["failed"] == [{"index": 2, "title": "Bad", "error":
                                 "This video or playlist is unavailable (removed, private or region-blocked)."}]
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "finished"
    assert types.count("item_done") == 2 and types.count("item_failed") == 1

    # Running again skips files that are already there
    events.clear()
    DownloadJob(entries[:1], "mp3", "320", str(tmp_path), on_event=events.append).run()
    assert "item_skipped" in [e["type"] for e in events]


def test_job_cancel_before_start(tmp_path):
    job = DownloadJob([Entry(1, "a", "https://youtu.be/a")], "mp3", "320", str(tmp_path))
    job.cancel()
    result = job.run()
    assert result["cancelled"] and result["files"] == []


def test_safe_folder_name():
    from ytdl.core import safe_folder_name
    assert safe_folder_name("Official Blender Open Movies") == "Official Blender Open Movies"
    assert safe_folder_name('a/b: c? "d"*') == "ab c d"
    assert safe_folder_name("  ...  ") == "Playlist"
    assert safe_folder_name(None) == "Playlist"
    assert safe_folder_name("CON") == "_CON"


def test_playlist_gets_its_own_folder(tmp_path):
    two = [Entry(1, "a", "https://youtu.be/a"), Entry(3, "b", "https://youtu.be/b")]
    job = DownloadJob(two, "mp3", "320", str(tmp_path), playlist_title="My: List")
    assert job.out_dir == str(tmp_path / "My List") and job.numbered

    # One video picked from a playlist is just a video: no subfolder, no number
    one = DownloadJob(two[:1], "mp3", "320", str(tmp_path), playlist_title="My: List")
    assert one.out_dir == str(tmp_path) and not one.numbered

    single = DownloadJob(two, "mp3", "320", str(tmp_path))
    assert single.out_dir == str(tmp_path)
