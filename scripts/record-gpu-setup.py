"""Record a successful GPU setup in the user's research workspace logs."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
report_path = root / "artifacts/gpu-environment-check.json"
report = json.loads(report_path.read_text(encoding="utf-8"))
assert report["checks"] and all(value == "passed" for value in report["checks"].values())
date = report["timestamp"][:10]
workspace = Path("E:/data")
development = workspace / "development" / f"{date}_gpu_environment_setup.md"
memory = workspace / "memory" / f"{date}_gpu_environment.md"
packages = "\n".join(f"- {name}: {version}" for name, version in report["packages"].items())
checks = "\n".join(f"- {name}: {status}" for name, status in report["checks"].items())
development_text = f"""# GPU 实验环境准备

时间：{report['timestamp']}

## 目标和初始状态

为后续科研实验配置本机 GPU。初始检查确认 RTX 4050 Laptop GPU / 6 GB 显存、NVIDIA 581.86 驱动正常；项目 Python 3.12 尚无 PyTorch/CuPy，未发现 CUDA Toolkit。

## 已完成

- 将 NVIDIA 官方 CUDA 12.8.1 组件（nvcc、头文件、运行库、计算库）安装到 `{report['cuda_path']}`，逐包校验官方 SHA256。
- GPU Python 环境：`{report['python']}`。
{packages}
- 保留原有驱动；为当前用户保存 CUDA_PATH 与 CUDA bin 路径。
- 新增 `E:/AIScientist/scripts/activate-gpu.ps1`；生产启动脚本自动激活该环境。已运行服务需重启才能继承新环境。

## 验证结果

显卡：{report['gpu']}，计算能力：{report['compute_capability']}。
PyTorch CUDA：{report['pytorch_cuda']}；cuDNN：{report['cudnn']}。
{checks}

完整机器可读结果：`{report_path}`。
复验命令：`E:/AIScientist/.venv/Scripts/python.exe E:/AIScientist/scripts/check-gpu-environment.py`。

## 问题及处理

官方大文件下载发生连接中断。复用已完成且校验通过的 PyTorch wheel；CUDA 剩余文件使用分块重试下载并校验 SHA256。
C 盘空间较少，工具链、下载文件和安装临时文件放在 E 盘。

## 使用边界和下一步

- 当前可使用 PyTorch/CuPy 在原生 Windows 上跑 GPU 实验。
- 新版 TensorFlow 的 CUDA 加速需要独立 WSL2/Linux 环境，本次未安装。
- 编译 nvcc 自定义 C++ 扩展还需要兼容的 MSVC Build Tools；本次未安装。CuPy NVRTC 内核已验证。
- GPU 冒烟测试使用合成数据，不代表科研实验结果或性能基准。
- 后续选定数据集和模型，使用较小 batch size 开始测试并记录实际峰值显存。
"""
memory_text = f"""# 本机 GPU 环境重要记忆

- 日期：{date}。
- GPU：{report['gpu']}，6 GB 显存，与桌面共享。驱动 581.86。
- 固定使用 `{report['python']}`；不要误用系统 Python 或 CPU 版 PyTorch。
- CUDA Toolkit 12.8.1：`{report['cuda_path']}`。驱动显示 CUDA 13.0 表示其支持能力，不是 Toolkit 安装版本。
{packages}
- PowerShell 激活：`. E:/AIScientist/scripts/activate-gpu.ps1`，随后在 `E:/data` 运行实验。
- WebUI 生产启动脚本已接入 GPU 环境，原有运行进程需要重启。
- PyTorch 训练步骤、torchvision CUDA 算子、CuPy 计算与 NVRTC 编译均通过实际 GPU 验证。
- 新版 TensorFlow GPU 需 WSL2/Linux；MSVC 自定义 CUDA/C++ 扩展编译环境未安装。
- GPU 包为项目虚拟环境额外依赖，未加入通用 uv.lock；重建/精确同步虚拟环境可能移除它们。
- 证据：`{report_path}`；过程：`{development}`。
"""
for path, content in [(development, development_text), (memory, memory_text)]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(path)
