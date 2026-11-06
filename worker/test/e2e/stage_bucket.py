"""Run the REAL newsbot.r2.upload against a fake S3 client and record what it would write to R2.

usage: stage_bucket.py STORE_DIR [KEY_PREFIX]
Renders 10 real 6 s MPEG-TS segments with ffmpeg (site/test/make_stream.sh), builds manifest.json with the real
newsbot.manifest.build_manifest, then calls newsbot.r2.upload(out, prefix). Every put is stored as STORE_DIR/<key>;
STORE_DIR/_puts.json lists [{key, content_type}] in upload order. No network, no credentials.
"""
import json, os, subprocess, sys, tempfile, types
from pathlib import Path

repo = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo))
store = Path(sys.argv[1]); store.mkdir(parents=True, exist_ok=True)
prefix = sys.argv[2] if len(sys.argv) > 2 else "bulletins/20261106T120000Z"

out = Path(tempfile.mkdtemp(prefix="bulletin-"))
subprocess.run(["bash", str(repo / "site/test/make_stream.sh"), str(out)], check=True, capture_output=True)
from newsbot import manifest, r2  # noqa: E402
manifest.build_manifest(out, {"generated_by": "e2e", "stories": []}, [])

puts = []
class FakeS3:
    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        dest = store / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(filename).read_bytes())
        puts.append({"key": key, "content_type": (ExtraArgs or {}).get("ContentType")})

fake = types.ModuleType("boto3"); fake.client = lambda *a, **k: FakeS3()
sys.modules["boto3"] = fake
for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
    os.environ.setdefault(k, "fake")
n = r2.upload(out, prefix)
(store / "_puts.json").write_text(json.dumps({"prefix": prefix, "puts": puts}, indent=1))
print(f"uploaded {n} objects under {prefix}/")
