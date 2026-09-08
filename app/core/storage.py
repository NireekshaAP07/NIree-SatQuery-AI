# File storage abstraction: local filesystem for MVP, S3-compatible for production.
# ⚠️  IMPORTANT — STORAGE NOTE:
# For MVP, files are stored on the LOCAL FILESYSTEM under STORAGE_LOCAL_ROOT (./data).
# In production (or when STORAGE_BACKEND=s3), files are stored in MinIO / S3 distributed object storage.
from __future__ import annotations

import io
import shutil
import uuid
from pathlib import Path
from typing import Union

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.logger import get_logger

settings = get_settings()
logger = get_logger("core.storage")


class LocalStorageBackend:
    """Stores files on the local filesystem under STORAGE_LOCAL_ROOT."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.storage_local_root)
        for subdir in ("raw", "derived", "tiles", "reports", "tmp"):
            (self.root / subdir).mkdir(parents=True, exist_ok=True)

    def save_upload(self, file_bytes: bytes, original_filename: str, subdir: str = "raw") -> Path:
        """Saves an uploaded file and returns its absolute path."""
        ext = Path(original_filename).suffix
        unique_name = f"{uuid.uuid4().hex}{ext}"
        dest = self.root / subdir / unique_name
        dest.write_bytes(file_bytes)
        return dest

    def get_path(self, relative_or_path: str | Path) -> Path:
        """Resolves a relative path safely within the storage root (prevents traversal)."""
        p = Path(relative_or_path)
        if p.is_absolute() and str(p.resolve()).startswith(str(self.root.resolve())):
            return p.resolve()
        resolved = (self.root / p).resolve()
        if not str(resolved).startswith(str(self.root.resolve())):
            raise ValueError(f"Path traversal attempt blocked: {relative_or_path}")
        return resolved

    def exists(self, relative_or_path: str | Path) -> bool:
        try:
            return self.get_path(relative_or_path).exists()
        except ValueError:
            return False

    def get_object_bytes(self, relative_or_path: str | Path) -> bytes:
        return self.get_path(relative_or_path).read_bytes()

    def download_file(self, relative_or_path: str | Path, target_path: str | Path) -> Path:
        src = self.get_path(relative_or_path)
        dest = Path(target_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        return dest

    def delete(self, relative_or_path: str | Path) -> None:
        try:
            path = self.get_path(relative_or_path)
            if path.exists():
                path.unlink()
        except ValueError:
            pass

    def save_derived(self, file_bytes: bytes, filename: str) -> Path:
        """Saves a derived product (tiles, change maps, etc.) separately from originals."""
        dest = self.root / "derived" / filename
        dest.write_bytes(file_bytes)
        return dest


class S3StorageBackend:
    """Stores files in MinIO / S3-compatible distributed object storage."""

    def __init__(
        self,
        bucket_name: str | None = None,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region_name: str | None = None,
        public_endpoint_url: str | None = None,
    ) -> None:
        self.bucket_name = bucket_name or settings.s3_bucket_name
        self.endpoint_url = endpoint_url or settings.s3_endpoint_url
        self.public_endpoint_url = public_endpoint_url or settings.s3_public_endpoint_url or self.endpoint_url
        self.region_name = region_name or settings.s3_region
        self.access_key = access_key or settings.s3_access_key
        self.secret_key = secret_key or settings.s3_secret_key

        # Local temp directory for caching raster operations if needed
        self.temp_dir = Path(settings.storage_local_root) / "tmp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # Primary internal S3 client (container-to-container)
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region_name,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

        # Public S3 client for presigned URLs (accessible by browser)
        if self.public_endpoint_url != self.endpoint_url:
            self.public_s3_client = boto3.client(
                "s3",
                endpoint_url=self.public_endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region_name,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
        else:
            self.public_s3_client = self.s3_client

    def _parse_key(self, key_or_uri: str) -> tuple[str, str]:
        """Extracts (bucket, key) from an s3:// URI or plain key."""
        s = str(key_or_uri).strip()
        if s.startswith("s3://"):
            parts = s[5:].split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
            return bucket, key
        return self.bucket_name, s.lstrip("/")

    def ensure_bucket(self) -> None:
        """Verifies or creates the storage bucket in MinIO / S3."""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "")
            if err_code in ("404", "NoSuchBucket"):
                try:
                    self.s3_client.create_bucket(Bucket=self.bucket_name)
                    logger.info("s3_bucket_created", bucket=self.bucket_name)
                except Exception as create_exc:
                    logger.warning("s3_bucket_create_failed", bucket=self.bucket_name, error=str(create_exc))
            else:
                logger.warning("s3_head_bucket_error", bucket=self.bucket_name, error=str(exc))

    def save_upload(self, file_bytes: bytes, original_filename: str, subdir: str = "raw") -> str:
        """Uploads a file to S3 and returns its canonical s3:// URI."""
        ext = Path(original_filename).suffix
        unique_name = f"{uuid.uuid4().hex}{ext}"
        key = f"{subdir}/{unique_name}".strip("/")
        
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=file_bytes,
        )
        uri = f"s3://{self.bucket_name}/{key}"
        logger.info("s3_upload_saved", uri=uri, size_bytes=len(file_bytes))
        return uri

    def save_derived(self, file_bytes: bytes, filename: str) -> str:
        """Uploads a derived asset (preview, tile, report) to S3 under derived/."""
        key = f"derived/{filename}".strip("/")
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=file_bytes,
        )
        uri = f"s3://{self.bucket_name}/{key}"
        logger.info("s3_derived_saved", uri=uri, size_bytes=len(file_bytes))
        return uri

    def get_object_bytes(self, key_or_uri: str) -> bytes:
        """Downloads object bytes from S3."""
        bucket, key = self._parse_key(key_or_uri)
        response = self.s3_client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def download_file(self, key_or_uri: str, target_path: str | Path) -> Path:
        """Downloads an S3 object to a local filesystem destination."""
        bucket, key = self._parse_key(key_or_uri)
        dest = Path(target_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.s3_client.download_file(bucket, key, str(dest))
        return dest

    def exists(self, key_or_uri: str) -> bool:
        """Checks if an object exists in the S3 bucket."""
        bucket, key = self._parse_key(key_or_uri)
        try:
            self.s3_client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "")
            if err_code in ("404", "NoSuchKey", "403"):
                return False
            return False

    def delete(self, key_or_uri: str) -> None:
        """Deletes an object from S3."""
        bucket, key = self._parse_key(key_or_uri)
        try:
            self.s3_client.delete_object(Bucket=bucket, Key=key)
            logger.info("s3_object_deleted", bucket=bucket, key=key)
        except ClientError as exc:
            logger.warning("s3_delete_failed", bucket=bucket, key=key, error=str(exc))

    def get_presigned_url(self, key_or_uri: str, expires_in: int = 3600) -> str:
        """Generates a secure time-limited presigned download URL."""
        bucket, key = self._parse_key(key_or_uri)
        url = self.public_s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url


def get_storage() -> Union[LocalStorageBackend, S3StorageBackend]:
    """Returns the configured storage backend (local or S3/MinIO)."""
    if settings.storage_backend == "local":
        return LocalStorageBackend(root=settings.storage_local_root)
    elif settings.storage_backend == "s3":
        return S3StorageBackend()
    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}. Use 'local' or 's3'.")
