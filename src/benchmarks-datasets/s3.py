import dataclasses
import os


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
