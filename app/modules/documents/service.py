"""
Documents module — Microsoft OneDrive integration via Graph API.
Handles upload, share, and track of all client-facing documents.
iCloud is deprecated — all new documents go to OneDrive.
"""
import logging
import os
from typing import Optional, BinaryIO
from sqlalchemy.orm import Session

from app.modules.documents.models import ClientDocument

logger = logging.getLogger(__name__)


def _graph_headers() -> Optional[dict]:
    """Get Graph API auth headers. Returns None if not configured."""
    import httpx
    tenant = os.getenv("MS_TENANT_ID")
    client_id = os.getenv("MS_CLIENT_ID")
    secret = os.getenv("MS_CLIENT_SECRET")

    if not all([tenant, client_id, secret]):
        logger.warning("OneDrive not configured — MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET required")
        return None

    resp = httpx.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
            "scope": "https://graph.microsoft.com/.default",
        }, timeout=15,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def upload_to_onedrive(
    db: Session,
    client_id: str,
    filename: str,
    content: bytes,
    document_type: str = "other",
    notes: Optional[str] = None,
) -> ClientDocument:
    """Upload file to OneDrive Business and record in DB."""
    import httpx

    root_folder = os.getenv("MS_ONEDRIVE_ROOT_FOLDER", "ZA Support/Clients")
    folder_path = f"{root_folder}/{client_id}"
    drive_path = f"/me/drive/root:/{folder_path}/{filename}:/content"

    headers = _graph_headers()
    onedrive_id = None
    onedrive_url = None

    if headers:
        upload_headers = {**headers, "Content-Type": "application/octet-stream"}
        try:
            url = f"https://graph.microsoft.com/v1.0{drive_path}"
            resp = httpx.put(url, content=content, headers=upload_headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            onedrive_id = data.get("id")
            onedrive_url = data.get("webUrl")
            logger.info(f"Uploaded {filename} for {client_id} to OneDrive: {onedrive_url}")
        except Exception as e:
            logger.error(f"OneDrive upload failed for {filename}: {e}")

    doc = ClientDocument(
        client_id=client_id,
        filename=filename,
        document_type=document_type,
        onedrive_id=onedrive_id,
        onedrive_url=onedrive_url,
        onedrive_path=f"{folder_path}/{filename}",
        file_size_bytes=str(len(content)),
        mime_type="application/pdf" if filename.endswith(".pdf") else "application/octet-stream",
        notes=notes,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def create_share_link(db: Session, doc_id: str) -> Optional[str]:
    """Create a sharing link for a document and update the record."""
    import httpx

    doc = db.query(ClientDocument).filter(ClientDocument.id == doc_id).first()
    if not doc or not doc.onedrive_id:
        return None

    headers = _graph_headers()
    if not headers:
        return None

    try:
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{doc.onedrive_id}/createLink"
        resp = httpx.post(url, json={"type": "view", "scope": "anonymous"}, headers=headers, timeout=15)
        resp.raise_for_status()
        link = resp.json().get("link", {}).get("webUrl")
        doc.share_link = link
        doc.shared_with_client = True
        db.commit()
        return link
    except Exception as e:
        logger.error(f"Share link creation failed: {e}")
        return None


def list_documents(db: Session, client_id: str) -> list:
    return db.query(ClientDocument).filter(
        ClientDocument.client_id == client_id
    ).order_by(ClientDocument.created_at.desc()).all()
