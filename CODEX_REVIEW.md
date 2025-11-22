# Benford's Law App – Codex Review
**Date:** 2025-11-21  
**Reviewer:** Codex (GPT-5)  

## Findings
- Fixed a high-severity path traversal vector in `/analyze` where a crafted `filename` could escape `uploads/` and read arbitrary local files.
- MAX file size and log level env vars were documented but unused; requests now honor `MAX_FILE_SIZE_MB` and `LOG_LEVEL`.
- Production stability risk: Matplotlib used the default interactive backend; switched to `Agg` to avoid display/GUI dependency crashes in headless deployments.
- Benford analysis previously accepted non-numeric columns, which produced unclear failures; now enforces numeric conversion and errors if data is non-numeric.
- Missing lifecycle hygiene and CSRF protection; both are now addressed (see below).

## Changes Made
- Added upload path sanitization helper to keep all user-provided filenames inside `uploads/` and reject tampered values.
- Wired `.env` settings for log level and upload size, with validation and sane fallbacks.
- Set Matplotlib backend to `Agg` for server-safe plotting.
- Hardened analyzer numeric handling to raise a clear error when the selected column is non-numeric or empty.
- Implemented session-backed CSRF tokens for upload/preview/analyze POST endpoints.
- Added periodic cleanup of `uploads/` and generated `static` assets with configurable retention/interval.
- Added in-process rate limiting on POST endpoints (upload/preview/analyze) with configurable window and request counts; optional Redis backend for multi-process deployments with automatic fallback to memory.
- Introduced a pytest suite covering CSRF enforcement, upload/preview/analyze flows, cleanup behavior, rate limiting (including over-limit path), malformed CSV handling, large-file rejection, and analyzer numeric validation.

## Testing
- `python -m compileall app.py benford/analyzer.py scripts/run_analysis.py tests`
- Automated tests added in `tests/` (`python -m pytest`). Not run in this session because `pytest` is not installed in the current venv; install from `requirements.txt` then execute.

## Recommended Next Steps
- Add observability/metrics for cleanup runs and rate-limit hits in production deployments.
- If Redis is used for rate limiting, consider a periodic key cleanup or TTL tuning for very high traffic.
