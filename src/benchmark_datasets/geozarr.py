"""Convert single-band GeoTIFFs to groups of a GeoZarr store (multiscales + proj: + spatial:).

Adapted from tmp/explore-geozarr/to-geozarr.py. Layout, for each group (e.g. "DSM05/4"):
    GROUP/       group: multiscales, proj:, spatial: (+ per-level spatial:shape/transform)
    GROUP/0/     group: proj:, spatial:; array <name> + x/y coords (full res)
    GROUP/1/     same, downsampled
    ...

Per-level proj:/spatial: attrs are written by rioxarray (Convention.ZARR), which also reads
them back: xr.open_zarr(DST, group="DSM05/4/1").rio.crs works without a spatial_ref coordinate.
"""

import os
from unittest import mock

import rioxarray
import xarray
import zarr
from geozarr_toolkit import MultiscalesConventionMetadata, create_zarr_conventions, validate_group
from rioxarray.enum import Convention

from .gdal import gdal_env, to_vsi_uri
from .s3 import S3Config, filesystem


def write(
    sources: dict[str, str],
    dst: str,
    name: str,
    levels: list[int] | None = None,
    chunks: int = 400,
    shards: int = 400,
    s3_config: S3Config | None = None,
) -> None:
    """Write one multiscale GeoZarr group per source raster.

    Args:
        sources: source raster URIs, keyed by group path (e.g. "DSM05/4").
        dst: URI of the Zarr store.
        name: name of the variable.
        levels: downsampling factors on top of full res (1).
        chunks: chunk size (same along x and y).
        shards: shard size (same along x and y).
        s3_config: S3 configuration options and credentials.
    """
    factors = [1] + (levels or [])
    storage_options = filesystem(dst, s3_config).storage_options or None
    for group, src in sources.items():
        # env vars rather than rasterio.Env, which is thread-local and would not reach the dask workers
        with mock.patch.dict(os.environ, gdal_env(s3_config)):
            da = rioxarray.open_rasterio(to_vsi_uri(src), masked=True, chunks={"x": shards, "y": shards})
            da = da.squeeze("band", drop=True)
            # Drop CF georeferencing (spatial_ref coord, grid_mapping) and GDAL attrs: the Zarr conventions replace
            crs = da.rio.crs
            da = da.drop_vars("spatial_ref")
            da.attrs, da.encoding = {}, {}
            layout = []
            for i, factor in enumerate(factors):
                attrs = _write_level(da, crs, dst, f"{group}/{i}", name, factor, chunks, shards, storage_options)
                layout.append(_layout_entry(attrs, i, factors))
        root = zarr.open_group(dst, path=group, mode="a", zarr_format=3, storage_options=storage_options)
        _write_root_attrs(root, layout)
        _validate(root, len(factors))
    zarr.consolidate_metadata(zarr.open_group(dst, mode="a", storage_options=storage_options).store)


def _write_level(da, crs, dst, group, name, factor, chunks, shards, storage_options) -> dict:
    """Write one (block-averaged) level as `group`, return the dataset attrs."""
    # ponytail: block average ignoring NaN only; add other resampling methods if needed.
    lvl = da if factor == 1 else da.coarsen(x=factor, y=factor, boundary="trim").mean()
    ds: xarray.Dataset = lvl.to_dataset(name=name)
    ds = ds.rio.write_crs(crs, convention=Convention.ZARR)
    ds = ds.rio.write_transform(ds.rio.transform(recalc=True), convention=Convention.ZARR)
    ds = ds.chunk({"x": shards, "y": shards})
    ds.to_zarr(
        dst,
        group=group,
        mode="w",
        zarr_format=3,
        consolidated=False,
        storage_options=storage_options,
        encoding={name: {"chunks": (chunks, chunks), "shards": (shards, shards)}},
    )
    return ds.attrs


def _layout_entry(attrs: dict, i: int, factors: list[int]) -> dict:
    entry = {"asset": str(i), "spatial:shape": attrs["spatial:shape"], "spatial:transform": attrs["spatial:transform"]}
    if i > 0:
        step = float(factors[i] // factors[i - 1])
        entry |= {
            "derived_from": str(i - 1),
            "transform": {"scale": [step, step], "translation": [0.0, 0.0]},
            "resampling_method": "average",
        }
    return entry


def _write_root_attrs(root: zarr.Group, layout: list[dict]) -> None:
    """Group: dataset-wide geo attrs (CRS, dims, bbox) next to multiscales; per-level shape/transform in layout."""
    base = dict(root["0"].attrs)  # full-resolution level's proj:/spatial: attrs
    root.attrs.update(
        {
            **{k: v for k, v in base.items() if k not in ("spatial:shape", "spatial:transform")},
            "zarr_conventions": create_zarr_conventions(MultiscalesConventionMetadata()) + base["zarr_conventions"],
            "multiscales": {"layout": layout},
        }
    )


def _validate(root: zarr.Group, nlevels: int) -> None:
    """Every group must validate against the conventions it declares."""
    groups = {"": root} | {str(i): root[str(i)] for i in range(nlevels)}
    errors = {path: errs for path, g in groups.items() if any((errs := validate_group(g)).values())}
    assert not errors, errors
