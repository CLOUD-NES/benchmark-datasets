"""Build a virtual Zarr store from a set of NetCDF3 files (e.g. KNMI gridded datasets).

Adapted from tmp/knmi-precipitation-virtualizarr.ipynb. Each output is skipped if it already exists,
unless --overwrite is given.

    python netcdf_to_virtual_zarr.py SRC_GLOB [--json DST] [--parquet DST] [--icechunk DST] [--skip-variables V ...]
"""

import argparse
from urllib.parse import urlsplit

import obstore
from obspec_utils.registry import ObjectStoreRegistry
from virtualizarr import open_virtual_mfdataset
from virtualizarr.parsers import NetCDF3Parser

from common import missing_outputs, public_href, write_outputs
from s3 import glob

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("src_glob")
    parser.add_argument("--json")
    parser.add_argument("--parquet")
    parser.add_argument("--icechunk")
    parser.add_argument("--skip-variables", nargs="*", default=[])
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--message", default="add virtual references")
    args = parser.parse_args()

    outputs = missing_outputs({"json": args.json, "parquet": args.parquet, "icechunk": args.icechunk}, args.overwrite)
    if not outputs:
        raise SystemExit(0)

    bucket = f"s3://{urlsplit(args.src_glob).netloc}"
    registry = ObjectStoreRegistry({bucket: obstore.store.from_url(bucket)})

    vds = open_virtual_mfdataset(
        glob(args.src_glob),
        registry=registry,
        parser=NetCDF3Parser(skip_variables=args.skip_variables),
        data_vars=None,
        compat="override",
        coords="minimal",
    )
    vds = vds.vz.rename_paths(public_href)
    write_outputs(vds, outputs, args.src_glob, args.overwrite, args.message)
