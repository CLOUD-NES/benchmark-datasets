"""Helpers shared by the virtual Zarr scripts."""

import os
import tempfile
from urllib.parse import urlsplit

import fsspec
import icechunk

from s3 import exists


def public_prefix(uri: str) -> str:
    """Public HTTPS prefix for the bucket of an S3 URI, e.g. https://objectstore.surf.nl/<bucket>/."""
    bucket = urlsplit(uri).netloc
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "").rstrip("/")
    return f"{endpoint}/{bucket}/" if endpoint else f"https://{bucket}.s3.amazonaws.com/"


def public_href(uri: str) -> str:
    """Public HTTPS link for an S3 URI, so it can be opened without S3 settings."""
    return uri.replace(f"s3://{urlsplit(uri).netloc}/", public_prefix(uri), 1)


def missing_outputs(outputs: dict[str, str | None], overwrite: bool) -> dict[str, str]:
    """Drop outputs not requested, and (unless overwrite) the ones already on S3."""
    return {k: v for k, v in outputs.items() if v and (overwrite or not exists(v))}


def write_outputs(vds, outputs: dict[str, str], src_uri: str, overwrite: bool, message: str) -> None:
    """Persist a virtual dataset as kerchunk JSON, kerchunk Parquet and/or Icechunk repository."""
    if "json" in outputs:
        # VirtualiZarr can only write JSON refs locally
        with tempfile.TemporaryDirectory() as tmp:
            local = os.path.join(tmp, "refs.json")
            vds.vz.to_kerchunk(local, format="json")
            fsspec.filesystem("s3").put(local, outputs["json"])
    if "parquet" in outputs:
        vds.vz.to_kerchunk(outputs["parquet"], format="parquet")
    if "icechunk" in outputs:
        session = create_icechunk_repo(outputs["icechunk"], public_prefix(src_uri), overwrite).writable_session("main")
        vds.vz.to_icechunk(session.store)
        session.commit(message)


def create_icechunk_repo(uri: str, chunk_prefix: str, overwrite: bool) -> icechunk.Repository:
    """Create an Icechunk repository whose virtual chunks are read anonymously over HTTP(S)."""
    if overwrite and exists(uri):
        fsspec.filesystem("s3").rm(uri, recursive=True)
    split = urlsplit(uri)
    storage = icechunk.s3_storage(bucket=split.netloc, prefix=split.path.strip("/"), from_env=True)
    config = icechunk.RepositoryConfig.default()
    config.set_virtual_chunk_container(
        icechunk.VirtualChunkContainer(url_prefix=chunk_prefix, store=icechunk.http_store(), name="http")
    )
    repo = icechunk.Repository.create(
        storage=storage,
        config=config,
        authorize_virtual_chunk_access={chunk_prefix: icechunk.Credentials.HttpAccess()},
    )
    # persist the configuration, so it's available when opening the repository again
    repo.save_config()
    return repo
