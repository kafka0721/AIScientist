"""Import an existing JSONL batch using the same implementation as the agent tool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from imaging_scientist import paths
from imaging_scientist.config import DomainEMAControls, get_effective_config
from imaging_scientist.memory.literature import import_literature_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Candidate JSONL path, relative to workspace")
    parser.add_argument("--workspace", type=Path, default=paths._active_workspace)
    parser.add_argument("--memory-dir", type=Path, default=paths.MEMORIES_DIR)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write eligible candidates; otherwise preview only",
    )
    parser.add_argument("--report", type=Path, help="Save machine-readable results")
    args = parser.parse_args()
    controls = DomainEMAControls.from_config(get_effective_config())
    if not controls.enabled:
        parser.error("Domain-EMA is disabled in the active configuration")
    result = import_literature_candidates(
        workspace=args.workspace,
        memory_dir=args.memory_dir,
        path=args.path,
        dry_run=not args.apply,
        expected_domain=controls.domain,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "rows"},
            ensure_ascii=False,
        )
    )
    return int(
        result["validation_failed"]
        or any(
            row["status"] in {"error", "verification_failed"} for row in result["rows"]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
