import os
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Protocol, Optional

from flask import Flask, request, render_template, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from benford.analyzer import BenfordAnalyzer
import pandas as pd
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

UPLOAD_FOLDER = Path('uploads')
STATIC_IMAGES_FOLDER = Path('static/images')
STATIC_REPORTS_FOLDER = Path('static/reports')
ALLOWED_EXTENSIONS = {'csv'}


def _get_log_level() -> int:
    """Resolve log level from environment with INFO fallback."""
    level_name = os.environ.get('LOG_LEVEL', 'INFO').upper()
    return getattr(logging, level_name, logging.INFO)


# Configure logging
logging.basicConfig(
    level=_get_log_level(),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _get_max_file_size() -> int:
    """Return max upload size in bytes, defaulting to 16MB."""
    raw_size = os.environ.get('MAX_FILE_SIZE_MB')
    if raw_size is None:
        return 16 * 1024 * 1024

    try:
        size_mb = int(raw_size)
        if size_mb <= 0:
            raise ValueError
        return size_mb * 1024 * 1024
    except ValueError:
        logger.warning("Invalid MAX_FILE_SIZE_MB '%s'; falling back to 16MB.", raw_size)
        return 16 * 1024 * 1024


def _get_retention_age() -> timedelta:
    """Return file retention age, defaulting to 24 hours."""
    raw_hours = os.environ.get('MAX_FILE_RETENTION_HOURS')
    if raw_hours is None:
        return timedelta(hours=24)
    try:
        hours = float(raw_hours)
        if hours <= 0:
            raise ValueError
        return timedelta(hours=hours)
    except ValueError:
        logger.warning("Invalid MAX_FILE_RETENTION_HOURS '%s'; using 24h.", raw_hours)
        return timedelta(hours=24)


def _get_cleanup_interval() -> timedelta:
    """Return cleanup interval, defaulting to 60 minutes."""
    raw_minutes = os.environ.get('CLEANUP_INTERVAL_MINUTES')
    if raw_minutes is None:
        return timedelta(minutes=60)
    try:
        minutes = float(raw_minutes)
        if minutes <= 0:
            raise ValueError
        return timedelta(minutes=minutes)
    except ValueError:
        logger.warning("Invalid CLEANUP_INTERVAL_MINUTES '%s'; using 60m.", raw_minutes)
        return timedelta(minutes=60)


MAX_FILE_SIZE = _get_max_file_size()
RETENTION_AGE = _get_retention_age()
CLEANUP_INTERVAL = _get_cleanup_interval()
try:
    RATE_LIMIT_REQUESTS = max(1, int(os.environ.get('RATE_LIMIT_REQUESTS', 30)))
except ValueError:
    logger.warning("Invalid RATE_LIMIT_REQUESTS env; using 30.")
    RATE_LIMIT_REQUESTS = 30

try:
    RATE_LIMIT_WINDOW_SECONDS = max(1.0, float(os.environ.get('RATE_LIMIT_WINDOW_SECONDS', 60)))
except ValueError:
    logger.warning("Invalid RATE_LIMIT_WINDOW_SECONDS env; using 60.")
    RATE_LIMIT_WINDOW_SECONDS = 60.0
RATE_LIMIT_BACKEND = os.environ.get('RATE_LIMIT_BACKEND', 'memory').lower()
REDIS_URL = os.environ.get('REDIS_URL')

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Create necessary directories on startup
for directory in [UPLOAD_FOLDER, STATIC_IMAGES_FOLDER, STATIC_REPORTS_FOLDER]:
    directory.mkdir(parents=True, exist_ok=True)
    logger.info(f"Ensured directory exists: {directory}")

UPLOAD_ROOT = UPLOAD_FOLDER.resolve()
_RATE_LIMIT_STORE: Dict[str, List[float]] = {}
_RATE_LIMIT_LOCK = threading.Lock()


class RateLimiter(Protocol):
    def check(self, key: str) -> bool: ...
    def reset(self) -> None: ...


class InMemoryRateLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.store: Dict[str, List[float]] = {}
        self.lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        with self.lock:
            entries = self.store.setdefault(key, [])
            entries[:] = [ts for ts in entries if ts >= window_start]
            if len(entries) >= self.max_requests:
                return False
            entries.append(now)
            return True

    def reset(self) -> None:
        with self.lock:
            self.store.clear()


class RedisRateLimiter:
    def __init__(self, url: str, max_requests: int, window_seconds: float):
        try:
            import redis  # type: ignore
        except ImportError:  # pragma: no cover - optional dependency
            logger.warning("Redis not installed; falling back to in-memory rate limiter.")
            self._fallback = InMemoryRateLimiter(max_requests, window_seconds)
            return
        self._fallback = None
        self.client = redis.Redis.from_url(url)
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def check(self, key: str) -> bool:
        if self._fallback:
            return self._fallback.check(key)
        pipe = self.client.pipeline()
        now_ms = int(time.time() * 1000)
        window_ms = int(self.window_seconds * 1000)
        key_name = f"rate:{key}"
        pipe.zremrangebyscore(key_name, 0, now_ms - window_ms)
        pipe.zcard(key_name)
        pipe.zadd(key_name, {str(now_ms): now_ms})
        pipe.expire(key_name, int(self.window_seconds))
        _, count, _, _ = pipe.execute()
        return int(count) <= self.max_requests

    def reset(self) -> None:
        if self._fallback:
            return self._fallback.reset()
        # Not clearing Redis keys to avoid collateral impact; noop.
        return


def _build_rate_limiter() -> RateLimiter:
    if RATE_LIMIT_BACKEND == 'redis' and REDIS_URL:
        logger.info("Using Redis rate limiter backend.")
        return RedisRateLimiter(REDIS_URL, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)
    if RATE_LIMIT_BACKEND == 'redis' and not REDIS_URL:
        logger.warning("RATE_LIMIT_BACKEND=redis but REDIS_URL missing; using memory.")
    return InMemoryRateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)


