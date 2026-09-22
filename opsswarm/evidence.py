from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

class EvidenceStore:
    def __init__(self, data_dir: str):
        self.path=Path(data_dir)/"evidence"
        self.path.mkdir(parents=True, exist_ok=True)

    def append(self, run_id: str, kind: str, payload: dict[str, Any]) -> str:
        eid=f"EV-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        rec={"id":eid,"timestamp":datetime.now(timezone.utc).isoformat(),"run_id":run_id,"kind":kind,"payload":payload}
        with (self.path/f"{run_id}.jsonl").open("a",encoding="utf-8") as f:
            f.write(json.dumps(rec,ensure_ascii=False,default=str)+"\n")
        return eid

    def list(self, run_id: str) -> list[dict[str, Any]]:
        p=self.path/f"{run_id}.jsonl"
        if not p.exists(): return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
