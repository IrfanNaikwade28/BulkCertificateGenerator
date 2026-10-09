import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CertificateStatus
from app.schemas.job import CertificateDetailResponse
from app.services import job_service, storage

router = APIRouter(tags=["certificates"])


@router.get(
    "/certificates/{certificate_id}",
    response_model=CertificateDetailResponse,
    summary="Get certificate metadata",
)
def get_certificate(
    certificate_id: uuid.UUID, db: Session = Depends(get_db)
) -> CertificateDetailResponse:
    certificate = job_service.get_certificate(db, certificate_id)
    if certificate is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return CertificateDetailResponse(
        certificate_id=certificate.id,
        job_id=certificate.job_id,
        recipient_name=certificate.recipient_name,
        email=certificate.email,
        status=certificate.status,
        error_code=certificate.error_code,
        file_size_bytes=certificate.file_size_bytes,
        created_at=certificate.created_at,
        generated_at=certificate.generated_at,
        download_url=f"/api/v1/certificates/{certificate.id}/download",
    )


@router.get(
    "/certificates/{certificate_id}/download",
    summary="Download the generated PDF",
)
def download_certificate(
    certificate_id: uuid.UUID, db: Session = Depends(get_db)
) -> FileResponse:
    certificate = job_service.get_certificate(db, certificate_id)
    if certificate is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if certificate.status != CertificateStatus.SUCCEEDED:
        raise HTTPException(status_code=409, detail="Certificate is not ready for download")

    path = storage.certificate_file_path(certificate.job_id, certificate.id)
    if not path.is_file():
        # Do not expose internal paths or storage details.
        raise HTTPException(status_code=404, detail="Certificate file not available")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"certificate-{certificate.id}.pdf",
    )
