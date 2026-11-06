"""Optional upload to Cloudflare R2 (S3 API). Only called when all R2 secrets exist; never logs them."""
from __future__ import annotations

import os
from pathlib import Path


def r2_configured() -> bool:
    need = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    return all(os.environ.get(k) for k in need)


def upload(out: Path, prefix: str) -> int:
    import boto3
    s3 = boto3.client("s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                      aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    n = 0
    for p in sorted(out.iterdir()):
        if p.suffix in (".ts", ".json", ".m3u8"):
            ct = {".ts": "video/mp2t", ".json": "application/json", ".m3u8": "application/vnd.apple.mpegurl"}[p.suffix]
            s3.upload_file(str(p), os.environ["R2_BUCKET"], f"{prefix}/{p.name}", ExtraArgs={"ContentType": ct})
            n += 1
    return n
