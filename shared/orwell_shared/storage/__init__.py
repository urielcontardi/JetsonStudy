from __future__ import annotations

from ..config import CloudConfig
from .base import StorageBackend
from .local import LocalStorageBackend
from .s3 import S3StorageBackend

__all__ = ["StorageBackend", "LocalStorageBackend", "S3StorageBackend", "get_backend"]


def get_backend(cfg: CloudConfig) -> StorageBackend:
    if cfg.backend == "local":
        return LocalStorageBackend(cfg.local_dir)
    if cfg.backend == "s3":
        if not cfg.bucket:
            raise ValueError("cloud.bucket é obrigatório para backend=s3")
        return S3StorageBackend(bucket=cfg.bucket, prefix=cfg.prefix)
    raise ValueError(f"backend de storage desconhecido: {cfg.backend}")
