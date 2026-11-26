import os
from urllib.parse import urlsplit

from .s3 import S3Config
from .shell import run_cmd


def cog_tile(src: str, dst: str, creation_options: dict[str, str] | None = None, s3_config: S3Config | None = None):
    """Convert one raster to a COG (1 -> 1)."""
    _raster("translate", "COG", [src], dst, creation_options, s3_config)


def cog_mosaic(
    src: list[str], dst: str, creation_options: dict[str, str] | None = None, s3_config: S3Config | None = None
):
    """Mosaic rasters into a single COG (N -> 1)."""
    _raster("mosaic", "COG", src, dst, creation_options, s3_config)


def vrt_mosaic(src: list[str], dst: str, s3_config: S3Config | None = None) -> None:
    """Mosaic rasters into a single VRT (N -> 1)."""
    _raster("mosaic", "VRT", src, dst, None, s3_config)


def _raster(
    cmd: str,
    output_format: str,
    src: list[str],
    dst: str,
    creation_options: dict[str, str] | None,
    s3_config: S3Config | None,
) -> None:
    if not urlsplit(dst).scheme:  # local output: GDAL doesn't create parent directories
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    args = ["gdal", "raster", cmd, "--output-format", output_format, "--overwrite"]
    for key, value in (creation_options or {}).items():
        args += ["--co", f"{key}={value}"]
    args += [to_vsi_uri(s) for s in src] + [to_vsi_uri(dst)]
    run_cmd(args, env=gdal_env(s3_config))


def gdal_env(s3_config: S3Config | None) -> dict[str, str]:
    """GDAL configuration options (as environment variables) to read/write from S3."""
    s3_config = s3_config or S3Config.from_env()
    env = {
        "CPL_VSIL_USE_TEMP_FILE_FOR_RANDOM_WRITE": "YES",
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "AWS_VIRTUAL_HOSTING": "FALSE",
        "AWS_NO_SIGN_REQUEST": "YES" if s3_config.is_anonymous else "NO",
    }
    optional = {
        "AWS_ACCESS_KEY_ID": s3_config.access_key_id,
        "AWS_SECRET_ACCESS_KEY": s3_config.secret_access_key,
        "AWS_REGION": s3_config.region,
        "AWS_S3_ENDPOINT": s3_config.endpoint_url if s3_config.endpoint_url else None,
    }
    return env | {k: v for k, v in optional.items() if v is not None}


def to_vsi_uri(uri: str) -> str:
    """Normalize URI using GDAL virtual filesystem notation."""
    split = urlsplit(uri)
    if split.scheme == "s3":
        return f"/vsis3/{split.netloc}{split.path}"
    if split.scheme in ("http", "https"):
        return f"/vsicurl/{uri}"
    return uri
