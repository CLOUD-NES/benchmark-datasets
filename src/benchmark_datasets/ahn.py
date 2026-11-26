"""Build the AHN (Actueel Hoogtebestand Nederland) benchmark datasets.

Prefixes are directories and can contain the placeholders {bucket}, {asset} and {version}. Outputs that
already exist are skipped, unless `overwrite` is set.
"""

import asyncio
import logging
import os
from itertools import product

import obstore
import rustac

from . import gdal, geozarr, virtual_zarr
from .s3 import S3Config, exists, glob, obstore_store

logger = logging.getLogger(__name__)

STAC_HREF_TEMPLATE = "https://raw.githubusercontent.com/cloud-nes/ahn-stac/main/data/AHN{version}.parquet"
PREFIX_ROOT = "s3://{bucket}/ahn"
PREFIX_VERSION = PREFIX_ROOT + "/{asset}/{version}"
PREFIX_RAW = PREFIX_VERSION + "/raw"
TIFF_GLOB = "*.[tT][iI][fF]"


def variant_name(creation_options: dict[str, str]) -> str:
    """Name of a COG variant from its creation options, e.g. COG-400-LERC_ZSTD-0.01.

    Values are sorted on the option keys, so the name doesn't depend on the order of the options.
    """
    return "-".join(["COG"] + [creation_options[key] for key in sorted(creation_options)])


def retrieve(
    assets: list[str],
    versions: list[int],
    bbox: list[float],
    prefix_dst: str | None = None,
    overwrite: bool = False,
    s3_config: S3Config | None = None,
) -> None:
    """Retrieve raw AHN tiles within a bounding box (WGS84) using the AHN STAC catalogs."""
    s3_config = s3_config or S3Config.from_env()
    for asset, version in product(assets, versions):
        dst_dir = _format(prefix_dst or PREFIX_RAW, asset, version, s3_config)
        items = asyncio.run(rustac.search(STAC_HREF_TEMPLATE.format(version=version), bbox=bbox))
        logger.info(f"AHN{version} {asset}: found {len(items)} items")
        dst_store = obstore_store(dst_dir, s3_config)
        for item in items:
            if asset not in item["assets"]:
                continue
            src_dir, filename = os.path.split(item["assets"][asset]["href"])
            if _skip(f"{dst_dir}/{filename}", overwrite, s3_config):
                continue
            resp = obstore.get(obstore_store(src_dir, s3_config), filename)
            obstore.put(dst_store, filename, resp)


def cog_tiles(
    assets: list[str],
    versions: list[int],
    creation_options: dict[str, str],
    prefix_src: str | None = None,
    prefix_dst: str | None = None,
    overwrite: bool = False,
    s3_config: S3Config | None = None,
) -> None:
    """Convert each raw tile to a COG."""
    s3_config = s3_config or S3Config.from_env()
    variant = variant_name(creation_options)
    for asset, version in product(assets, versions):
        src_dir = _format(prefix_src or PREFIX_RAW, asset, version, s3_config)
        dst_dir = _format(prefix_dst or PREFIX_VERSION, asset, version, s3_config) + f"/{variant}"
        for src in glob(f"{src_dir}/{TIFF_GLOB}", s3_config):
            dst = f"{dst_dir}/{os.path.basename(src)}"
            if not _skip(dst, overwrite, s3_config):
                gdal.cog_tile(src, dst, creation_options=creation_options, s3_config=s3_config)


def cog_mosaic(
    assets: list[str],
    versions: list[int],
    creation_options: dict[str, str],
    prefix_src: str | None = None,
    prefix_dst: str | None = None,
    overwrite: bool = False,
    s3_config: S3Config | None = None,
) -> None:
    """Mosaic the raw tiles into a single COG (N -> 1)."""
    s3_config = s3_config or S3Config.from_env()
    variant = variant_name(creation_options)
    for asset, version in product(assets, versions):
        src_dir = _format(prefix_src or PREFIX_RAW, asset, version, s3_config)
        dst = _format(prefix_dst or PREFIX_VERSION, asset, version, s3_config) + f"/{variant}-mosaic.tif"
        if not _skip(dst, overwrite, s3_config):
            srcs = _glob_tiffs(src_dir, s3_config)
            gdal.cog_mosaic(srcs, dst, creation_options=creation_options, s3_config=s3_config)


