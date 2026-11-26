import dataclasses
import os
from functools import lru_cache

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
    def is_anonymous(self):
        """For public buckets, skip signature."""
        return self.access_key_id is None and self.secret_access_key is None


@lru_cache
def s3_filesystem(s3_config: S3Config) -> s3fs.S3FileSystem:
    return s3fs.S3FileSystem(
        anon=s3_config.is_anonymous,
        endpoint_url=s3_config.endpoint_url if s3_config.endpoint_url else None,
        client_kwargs={"region_name": s3_config.region} if s3_config.region else {},
        key=s3_config.access_key_id if s3_config.access_key_id else None,
        secret=s3_config.secret_access_key if s3_config.secret_access_key else None,
    )


def exists(path: str, s3_config: S3Config | None) -> bool:
    s3_config = S3Config.from_env() if s3_config is None else s3_config
    fs = s3_filesystem(s3_config)
    return fs.exists(path=path)


def glob(path: str, s3_config: S3Config | None) -> list[str]:
    fs = s3_filesystem(s3_config)
    return [fs.unstrip_protocol(p) for p in fs.glob(path=path)]
