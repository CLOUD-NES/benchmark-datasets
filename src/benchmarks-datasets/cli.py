import logging

import click

from .s3 import S3Config


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
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    ctx.obj = S3Config.from_env(
        bucket=s3_bucket,
        endpoint_url=s3_endpoint_url,
        region=s3_region,
        access_key_id=s3_access_key_id,
        secret_access_key=s3_secret_access_key,
    )
