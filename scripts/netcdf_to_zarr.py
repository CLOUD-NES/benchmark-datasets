"""Concatenate NetCDF3 files and rewrite them as a Zarr v3 store.

Adapted from tmp/knmi-precipitation-zarr.ipynb.

    python netcdf_to_zarr.py SRC_GLOB DST [--chunks time=-1,x=100,y=100]
"""

import argparse

import fsspec
import xarray as xr

from s3 import glob

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("src_glob")
    parser.add_argument("dst")
    parser.add_argument("--chunks", help="comma-separated dim=size pairs, e.g. time=-1,x=100,y=100")
    args = parser.parse_args()

    fs = fsspec.filesystem("s3")
    files = [fs.open(path, mode="rb") for path in glob(args.src_glob)]
    ds = xr.open_mfdataset(files, engine="scipy", combine="by_coords", parallel=True)
    if args.chunks:
        ds = ds.chunk({dim: int(size) for dim, size in (pair.split("=") for pair in args.chunks.split(","))})
    ds.to_zarr(args.dst, mode="w", zarr_format=3)
