from collections.abc import Generator
from contextlib import contextmanager
from urllib.parse import urlsplit

import rasterio

from .s3 import S3Config
from .shell import run_cmd


def cog_tile(
    src: str,
    dst: str,
    creation_options: dict[str, str] | None = None,
    s3_config: S3Config | None = None,
) -> None:
    _raster(
        cmd="translate",
        format="COG",
        src= _to_vsi_uri(src),
        dst=_to_vsi_uri(dst),
        creation_options=creation_options,
        s3_config=s3_config,
    )


def cog_mosaic(
    src: list[str],
    dst: str,
    creation_options: dict[str, str] | None = None,
    s3_config: S3Config | None = None,
) -> None:
    _raster(
        cmd="mosaic",
        format="COG",
        src=" ".join([_to_vsi_uri(el) for el in src]),
        dst=_to_vsi_uri(dst),
        creation_options=creation_options,
        s3_config=s3_config,
    )


def vrt_mosaic(
    src: list[str],
    dst: str,
    s3_config: S3Config | None = None,
) -> None:
    _raster(
        cmd="mosaic",
        format="VRT",
        src=" ".join([_to_vsi_uri(el) for el in src]),
        dst=_to_vsi_uri(dst),
        s3_config=s3_config,
    )


def _raster(
    cmd: str,
    format: str,
    src: str,
    dst: str,
    creation_options: dict[str, str] | None = None,
    s3_config: S3Config | None = None,
) -> None:
    creation_options = creation_options if creation_options else {}

    cmd = f"gdal raster {cmd} --output-format {format} --overwrite"
    for key, value in creation_options.items():
        cmd += f"--co {key}={value} "
    cmd += f"{src} {dst}"

    with _env(s3_config):
        run_cmd(cmd)


@contextmanager
def _env(s3_config: S3Config | None) -> Generator[None]:
    s3_config = s3_config if s3_config else S3Config.from_env()
    env = {
        "CPL_VSIL_USE_TEMP_FILE_FOR_RANDOM_WRITE": "YES",
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "AWS_VIRTUAL_HOSTING": False,
        "AWS_NO_SIGN_REQUEST": "YES" if s3_config.is_anonymous else "NO",
    }
    if s3_config.access_key_id is not None:
        env["aws_access_key_id"] = s3_config.access_key_id
    if s3_config.secret_access_key is not None:
        env["aws_secret_access_key"] = s3_config.secret_access_key
    if s3_config.region is not None:
        env["AWS_REGION"] = s3_config.region
    if s3_config.endpoint_url is not None:
        env["AWS_S3_ENDPOINT"] = s3_config.endpoint_url

    with rasterio.Env(**env):
        yield


def _to_vsi_uri(uri: str) -> str:
    """Normalize URI using GDAL virtual filesystem notation."""
    split = urlsplit(uri)
    if split.scheme == "s3":
        return "/".join(["/vsis3", split.netloc, split.path])
    elif split.scheme.startswith("http"):
        return "/".join(["/vsicurl", f"{split.scheme}:/", split.netloc, split.path])
    elif not split.scheme:
        return split.path
    else:
        return uri
