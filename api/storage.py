"""
api/storage.py — Abstraction stockage pour fichiers volumineux (GPS, streams).

En production : stocke dans Cloudflare R2 (S3-compatible).
En developpement : stocke sur le systeme de fichiers local.

Seuls les sous-repertoires gps/, streams/ et garmin/streams/ des dossiers
utilisateurs sont geres par R2. Tout le reste reste en local.

Variables d'environnement requises pour R2 :
    R2_BUCKET, R2_ENDPOINT, R2_ACCESS_KEY, R2_SECRET_KEY
"""

import io
import json
import os

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_USERS_DIR = os.path.join(_ROOT, "data", "users")

# ── R2 configuration ─────────────────────────────────────────────────────────

_R2_BUCKET = os.environ.get("R2_BUCKET", "")
_R2_ENDPOINT = os.environ.get("R2_ENDPOINT", "")
_R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY", "")
_R2_SECRET_KEY = os.environ.get("R2_SECRET_KEY", "")

USE_R2 = bool(_R2_BUCKET and _R2_ENDPOINT and _R2_ACCESS_KEY and _R2_SECRET_KEY)

# Subdirectories managed by R2 (relative to user base dir)
# `track` contient les données stade par utilisateur (track_pr.json, sessions/,
# inferred.json) générées pendant le sync : elles doivent vivre dans R2 en prod
# car le filesystem du conteneur Railway est éphémère.
_R2_MANAGED = ("gps", "streams", os.path.join("garmin", "streams"), "track")

_s3_client = None


def _s3():
    """Lazy-init the S3-compatible client (only imports boto3 when needed)."""
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client(
            "s3",
            endpoint_url=_R2_ENDPOINT,
            aws_access_key_id=_R2_ACCESS_KEY,
            aws_secret_access_key=_R2_SECRET_KEY,
            region_name="auto",
        )
    return _s3_client


def _to_key(path: str) -> str | None:
    """
    Convert an absolute local path to an R2 object key.
    Returns None if R2 is off or path is not in an R2-managed directory.

    /app/data/users/abc123/gps/strava_456.json -> abc123/gps/strava_456.json
    """
    if not USE_R2:
        return None
    try:
        rel = os.path.relpath(path, _USERS_DIR)
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    parts = rel.replace("\\", "/").split("/")
    if len(parts) < 3:
        return None
    for managed in _R2_MANAGED:
        mp = managed.replace("\\", "/").split("/")
        if parts[1:1 + len(mp)] == mp:
            return "/".join(parts)
    return None


def _dir_prefix(path: str) -> str | None:
    """Convert a directory path to an R2 listing prefix."""
    if not USE_R2:
        return None
    try:
        rel = os.path.relpath(path, _USERS_DIR)
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    parts = rel.replace("\\", "/").split("/")
    if len(parts) < 2:
        return None
    for managed in _R2_MANAGED:
        mp = managed.replace("\\", "/").split("/")
        if parts[1:1 + len(mp)] == mp and len(parts) == 1 + len(mp):
            return "/".join(parts) + "/"
    return None


# ── Public API ────────────────────────────────────────────────────────────────


def read_json(path: str) -> dict | None:
    """Read a JSON file from R2 or local filesystem."""
    key = _to_key(path)
    if key:
        try:
            obj = _s3().get_object(Bucket=_R2_BUCKET, Key=key)
            return json.loads(obj["Body"].read())
        except Exception:
            return None
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data: dict | list, indent: int = 2) -> None:
    """Write a JSON file to R2 or local filesystem."""
    key = _to_key(path)
    if key:
        body = json.dumps(data, indent=indent, ensure_ascii=False).encode("utf-8")
        _s3().put_object(Bucket=_R2_BUCKET, Key=key, Body=body,
                         ContentType="application/json")
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)


def read_csv(path: str) -> pd.DataFrame | None:
    """Read a CSV file from R2 or local filesystem."""
    key = _to_key(path)
    if key:
        try:
            obj = _s3().get_object(Bucket=_R2_BUCKET, Key=key)
            return pd.read_csv(io.BytesIO(obj["Body"].read()))
        except Exception:
            return None
    if not os.path.exists(path):
        return None
    return pd.read_csv(path)


def write_csv(path: str, df: pd.DataFrame) -> None:
    """Write a DataFrame as CSV to R2 or local filesystem."""
    key = _to_key(path)
    if key:
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        _s3().put_object(Bucket=_R2_BUCKET, Key=key,
                         Body=buf.getvalue().encode("utf-8"),
                         ContentType="text/csv")
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_csv(path, index=False)


def exists(path: str) -> bool:
    """Check if a file exists in R2 or on local filesystem."""
    key = _to_key(path)
    if key:
        try:
            _s3().head_object(Bucket=_R2_BUCKET, Key=key)
            return True
        except Exception:
            return False
    return os.path.exists(path)


def listdir(path: str) -> list[str]:
    """List filenames in a directory (R2 prefix or local)."""
    prefix = _dir_prefix(path)
    if prefix:
        s3 = _s3()
        names = []
        kwargs: dict = {"Bucket": _R2_BUCKET, "Prefix": prefix}
        while True:
            resp = s3.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                name = obj["Key"][len(prefix):]
                if name and "/" not in name:
                    names.append(name)
            if not resp.get("IsTruncated"):
                break
            kwargs["ContinuationToken"] = resp["NextContinuationToken"]
        return names
    if not os.path.isdir(path):
        return []
    return os.listdir(path)


def isdir(path: str) -> bool:
    """Check if a directory exists locally or has any objects in R2."""
    prefix = _dir_prefix(path)
    if prefix:
        try:
            resp = _s3().list_objects_v2(Bucket=_R2_BUCKET, Prefix=prefix, MaxKeys=1)
            return resp.get("KeyCount", 0) > 0
        except Exception:
            return False
    return os.path.isdir(path)
