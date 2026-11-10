# CLOUD-NES datasets

Build the CLOUD-NES benchmark datasets: convert existing raster, vector and tensor datasets to cloud-native
formats (COG, GeoParquet, Zarr, virtual Zarr) and catalogue them (STAC) on S3 object storage.

## Setup

Dependencies (including [just](https://github.com/casey/just)) are managed with [pixi](https://pixi.sh):

```bash
pixi install
pixi shell
```

S3 configuration is read from a `.env` file in the repository root (loaded automatically by `just`):

```shell
# s3fs, obstore, rustac, icechunk
AWS_ACCESS_KEY_ID="<YOUR-ACCESS-KEY-ID>"
AWS_SECRET_ACCESS_KEY="<YOUR-SECRET-ACCESS-KEY>"
AWS_ENDPOINT_URL="https://objectstore.surf.nl"
AWS_REGION="default"
# GDAL
AWS_S3_ENDPOINT="objectstore.surf.nl"
CPL_VSIL_USE_TEMP_FILE_FOR_RANDOM_WRITE="YES"
# target bucket (default: cloud-nes-benchmarks-tmp)
BUCKET="cloud-nes-benchmarks-tmp"
```

## Usage

```bash
just                                    # list datasets and their recipes
just ahn-dsm05                          # build all missing outputs of a dataset
just ahn-dsm05 cog 2000 LZW             # build one output
just --dry-run ahn-dsm05 vrt 400 LZW    # print the commands without running them
FORCE=1 just brp-2025 geoparquet 2.0 10000   # rebuild, even if the output exists
```

Outputs that already exist on S3 are skipped. Each dataset's `raw` recipe (or the comment above it) describes
how the source data is uploaded to the bucket.

## Layout

- `justfile`: one module per dataset.
- `lib.just`: shared variables (`bucket`, `FORCE`) and recipes (COG tiles/mosaic, VRT, STAC items, GeoParquet,
  URL upload), imported by every dataset.
- `datasets/<name>/justfile`: dataset paths, variants and custom steps.
- `scripts/`: Python scripts for the steps that are more than a single command (STAC, Zarr, virtual Zarr).

## Development

```bash
pixi run lint
```
