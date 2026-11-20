"""Convert a single-band GeoTIFF to a GeoZarr store (multiscales + proj: + spatial:).

Adapted from tmp/explore-geozarr/to-geozarr.py. The destination is overwritten.

Layout:
    DST/            group: multiscales, proj:, spatial: (+ per-level spatial:shape/transform)
    DST/0/          group: proj:, spatial:; array <name> + x/y coords (full res)
    DST/1/          same, 2x average-downsampled
    ...

Per-level proj:/spatial: attrs are written by rioxarray (Convention.ZARR), which also reads
them back: xr.open_zarr(DST, group="1").rio.crs works without a spatial_ref coordinate.

    python tiff_to_geozarr.py SRC DST [--levels 2 4 8] [--chunks 200] [--shards 400]
"""

import argparse
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import rioxarray
import zarr
from geozarr_toolkit import MultiscalesConventionMetadata, create_zarr_conventions, validate_group
from rioxarray.enum import Convention

from common import S3_FILESYSTEM, remove


def write_level(da, crs, dst, name, i, factor, chunks, shards):
    """Write one (block-averaged) level as group `i`, return the dataset attrs."""
    # ponytail: block average ignoring NaN only; add other resampling methods if needed.
    lvl = da if factor == 1 else da.coarsen(x=factor, y=factor, boundary="trim").mean()
    ds = lvl.to_dataset(name=name)
    ds = ds.rio.write_crs(crs, convention=Convention.ZARR)
    ds = ds.rio.write_transform(ds.rio.transform(recalc=True), convention=Convention.ZARR)
    # rioxarray 0.24 writes rasterio's default WKT1 under proj:wkt2; store actual WKT2.
    ds.attrs["proj:wkt2"] = crs.to_wkt(version="WKT2_2019")
    assert ds.attrs["spatial:transform"][0] == da.rio.resolution()[0] * factor, ds.attrs["spatial:transform"]
    ds.to_zarr(
        dst,
        group=str(i),
        mode="w",
        zarr_format=3,
        consolidated=False,
        encoding={name: {"chunks": (chunks, chunks), "shards": (shards, shards)}},
    )
    return ds.attrs


def layout_entry(attrs, i, factors):
    entry = {"asset": str(i), "spatial:shape": attrs["spatial:shape"], "spatial:transform": attrs["spatial:transform"]}
    if i > 0:
        step = float(factors[i] // factors[i - 1])
        entry |= {
            "derived_from": str(i - 1),
            "transform": {"scale": [step, step], "translation": [0.0, 0.0]},
            "resampling_method": "average",
        }
    return entry


def write_root_attrs(dst, layout):
    """Root: dataset-wide geo attrs (CRS, dims, bbox) next to multiscales; per-level shape/transform in layout."""
    root = zarr.open_group(dst, mode="a", zarr_format=3)
    base = dict(root["0"].attrs)  # full-resolution level's proj:/spatial: attrs
    root.attrs.update(
        {
            **{k: v for k, v in base.items() if k not in ("spatial:shape", "spatial:transform")},
            "zarr_conventions": create_zarr_conventions(MultiscalesConventionMetadata()) + base["zarr_conventions"],
            "multiscales": {"layout": layout},
        }
    )
    zarr.consolidate_metadata(dst)


def validate(dst, nlevels):
    """Every group must validate against the conventions it declares."""
    root = zarr.open_group(dst, mode="r")
    groups = {"": root} | {str(i): root[str(i)] for i in range(nlevels)}
    errors = {path: errs for path, g in groups.items() if any((errs := validate_group(g)).values())}
    assert not errors, errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("--levels", type=int, nargs="+", help="downsampling factors on top of full res (1)")
    parser.add_argument("--chunks", type=int, default=200)
    parser.add_argument("--shards", type=int, default=400)
    args = parser.parse_args()
    levels = [1] + (args.levels or [])

    name = PurePosixPath(urlsplit(args.src).path).stem
    remove(args.dst)

    with S3_FILESYSTEM.open(args.src, mode="rb") as f:
        da = rioxarray.open_rasterio(f, masked=True).squeeze("band", drop=True)
        # Drop CF georeferencing (spatial_ref coord, grid_mapping) and GDAL attrs: the Zarr conventions replace them.
        crs = da.rio.crs
        da = da.drop_vars("spatial_ref")
        da.attrs, da.encoding = {}, {}
        layout = [
            layout_entry(write_level(da, crs, args.dst, name, i, f, args.chunks, args.shards), i, levels)
            for i, f in enumerate(levels)
        ]

    write_root_attrs(args.dst, layout)
    validate(args.dst, len(levels))
    print(f"wrote {args.dst}, all groups valid")
