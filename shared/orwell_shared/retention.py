from __future__ import annotations

import os
import shutil

from .index import SegmentIndex


def disk_usage(path: str) -> tuple[int, int]:
    """Retorna (used_bytes, total_bytes) do filesystem que contém `path`."""
    u = shutil.disk_usage(path)
    return (u.used, u.total)


def plan_eviction(used_bytes: int, capacity_bytes: int, high_watermark_pct: int,
                  oldest_first: list[tuple[str, int]]) -> list[str]:
    """Decide quais paths apagar (mais antigos primeiro) até cair abaixo do watermark.

    `oldest_first`: lista de (path, size) ordenada do mais antigo ao mais novo.
    Função pura — não toca disco.
    """
    target = capacity_bytes * high_watermark_pct / 100.0
    if used_bytes <= target:
        return []
    to_delete: list[str] = []
    remaining = used_bytes
    for path, size in oldest_first:
        if remaining <= target:
            break
        to_delete.append(path)
        remaining -= size
    return to_delete


def _oldest_first(index: SegmentIndex) -> list[tuple[str, int]]:
    rows = index._conn.execute(
        "SELECT path, size FROM segments ORDER BY t_start"
    ).fetchall()
    return [(r["path"], r["size"]) for r in rows]


def run_eviction(index: SegmentIndex, used_bytes: int, capacity_bytes: int,
                 high_watermark_pct: int) -> list[str]:
    """Aplica plan_eviction: apaga arquivos do disco e remove do índice."""
    victims = plan_eviction(used_bytes, capacity_bytes, high_watermark_pct,
                            _oldest_first(index))
    for path in victims:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        index.delete(path)
    return victims
