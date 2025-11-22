# Benford's Law Analysis Web Application

This project provides a secure, production-ready web application to analyze datasets for conformity with Benford's Law. Users can upload a CSV file, preview the data, select a column, and receive a detailed analysis with plots and statistical reports.

The application has been hardened with enterprise-grade security features and is ready for public deployment.

![Screenshot of Benford's Law App](https://raw.githubusercontent.com/your-username/your-repo/main/screenshot.png)
*(Note: You should replace the above screenshot link with one from your actual repository after pushing.)*

---

## Features

-   **Easy File Uploads**: Simple web interface to upload and analyze CSV files.
-   **Data Preview**: Preview your data and column headers before running the full analysis.
-   **Rich Visualizations**: Generates `matplotlib` plots to visualize first-digit frequencies against the Benford's Law curve.
-   **Detailed Reports**: Provides statistical output, including Chi-squared tests, to validate conformity.
-   **Curated Examples**: Browse preloaded conforming and non-conforming datasets to see Benford's Law in action (`/examples`).
-   **Educational UI**: Landing page explains Benford's Law and the expected digit distribution.
-   **Plain-Language Results**: Results page summarizes p-value/chi-squared with a clear interpretation.
-   **Kaggle Integration**: Search Kaggle datasets, preview CSVs, and run Benford analysis (credentials encrypted in-session).

### Production & Security Features

-   **CSRF Protection**: All form submissions are protected against Cross-Site Request Forgery.
-   **Rate Limiting**: Protects the server from abuse by limiting the number of requests per IP. (Default: 30 requests per minute).
-   **Path Traversal Secure**: Upload and analysis endpoints are secured against path traversal attacks.
-   **Automated File Cleanup**: Cleanup runs on incoming requests (via `before_request`) and removes files older than the configured retention window. In very low-traffic deployments, consider a scheduled job/cron to trigger cleanup.
-   **Scalable**: Supports a Redis backend for rate limiting, allowing it to scale across multiple web workers.

---

## Setup and Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd benfords_law
```

### 2. Create and Activate a Virtual Environment

```bash
# For macOS/Linux
python3 -m venv venv
source venv/bin/activate

# For Windows
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies

Install all required packages from `requirements.txt`.

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

The application is configured using environment variables. Copy the example file and edit it.

```bash
cp .env.example .env
```

Now, open the `.env` file and set the following (defaults shown where applicable):

-   `FLASK_APP=app` (default)
-   `FLASK_ENV=development` (set to `production` when deploying)
-   `SECRET_KEY` (**required** for sessions/CSRF; generate with `python -c "import secrets; print(secrets.token_hex())"`)
-   `MAX_FILE_SIZE_MB=16`
-   `MAX_FILE_RETENTION_HOURS=24`
-   `CLEANUP_INTERVAL_MINUTES=60`
-   `LOG_LEVEL=INFO`
-   `RATE_LIMIT_REQUESTS=30`
-   `RATE_LIMIT_WINDOW_SECONDS=60`
-   `RATE_LIMIT_BACKEND=memory` (set to `redis` to enable Redis)
-   `REDIS_URL` (required if `RATE_LIMIT_BACKEND=redis`; e.g., `redis://localhost:6379/0`)

---

## Running the Application

### For Development

Once you have configured your `.env` file, you can run the local development server:

```bash
flask run
```

Navigate to `http://127.0.0.1:5000` in your web browser.

### Running the Test Suite

The project includes a comprehensive test suite using `pytest`. To run the tests:

```bash
pytest
```

---

## Deployment

This application is built to be deployed on platforms like Heroku, DigitalOcean, Railway, or PythonAnywhere.

### Key Deployment Considerations:

1.  **Environment Variables**: On your hosting provider, make sure to set the same environment variables as in your `.env` file, especially `SECRET_KEY` and `FLASK_ENV=production`.
2.  **WSGI Server**: Do not use the Flask development server (`flask run`) in production. Use a production-ready WSGI server like **Gunicorn** or **uWSGI**.
    ```bash
    # Example Gunicorn command for 3 workers
    gunicorn --workers 3 --bind 0.0.0.0:8000 app:app
    ```
3.  **Redis for Scaling**: If you deploy with multiple Gunicorn workers, you **must** configure a `REDIS_URL` to ensure the rate limiter works correctly across all workers.
4.  **File Storage**: The default file storage is ephemeral on many hosting platforms (like Heroku). For a robust production setup, consider using an external storage service like **Amazon S3** for uploads and reports. If traffic is very low, you may want a scheduled job (cron) to trigger periodic cleanup.

---

## Project Structure

```
.
├── app.py                  # Main Flask application
├── benford/                # Core analysis logic
│   ├── analyzer.py
│   ├── interpretation.py
│   └── external_data.py
├── data/examples/          # Curated example datasets + metadata
├── static/                 # Generated plots/reports
├── templates/              # HTML templates (base, upload, preview, results, examples, kaggle, learn)
├── tests/                  # Pytest test suite
├── .env.example            # Environment variable template
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

## Examples

- Browse curated datasets at `/examples` (or click “Browse examples” on the landing page).
- Example files live in `data/examples/` with metadata in `data/examples/metadata.json`.

## Kaggle Integration

- Navigate to `/kaggle` (or click “Data Sources”).
- Enter Kaggle username and API key (stored encrypted in session for 1 hour).
- Search for datasets; only CSV files are shown, ranked by suitability for Benford analysis.
- Preview up to 100 rows before downloading; downloads are limited to CSVs under 50MB and 500k rows.
- Then run the standard analysis flow.
