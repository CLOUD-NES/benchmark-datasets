# Beeldmateriaal (BM) aerial images: `just bm` builds all outputs, `just bm <recipe>` a single step.
# Outputs that already exist are skipped: set FORCE=1 to rebuild them. Set BUCKET to choose the bucket.

set dotenv-load

overwrite := if env("FORCE", "") == "" { "" } else { "--overwrite" }
bbox := "5.085297 52.050390 5.197220 52.117516" # Utrecht (WGS84 lon/lat)
rgb := "bench-data bm --asset RGB --year 2021 --year 2022 --year 2023 --year 2024 --year 2025 --year 2026 " + overwrite
cir := "bench-data bm --asset CIR --year 2025 --year 2026 " + overwrite # CIR only available from 2025

# COG variant (creation options)
co_jpeg := "--co BLOCKSIZE=512 --co COMPRESS=JPEG"
zarr := co_jpeg + " --chunks 512 --shards 4096 --level 2 --level 4 --level 8"

# build all BM outputs
[default]
all: retrieve cog-tiles cog-mosaic vrt-mosaic geozarr

# retrieve raw tiles within the bounding box
retrieve:
    {{ rgb }} retrieve --bbox {{ bbox }}
    {{ cir }} retrieve --bbox {{ bbox }}

# one COG per raw tile
cog-tiles: retrieve
    {{ rgb }} cog-tiles {{ co_jpeg }}
    {{ cir }} cog-tiles {{ co_jpeg }}

# one COG mosaic of all raw tiles
cog-mosaic: retrieve
    {{ rgb }} cog-mosaic {{ co_jpeg }}
    {{ cir }} cog-mosaic {{ co_jpeg }}

# one VRT mosaic of all COG tiles
vrt-mosaic: cog-tiles
    {{ rgb }} vrt-mosaic {{ co_jpeg }}
    {{ cir }} vrt-mosaic {{ co_jpeg }}

# one GeoZarr store (JPEG) per year: RGB for 2021-2024, RGB and CIR for 2025-2026
geozarr: cog-mosaic
    bench-data bm --asset RGB --year 2021 --year 2022 --year 2023 --year 2024 {{ overwrite }} geozarr {{ zarr }}
    bench-data bm --asset RGB --asset CIR --year 2025 --year 2026 {{ overwrite }} geozarr {{ zarr }}
