from __future__ import annotations
from pathlib import Path
from .models import RunRecord

class RunStore:
    def __init__(self, data_dir: str):
        self.path = Path(data_dir) / "runs"
        self.path.mkdir(parents=True, exist_ok=True)

    def save(self, run: RunRecord) -> None:
        (self.path / f"{run.run_id}.json").write_text(run.model_dump_json(indent=2), encoding="utf-8")

    def load_all(self) -> list[RunRecord]:
        out=[]
        for p in self.path.glob("*.json"):
            try: out.append(RunRecord.model_validate_json(p.read_text(encoding="utf-8")))
            except Exception: pass
        return out
