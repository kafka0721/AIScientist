"""Install verified NVIDIA CUDA 12.8 components into the project's local home."""

import concurrent.futures
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from gpu_download import fetch

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts/cuda-redistrib-12.8.1.json"
DEST = ROOT / ".local-home/cuda/v12.8"
CACHE = ROOT / ".local-home/gpu-downloads"
COMPONENTS = (
    "cuda_cccl", "cuda_cudart", "cuda_nvcc", "cuda_nvrtc", "cuda_cuobjdump",
    "cuda_nvdisasm", "cuda_nvprune", "cuda_cuxxfilt", "cuda_cupti",
    "cuda_profiler_api", "cuda_nvtx", "cuda_nvml_dev", "cuda_demo_suite",
    "libcublas", "libcufft", "libcurand", "libcusolver", "libcusparse",
    "libnvjitlink", "libnvfatbin", "libnpp", "libnvjpeg",
)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(item):
    name, component = item
    info = component["windows-x86_64"]
    archive = CACHE / Path(info["relative_path"]).name
    if archive.exists() and sha256(archive) == info["sha256"]:
        return name, archive, component
    url = "https://developer.download.nvidia.com/compute/cuda/redist/" + info["relative_path"]
    print(f"Downloading {name} ({int(info['size']) / 2**20:.1f} MiB)", flush=True)
    fetch(url, archive, info["sha256"], int(info["size"]))
    return name, archive, component


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    CACHE.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    installed = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(download, (name, manifest[name])) for name in COMPONENTS]
        for future in concurrent.futures.as_completed(futures):
            name, archive, component = future.result()
            with zipfile.ZipFile(archive) as zf:
                for entry in zf.infolist():
                    relative = Path(*Path(entry.filename).parts[1:])
                    if not relative.parts or entry.is_dir():
                        continue
                    # Preserve per-component licenses and metadata when merging archives.
                    if len(relative.parts) == 1:
                        relative = Path("component-metadata") / name / relative
                    target = (DEST / relative).resolve()
                    if not target.is_relative_to(DEST.resolve()):
                        raise ValueError(f"Invalid archive path: {entry.filename}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(entry) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
            installed[name] = {"version": component["version"], **component["windows-x86_64"]}
            print(f"Installed {name}", flush=True)
    report = {"cuda": "12.8.1", "path": str(DEST), "components": installed}
    (DEST / "installed-components.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"CUDA components ready: {DEST}", flush=True)


if __name__ == "__main__":
    main()
