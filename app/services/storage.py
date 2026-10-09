import uuid
from pathlib import Path

from app.config import get_settings


def certificate_file_path(job_id: uuid.UUID, certificate_id: uuid.UUID) -> Path:
    """Resolve the internal storage path for a generated certificate PDF.

    This path is internal only and must never appear in API responses.
    """
    return Path(get_settings().storage_dir) / str(job_id) / f"{certificate_id}.pdf"
