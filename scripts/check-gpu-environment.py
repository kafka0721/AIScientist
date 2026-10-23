"""Run small numerical GPU checks and save an experiment environment report."""

import datetime
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUDA = ROOT / ".local-home/cuda/v12.8"
os.environ["CUDA_PATH"] = str(CUDA)
os.environ["PATH"] = str(CUDA / "bin") + os.pathsep + os.environ.get("PATH", "")
# Keep generated kernel caches on E:, alongside the experiment environment.
os.environ.setdefault("CUPY_CACHE_DIR", str(ROOT / ".local-home/cupy-cache"))

import numpy as np
import torch
import torchvision
import cupy as cp


def main():
    assert torch.cuda.is_available(), "PyTorch cannot access CUDA"
    torch.manual_seed(20260919)
    torch.backends.cuda.matmul.allow_tf32 = False
    cpu = torch.randn(256, 256)
    gpu = cpu.cuda()
    torch.testing.assert_close((gpu @ gpu.T).cpu(), cpu @ cpu.T, rtol=1e-4, atol=1e-4)

    model = torch.nn.Sequential(
        torch.nn.Conv2d(3, 8, 3, padding=1), torch.nn.ReLU(),
        torch.nn.AdaptiveAvgPool2d(1), torch.nn.Flatten(), torch.nn.Linear(8, 4),
    ).cuda()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
    inputs = torch.randn(4, 3, 64, 64, device="cuda")
    labels = torch.tensor([0, 1, 2, 3], device="cuda")
    before = model[0].weight.detach().clone()
    loss = torch.nn.functional.cross_entropy(model(inputs), labels)
    loss.backward()
    assert torch.isfinite(loss).item()
    assert all(p.grad is not None and torch.isfinite(p.grad).all().item() for p in model.parameters())
    optimizer.step()
    assert not torch.equal(before, model[0].weight)
    boxes = torch.tensor([[0, 0, 10, 10], [1, 1, 9, 9]], dtype=torch.float32, device="cuda")
    selected = torchvision.ops.nms(boxes, torch.tensor([0.9, 0.8], device="cuda"), 0.5)
    assert selected.tolist() == [0]
    torch.cuda.synchronize()

    a = cp.arange(256, dtype=cp.float32).reshape(16, 16) / 100
    np.testing.assert_allclose(cp.asnumpy(a @ a.T), cp.asnumpy(a) @ cp.asnumpy(a).T, rtol=1e-5)
    np.testing.assert_allclose(cp.asnumpy(cp.fft.ifft(cp.fft.fft(a))), cp.asnumpy(a), atol=1e-5)
    matrix = cp.eye(8, dtype=cp.float64) * 2
    np.testing.assert_allclose(cp.asnumpy(cp.linalg.solve(matrix, cp.ones(8))), np.full(8, 0.5))
    kernel = cp.RawKernel('extern "C" __global__ void twice(float* x) { int i = threadIdx.x; x[i] *= 2; }', 'twice')
    values = cp.arange(32, dtype=cp.float32)
    kernel((1,), (32,), (values,))
    np.testing.assert_array_equal(cp.asnumpy(values), np.arange(32, dtype=np.float32) * 2)
    cp.cuda.Stream.null.synchronize()

    report = {
        "timestamp": datetime.datetime.now().astimezone().isoformat(),
        "python": sys.executable, "python_version": sys.version,
        "gpu": torch.cuda.get_device_name(0),
        "compute_capability": list(torch.cuda.get_device_capability(0)),
        "gpu_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        "packages": {name: importlib.metadata.version(name) for name in
                     ["torch", "torchvision", "torchaudio", "cupy-cuda12x", "numpy"]},
        "pytorch_cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
        "cuda_path": str(CUDA),
        "nvcc": subprocess.check_output([str(CUDA / "bin/nvcc.exe"), "--version"], text=True).strip(),
        "nvidia_smi": subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.free", "--format=csv,noheader"], text=True).strip(),
        "checks": {name: "passed" for name in [
            "pytorch_gpu_matmul_matches_cpu", "cnn_forward_backward_optimizer",
            "torchvision_cuda_nms", "cupy_matmul", "cupy_fft",
            "cupy_linear_solve", "cupy_nvrtc_kernel_compilation",
        ]},
        "training_smoke_test_loss": loss.item(),
        "limitations": [
            "TensorFlow CUDA on current Python requires a separate WSL2/Linux environment.",
            "MSVC host compiler is not installed; custom nvcc C++ extensions require Visual Studio Build Tools.",
        ],
    }
    output = ROOT / "artifacts/gpu-environment-check.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