def vrt_mosaic(
    assets: list[str],
    versions: list[int],
    creation_options: dict[str, str],
    prefix_src: str | None = None,
    prefix_dst: str | None = None,
    overwrite: bool = False,
    s3_config: S3Config | None = None,
) -> None:
    """Mosaic the COG tiles of a variant (selected by its creation options) into a VRT (N -> 1)."""
    s3_config = s3_config or S3Config.from_env()
    variant = variant_name(creation_options)
    for asset, version in product(assets, versions):
        src_dir = _format(prefix_src or PREFIX_VERSION + f"/{variant}", asset, version, s3_config)
        dst = _format(prefix_dst or PREFIX_VERSION, asset, version, s3_config) + f"/{variant}-mosaic.vrt"
        if not _skip(dst, overwrite, s3_config):
            gdal.vrt_mosaic(_glob_tiffs(src_dir, s3_config), dst, s3_config=s3_config)


def virtual_zarr_store(
    assets: list[str],
    versions: list[int],
    creation_options: dict[str, str],
    mosaic: bool = False,
    output_formats: list[str] | None = None,
    prefix_src: str | None = None,
    prefix_dst: str | None = None,
    overwrite: bool = False,
    s3_config: S3Config | None = None,
) -> None:
    """Build one virtual Zarr store for the COG tiles (or mosaic) of a variant, with {asset}/{version} groups."""
    s3_config = s3_config or S3Config.from_env()
    variant = variant_name(creation_options) + ("-mosaic" if mosaic else "")
    dst_dir = _format(prefix_dst or PREFIX_ROOT, None, None, s3_config)
    extensions = {"kerchunk-json": "kerchunk.json", "kerchunk-parquet": "kerchunk.parquet", "icechunk": "icechunk"}
    outputs = {
        fmt: f"{dst_dir}/{variant}-vzarr-{extensions[fmt]}"
        for fmt in (output_formats or virtual_zarr.OUTPUT_FORMATS)
        if not _skip(f"{dst_dir}/{variant}-vzarr-{extensions[fmt]}", overwrite, s3_config)
    }
    if not outputs:
        return
    datasets = {}
    for asset, version in product(assets, versions):
        src_dir = _format(prefix_src or PREFIX_VERSION, asset, version, s3_config)
        srcs = [f"{src_dir}/{variant}.tif"] if mosaic else _glob_tiffs(f"{src_dir}/{variant}", s3_config)
        datasets[f"{asset}/{version}"] = virtual_zarr.open_virtual_tiffs(srcs, name=asset, s3_config=s3_config)
    virtual_zarr.write(datasets, outputs, s3_config=s3_config, message=f"add virtual references for {variant}")


def geozarr_store(
    assets: list[str],
    versions: list[int],
    creation_options: dict[str, str],
    chunks: int = 400,
    shards: int = 400,
    levels: list[int] | None = None,
    prefix_src: str | None = None,
    prefix_dst: str | None = None,
    overwrite: bool = False,
    s3_config: S3Config | None = None,
) -> None:
    """Build one GeoZarr store from the COG mosaics of a variant, with {asset}/{version} groups."""
    s3_config = s3_config or S3Config.from_env()
    variant = variant_name(creation_options)
    dst_dir = _format(prefix_dst or PREFIX_ROOT, None, None, s3_config)
    dst = f"{dst_dir}/geozarr-c-{chunks}-{chunks}-s-{shards}-{shards}.zarr"
    if _skip(dst, overwrite, s3_config):
        return
    for asset, version in product(assets, versions):
        src = _format(prefix_src or PREFIX_VERSION, asset, version, s3_config) + f"/{variant}-mosaic.tif"
        # ponytail: one variable per group, named after the asset; assets of one version could share a group
        geozarr.write({f"{asset}/{version}": src}, dst, asset, levels, chunks, shards, s3_config)


def stac(assets: list[str], versions: list[int], s3_config: S3Config | None = None) -> None:
    """Build STAC items/collections/catalogs (not implemented yet)."""
    logger.warning("STAC generation is not implemented yet, skipping")


def _format(prefix: str, asset: str | None, version: int | None, s3_config: S3Config) -> str:
    if "{bucket}" in prefix and not s3_config.bucket:
        raise ValueError("No bucket configured: set BUCKET or use --s3-bucket")
    return prefix.format(bucket=s3_config.bucket, asset=asset, version=version).rstrip("/")


def _glob_tiffs(prefix: str, s3_config: S3Config) -> list[str]:
    uris = glob(f"{prefix}/{TIFF_GLOB}", s3_config)
    if not uris:
        raise FileNotFoundError(f"No GeoTIFF found in {prefix}")
    return uris


def _skip(uri: str, overwrite: bool, s3_config: S3Config) -> bool:
    if not overwrite and exists(uri, s3_config):
        logger.info(f"Skipping {uri}: already exists")
        return True
    return False
