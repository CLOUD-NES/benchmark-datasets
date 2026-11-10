"""Minimal S3 helpers for the justfile recipes.

    python s3.py exists URI      exit code 0 if the object (or prefix) exists
    python s3.py ls [--vsi] GLOB print matching URIs, one per line (/vsis3/... with --vsi)

Credentials and endpoint are read from the environment (AWS_* variables).
"""

import argparse
import sys

import fsspec


def glob(pattern: str, vsi: bool = False) -> list[str]:
    prefix = "/vsis3/" if vsi else "s3://"
    return [prefix + path for path in sorted(fsspec.filesystem("s3").glob(pattern))]


def exists(uri: str) -> bool:
    return fsspec.filesystem("s3").exists(uri)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("exists").add_argument("uri")
    ls = sub.add_parser("ls")
    ls.add_argument("pattern")
    ls.add_argument("--vsi", action="store_true")
    args = parser.parse_args()

    if args.cmd == "exists":
        sys.exit(0 if exists(args.uri) else 1)
    print("\n".join(glob(args.pattern, args.vsi)))
