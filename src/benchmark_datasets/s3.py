import dataclasses
import os
from functools import lru_cache
from urllib.parse import urlsplit

import fsspec
import obstore.store
import s3fs


@dataclasses.dataclass(frozen=True)
class S3Config:
    """S3 configuration options and credentials."""

    bucket: str | None = None
    endpoint_url: str | None = None
    region: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None

    @classmethod
    def from_env(
        cls,
        bucket: str | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> "S3Config":
        """Build an S3Config, filling in missing fields from environment variables."""
        return cls(
            bucket=bucket or os.getenv("BUCKET"),
            endpoint_url=endpoint_url or os.getenv("AWS_ENDPOINT_URL"),
            region=region or os.getenv("AWS_REGION"),
            access_key_id=access_key_id or os.getenv("AWS_ACCESS_KEY_ID"),
            secret_access_key=secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY"),
        )

    @property
    def is_anonymous(self) -> bool:
        """For public buckets, skip signature."""
        return self.access_key_id is None and self.secret_access_key is None


@lru_cache
def s3_filesystem(s3_config: S3Config) -> s3fs.S3FileSystem:
    return s3fs.S3FileSystem(
        anon=s3_config.is_anonymous,
        endpoint_url=s3_config.endpoint_url,
        client_kwargs={"region_name": s3_config.region} if s3_config.region else {},
        key=s3_config.access_key_id,
        secret=s3_config.secret_access_key,
    )


def filesystem(uri: str, s3_config: S3Config | None = None) -> fsspec.AbstractFileSystem:
    """S3 filesystem for s3:// URIs, the matching fsspec filesystem otherwise (e.g. local paths)."""
    protocol = urlsplit(uri).scheme
    if protocol == "s3":
        return s3_filesystem(s3_config or S3Config.from_env())
    return fsspec.filesystem(protocol or "file")


def exists(uri: str, s3_config: S3Config | None = None) -> bool:
    return filesystem(uri, s3_config).exists(uri)


def glob(pattern: str, s3_config: S3Config | None = None) -> list[str]:
    """Find files by glob-matching, return full URIs (sorted)."""
    fs = filesystem(pattern, s3_config)
    return sorted(fs.unstrip_protocol(p) if urlsplit(pattern).scheme else p for p in fs.glob(pattern))


def remove(uri: str, s3_config: S3Config | None = None) -> None:
    """Delete a file or prefix, if it exists."""
    fs = filesystem(uri, s3_config)
    if fs.exists(uri):
        fs.rm(uri, recursive=True)


def public_prefix(uri: str, s3_config: S3Config | None = None) -> str:
    """Public HTTPS prefix for the bucket of an S3 URI, e.g. https://objectstore.surf.nl/<bucket>/."""
    s3_config = s3_config or S3Config.from_env()
    bucket = urlsplit(uri).netloc
    return f"{s3_config.endpoint_url}/{bucket}/" if s3_config.endpoint_url else f"https://{bucket}.s3.amazonaws.com/"


def public_href(uri: str, s3_config: S3Config | None = None) -> str:
    """Public HTTPS link for an S3 URI, so it can be opened without S3 settings."""
    if urlsplit(uri).scheme != "s3":
        return uri
    bucket = urlsplit(uri).netloc
    return uri.replace(f"s3://{bucket}/", public_prefix(uri, s3_config), 1)


def obstore_store(uri: str, s3_config: S3Config | None = None) -> obstore.store.ObjectStore:
    """Object store rooted at the given URI (S3, HTTP(S) or a local directory)."""
    split = urlsplit(uri)
    if split.scheme == "s3":
        s3_config = s3_config or S3Config.from_env()
        options = {
            "endpoint": s3_config.endpoint_url,
            "region": s3_config.region,
            "access_key_id": s3_config.access_key_id,
            "secret_access_key": s3_config.secret_access_key,
            "skip_signature": s3_config.is_anonymous or None,
        }
        return obstore.store.from_url(uri, **{k: v for k, v in options.items() if v is not None})
    if split.scheme:
        return obstore.store.from_url(uri)
    return obstore.store.LocalStore(prefix=uri, mkdir=True)
