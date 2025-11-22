import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Protocol, List, Optional, Dict, Tuple

import pandas as pd
from cryptography.fernet import Fernet, InvalidToken


class ExternalDataError(Exception):
    """Generic external data integration error."""


class ExternalDataAuthError(ExternalDataError):
    """Raised when authentication fails."""


class ExternalDataRateLimitError(ExternalDataError):
    """Raised when rate limits are exceeded."""


class ExternalDataSource(Protocol):
    """Protocol for external data source integrations."""

    def authenticate(self, credentials: Dict[str, str]) -> bool:
        ...

    def search(self, query: str, filters: Optional[Dict] = None) -> List[Dict]:
        ...

    def get_metadata(self, dataset_id: str) -> Dict:
        ...

    def download(self, dataset_id: str, file_name: str, output_path: Path) -> Path:
        ...


def _get_fernet(secret_key: str) -> Fernet:
    """Derive a Fernet key from the Flask secret key."""
    digest = hashlib.sha256(secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_credentials(secret_key: str, credentials: Dict[str, str]) -> str:
    f = _get_fernet(secret_key)
    return f.encrypt(json.dumps(credentials).encode()).decode()


def decrypt_credentials(secret_key: str, token: str) -> Dict[str, str]:
    f = _get_fernet(secret_key)
    try:
        payload = f.decrypt(token.encode())
        data = json.loads(payload.decode())
        if not isinstance(data, dict):
            raise ExternalDataAuthError("Invalid credential payload.")
        return data
    except InvalidToken as exc:
        raise ExternalDataAuthError("Invalid or expired credentials.") from exc
    except json.JSONDecodeError as exc:
        raise ExternalDataAuthError("Malformed credentials.") from exc


def sanitize_credential(value: str) -> str:
    """Return a partially masked credential for safe logging."""
    if not value:
        return "***"
    return f"{value[:3]}***"


def validate_dataset_ref(ref: str) -> str:
    """Ensure dataset reference matches expected kaggle pattern owner/dataset."""
    pattern = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+$")
    if not pattern.match(ref):
        raise ExternalDataError("Invalid dataset reference.")
    return ref


def validate_filename(name: str) -> str:
    if not name or "/" in name or "\\" in name:
        raise ExternalDataError("Invalid filename.")
    return name


def suitability_score(title: str, ref: str) -> int:
    positive = ["population", "finance", "financial", "measurement", "measure", "sales", "revenue", "gdp", "income", "earthquake", "river", "length"]
    negative = ["image", "text", "nlp", "classification", "sentiment", "review"]
    score = 0
    text = f"{title} {ref}".lower()
    for word in positive:
        if word in text:
            score += 2
    for word in negative:
        if word in text:
            score -= 2
    return score


class KaggleConfig:
    max_download_bytes: int = 50 * 1024 * 1024  # 50MB
    max_rows: int = 500_000
    search_limit: int = 10


class KaggleDataSource:
    """Kaggle API integration with security and validation."""

    def __init__(self, config: Optional[KaggleConfig] = None):
        self.config = config or KaggleConfig()
        self._api = None

    def _load_api(self):
        try:
            from kaggle import KaggleApi  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ExternalDataError("Kaggle API library is not installed.") from exc
        api = KaggleApi()
        api.authenticate()
        self._api = api
        return api

    def _get_api(self):
        if self._api is None:
            return self._load_api()
        return self._api

    def authenticate(self, credentials: Dict[str, str]) -> bool:
        username = credentials.get("username", "").strip()
        key = credentials.get("key", "").strip()
        if not username or not key:
            raise ExternalDataAuthError("Username and API key are required.")
        if not re.match(r"^[A-Za-z0-9_-]{3,}$", username):
            raise ExternalDataAuthError("Invalid Kaggle username format.")
        if not re.match(r"^[A-Za-z0-9\\-]{8,}$", key):
            raise ExternalDataAuthError("Invalid Kaggle API key format.")

        os.environ["KAGGLE_USERNAME"] = username
        os.environ["KAGGLE_KEY"] = key
        api = self._load_api()
        return api is not None

    def search(self, query: str, filters: Optional[Dict] = None) -> List[Dict]:
        api = self._get_api()
        datasets = api.dataset_list(search=query, page_size=self.config.search_limit)
        results = []
        for ds in datasets:
            ref = f"{ds.owner_slug}/{ds.dataset_slug}"
            ref = validate_dataset_ref(ref)
            files = api.dataset_list_files(ref)
            csv_files = [f for f in files.files if f.name.lower().endswith(".csv")]
            if not csv_files:
                continue
            results.append({
                "ref": ref,
                "title": ds.title,
                "description": getattr(ds, "subtitle", "") or "",
                "csv_files": [{"name": f.name, "size": f.totalBytes} for f in csv_files],
                "score": suitability_score(ds.title, ref)
            })
        return sorted(results, key=lambda r: r["score"], reverse=True)

    def get_metadata(self, dataset_id: str) -> Dict:
        api = self._get_api()
        ref = validate_dataset_ref(dataset_id)
        files = api.dataset_list_files(ref)
        csv_files = [f for f in files.files if f.name.lower().endswith(".csv")]
        return {
            "ref": ref,
            "csv_files": [{"name": f.name, "size": f.totalBytes} for f in csv_files]
        }

    def download(self, dataset_id: str, file_name: str, output_path: Path) -> Path:
        api = self._get_api()
        ref = validate_dataset_ref(dataset_id)
        safe_name = validate_filename(file_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        api.dataset_download_file(ref, safe_name, path=str(output_path.parent), force=True, quiet=True)
        csv_path = output_path.parent / safe_name
        zip_path = output_path.parent / f"{safe_name}.zip"
        if zip_path.exists():
            import zipfile

            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(output_path.parent)
            zip_path.unlink(missing_ok=True)
        if not csv_path.exists():
            raise ExternalDataError("Downloaded file not found after extraction.")
        return csv_path


def read_preview(path: Path, max_rows: int = 100) -> Tuple[str, List[str], List[str], int]:
    df = pd.read_csv(path)
    preview_html = df.head(max_rows).to_html(classes='preview-table', index=False)
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    all_cols = df.columns.tolist()
    return preview_html, numeric_cols, all_cols, len(df)
