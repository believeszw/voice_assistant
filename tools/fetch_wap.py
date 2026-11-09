"""下载并解压 webrtc-audio-processing sdist（pip 的 metadata 构建会失败，绕过它）。"""
import io
import json
import os
import tarfile
import urllib.request

DEST = os.path.join("tools", "wap_src")
os.makedirs(DEST, exist_ok=True)

with urllib.request.urlopen(
        "https://pypi.org/pypi/webrtc-audio-processing/0.1.3/json", timeout=60) as r:
    meta = json.load(r)
url = None
for f in meta["urls"]:
    if f["filename"].endswith(".tar.gz"):
        url = f["url"]
        break
print("tarball:", url)
with urllib.request.urlopen(url, timeout=120) as r:
    data = r.read()
print("bytes:", len(data))
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
    tf.extractall(DEST)
print("extracted to", DEST)
for name in sorted(os.listdir(DEST)):
    print(" ", name)