rate_limiter: RateLimiter = _build_rate_limiter()


def reset_rate_limits() -> None:
    """Clear rate limiter state (used in tests)."""
    try:
        rate_limiter.reset()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to reset rate limits: %s", exc)


def cleanup_stale_files(root: Path, older_than: timedelta) -> None:
    """Remove files older than the provided age inside the given root."""
    if not root.exists():
        return

    now = datetime.now()
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if now - mtime > older_than:
                path.unlink(missing_ok=True)
                logger.info("Cleaned up old file: %s", path)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to clean up %s: %s", path, exc)


def maybe_run_cleanup() -> None:
    """Run periodic cleanup based on configured interval."""
    last_run = app.config.get('LAST_CLEANUP_AT')
    now = datetime.now()
    if last_run and now - last_run < CLEANUP_INTERVAL:
        return

    cleaned_total = 0
    logger.info(
        "Running cleanup (retention=%s, interval=%s)", RETENTION_AGE, CLEANUP_INTERVAL
    )
    for folder in [UPLOAD_FOLDER, STATIC_IMAGES_FOLDER, STATIC_REPORTS_FOLDER]:
        before = sum(1 for _ in folder.glob("*") if _.is_file())
        cleanup_stale_files(folder, RETENTION_AGE)
        after = sum(1 for _ in folder.glob("*") if _.is_file())
        cleaned = max(before - after, 0)
        cleaned_total += cleaned
        if cleaned:
            logger.info("Cleanup removed %s files from %s", cleaned, folder)
    logger.info("Cleanup finished; total files removed: %s", cleaned_total)

    app.config['LAST_CLEANUP_AT'] = now


@app.before_request
def _before_request():
    maybe_run_cleanup()
    if request.method == 'POST' and request.endpoint in {'upload_file', 'preview_data', 'analyze_data'}:
        identifier = request.remote_addr or 'unknown'
        if not rate_limiter.check(identifier):
            flash('Too many requests. Please wait a moment and try again.')
            logger.warning("Rate limit exceeded for %s", identifier)
            return redirect(url_for('upload_file'))

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_csrf_token() -> str:
    """Return the current session CSRF token, creating one if needed."""
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return token


