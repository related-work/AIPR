from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError


PROGRESS_FILE_ENV = "AI_PR_REVIEW_PROGRESS_FILE"
ProgressStatus = Literal["running", "completed", "failed", "skipped"]


class ProgressEvent(BaseModel):
    stage: str
    label: str
    status: ProgressStatus
    timestamp: str
    message: str | None = None


class ProgressReporter:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None

    @classmethod
    def from_env(cls) -> "ProgressReporter":
        return cls(os.environ.get(PROGRESS_FILE_ENV))

    def emit(
        self,
        stage: str,
        label: str,
        status: ProgressStatus,
        message: str | None = None,
    ) -> None:
        if self._path is None:
            return
        event = ProgressEvent(
            stage=stage,
            label=label,
            status=status,
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
            message=message,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json(exclude_none=True) + "\n")


def read_progress_events(path: str | Path) -> list[dict]:
    progress_path = Path(path)
    if not progress_path.exists():
        return []

    events: list[dict] = []
    for line in progress_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = ProgressEvent.model_validate_json(line)
        except (ValueError, ValidationError):
            continue
        events.append(event.model_dump(exclude_none=True))
    return events
