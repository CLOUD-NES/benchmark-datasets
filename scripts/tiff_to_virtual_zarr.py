"""Build a virtual Zarr store from a set of (Cloud-Optimized) GeoTIFF tiles.

Adapted from https://github.com/CLOUD-NES/ahn-virtual-zarr (notebooks/build-virtual-zarr-dsm.ipynb).
Only the highest resolution (first IFD) is referenced. Each output is skipped if it already exists,
unless --overwrite is given.

    python tiff_to_virtual_zarr.py SRC_GLOB [--json DST] [--parquet DST] [--icechunk DST] [--overwrite]
"""

import argparse
from urllib.parse import urlsplit

import numpy as np
import obstore
import xarray
from obspec_utils.registry import ObjectStoreRegistry
from virtual_tiff import VirtualTIFF
from virtualizarr import open_virtual_dataset

from common import missing_outputs, public_href, write_outputs
from s3 import glob


def _generate_coords(attrs, shape):
    """Produce coordinate arrays from the GeoTIFF tags (virtual-tiff does not parse coordinates).

    Adapted from kerchunk: https://github.com/fsspec/kerchunk/blob/3cd5ddc/kerchunk/tiff.py#L110
    """
    height, width = shape[-2:]
    xscale, yscale, zscale = attrs["model_pixel_scale"][:3]
    x0, y0, z0 = attrs["model_tiepoint"][3:6]
    out = {
        "x": np.arange(width) * xscale + x0 + xscale / 2,
        "y": np.arange(height) * -yscale + y0 - yscale / 2,
    }
    if len(shape) > 2:
        out["z"] = np.arange(shape[-3]) * zscale + z0 + zscale / 2
    return out


def open_virtual_tiff(path, registry, parser):
    ds = open_virtual_dataset(path, registry=registry, parser=parser)
    return ds.assign_coords(_generate_coords(ds["0"].attrs, ds["0"].shape))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("src_glob")
    parser.add_argument("--json")
    parser.add_argument("--parquet")
    parser.add_argument("--icechunk")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--message", default="add virtual references")
    args = parser.parse_args()

    outputs = missing_outputs({"json": args.json, "parquet": args.parquet, "icechunk": args.icechunk}, args.overwrite)
    if not outputs:
        raise SystemExit(0)

    bucket = f"s3://{urlsplit(args.src_glob).netloc}"
    registry = ObjectStoreRegistry({bucket: obstore.store.from_url(bucket)})
    tiff_parser = VirtualTIFF(ifd=0)

    vds = [open_virtual_tiff(path, registry, tiff_parser) for path in glob(args.src_glob)]
    vds = xarray.combine_by_coords(vds, join="outer", combine_attrs="drop_conflicts")
    vds = vds.vz.rename_paths(public_href)
    write_outputs(vds, outputs, args.src_glob, args.overwrite, args.message)
