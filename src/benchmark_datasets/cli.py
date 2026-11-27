import asyncio
import logging
from dataclasses import dataclass

import click

from . import ahn as _ahn
from .s3 import S3Config
from .virtual_zarr import OUTPUT_FORMATS

PREFIX_HELP = "Placeholders {bucket}, {asset} and {version} are filled in."


@dataclass
class AHNContext:
    """Options shared by all AHN commands."""

    s3_config: S3Config
    assets: list[str]
    versions: list[int]
    overwrite: bool

    def kwargs(self) -> dict:
        """Keyword arguments common to all functions in the ahn module."""
        return {"assets": self.assets, "versions": self.versions, "s3_config": self.s3_config}


def _parse_creation_options(ctx, param, values: tuple[str, ...]) -> dict[str, str]:
    options = {}
    for value in values:
        key, sep, val = value.partition("=")
        if not sep or not key or not val:
            raise click.BadParameter(f"expected KEY=VALUE, got {value!r}")
        options[key.upper()] = val
    return options


creation_options = click.option(
    "--co",
    "creation_options",
    multiple=True,
    required=True,
    callback=_parse_creation_options,
    metavar="KEY=VALUE",
    help="GDAL COG creation option, can be repeated. Also defines the variant name (e.g. COG-400-ZSTD).",
)
prefix_src = click.option("--prefix-src", help=f"Prefix of the input data. {PREFIX_HELP}")
prefix_dst = click.option("--prefix-dst", help=f"Prefix of the output data. {PREFIX_HELP}")


@click.group()
@click.version_option()
@click.option("--s3-bucket")
@click.option("--s3-endpoint-url")
@click.option("--s3-region")
@click.option("--s3-access-key-id")
@click.option("--s3-secret-access-key")
@click.option("--debug", is_flag=True, default=False, help="Print debug logs.")
@click.pass_context
def cli(
    ctx,
    s3_bucket: str | None,
    s3_endpoint_url: str | None,
    s3_region: str | None,
    s3_access_key_id: str | None,
    s3_secret_access_key: str | None,
    debug: bool = False,
) -> None:
    """Set up and run data access benchmarks."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    ctx.obj = S3Config.from_env(
        bucket=s3_bucket,
        endpoint_url=s3_endpoint_url,
        region=s3_region,
        access_key_id=s3_access_key_id,
        secret_access_key=s3_secret_access_key,
    )


@cli.group()
@click.option("--asset", "assets", multiple=True, required=True, help="AHN asset (e.g. DSM05), can be repeated.")
@click.option(
    "--version",
    "versions",
    multiple=True,
    required=True,
    type=click.IntRange(2, 6),
    help="AHN version, can be repeated.",
)
@click.option("--overwrite", is_flag=True, help="Rebuild outputs that already exist.")
@click.pass_context
def ahn(ctx, assets: tuple[str, ...], versions: tuple[int, ...], overwrite: bool) -> None:
    """Actueel Hoogtebestand Nederland (AHN)."""
    ctx.obj = AHNContext(ctx.obj, list(assets), list(versions), overwrite)


@ahn.command()
@click.option(
    "--bbox", nargs=4, type=float, required=True, metavar="MINX MINY MAXX MAXY", help="Bounding box (WGS84 lon/lat)."
)
@prefix_dst
@click.pass_obj
def retrieve(obj: AHNContext, bbox: tuple[float, ...], prefix_dst: str | None) -> None:
    """Retrieve raw tiles within a bounding box from the AHN STAC catalog."""
    asyncio.run(_ahn.retrieve(**obj.kwargs(), bbox=list(bbox), prefix_dst=prefix_dst, overwrite=obj.overwrite))


@ahn.command()
@creation_options
@prefix_src
@prefix_dst
@click.pass_obj
def cog_tiles(obj: AHNContext, creation_options: dict, prefix_src: str | None, prefix_dst: str | None) -> None:
    """Convert each raw tile to a COG."""
    _ahn.cog_tiles(
        **obj.kwargs(),
        creation_options=creation_options,
        prefix_src=prefix_src,
        prefix_dst=prefix_dst,
        overwrite=obj.overwrite,
    )


@ahn.command()
@creation_options
@prefix_src
@prefix_dst
@click.pass_obj
def cog_mosaic(obj: AHNContext, creation_options: dict, prefix_src: str | None, prefix_dst: str | None) -> None:
    """Mosaic the raw tiles into a single COG."""
    _ahn.cog_mosaic(
        **obj.kwargs(),
        creation_options=creation_options,
        prefix_src=prefix_src,
        prefix_dst=prefix_dst,
        overwrite=obj.overwrite,
    )


@ahn.command()
@creation_options
@prefix_src
@prefix_dst
@click.pass_obj
def vrt_mosaic(obj: AHNContext, creation_options: dict, prefix_src: str | None, prefix_dst: str | None) -> None:
    """Mosaic the COG tiles of the variant defined by the creation options into a VRT."""
    _ahn.vrt_mosaic(
        **obj.kwargs(),
        creation_options=creation_options,
        prefix_src=prefix_src,
        prefix_dst=prefix_dst,
        overwrite=obj.overwrite,
    )


@ahn.command()
@creation_options
@click.option("--mosaic", is_flag=True, help="Reference the COG mosaics instead of the COG tiles.")
@click.option(
    "--format",
    "output_formats",
    multiple=True,
    type=click.Choice(OUTPUT_FORMATS),
    help="Output format, can be repeated (default: all).",
)
@prefix_src
@prefix_dst
@click.pass_obj
def virtual_zarr(
    obj: AHNContext,
    creation_options: dict,
    mosaic: bool,
    output_formats: tuple[str, ...],
    prefix_src: str | None,
    prefix_dst: str | None,
) -> None:
    """Build one virtual Zarr store from the COGs of the given variant (assets as variables, versions as dim)."""
    _ahn.virtual_zarr_store(
        **obj.kwargs(),
        creation_options=creation_options,
        mosaic=mosaic,
        output_formats=list(output_formats) or None,
        prefix_src=prefix_src,
        prefix_dst=prefix_dst,
        overwrite=obj.overwrite,
    )


@ahn.command()
@creation_options
@click.option("--chunks", type=int, default=400, show_default=True, help="Chunk size (x and y).")
@click.option("--shards", type=int, default=400, show_default=True, help="Shard size (x and y).")
@click.option("--level", "levels", type=int, multiple=True, help="Downsampling factor of an overview, can be repeated.")
@prefix_src
@prefix_dst
@click.pass_obj
def geozarr(
    obj: AHNContext,
    creation_options: dict,
    chunks: int,
    shards: int,
    levels: tuple[int, ...],
    prefix_src: str | None,
    prefix_dst: str | None,
) -> None:
    """Build one GeoZarr store from the COG mosaics of the given variant (assets as variables, versions as dim)."""
    _ahn.geozarr_store(
        **obj.kwargs(),
        creation_options=creation_options,
        chunks=chunks,
        shards=shards,
        levels=list(levels),
        prefix_src=prefix_src,
        prefix_dst=prefix_dst,
        overwrite=obj.overwrite,
    )


@ahn.command()
@click.pass_obj
def stac(obj: AHNContext) -> None:
    """Build STAC items, collections and catalogs (not implemented yet)."""
    _ahn.stac(**obj.kwargs())
