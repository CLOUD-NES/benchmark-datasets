"""Build virtual Zarr stores (kerchunk JSON/Parquet, Icechunk) from (Cloud-Optimized) GeoTIFFs.

Adapted from https://github.com/CLOUD-NES/ahn-virtual-zarr (notebooks/build-virtual-zarr-dsm.ipynb).
Only the highest resolution (first IFD) is referenced. A store holds one variable per asset, with versions
stacked along a "version" dimension (all rasters are assumed to share the same grid).
"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import icechunk
import numpy as np
import obstore.store
import pandas as pd
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


def stack_versions(datasets: dict[str, dict[int, xarray.Dataset]]) -> xarray.Dataset:
    """Combine virtual datasets in one: a variable per name, versions stacked along a "version" dimension.

    Args:
        datasets: virtual datasets (as from `open_virtual_tiffs`), keyed by variable name and version.
    """
    return xarray.Dataset(
        {
            name: xarray.concat(
                [versions[v][name] for v in sorted(versions)],
                dim=pd.Index(sorted(versions), name="version"),
                join="exact",  # fail loudly if the grids differ after all
                coords="minimal",
                compat="override",
                combine_attrs="drop_conflicts",
            )
            for name, versions in datasets.items()
        }
    )


def write(
    ds: xarray.Dataset,
    outputs: dict[str, str],
    s3_config: S3Config | None = None,
    message: str = "add virtual references",
) -> None:
    """Persist a virtual dataset in the requested output formats.

    Args:
        ds: virtual dataset.
        outputs: destination URIs, keyed by output format (see OUTPUT_FORMATS).
        s3_config: S3 configuration options and credentials.
        message: Icechunk commit message.
    """
    if "kerchunk-json" in outputs or "kerchunk-parquet" in outputs:
        refs = ds.vz.to_kerchunk(format="dict")
        if "kerchunk-json" in outputs:
            uri = outputs["kerchunk-json"]
            filesystem(uri, s3_config).pipe(uri, json.dumps(refs).encode())
        if "kerchunk-parquet" in outputs:
            uri = outputs["kerchunk-parquet"]
            remove(uri, s3_config)
            refs_to_dataframe(refs, uri, storage_options=filesystem(uri, s3_config).storage_options)
    if "icechunk" in outputs:
        repo = create_icechunk_repo(outputs["icechunk"], _chunk_prefix(ds), s3_config)
        session = repo.writable_session("main")
        ds.vz.to_icechunk(session.store)
        session.commit(message)


def create_icechunk_repo(uri: str, chunk_prefix: str, s3_config: S3Config | None = None) -> icechunk.Repository:
    """Create an Icechunk repository whose virtual chunks (under `chunk_prefix`) are read anonymously over HTTP(S).

    Local virtual chunks (file:// prefix) are also supported.
    """
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

    prefix = chunk_prefix
    if urlsplit(prefix).scheme == "file":
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


def _chunk_prefix(ds: xarray.Dataset) -> str:
    """URL prefix of all the files referenced by the virtual dataset, for the Icechunk virtual chunk container.

    For remote files, scheme and host (e.g. https://objectstore.example.com/); for local files, the deepest
    common directory (icechunk wants a path in file:// prefixes).
    """
    paths = {str(p) for var in ds.data_vars.values() for p in np.asarray(var.data.manifest._paths).ravel() if p}
    if not paths:
        raise ValueError("No virtual references found")
    roots = {_store_root(p) for p in paths}
    if len(roots) > 1:
        raise ValueError(f"Virtual references from multiple locations are not supported: {roots}")
    if roots == {"file://"}:
        return Path(os.path.commonpath([os.path.dirname(urlsplit(p).path) for p in paths])).as_uri() + "/"
    return f"{roots.pop()}/"
