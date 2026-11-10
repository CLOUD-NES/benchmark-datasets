# Shared variables and recipes, imported by every dataset justfile.
#
# Outputs are skipped if they already exist on S3; set FORCE=1 to rebuild them.
# Set BUCKET to choose the bucket, e.g. BUCKET=cloud-nes-benchmarks (in .env or per command).

set dotenv-load

scripts := source_directory() / "scripts"
s3 := "python " + scripts / "s3.py"
bucket := "s3://" + env("BUCKET", "cloud-nes-benchmarks-tmp")
force := env("FORCE", "")

# `{{skip}} DST || cmd` runs cmd only if DST is missing (or FORCE is set)
skip := if force == "" { s3 + " exists" } else { "false" }
overwrite := if force == "" { "" } else { "--overwrite" }

# N → N: one COG per source file
[private]
cog-tiles src_glob dst_dir blocksize="512" compress="LZW" bigtiff="NO":
    #!/usr/bin/env bash
    set -euo pipefail
    for src in $({{s3}} ls "{{src_glob}}"); do
      dst="{{dst_dir}}/$(basename "$src")"
      {{skip}} "$dst" && continue
      gdal raster translate --output-format COG --overwrite \
        --co BLOCKSIZE={{blocksize}} --co COMPRESS={{compress}} --co BIGTIFF={{bigtiff}} \
        "/vsis3/${src#s3://}" "/vsis3/${dst#s3://}"
    done

# N → 1: COG mosaic
[private]
cog-mosaic src_glob dst blocksize="512" compress="LZW" bigtiff="NO":
    {{skip}} "{{dst}}" || gdal raster mosaic --output-format COG --overwrite \
      --co BLOCKSIZE={{blocksize}} --co COMPRESS={{compress}} --co BIGTIFF={{bigtiff}} \
      $({{s3}} ls --vsi "{{src_glob}}") "{{replace(dst, 's3://', '/vsis3/')}}"

# N → 1: VRT mosaic
[private]
vrt-mosaic src_glob dst:
    {{skip}} "{{dst}}" || gdal raster mosaic --output-format VRT --overwrite \
      $({{s3}} ls --vsi "{{src_glob}}") "{{replace(dst, 's3://', '/vsis3/')}}"

# N → 1: STAC items (rio-stac) as stac-geoparquet, with public HTTPS asset hrefs
[private]
stac-items src_glob dst media_type="image/tiff; application=geotiff; profile=cloud-optimized":
    {{skip}} "{{dst}}" || python {{scripts}}/stac_items.py --public-hrefs --asset-media-type "{{media_type}}" \
      "{{src_glob}}" "{{dst}}"

# 1 → 1: vector file to GeoParquet
[private]
to-geoparquet src dst version="1.1" row_group_size="100000":
    {{skip}} "{{dst}}" || gpio convert geoparquet --geoparquet-version {{version}} --row-group-size {{row_group_size}} \
      "{{src}}" "{{dst}}"

# Upload (stream) each URL listed in a text file to dst_dir
[private]
upload-urls url_file dst_dir:
    #!/usr/bin/env bash
    set -euo pipefail
    while IFS= read -r url || [[ -n "$url" ]]; do
      [[ -z "$url" ]] && continue
      dst="{{dst_dir}}/$(basename "$url")"
      {{skip}} "$dst" && continue
      gdal vsi copy "/vsicurl/$url" "/vsis3/${dst#s3://}"
    done < "{{url_file}}"
