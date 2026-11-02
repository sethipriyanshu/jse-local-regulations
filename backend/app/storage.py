"""Blob storage for page snapshots and exports: Azure Blob in deployed environments,
a local folder in development and tests ("file:<dir>" connection string)."""

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


class BlobStore(Protocol):
    def put(self, name: str, data: bytes, content_type: str) -> None: ...
    def get(self, name: str) -> bytes: ...


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, name: str) -> Path:
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"blob name escapes the store: {name}")
        return path

    def put(self, name: str, data: bytes, content_type: str) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, name: str) -> bytes:
        return self._path(name).read_bytes()


class AzureBlobStore:
    def __init__(self, connection_string: str, container: str) -> None:
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient.from_connection_string(connection_string)
        self.container = service.get_container_client(container)
        if not self.container.exists():
            self.container.create_container()

    def put(self, name: str, data: bytes, content_type: str) -> None:
        from azure.storage.blob import ContentSettings

        self.container.upload_blob(
            name, data, overwrite=True, content_settings=ContentSettings(content_type=content_type)
        )

    def get(self, name: str) -> bytes:
        return self.container.download_blob(name).readall()


@lru_cache
def get_store() -> BlobStore:
    s = get_settings()
    conn = s.storage_connection_string
    if conn.startswith("file:"):
        root = Path(conn.removeprefix("file:"))
        return LocalBlobStore(root if root.is_absolute() else REPO_ROOT / root)
    return AzureBlobStore(conn, s.storage_container)
