from __future__ import annotations

from pydantic import BaseModel


class DetectionEvent(BaseModel):
    camera_id: str
    ts_event: float          # epoch seconds (UTC)
    label: str
    score: float
    pre_s: float = 5.0
    post_s: float = 5.0

    def clip_window(self) -> tuple[float, float]:
        return (self.ts_event - self.pre_s, self.ts_event + self.post_s)
