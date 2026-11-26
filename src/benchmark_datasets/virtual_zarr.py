"""Build virtual Zarr stores (kerchunk JSON/Parquet, Icechunk) from (Cloud-Optimized) GeoTIFFs.

Adapted from https://github.com/CLOUD-NES/ahn-virtual-zarr (notebooks/build-virtual-zarr-dsm.ipynb).
Only the highest resolution (first IFD) is referenced. A store can hold multiple groups (e.g. "DSM05/4").
"""

import json
from pathlib import Path
from urllib.parse import urlsplit

import icechunk
import numpy as np
import obstore.store
import xarray
from kerchunk.df import refs_to_dataframe
from obspec_utils.registry import ObjectStoreRegistry
from virtual_tiff import VirtualTIFF
from virtualizarr import open_virtual_dataset

from .s3 import S3Config, filesystem, obstore_store, public_href, remove

OUTPUT_FORMATS = ("kerchunk-json", "kerchunk-parquet", "icechunk")


def open_virtual_tiffs(uris: list[str], name: str, s3_config: S3Config | None = None) -> xarray.Dataset:
    """Open GeoTIFFs as virtual datasets, combine them by coordinates, call the variable `name`.

    References to S3 objects are rewritten as public HTTPS links.
    """
    urls = [u if urlsplit(u).scheme else Path(u).resolve().as_uri() for u in uris]
    registry = ObjectStoreRegistry({_store_root(u): _registry_store(u, s3_config) for u in urls})
    parser = VirtualTIFF(ifd=0)
    vds = [_open_virtual_tiff(url, registry, parser) for url in urls]
    vds = xarray.combine_by_coords(vds, join="outer", combine_attrs="drop_conflicts") if len(vds) > 1 else vds[0]
    vds = vds.rename({"0": name})
    return vds.vz.rename_paths(lambda p: public_href(p, s3_config))


def write(
    datasets: dict[str, xarray.Dataset],
    outputs: dict[str, str],
    s3_config: S3Config | None = None,
    message: str = "add virtual references",
) -> None:
    """Persist virtual datasets, one per group, in the requested output formats.

    Args:
        datasets: virtual datasets, keyed by group path (e.g. "DSM05/4").
        outputs: destination URIs, keyed by output format (see OUTPUT_FORMATS).
        s3_config: S3 configuration options and credentials.
        message: Icechunk commit message.
    """
    if "kerchunk-json" in outputs or "kerchunk-parquet" in outputs:
        refs = merge_kerchunk_refs({g: ds.vz.to_kerchunk(format="dict") for g, ds in datasets.items()})
        if "kerchunk-json" in outputs:
            uri = outputs["kerchunk-json"]
            filesystem(uri, s3_config).pipe(uri, json.dumps(refs).encode())
        if "kerchunk-parquet" in outputs:
            uri = outputs["kerchunk-parquet"]
            remove(uri, s3_config)
            refs_to_dataframe(refs, uri, storage_options=filesystem(uri, s3_config).storage_options)
    if "icechunk" in outputs:
        sample_href = _first_chunk_href(next(iter(datasets.values())))
        repo = create_icechunk_repo(outputs["icechunk"], sample_href, s3_config)
        session = repo.writable_session("main")
        for group, ds in datasets.items():
            ds.vz.to_icechunk(session.store, group=group)
        session.commit(message)


def merge_kerchunk_refs(refs: dict[str, dict]) -> dict:
    """Merge kerchunk references of multiple datasets in a single store, one group per dataset."""
    merged = {".zgroup": json.dumps({"zarr_format": 2})}
    for group, group_refs in refs.items():
        parts = group.strip("/").split("/")
        for i in range(1, len(parts)):  # intermediate groups
            merged["/".join(parts[:i] + [".zgroup"])] = json.dumps({"zarr_format": 2})
        merged |= {f"{group}/{key}": value for key, value in group_refs["refs"].items()}
    return {"version": 1, "refs": merged}


def create_icechunk_repo(uri: str, chunk_href: str, s3_config: S3Config | None = None) -> icechunk.Repository:
    """Create an Icechunk repository whose virtual chunks are read anonymously over HTTP(S) (or locally)."""
    remove(uri, s3_config)
    split = urlsplit(uri)
    if split.scheme == "s3":
        s3_config = s3_config or S3Config.from_env()
        storage = icechunk.s3_storage(
            bucket=split.netloc,
            prefix=split.path.strip("/"),
            endpoint_url=s3_config.endpoint_url,
            region=s3_config.region,
            access_key_id=s3_config.access_key_id,
            secret_access_key=s3_config.secret_access_key,
            anonymous=s3_config.is_anonymous,
            force_path_style=s3_config.endpoint_url is not None,
        )
    else:
        storage = icechunk.local_filesystem_storage(uri)

    prefix = f"{_store_root(chunk_href)}/"
    if prefix == "file:///":
        # icechunk wants a path in file:// prefixes: use the directory of the referenced files
        prefix = chunk_href.rsplit("/", 1)[0] + "/"
        store, credentials = (
            icechunk.local_filesystem_store(urlsplit(prefix).path),
            icechunk.Credentials.LocalFileSystemAccess(),
        )
    else:
        store, credentials = icechunk.http_store(), icechunk.Credentials.HttpAccess()

    config = icechunk.RepositoryConfig.default()
    config.set_virtual_chunk_container(icechunk.VirtualChunkContainer(url_prefix=prefix, store=store))
    repo = icechunk.Repository.create(
        storage=storage,
        config=config,
        authorize_virtual_chunk_access={prefix: credentials},
    )
    # persist the configuration, so it's available when opening the repository again
    repo.save_config()
    return repo


def _open_virtual_tiff(url: str, registry: ObjectStoreRegistry, parser: VirtualTIFF) -> xarray.Dataset:
    ds = open_virtual_dataset(url, registry=registry, parser=parser)
    return ds.assign_coords(_generate_coords(ds["0"].attrs, ds["0"].shape))


def _generate_coords(attrs: dict, shape: tuple[int, ...]) -> dict[str, np.ndarray]:
    """Produce coordinate arrays from the GeoTIFF tags (virtual-tiff does not parse coordinates).

    Adapted from kerchunk: https://github.com/fsspec/kerchunk/blob/3cd5ddc/kerchunk/tiff.py#L110
    """
    *_, height, width = shape
    xscale, yscale, zscale = attrs["model_pixel_scale"][:3]
    x0, y0, z0 = attrs["model_tiepoint"][3:6]
    out = {
        "x": np.arange(width) * xscale + x0 + xscale / 2,
        "y": np.arange(height) * -yscale + y0 - yscale / 2,
    }
    if len(shape) > 2:
        out["z"] = np.arange(shape[-3]) * zscale + z0 + zscale / 2
    return out


def _store_root(url: str) -> str:
    split = urlsplit(url)
    return f"{split.scheme}://{split.netloc}"


def _registry_store(url: str, s3_config: S3Config | None) -> obstore.store.ObjectStore:
    root = _store_root(url)
    return obstore.store.LocalStore() if root == "file://" else obstore_store(root, s3_config)


def _first_chunk_href(ds: xarray.Dataset) -> str:
    """Path of one of the files referenced by the virtual dataset."""
    for var in ds.data_vars.values():
        manifest = var.data.manifest
        return str(next(p for p in np.asarray(manifest._paths).ravel() if p))
    raise ValueError("No virtual variable found")
