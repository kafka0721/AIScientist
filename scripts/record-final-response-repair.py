"""Verify the repaired literature run, then optionally record workspace completion."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path('E:/data')
THREAD = '01a0b872-afa2-7292-8565-c479a7f59ac7'
RUN = '01a0bdbe-3e8f-7153-9ebf-4db88763a78f'


def main(record_workspace: bool) -> None:
    opener = build_opener(ProxyHandler({}))

    def get(suffix: str):
        with opener.open(f'http://127.0.0.1:6174/threads/{THREAD}/{suffix}', timeout=15) as response:
            return json.load(response)

    run, state = get(f'runs/{RUN}'), get('state')
    last = state['values']['messages'][-1]
    assert run['status'] == 'success', 'Run has not succeeded'
    assert not state.get('next') and not state.get('tasks'), 'Pending graph work remains'
    assert last['type'] == 'ai' and last.get('content') and not last.get('tool_calls')
    metadata = last['response_metadata']
    assert metadata.get('finish_reason') == 'stop'
    assert metadata.get('model_name') == 'gpt-6-astra'
    assert all(t['status'] == 'completed' for t in state['values']['todos'])

    literature = WORKSPACE / 'development/image_classification_literature'
    ingestion = json.loads((literature / 'ingestion_report.json').read_text(encoding='utf-8'))
    candidates = ingestion['candidates']
    assert len(candidates) == len({c['observation_id'] for c in candidates}) == 55
    counts: dict[str, int] = {}
    memory_root = ROOT / '.local-home/.witaiscientist/memories/observations/domain/generic'
    for candidate in candidates:
        role, oid = candidate['role'], candidate['observation_id']
        assert all(candidate[k] for k in ('readback_verified', 'importer_retrieval_verified', 'independent_retrieval_verified'))
        memory_path = memory_root / role / f'{oid}.md'
        raw = memory_path.read_text(encoding='utf-8')
        fields = yaml.safe_load(raw.split('---', 2)[1])
        assert fields['id'] == oid
        assert fields['domain']['role'] == role
        assert fields['domain']['task_type'] == 'image_classification'
        assert fields['domain']['evidence_status'] == 'source_unverified'
        counts[role] = counts.get(role, 0) + 1
    assert counts == {'direction_positive': 17, 'direction_negative': 20, 'strategy': 18}

    report = {
        'verified_at_utc': datetime.now(timezone.utc).isoformat(),
        'thread_id': THREAD, 'run_id': RUN, 'status': run['status'],
        'finish_reason': metadata['finish_reason'], 'model': metadata['model_name'],
        'messages': len(state['values']['messages']), 'next': state['next'], 'tasks': state['tasks'],
        'token_usage': metadata.get('token_usage'), 'verified_memory_files': len(candidates),
        'roles': counts, 'tests_passed': 223,
        'probe_artifact': 'response-diagnostic-httpx-model-short-fresh-153542.json',
        'limitations': ['literature/source_unverified', 'figures not visually audited',
                        'external AlexNet supplement unavailable', 'no local GPU training'],
    }
    probe = json.loads((ROOT / 'artifacts' / report['probe_artifact']).read_text(encoding='utf-8'))
    assert all(row['ok'] and row.get('finish_reason') == 'stop' for row in probe['results'])
    (ROOT / 'artifacts/final-response-repair-verification.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'artifacts/literature-final-response.md').write_text(last['content'] + '\n', encoding='utf-8')

    note = f'''# 2026-09-20 最终答复中断修复与验收

核验时间（UTC）：{report['verified_at_utc']}

## 结果

原任务 {THREAD} 从最后 model 检查点以空输入恢复，未追加新提示、未重新执行论文导入。
运行 {RUN} 于 2026-09-20 07:36:40 UTC 正常结束（总耗时约43.5秒）。
模型 gpt-6-astra，finish_reason=stop，212条消息，最终答复已保存，next=[]，tasks=[]，todos全部完成。
入库报告55条条目均逐一核对实际domain文件、ID、role、task_type与source_unverified状态；正向17、负向20、策略18。
既有报告记录全文文本18篇/243页和55条回读及独立检索成功。本次未重新运行检索或训练。

## 原因证据与边界

不能只依据 APIConnectionError 推断API密钥或分组故障。此前受控测试中，小请求成功，大请求（包括短提示加合法JSON空白）在上传/等待响应阶段反复失败，Windows curl也出现上传失败；改走现有本地代理后大请求完整成功。失败相关的是连接路径承载大请求的行为，而非只发生于模型思考或记忆写入。
本轮失败检查点请求体实测228416字节。从中断处重试仍带上历史上下文，因此没有改变原先的大请求条件。
原两次收尾失败没有完整底层阶段日志，无法据此唯一定位中间设备或断言每次均为同一底层原因。当前修复在同一原任务最后节点实测通过。

## 修改

- 增加 gateway_proxy 显式配置，统一网关同步/异步客户端和模型目录请求的代理/TLS策略；保留调用方显式客户端优先级。
- 本机配置 x25519 + http://127.0.0.1:7890，保留证书验证。
- 增加安全传输日志：阶段、字节数、耗时、异常链类型，不记录正文、密钥或异常文本。该日志覆盖send阶段，并非完整覆盖已返回响应后的流读取。
- 仅连接建立失败在本层额外重试一次；本层不重放读取/写入错误或部分流。SDK原有两次重试仍存在。
- 223项相关测试通过，含同步/异步真实本地CONNECT代理、覆盖环境代理、无敏感信息日志、读取错误不被本层重试等。
- 230131字节大请求预检完整返回，HTTP200、finish_reason=stop，约3.8秒；随后原始对话实际生成最终总结。

## 部署中发现的问题与运行条件

首次启用代理时 FlClash 进程存在但7890未监听，导致验证运行01a0bdb7-4882-71b1-a1a5-6bce0cadfbb1连接拒绝。此为本次部署引入的失败，不能拿来解释原两次中断。
已通过FlClash现有启动按钮恢复监听；系统代理和虚拟网卡保持关闭。后续运行项目需保持FlClash代理启动，不能只打开窗口。无需更换API密钥或降低到gpt-5.5。

## 科研状态与记录

manifest.json 的 reading_in_progress 是遗留总状态；确认最终答复和55条真实存储后改为 completed_with_limitations，并保留逐篇证据状态。
文献证据仍为literature/source_unverified，图像尚未逐页目视核验、AlexNet外部补充未读、未运行本机GPU实验。未将运维修复记忆导入科研domain。
工程验收：E:/AIScientist/artifacts/final-response-repair-verification.json。
最终答复副本：E:/AIScientist/artifacts/literature-final-response.md。
本记录同步至 E:/data/development 和 E:/data/memory。
'''
    (ROOT / 'artifacts/final-response-repair.md').write_text(note, encoding='utf-8')
    if record_workspace:
        manifest_path = literature / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        backup = ROOT / 'artifacts/literature-manifest-before-finalization.json'
        if not backup.exists():
            backup.write_bytes(manifest_path.read_bytes())
        manifest['execution_status'] = 'completed_with_limitations'
        manifest['final_response_verification'] = {
            'run_id': RUN, 'finish_reason': 'stop', 'pending_nodes': [],
            'verified_at_utc': report['verified_at_utc'], 'verified_memory_files': 55,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        for directory in ('development', 'memory'):
            (WORKSPACE / directory / '2026-09-20_final_response_repair.md').write_text(note, encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--record-workspace', action='store_true')
    main(parser.parse_args().record_workspace)
