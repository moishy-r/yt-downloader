"""API tests for the local server (no network)."""

import pytest

from ytdl.web.server import create_app


@pytest.fixture
def client():
    app = create_app("web")
    return app.test_client()


def test_config_includes_legal_notice(client):
    cfg = client.get("/api/config", base_url="http://127.0.0.1:8765").get_json()
    assert "permission" in cfg["legal"]["text"]
    assert cfg["qualities"]["mp3"][0][0] == "320"


def test_index_served(client):
    r = client.get("/", base_url="http://localhost:8765")
    assert r.status_code == 200 and b"YT Downloader" in r.data


def test_rejects_foreign_host(client):
    assert client.get("/api/config", base_url="http://evil.example:8765").status_code == 403


def test_rejects_cross_site_post(client):
    r = client.post("/api/fetch", json={"url": "x"}, base_url="http://127.0.0.1:8765",
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_rejects_non_json_post(client):
    r = client.post("/api/fetch", data="url=x", base_url="http://127.0.0.1:8765",
                    content_type="application/x-www-form-urlencoded")
    assert r.status_code == 415


def test_fetch_bad_url_is_friendly(client):
    r = client.post("/api/fetch", json={"url": "https://vimeo.com/1"},
                    base_url="http://127.0.0.1:8765")
    assert r.status_code == 400 and "YouTube" in r.get_json()["error"]


def test_start_job_validates(client):
    base = "http://127.0.0.1:8765"
    assert client.post("/api/jobs", json={"entries": []}, base_url=base).status_code == 400
    r = client.post("/api/jobs", json={"fmt": "mp3", "quality": "999",
                                       "entries": [{"index": 1, "url": "https://youtu.be/x"}]},
                    base_url=base)
    assert r.status_code == 400


def test_pick_folder_uses_native_picker(client, monkeypatch):
    import ytdl.web.server as srv
    monkeypatch.setattr(srv, "pick_folder", lambda start: "/Users/me/Music")
    r = client.post("/api/pick-folder", json={"start": ""}, base_url="http://127.0.0.1:8765")
    assert r.get_json() == {"path": "/Users/me/Music"}

    def unavailable(start):
        raise srv.PickerUnavailable("nope")
    monkeypatch.setattr(srv, "pick_folder", unavailable)
    r = client.post("/api/pick-folder", json={}, base_url="http://127.0.0.1:8765")
    assert r.status_code == 501
