import io
import os
import time
from datetime import datetime, timedelta

import pytest

import app as flask_app
from benford.analyzer import BenfordAnalyzer


@pytest.fixture(autouse=True)
def reset_rate_limits():
    flask_app.reset_rate_limits()
    yield
    flask_app.reset_rate_limits()


@pytest.fixture
def temp_app(monkeypatch, tmp_path):
    upload = tmp_path / "uploads"
    images = tmp_path / "static" / "images"
    reports = tmp_path / "static" / "reports"
    for path in [upload, images, reports]:
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(flask_app, "UPLOAD_FOLDER", upload)
    monkeypatch.setattr(flask_app, "STATIC_IMAGES_FOLDER", images)
    monkeypatch.setattr(flask_app, "STATIC_REPORTS_FOLDER", reports)
    monkeypatch.setattr(flask_app, "UPLOAD_ROOT", upload.resolve())
    monkeypatch.setattr(flask_app, "RETENTION_AGE", timedelta(seconds=0.1))
    monkeypatch.setattr(flask_app, "CLEANUP_INTERVAL", timedelta(seconds=0))
    monkeypatch.setattr(flask_app, "RATE_LIMIT_REQUESTS", 30)
    monkeypatch.setattr(flask_app, "RATE_LIMIT_WINDOW_SECONDS", 60.0)

    flask_app.app.config["UPLOAD_FOLDER"] = str(upload)
    flask_app.app.config["LAST_CLEANUP_AT"] = None
    flask_app.rate_limiter = flask_app.InMemoryRateLimiter(30, 60.0)

    yield flask_app.app


def _get_csrf(client):
    response = client.get("/")
    assert response.status_code == 200
    with client.session_transaction() as sess:
        return sess["csrf_token"]


def test_csrf_is_required(temp_app):
    client = temp_app.test_client()
    resp = client.post("/preview", data={}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid or missing CSRF token" in resp.data


def test_preview_succeeds_with_csrf_and_file(temp_app, tmp_path):
    client = temp_app.test_client()
    token = _get_csrf(client)
    csv_bytes = b"value,name\n1,A\n2,B\n"
    data = {
        "csrf_token": token,
        "file": (io.BytesIO(csv_bytes), "data.csv"),
    }

    resp = client.post("/preview", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Data Preview" in resp.data
    assert b"value" in resp.data

    upload_files = list((tmp_path / "uploads").iterdir())
    assert len(upload_files) == 1


def test_analyze_flow_creates_outputs(temp_app, tmp_path):
    client = temp_app.test_client()
    token = _get_csrf(client)
    csv_bytes = b"value\n1\n2\n3\n"
    data = {
        "csrf_token": token,
        "file": (io.BytesIO(csv_bytes), "values.csv"),
    }
    resp = client.post("/preview", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200

    upload_files = list((tmp_path / "uploads").iterdir())
    assert upload_files, "Expected uploaded file to exist"
    filename = upload_files[0].name

    token = _get_csrf(client)
    resp = client.post(
        "/analyze",
        data={"filename": filename, "column": "value", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 302  # Redirect to results

    images = list((tmp_path / "static" / "images").glob("benford_plot_*.png"))
    reports = list((tmp_path / "static" / "reports").glob("benford_report_*.txt"))
    assert images, "Expected plot image to be created"
    assert reports, "Expected report file to be created"


def test_cleanup_removes_old_files(temp_app, tmp_path, monkeypatch):
    old_file = (tmp_path / "uploads" / "old.csv")
    old_file.write_text("value\n1\n")
    stale_time = time.time() - 3600
    os.utime(old_file, times=(stale_time, stale_time))

    flask_app.maybe_run_cleanup()

    assert not old_file.exists(), "Old file should have been removed by cleanup"


def test_rate_limiting_blocks_after_threshold(temp_app, monkeypatch):
    flask_app.rate_limiter = flask_app.InMemoryRateLimiter(2, 60.0)

    client = temp_app.test_client()
    token = _get_csrf(client)

    data = {"csrf_token": token}
    for _ in range(2):
        resp = client.post("/preview", data=data, follow_redirects=False)
        assert resp.status_code == 302  # allowed but redirected due to missing file

    resp = client.post("/preview", data=data, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Too many requests" in resp.data


def test_analyzer_rejects_non_numeric(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("col\nabc\n")

    analyzer = BenfordAnalyzer(str(csv_path), "col")
    with pytest.raises(ValueError):
        analyzer.run()


def test_malformed_csv_preview(temp_app):
    client = temp_app.test_client()
    token = _get_csrf(client)
    data = {
        "csrf_token": token,
        "file": (io.BytesIO(b"\xff\xff\x00\x00notcsv"), "bad.csv"),
    }
    resp = client.post("/preview", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Error reading CSV file" in resp.data


def test_large_file_rejected(temp_app, monkeypatch):
    # Set a tiny limit for the test
    monkeypatch.setattr(flask_app, "MAX_FILE_SIZE", 10)
    temp_app.config["MAX_CONTENT_LENGTH"] = 10

    client = temp_app.test_client()
    token = _get_csrf(client)
    payload = b"x" * 50  # exceeds limit
    data = {"csrf_token": token, "file": (io.BytesIO(payload), "big.csv")}
    resp = client.post("/preview", data=data, content_type="multipart/form-data", follow_redirects=True)
    # Flask returns 413 and our handler redirects with flash
    assert resp.status_code == 200
    assert b"File is too large" in resp.data
