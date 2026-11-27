# Beeldmateriaal (BM) aerial images: `just bm` builds all outputs, `just bm <recipe>` a single step.
# Outputs that already exist are skipped. Set BUCKET to choose the bucket.

set dotenv-load

bbox := "5.085297 52.050390 5.197220 52.117516" # Utrecht (WGS84 lon/lat)
bench := "bench-data bm --asset RGB --year 2021 --year 2022 --year 2023 --year 2024 --year 2025 --year 2026 "

# COG variant (creation options)
co_jpeg := "--co BLOCKSIZE=512 --co COMPRESS=JPEG"

# build all BM outputs
[default]
all: retrieve cog-tiles cog-mosaic vrt-mosaic geozarr

# retrieve raw tiles within the bounding box
retrieve:
    {{ bench }} retrieve --bbox {{ bbox }}

# one COG per raw tile
cog-tiles: retrieve
    {{ bench }} cog-tiles {{ co_jpeg }}

# one COG mosaic of all raw tiles
cog-mosaic: retrieve
    {{ bench }} cog-mosaic {{ co_jpeg }}

# one VRT mosaic of all COG tiles
vrt-mosaic: cog-tiles
    {{ bench }} vrt-mosaic {{ co_jpeg }}

# one GeoZarr store (JPEG) per year
geozarr: cog-mosaic
    {{ bench }} geozarr {{ co_jpeg }} --chunks 512 --shards 4096 --level 2 --level 4 --level 8

# STAC items, collections and catalogs
stac:
    {{ bench }} stac