def validate_csrf(form_token: str) -> bool:
    expected = session.get('csrf_token')
    if not expected or not form_token:
        return False
    return secrets.compare_digest(expected, form_token)


@app.errorhandler(413)
def request_entity_too_large(_):
    flash('File is too large. Please upload a smaller file.')
    return redirect(url_for('upload_file'))

def validate_csv_mime_type(file):
    """Validate that the uploaded file is actually a CSV by checking content."""
    # Read first few bytes to check for CSV-like content
    file.seek(0)
    try:
        # Try to read as CSV
        pd.read_csv(file, nrows=1)
        file.seek(0)
        return True
    except Exception:
        file.seek(0)
        return False

def generate_unique_filename(base_name, extension):
    """Generate a unique filename with timestamp."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"{base_name}_{timestamp}.{extension}"


def build_upload_path(filename: str):
    """
    Sanitize a provided filename and ensure it remains within the uploads directory.

    :returns: tuple of (safe filename, resolved Path)
    :raises ValueError: if the resolved path escapes the uploads root.
    """
    safe_name = secure_filename(filename)
    candidate = (UPLOAD_ROOT / safe_name).resolve()

    if UPLOAD_ROOT not in candidate.parents and candidate != UPLOAD_ROOT:
        raise ValueError("Invalid upload path")

    return safe_name, candidate

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if not validate_csrf(request.form.get('csrf_token')):
            flash('Invalid or missing CSRF token. Please try again.')
            logger.warning("CSRF validation failed on upload.")
            return redirect(url_for('upload_file'))

        if 'file' not in request.files:
            flash('No file part')
            logger.warning("Upload attempt with no file part")
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('No selected file')
            logger.warning("Upload attempt with empty filename")
            return redirect(request.url)

        if not file or not allowed_file(file.filename):
            flash('Invalid file type. Please upload a CSV file.')
            logger.warning(f"Upload attempt with invalid file type: {file.filename}")
            return redirect(request.url)

        # Validate MIME type
        if not validate_csv_mime_type(file):
            flash('File does not appear to be a valid CSV file.')
            logger.warning(f"Upload attempt with invalid CSV content: {file.filename}")
            return redirect(request.url)

        # Save uploaded file with unique name
        original_filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{original_filename}"
        _, filepath = build_upload_path(filename)
        file.save(filepath)
        logger.info(f"File uploaded successfully: {filename}")

        column = request.form.get('column', '').strip()
        if not column:
            flash('Column name is required')
            return redirect(request.url)

        # Generate unique output filenames
        plot_filename = generate_unique_filename('benford_plot', 'png')
        report_filename = generate_unique_filename('benford_report', 'txt')
        plot_path = STATIC_IMAGES_FOLDER / plot_filename
        report_path = STATIC_REPORTS_FOLDER / report_filename

        analyzer = BenfordAnalyzer(str(filepath), column, str(plot_path), str(report_path))
        try:
            analyzer.run()
            logger.info(f"Analysis completed successfully for column: {column}")
            # Store filenames in session or pass via URL params
            return redirect(url_for('show_results', plot=plot_filename, report=report_filename))
        except FileNotFoundError as e:
            flash(f'File error: {str(e)}')
            logger.error(f"File not found during analysis: {str(e)}")
            return redirect(request.url)
        except ValueError as e:
            # Provide helpful error message with available columns
            try:
                df = pd.read_csv(filepath)
                numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
                all_cols = df.columns.tolist()

                if numeric_cols:
                    flash(f"Column '{column}' not found or not numeric. Available numeric columns: {', '.join(numeric_cols)}")
                else:
                    flash(f"No numeric columns found in the CSV. Available columns: {', '.join(all_cols)}")
                logger.warning(f"Invalid column requested: {column}")
            except Exception:
                flash(f'Error: {str(e)}')
            return redirect(request.url)
        except Exception as e:
            flash(f'An unexpected error occurred: {str(e)}')
            logger.error(f"Unexpected error during analysis: {str(e)}", exc_info=True)
            return redirect(request.url)

    return render_template('upload.html', csrf_token=get_csrf_token())

@app.route('/preview', methods=['POST'])
def preview_data():
    """Preview uploaded CSV and show available columns."""
    if not validate_csrf(request.form.get('csrf_token')):
        flash('Invalid or missing CSRF token. Please try again.')
        logger.warning("CSRF validation failed on preview.")
        return redirect(url_for('upload_file'))

    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('upload_file'))

    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('upload_file'))

    if not file or not allowed_file(file.filename):
        flash('Invalid file type. Please upload a CSV file.')
        return redirect(url_for('upload_file'))

    try:
        # Read CSV for preview
        df = pd.read_csv(file)
        file.seek(0)

        # Get column information
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        all_cols = df.columns.tolist()

        # Get preview data (first 10 rows)
        preview_html = df.head(10).to_html(classes='preview-table', index=False)

        # Save file temporarily for later analysis
        original_filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{original_filename}"
        _, filepath = build_upload_path(filename)
        file.save(filepath)

        return render_template('preview.html',
                             preview_html=preview_html,
                             numeric_cols=numeric_cols,
                             all_cols=all_cols,
                             filename=os.path.basename(filepath),
                             row_count=len(df),
                             csrf_token=get_csrf_token())
    except Exception as e:
        flash(f'Error reading CSV file: {str(e)}')
        logger.error(f"Error previewing CSV: {str(e)}", exc_info=True)
        return redirect(url_for('upload_file'))

@app.route('/analyze', methods=['POST'])
def analyze_data():
    """Analyze the previously uploaded file."""
    if not validate_csrf(request.form.get('csrf_token')):
        flash('Invalid or missing CSRF token. Please try again.')
        logger.warning("CSRF validation failed on analysis.")
        return redirect(url_for('upload_file'))

    filename = request.form.get('filename')
    column = request.form.get('column', '').strip()

    if not filename or not column:
        flash('Missing filename or column')
        return redirect(url_for('upload_file'))

    try:
        _, filepath = build_upload_path(filename)
    except ValueError:
        flash('Invalid filename provided.')
        logger.warning("Attempted analysis with invalid filename: %s", filename)
        return redirect(url_for('upload_file'))

    if not filepath.exists():
        flash('Uploaded file not found. Please upload again.')
        return redirect(url_for('upload_file'))

    # Generate unique output filenames
    plot_filename = generate_unique_filename('benford_plot', 'png')
    report_filename = generate_unique_filename('benford_report', 'txt')
    plot_path = STATIC_IMAGES_FOLDER / plot_filename
    report_path = STATIC_REPORTS_FOLDER / report_filename

    analyzer = BenfordAnalyzer(str(filepath), column, str(plot_path), str(report_path))
    try:
        analyzer.run()
        logger.info(f"Analysis completed successfully for column: {column}")
        return redirect(url_for('show_results', plot=plot_filename, report=report_filename))
    except ValueError as e:
        flash(f'Error: {str(e)}')
        logger.warning(f"Invalid column during analysis: {column}")
        return redirect(url_for('upload_file'))
    except Exception as e:
        flash(f'An unexpected error occurred: {str(e)}')
        logger.error(f"Unexpected error during analysis: {str(e)}", exc_info=True)
        return redirect(url_for('upload_file'))

@app.route('/results')
def show_results():
    plot_filename = request.args.get('plot', 'benford_plot.png')
    report_filename = request.args.get('report', 'benford_report.txt')

    plot_url = url_for('static', filename=f'images/{plot_filename}')
    report_url = url_for('static', filename=f'reports/{report_filename}')
    return render_template('results.html', plot_url=plot_url, report_url=report_url)

if __name__ == '__main__':
    # Only use debug mode if not in production
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    app.run(debug=debug_mode)
