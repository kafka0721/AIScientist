"""Repair completed P01-P04 imports through the canonical literature validator."""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ['WITAISCIENTIST_CONFIG_PATH'] = str(ROOT / 'user-config/config.yaml')

from imaging_scientist.config import DomainEMAControls, get_effective_config
from imaging_scientist.memory.literature import import_literature_candidates


def main():
    workspace = Path('E:/data')
    memory = ROOT / '.local-home/.witaiscientist/memories'
    controls = DomainEMAControls.from_config(get_effective_config())
    assert controls.enabled and controls.domain.value == 'generic'
    reports = ROOT / 'artifacts/image-classification-domain-repair'
    reports.mkdir(parents=True, exist_ok=True)
    batches = []
    for name in ['P01_GoogLeNet', 'P02_ResNet', 'P03_MobileNetV1', 'P04_ResNeXt']:
        source = workspace / f'development/image_classification_literature/candidates/{name}.jsonl'
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        args = dict(workspace=workspace, memory_dir=memory,
                    path=str(source.relative_to(workspace)), expected_domain=controls.domain)
        preflight = import_literature_candidates(**args, dry_run=True)
        (reports / f'{name}_preflight.json').write_text(json.dumps(preflight, ensure_ascii=False, indent=2), encoding='utf-8')
        assert not preflight['validation_failed'], f'{name}: preflight failed'
        batches.append((name, source, digest, args))
    results = []
    for name, source, digest, args in batches:
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, f'{name}: source changed'
        result = import_literature_candidates(**args, dry_run=False)
        (reports / f'{name}_apply.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        assert not result['validation_failed']
        assert all(row['status'] in ('created', 'existing') and row['readback_verified'] and row['retrieval_verified'] for row in result['rows']), f'{name}: verification failed'
        results.append(dict(paper=name, source_sha256=digest, **result))
    rows = [row for batch in results for row in batch['rows']]
    summary = dict(timestamp=datetime.now().astimezone().isoformat(), domain=controls.domain.value,
                   provider=get_effective_config().provider, model=get_effective_config().model,
                   total=len(rows), roles=dict(Counter(row['role'] for row in rows)),
                   counts=dict(Counter(row['status'] for row in rows)),
                   readback_verified=all(row['readback_verified'] for row in rows),
                   retrieval_verified=all(row['retrieval_verified'] for row in rows),
                   reports=str(reports), batches=results)
    (reports / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k != 'batches'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
