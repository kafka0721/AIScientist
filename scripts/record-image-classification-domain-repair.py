"""Persist the verified domain repair checkpoint without replacing live progress."""
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path('E:/data')
reports = ROOT / 'artifacts/image-classification-domain-repair'
summary = json.loads((reports / 'summary.json').read_text(encoding='utf-8'))
literature = WORKSPACE / 'development/image_classification_literature'
ingestion = literature / 'ingestion'
checkpoint = ingestion / 'domain_repair_2026-09-19'
checkpoint.mkdir(parents=True, exist_ok=True)
for source in reports.glob('*.json'):
    shutil.copy2(source, checkpoint / source.name)

p05 = json.loads((ingestion / 'P05_import_2026-09-19_01.json').read_text(encoding='utf-8'))
assert not p05['validation_failed']
assert all(row['readback_verified'] and row['retrieval_verified'] for row in p05['rows'])
rows = [row for batch in summary['batches'] for row in batch['rows']] + p05['rows']
roles = Counter(row['role'] for row in rows)

note = f'''# 图像分类 Domain 记忆入库修复

修复时间：{summary['timestamp']}。

原因：候选的 domain=generic，但平台配置仍为旧研究领域 its，验证器因此拒绝写入。
已将 E:/AIScientist/user-config/config.yaml 的 domain_ema_domain 改为 generic，
通过已有 runtime-config 接口热加载配置，未重启或中断正在阅读的任务。
模型保持 custom-openai / gpt-6-astra。

P01–P04 的 14 条候选经过正式导入器重新预检并创建：正向方向 4、负向方向 6、执行策略 4。
每条均有 observation_id，readback_verified=true，retrieval_verified=true。
运行中的平台随后自行成功导入 P05 的 3 条候选，证明活动任务已使用新 domain。
截至本检查点，P01–P05 共 {len(rows)} 条：正向 {roles['direction_positive']}、负向 {roles['direction_negative']}、策略 {roles['strategy']}。

真实存储：E:/AIScientist/.local-home/.witaiscientist/memories/observations/domain/generic/。
范围：project_id=P-f99aa7e849f60d39，task_type=image_classification。
原始修复报告：development/image_classification_literature/ingestion/domain_repair_2026-09-19/。
P05 平台报告：development/image_classification_literature/ingestion/P05_import_2026-09-19_01.json。

历史 dry-run 错误保留用于审计；其中“0 入库”“domain 不匹配”只代表修复前状态。
本检查点覆盖 P01–P04 旧的 blocked/invalid_domain_mismatch 状态，后续续接请以成功入库报告及实际检索为准。
阅读任务仍在执行，未覆盖其正在维护的 manifest 或逐篇笔记。
文献记录仍为 literature/source_unverified，入库和检索成功不代表已在本机复现实验。
'''
for directory in ['development', 'memory']:
    target = WORKSPACE / directory / '2026-09-19_image_classification_domain_repair.md'
    target.write_text(note, encoding='utf-8')
marker = '\n\n## 2026-09-19 Domain 修复检查点\n\n'
appendix = (marker + '活动领域已切换并热加载为 generic。P01–P04 的 14 条候选已正式入库且逐条回读、检索通过；'
            '平台随后自行成功导入 P05 的 3 条候选，当前已核验 17 条（正向5/负向7/策略5）。'
            '历史 domain mismatch/0入库 状态已被本检查点覆盖。'
            '详见 /development/2026-09-19_image_classification_domain_repair.md；'
            '原始报告见 ingestion/domain_repair_2026-09-19/summary.json。\n')
for target in [literature / 'progress.md', literature / 'journal.md', WORKSPACE / 'memory/image_classification_literature.md']:
    if marker not in target.read_text(encoding='utf-8'):
        with target.open('a', encoding='utf-8') as stream:
            stream.write(appendix)
print(json.dumps(dict(recorded=True, verified_total=len(rows), roles=dict(roles), checkpoint=str(checkpoint)), ensure_ascii=False))
