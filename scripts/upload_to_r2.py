#!/usr/bin/env python3
"""Upload converted Markdown books to a Cloudflare R2 bucket, idempotently.

A local manifest (r2_manifest.json) records every uploaded object with its R2
key, size, sha256 and upload timestamp. On each run only files that are NEW or
CHANGED (sha256 differs) are uploaded; everything already in the manifest is
skipped. That's how later conversions get separated from what's already pushed.

Credentials are read from the environment (never hard-coded):
    R2_ACCOUNT_ID          Cloudflare account id (used to build the endpoint)
    R2_ACCESS_KEY_ID       R2 API token access key id
    R2_SECRET_ACCESS_KEY   R2 API token secret
    R2_BUCKET              target bucket name
Optional:
    R2_PREFIX              key prefix inside the bucket (default: "books")

Usage:
    .venv/bin/python upload_to_r2.py            # upload new/changed files
    .venv/bin/python upload_to_r2.py --dry-run  # show what WOULD upload
"""
import os
import sys
import json
import hashlib
import datetime
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "data" / "converted"
MANIFEST = ROOT / "index" / "r2_manifest.json"


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def main():
    dry = "--dry-run" in sys.argv

    files = sorted(p for p in SRC_ROOT.rglob("*.md"))
    if not files:
        print(f"No .md files under {SRC_ROOT}/")
        return

    manifest = load_manifest()
    prefix = os.environ.get("R2_PREFIX", "books").strip("/")

    # Decide what needs uploading.
    todo, skip = [], []
    for f in files:
        rel = f.relative_to(SRC_ROOT).as_posix()
        digest = sha256(f)
        entry = manifest.get(rel)
        if entry and entry.get("sha256") == digest:
            skip.append(rel)
        else:
            key = f"{prefix}/{rel}" if prefix else rel
            todo.append((f, rel, key, digest))

    print(f"{len(files)} local file(s): {len(skip)} already uploaded, "
          f"{len(todo)} new/changed.")
    for _, rel, key, _ in todo:
        print(f"  -> {rel}   (r2 key: {key})")
    if not todo:
        print("Nothing to upload. Bucket is in sync with converted/.")
        return
    if dry:
        print("\n[dry-run] No upload performed.")
        return

    # Need credentials only when actually uploading.
    required = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"\nMissing env vars: {', '.join(missing)}")
        print("Set them (see the docstring) and re-run.")
        sys.exit(1)

    import boto3
    from botocore.config import Config

    account = os.environ["R2_ACCOUNT_ID"]
    bucket = os.environ["R2_BUCKET"]
    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for f, rel, key, digest in todo:
        size = f.stat().st_size
        s3.upload_file(
            str(f), bucket, key,
            ExtraArgs={"ContentType": "text/markdown; charset=utf-8"},
        )
        manifest[rel] = {
            "key": key, "bucket": bucket, "size": size,
            "sha256": digest, "uploaded_at": now,
        }
        print(f"  uploaded {rel}  ({size // 1024} KB)")
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(f"\nDone. {len(todo)} file(s) uploaded to "
          f"r2://{bucket}/{prefix}. Manifest: {MANIFEST}")


if __name__ == "__main__":
    main()
