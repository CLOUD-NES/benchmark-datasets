import os
from typing import Any

from . import gdal
from .s3 import S3Config, exists, glob

TEMPLATE_PREFIX_ROOT = "ahn/{asset}/{version}/"


def retrieve(
    asset: str,
    version: int,
    bbox: list[float],
    prefix: str | None = None,
    s3_config: S3Config | None = None,
) -> None:
    """Retrieve raw AHN data products to the object store.

    Args:
        version (int): AHN version (between 2 and 6).
        asset (str): name of the asset file.
        bbox (list[float]): only retrieve data within the given bounding box.
        prefix (str | None, optional): Custom prefix for the dataset. Defaults to None.
        s3_config (S3Config | None, optional): S3 configuration options and credentials. Defaults to None.
    """
    prefix = prefix if prefix else _get_default_prefix(version, asset)
    tiles = search(version, asset, bbox)
    return stream_to_s3(tiles, prefix, s3_config, s3_config=s3_config)


def cog_tiles(
    asset: str,
    version: int,
    prefix_src: str | None = None,
    prefix_dst: str | None = None,
    creation_options: dict | None = None,
    s3_config: S3Config | None = None,
):
    creation_options = creation_options if creation_options else {}
    prefix_src = prefix_src if prefix_src else _get_default_prefix(version, asset)
    prefix_dst = prefix_dst if prefix_dst else _get_default_prefix(version, asset)
    for tile_src_uri in glob(prefix_src, s3_config):
        tile_dst_uri = "/".join([prefix_dst, os.path.basename(tile_src)])
        if not exists(tile_dst_uri, s3_config):
            gdal.cog_tile(tile_src_uri, tile_dst_uri, creation_options=creation_options, s3_config=s3_config)


def cog_mosaic(
    asset: str,
    version: int,
    prefix_src: str | None = None,
    prefix_dst: str | None = None,
    creation_options: dict | None = None,
    s3_config: S3Config | None = None,
) -> None:
    creation_options = creation_options if creation_options else {}
    prefix_src = prefix_src if prefix_src else _get_default_prefix(version, asset)
    prefix_dst = prefix_dst if prefix_dst else _get_default_prefix(version, asset)
    tile_dst_uri = "/".join([prefix_dst, "COG-mosaic.TIF"]) # TODO
    if not exists(tile_dst_uri, s3_config):
        tile_src_uris = glob(prefix_src, s3_config)
        gdal.cog_mosaic(tile_src_uris, tile_dst_uri, creation_options=creation_options, s3_config=s3_config)


def vrt_mosaic(
    asset: str,
    version: int,
    prefix_src: str | None = None,
    prefix_dst: str | None = None,
    s3_config: S3Config | None = None,
) -> None:
    prefix_src = prefix_src if prefix_src else _get_default_prefix(version, asset)
    prefix_dst = prefix_dst if prefix_dst else _get_default_prefix(version, asset)
    tile_dst_uri = "/".join([prefix_dst, "COG-mosaic.TIF"]) # TODO
    if not exists(tile_dst_uri, s3_config):
        tile_src_uris = glob(prefix_src, s3_config)
        gdal.vrt_mosaic(tile_src_uris, tile_dst_uri, s3_config=s3_config)


def virtual_zarr(
    asset: str,
    versions: list[int] | None = None,
    prefix_src: str | None = None,
    prefix_dst: str | None = None,
    kerchunk_json: bool = True,
    kerchunk_parquet: bool = True,
    icechunk: bool = True,
    s3_config: S3Config | None = None,
) -> None:
    prefix_src = prefix_src if prefix_src else _get_default_prefix(version, asset)
    prefix_dst = prefix_dst if prefix_dst else _get_default_prefix(version, asset)


def _get_default_prefix(version: int, asset: str, **extra: dict[str, Any]) -> str:
    return ""
