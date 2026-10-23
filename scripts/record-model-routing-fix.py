"""Save the model-routing repair evidence in the research workspace logs."""

import datetime
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
connection = json.loads((root / "artifacts/model-connection-check.json").read_text(encoding="utf-8"))
child = json.loads((root / "artifacts/subagent-model-live-check.json").read_text(encoding="utf-8"))
assert all(row["status"] == "success" for row in connection)
assert child["status"] == "passed"
now = datetime.datetime.now().astimezone()
text = f"""# 平台模型调用同步修复

记录时间：{now.isoformat()}

## 已确认的问题

- 论文任务主代理实际调用 gpt-6-astra，但同步 general-purpose 子代理仍绑定旧模型 gpt-5.5。
- 根因：同步子代理中间件未包含 ConfigurableModelMiddleware，缺少每次调用读取当前选择的逻辑。
- 工具选择器也可能固定图构建时的模型；本机另配有 DashScope/qwen3.6-flash 辅助模型，其调用返回 401。
- 历史任务在 16:20:27 和 16:57:41 以 APIConnectionError 结束。现有证据不能将其归因于中转站分组配置。

## 已实施修复

- 为同步子代理接入运行时模型选择，继承父任务的 use_active_model 或显式 model/model_provider。
- 无独立辅助配置时，工具选择器使用当前 request.model，避免缓存旧的主模型。
- 本机 auxiliary_model/auxiliary_provider 设为空，跟随当前主模型 gpt-6-astra/custom-openai。
- 保留显式独立辅助模型的产品能力；本次本机配置统一使用所选主模型。
- 已重启平台，工作区仍为 E:\\data；服务健康检查通过。

## 验证证据

- 84 项相关测试通过，包含同一编译图不重建、连续切换模型时主代理与同步子代理同时更新的同步/异步执行回归测试。
- 两次真实主模型请求成功，返回模型均为 gpt-6-astra。
- 一次真实 task 子代理请求成功，返回模型 gpt-6-astra；旧绑定没有被使用。
- 结果文件：E:\\AIScientist\\artifacts\\model-connection-check.json 和 E:\\AIScientist\\artifacts\\subagent-model-live-check.json。
- 原论文任务检查点保留 40 条消息；重启前快照：E:\\AIScientist\\artifacts\\literature-state-before-model-fix.json。

## 后续状态与边界

没有自动续跑论文任务，原检查点中的 error 仍表示上一次运行失败，不代表本次修复测试失败。
在平台中继续原任务时将使用修复后的模型路由。
本次未复现中转连接错误，不能据短请求成功宣称长任务网络稳定性已得到保证。
领域配置仍为 its；图像分类候选导入需要匹配 generic/image_classification。
"""
outputs = [
    root / "artifacts/model-routing-fix.md",
    Path("E:/data/development") / f"{now:%Y-%m-%d}_model_routing_fix.md",
    Path("E:/data/memory") / f"{now:%Y-%m-%d}_model_routing_fix.md",
]
for output in outputs:
    output.write_text(text, encoding="utf-8")
    print(output)
