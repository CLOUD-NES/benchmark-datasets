"""Convert GeoTIFFs to a GeoZarr store (multiscales + proj: + spatial:).

Adapted from tmp/explore-geozarr/to-geozarr.py. Each source raster is one version of one variable:
all rasters share the same grid (extent, CRS, resolution), versions are stacked along a "version" dimension
(or dropped, for a single version). Multi-band rasters get a trailing "band" dimension. Layout:
    DST/         group: multiscales, proj:, spatial: (+ per-level spatial:shape/transform)
    DST/0/       group: proj:, spatial:; arrays <variable>([version,] y, x[, band]) + coords (full res)
    DST/1/       same, downsampled
    ...

Per-level proj:/spatial: attrs are written by rioxarray (Convention.ZARR), which also reads
them back: xr.open_zarr(DST, group="1").rio.crs works without a spatial_ref coordinate.

JPEG-compressed stores use the zarr-extensions `jpeg` codec, which requires (y, x[, band]) chunks of 8-bit data
(hence no version dimension). Its imagecodecs implementation must be registered before reading them:
`zarr.registry.register_codec("jpeg", imagecodecs.zarr.JpegCodec)`.
"""

import os
from contextlib import ExitStack
from unittest import mock

import numpy
import pandas as pd
import rioxarray
import xarray
import zarr
import zarr.registry
from geozarr_toolkit import MultiscalesConventionMetadata, create_zarr_conventions, validate_group
from imagecodecs.zarr import JpegCodec
from rioxarray.enum import Convention

from .gdal import gdal_env, to_vsi_uri
from .s3 import S3Config, filesystem


def write(
    sources: dict[str, dict[int, str]],
    dst: str,
    levels: list[int] | None = None,
    chunks: int = 400,
    shards: int = 400,
    masked: bool = True,
    serializer: object = None,
    version_dim: bool = True,
    s3_config: S3Config | None = None,
) -> None:
    """Write a multiscale GeoZarr store with one variable per asset and a version dimension.

    Args:
        sources: source raster URIs, keyed by variable name and version (e.g. {"DSM05": {4: "s3://..."}}).
        dst: URI of the Zarr store.
        levels: downsampling factors on top of full res (1).
        chunks: chunk size (same along x and y, 1 along version).
        shards: shard size (same along x and y, 1 along version).
        masked: mask nodata as NaN (converts to float).
        serializer: Zarr array-to-bytes codec (default: Zarr's).
        version_dim: keep the version dimension, otherwise sources must have a single version.
        s3_config: S3 configuration options and credentials.
    """
    factors = [1] + (levels or [])
    storage_options = filesystem(dst, s3_config).storage_options or None
    if isinstance(serializer, JpegCodec):
        zarr.registry.register_codec("jpeg", JpegCodec)  # needed to read back the metadata
    # env vars rather than rasterio.Env, which is thread-local and would not reach the dask workers
    # rasters are closed on exit: leaving them to the garbage collector errors at interpreter shutdown
    with mock.patch.dict(os.environ, gdal_env(s3_config)), ExitStack() as stack:
        ds, crs = open_dataset(sources, stack, shards, masked)
        if not version_dim:
            ds = ds.squeeze("version", drop=True)
        layout = []
        for i, factor in enumerate(factors):
            attrs = _write_level(ds, crs, dst, str(i), factor, chunks, shards, serializer, storage_options)
            layout.append(_layout_entry(attrs, i, factors))
    root = zarr.open_group(dst, mode="a", zarr_format=3, storage_options=storage_options)
    _write_root_attrs(root, layout)
    _validate(root, len(factors))
    zarr.consolidate_metadata(root.store)


def open_dataset(
    sources: dict[str, dict[int, str]], stack: ExitStack, chunksize: int = 400, masked: bool = True
) -> tuple[xarray.Dataset, object]:
    """Lazily open the source rasters as one dataset: a variable per name, stacked along "version".

    All rasters are assumed to share the same grid (extent, CRS, resolution). They are closed with `stack`, so
    the dataset must be computed before then. Returns the dataset and its CRS.
    """
    arrays = {
        name: [_open_raster(uri, stack, chunksize, masked) for _, uri in sorted(versions.items())]
        for name, versions in sources.items()
    }
    crs = next(iter(arrays.values()))[0].rio.crs
    variables = {
        name: xarray.concat(
            [da.drop_vars("spatial_ref") for da in das],
            dim=pd.Index(sorted(sources[name]), name="version"),
            join="exact",  # fail loudly if the grids differ after all
        )
        for name, das in arrays.items()
    }
    return xarray.Dataset(variables), crs


def _open_raster(uri: str, stack: ExitStack, chunksize: int, masked: bool) -> xarray.DataArray:
    chunks = {"x": chunksize, "y": chunksize, "band": -1}
    da = rioxarray.open_rasterio(to_vsi_uri(uri), masked=masked, chunks=chunks)
    assert isinstance(da, xarray.DataArray)
    stack.enter_context(da)
    da = da.squeeze("band", drop=True) if da.sizes["band"] == 1 else da.transpose("y", "x", "band")
    # Drop GDAL attrs and encoding: the Zarr conventions replace them
    da.attrs, da.encoding = {}, {}
    return da


def _write_level(ds, crs, dst, group, factor, chunks, shards, serializer, storage_options) -> dict:
    """Write one (block-averaged) level as `group`, return the dataset attrs."""
    # ponytail: block average ignoring NaN only; add other resampling methods if needed.
    lvl = ds if factor == 1 else ds.coarsen(x=factor, y=factor, boundary="trim").mean().map(_round_like, src=ds)
    lvl = lvl.rio.write_crs(crs, convention=Convention.ZARR)
    lvl = lvl.rio.write_transform(lvl.rio.transform(recalc=True), convention=Convention.ZARR)
    lvl = lvl.chunk({d: s for d, s in {"version": 1, "x": shards, "y": shards}.items() if d in lvl.dims})
    # zarr can pass views of the blocks to the codecs, and the JPEG encoder requires C-contiguous ones
    lvl = lvl.map(lambda da: da.copy(data=da.data.map_blocks(numpy.ascontiguousarray)))
    encoding = {
        name: {"chunks": _block(lvl[name], chunks), "shards": _block(lvl[name], shards)}
        | ({"serializer": serializer, "compressors": None} if serializer else {})
        for name in lvl.data_vars
    }
    lvl.to_zarr(
        dst,
        group=group,
        mode="w",
        zarr_format=3,
        consolidated=False,
        storage_options=storage_options,
        encoding=encoding,
    )
    return lvl.attrs


def _block(da: xarray.DataArray, size: int) -> tuple[int, ...]:
    """Chunk/shard shape: `size` along x and y, 1 along version, whole bands."""
    return tuple(size if d in ("x", "y") else 1 if d == "version" else da.sizes[d] for d in da.dims)


def _round_like(da: xarray.DataArray, src: xarray.Dataset) -> xarray.DataArray:
    """Cast an averaged integer variable back to its source dtype (mean returns floats)."""
    dtype = src[da.name].dtype
    return da.round().astype(dtype) if dtype.kind in "iu" else da


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
    """Root: dataset-wide geo attrs (CRS, dims, bbox) next to multiscales; per-level shape/transform in layout."""
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
