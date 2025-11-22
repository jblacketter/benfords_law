import io
import os
import time
from datetime import datetime, timedelta

import pytest

import app as flask_app
from benford import external_data
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


def test_kaggle_credential_encrypt_decrypt():
    secret = "supersecret"
    token = external_data.encrypt_credentials(secret, {"username": "user", "key": "abcd1234ef"})
    creds = external_data.decrypt_credentials(secret, token)
    assert creds["username"] == "user"
    assert creds["key"] == "abcd1234ef"


def test_validate_dataset_ref():
    good = "owner/dataset-name_123"
    assert external_data.validate_dataset_ref(good) == good
    bad = "owner/../../etc"
    with pytest.raises(external_data.ExternalDataError):
        external_data.validate_dataset_ref(bad)


def test_learn_page_loads(temp_app):
    """Test that the /learn route loads successfully."""
    client = temp_app.test_client()
    resp = client.get("/learn")
    assert resp.status_code == 200
    assert b"Understanding Benford's Law" in resp.data
    assert b"What is Benford's Law?" in resp.data
    assert b"Why Does It Occur?" in resp.data
    assert b"Real-World Applications" in resp.data


def test_examples_page_loads(temp_app):
    """Test that the /examples route loads with example datasets."""
    client = temp_app.test_client()
    resp = client.get("/examples")
    assert resp.status_code == 200
    assert b"Explore Example Datasets" in resp.data
    # Should show at least some example datasets if metadata loads
    # Even if metadata.json is empty, the page should still render


def test_interpretation_module():
    """Test the interpretation.py module functions correctly."""
    from benford.interpretation import interpret_results

    # Test conforming data (high p-value)
    result = interpret_results(p_value=0.8, chi_squared=2.5, dataset_name="Test Dataset", expectation="conform")
    assert "likely follows Benford's Law" in result["headline"]
    assert "Test Dataset" in result["headline"]
    assert "No red flags detected" in result["guidance"]
    assert "This matches the expected behavior" in result["detail"]

    # Test non-conforming data (low p-value)
    result = interpret_results(p_value=0.01, chi_squared=25.0, dataset_name="Bad Data", expectation="conform")
    assert "likely does not follow Benford's Law" in result["headline"]
    assert "Significant deviation detected" in result["guidance"]
    assert "This result differs from the typical expectation" in result["detail"]

    # Test expected non-conformer
    result = interpret_results(p_value=0.001, chi_squared=30.0, dataset_name="Dice Rolls", expectation="nonconform")
    assert "likely does not follow Benford's Law" in result["headline"]
    assert "This deviation is expected" in result["detail"]

    # Test missing statistics
    result = interpret_results(p_value=None, chi_squared=None)
    assert "Could not interpret results" in result["headline"]
    assert "did not return a p-value" in result["detail"]


def test_example_analysis_requires_csrf(temp_app, monkeypatch):
    """Test that example analysis endpoint requires CSRF token."""
    # Mock example datasets - don't need real CSV for CSRF test
    mock_examples = [
        {
            "id": "test_example",
            "name": "Test Example",
            "filename": "test.csv",
            "column": "value",
            "expectation": "conform"
        }
    ]
    monkeypatch.setattr(flask_app, "EXAMPLE_DATASETS", mock_examples)

    client = temp_app.test_client()

    # Test without CSRF - should fail and redirect
    resp = client.post("/examples/analyze/test_example", data={}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid or missing CSRF token" in resp.data


def test_example_download(temp_app, monkeypatch):
    """Test that example datasets can be downloaded."""
    # Mock example datasets
    mock_examples = [
        {
            "id": "download_test",
            "name": "Download Test",
            "filename": "download_test.csv",
            "column": "value",
            "expectation": "conform"
        }
    ]
    monkeypatch.setattr(flask_app, "EXAMPLE_DATASETS", mock_examples)

    # Create the test CSV file
    examples_folder = flask_app.EXAMPLES_FOLDER
    examples_folder.mkdir(parents=True, exist_ok=True)
    test_csv = examples_folder / "download_test.csv"
    test_csv.write_text("value\n1\n2\n3\n")

    monkeypatch.setattr(flask_app, "EXAMPLES_ROOT", examples_folder.resolve())

    client = temp_app.test_client()
    resp = client.get("/examples/download/download_test")
    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"]
    assert "download_test.csv" in resp.headers["Content-Disposition"]
