"""
Cloud storage abstraction for document files.

Supports two backends, selected automatically:
  - Local disk  — when S3_BUCKET is empty (development default, zero config)
  - AWS S3 / Cloudflare R2 — when S3_BUCKET is set (production)

Cloudflare R2 is fully S3-compatible.  Set:
    S3_ENDPOINT_URL  = https://<account_id>.r2.cloudflarestorage.com
    S3_REGION        = auto
    S3_BUCKET        = <your-bucket-name>
    S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY = R2 API token pair
"""

import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)


def _settings():
    from app.core.config import settings
    return settings


def is_cloud() -> bool:
    """Return True when S3/R2 is configured."""
    return bool(_settings().S3_BUCKET)


def _s3():
    """Return a boto3 S3 client.  Import is lazy so boto3 is optional in dev."""
    import boto3  # noqa: PLC0415
    from botocore.config import Config  # noqa: PLC0415
    s = _settings()
    kwargs: dict = {
        "aws_access_key_id": s.S3_ACCESS_KEY_ID,
        "aws_secret_access_key": s.S3_SECRET_ACCESS_KEY,
        "region_name": s.S3_REGION or "auto",
        "config": Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    }
    if s.S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = s.S3_ENDPOINT_URL
    return boto3.client("s3", **kwargs)


# ── Public API ──────────────────────────────────────────────────────────────

def save_file(content: bytes, key: str) -> str:
    """
    Persist *content* under *key*.

    Local mode  → writes to UPLOAD_DIR/<key>; creates parent dirs.
    Cloud mode  → uploads to S3_BUCKET/<key>.

    Returns the key (unchanged) so callers can store it in the DB.
    """
    if is_cloud():
        s = _settings()
        _s3().put_object(Bucket=s.S3_BUCKET, Key=key, Body=content)
        logger.info("Stored %d bytes → s3://%s/%s", len(content), s.S3_BUCKET, key)
    else:
        dest = Path(_settings().UPLOAD_DIR) / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        logger.debug("Stored %d bytes → %s", len(content), dest)
    return key


def delete_file(key: str) -> None:
    """
    Delete a stored file.  Best-effort — never raises.

    Local mode  → deletes UPLOAD_DIR/<key>.
    Cloud mode  → deletes S3_BUCKET/<key>.
    """
    try:
        if is_cloud():
            s = _settings()
            _s3().delete_object(Bucket=s.S3_BUCKET, Key=key)
            logger.info("Deleted s3://%s/%s", s.S3_BUCKET, key)
        else:
            path = Path(_settings().UPLOAD_DIR) / key
            if path.exists():
                path.unlink()
            logger.debug("Deleted %s", path)
    except Exception:
        logger.warning("Could not delete file: %s", key, exc_info=True)


@contextmanager
def open_local(key: str) -> Generator[str, None, None]:
    """
    Context manager that yields a *local filesystem path* for *key*.

    Local mode  → yields the real path (no copy).
    Cloud mode  → downloads to a temp file, yields its path, then removes it.

    Usage::

        with open_local(doc.file_path) as path:
            pages = extract_pdf(path)
    """
    if not is_cloud():
        yield str(Path(_settings().UPLOAD_DIR) / key)
        return

    # Cloud: download to a temp file
    s = _settings()
    suffix = Path(key).suffix
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(tmp_fd)
    try:
        _s3().download_file(s.S3_BUCKET, key, tmp_path)
        logger.debug("Downloaded s3://%s/%s → %s", s.S3_BUCKET, key, tmp_path)
        yield tmp_path
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
