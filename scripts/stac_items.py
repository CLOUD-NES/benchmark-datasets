"""Create one STAC item per raster file with rio-stac and save them as a stac-geoparquet file.

python stac_items.py [--public-hrefs] [--asset-media-type TYPE] SRC_GLOB DST
"""

import argparse
import os

import obstore
import rio_stac
import rustac

from common import public_href
from s3 import glob

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("src_glob")
    parser.add_argument("dst")
    parser.add_argument("--public-hrefs", action="store_true", help="use HTTPS hrefs for the assets")
    parser.add_argument("--asset-media-type")
    args = parser.parse_args()

    items = []
    for src in glob(args.src_glob):
        href = public_href(src) if args.public_hrefs else None
        item = rio_stac.create_stac_item(source=src, asset_href=href, asset_media_type=args.asset_media_type)
        items.append(item.to_dict())

    dst_base, filename = os.path.split(args.dst)
    rustac.write_sync(href=filename, value=items, store=obstore.store.from_url(dst_base))
