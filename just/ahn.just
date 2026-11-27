# Actueel Hoogtebestand Nederland (AHN): `just ahn` builds all outputs, `just ahn <recipe>` a single step.
# Outputs that already exist are skipped: set FORCE=1 to rebuild them. Set BUCKET to choose the bucket.

set dotenv-load

bbox := "5.085297 52.050390 5.197220 52.117516" # Utrecht (WGS84 lon/lat)
bench := "bench-data ahn --asset DSM05 --version 2 --version 3 --version 4 --version 5 --version 6"

# COG variants (creation options)
co_zstd := "--co BLOCKSIZE=400 --co COMPRESS=ZSTD"
co_lerc := "--co BLOCKSIZE=400 --co COMPRESS=LERC_ZSTD --co MAX_Z_ERROR=0.01"

# build all AHN outputs
[default]
all: retrieve cog-tiles cog-mosaic vrt-mosaic virtual-zarr geozarr stac

# retrieve raw tiles within the bounding box
retrieve:
    {{ bench }} retrieve --bbox {{ bbox }}

# one COG per raw tile
cog-tiles: retrieve
    {{ bench }} cog-tiles {{ co_zstd }}
    {{ bench }} cog-tiles {{ co_lerc }}

# one COG mosaic of all raw tiles
cog-mosaic: retrieve
    {{ bench }} cog-mosaic {{ co_zstd }}
    {{ bench }} cog-mosaic {{ co_lerc }}

# one VRT mosaic of all COG tiles
vrt-mosaic: cog-tiles
    {{ bench }} vrt-mosaic {{ co_zstd }}
    {{ bench }} vrt-mosaic {{ co_lerc }}

# virtual Zarr stores (kerchunk JSON/Parquet, Icechunk) of COG tiles and mosaics
virtual-zarr: cog-tiles cog-mosaic
    {{ bench }} virtual-zarr {{ co_zstd }}
    {{ bench }} virtual-zarr {{ co_zstd }} --mosaic

# GeoZarr store
geozarr: cog-mosaic
    {{ bench }} geozarr {{ co_zstd }} --chunks 400 --shards 4000 --level 2 --level 4 --level 8

# STAC items, collections and catalogs
stac:
    {{ bench }} stac
