"""Resumable, hash-verified HTTPS downloads for the local GPU setup."""

import concurrent.futures
import hashlib
import shutil
import time
import urllib.request
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(url, target, expected_hash, size=None):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and digest(target) == expected_hash:
        return target
    if size is None:
        for attempt in range(8):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as response:
                    size = int(response.headers["Content-Length"])
                break
            except Exception:
                if attempt == 7:
                    raise
                time.sleep(2)
    part_dir = target.with_name(target.name + ".parts")
    part_dir.mkdir(exist_ok=True)
    chunk = 16 * 2**20

    def part(index):
        start = index * chunk
        end = min(size, start + chunk) - 1
        path = part_dir / str(index)
        if path.exists() and path.stat().st_size == end - start + 1:
            return path
        for attempt in range(10):
            try:
                request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
                with urllib.request.urlopen(request, timeout=45) as response:
                    if response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-{end}/"):
                        raise RuntimeError("Server did not honor the requested byte range")
                    with path.open("wb") as output:
                        shutil.copyfileobj(response, output, length=2**20)
                if path.stat().st_size != end - start + 1:
                    raise RuntimeError("Incomplete download segment")
                return path
            except Exception:
                if attempt == 9:
                    raise
                time.sleep(min(attempt + 1, 5))

    count = (size + chunk - 1) // chunk
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(part, index) for index in range(count)]
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            future.result()
            if completed % 8 == 0 or completed == count:
                print(f"{target.name}: {completed}/{count} segments", flush=True)
    partial = target.with_name(target.name + ".assembling")
    with partial.open("wb") as output:
        for index in range(count):
            with (part_dir / str(index)).open("rb") as source:
                shutil.copyfileobj(source, output, length=2**20)
    if digest(partial) != expected_hash:
        raise RuntimeError(f"SHA256 mismatch: {target}")
    partial.replace(target)
    print(f"SHA256 verified: {target.name}", flush=True)
    return target


if __name__ == "__main__":
    import json
    import urllib.parse

    root = Path(__file__).resolve().parents[1]
    plan = json.loads((root / "artifacts/gpu-pytorch-install-plan.json").read_text(encoding="utf-8"))
    info = next(item["download_info"] for item in plan["install"] if item["metadata"]["name"] == "torch")
    name = urllib.parse.unquote(info["url"].rsplit("/", 1)[1])
    fetch(info["url"], root / ".local-home/gpu-downloads" / name, info["archive_info"]["hashes"]["sha256"])
