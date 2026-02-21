"""
Google Drive Storage Service
Uploads invoice PDFs to a shared Google Drive folder via the Drive API.
Uses OAuth credentials from GMAIL_TOKEN_B64 (same env var as email service,
now with both gmail.modify and drive scopes).
"""
import base64
import json
import io
import logging
import re
from typing import Optional

from config import config

logger = logging.getLogger(__name__)

# Google Drive API
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    DRIVE_API_AVAILABLE = True
except ImportError:
    DRIVE_API_AVAILABLE = False
    Request = None
    Credentials = None
    build = None
    MediaIoBaseUpload = None

# Target folder in Google Drive (already exists with 39 manually-copied PDFs)
DRIVE_FOLDER_ID = "1B4nA6s2nprirBDn5w6-_QUjD1VtyclkA"


class DriveStorageService:
    """Upload invoice PDFs to Google Drive via API"""

    def __init__(self):
        self.service = None
        self.creds = None
        self.folder_id = DRIVE_FOLDER_ID
        self._authenticate()

    def _authenticate(self):
        """Load OAuth credentials from GMAIL_TOKEN_B64 env var"""
        if not DRIVE_API_AVAILABLE:
            logger.warning("Google API client not installed — Drive storage disabled")
            return

        token_b64 = config.GMAIL_TOKEN_B64
        if not token_b64:
            logger.warning("GMAIL_TOKEN_B64 not set — Drive storage disabled")
            return

        try:
            token_json = base64.b64decode(token_b64).decode('utf-8')
            token_data = json.loads(token_json)
            self.creds = Credentials.from_authorized_user_info(token_data)

            # Refresh if expired
            if self.creds and self.creds.expired and self.creds.refresh_token:
                logger.info("Refreshing expired Drive token...")
                self.creds.refresh(Request())

            self.service = build('drive', 'v3', credentials=self.creds)
            logger.info("Google Drive API authenticated successfully")
        except Exception as e:
            logger.error(f"Failed to authenticate Drive API: {e}")
            self.service = None

    def upload_pdf(self, content: bytes, filename: str, mime_type: str = 'application/pdf') -> str:
        """Upload PDF bytes to Google Drive folder. Returns the Drive file ID."""
        if not self.service:
            raise RuntimeError("Drive API not connected")

        # Check if file with same name already exists in folder
        existing = self.service.files().list(
            q=f"name='{filename}' and '{self.folder_id}' in parents and trashed=false",
            fields='files(id)'
        ).execute().get('files', [])

        if existing:
            # Update existing file
            file_id = existing[0]['id']
            media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type)
            self.service.files().update(
                fileId=file_id,
                media_body=media
            ).execute()
            logger.info(f"Updated existing Drive file: {filename} ({file_id})")
            return file_id

        # Create new file
        file_metadata = {
            'name': filename,
            'parents': [self.folder_id],
            'mimeType': mime_type
        }
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type)
        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()

        file_id = file['id']
        logger.info(f"Uploaded to Drive: {filename} ({file_id}, {len(content)} bytes)")
        return file_id

    def upload_from_local_file(self, path: str, filename: Optional[str] = None) -> str:
        """Read a local file and upload to Drive. Returns the Drive file ID."""
        import os
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        if not filename:
            filename = os.path.basename(path)
        with open(path, 'rb') as f:
            content = f.read()
        return self.upload_pdf(content, filename)

    def get_file_link(self, file_id: str) -> str:
        """Return Google Drive web view link for a file"""
        return f"https://drive.google.com/file/d/{file_id}/view"

    def get_folder_link(self) -> str:
        """Return Google Drive web link for the invoice folder"""
        return f"https://drive.google.com/drive/folders/{self.folder_id}"

    def list_files(self) -> list:
        """List all files in the invoice folder"""
        if not self.service:
            return []
        results = []
        page_token = None
        while True:
            resp = self.service.files().list(
                q=f"'{self.folder_id}' in parents and trashed=false",
                pageSize=100,
                fields='nextPageToken, files(id, name, mimeType, size, modifiedTime)',
                pageToken=page_token
            ).execute()
            for f in resp.get('files', []):
                results.append({
                    'id': f['id'],
                    'name': f['name'],
                    'mimeType': f.get('mimeType', ''),
                    'size': int(f.get('size', 0)),
                    'modified': f.get('modifiedTime', '')
                })
            page_token = resp.get('nextPageToken')
            if not page_token:
                break
        return results

    def get_file_count(self) -> int:
        """Get count of files in the invoice folder"""
        if not self.service:
            return 0
        resp = self.service.files().list(
            q=f"'{self.folder_id}' in parents and trashed=false",
            pageSize=1,
            fields='files(id)'
        ).execute()
        # For accurate count, use list_files; this is a quick check
        return len(self.list_files())

    @property
    def is_connected(self) -> bool:
        """Check if Drive API is accessible"""
        if not self.service:
            return False
        try:
            self.service.files().get(
                fileId=self.folder_id, fields='id'
            ).execute()
            return True
        except Exception:
            return False


def sanitize_filename(invoice_number: str, client_name: str) -> str:
    """Generate Drive-friendly filename from invoice data.
    E.g. Faktura_01_02_2026_Bauceram_GmbH.pdf"""
    safe_number = invoice_number.replace('/', '_')
    safe_client = re.sub(r'[^\w\s-]', '', client_name).replace(' ', '_')
    return f"Faktura_{safe_number}_{safe_client}.pdf"


# Singleton
_drive_service: Optional[DriveStorageService] = None


def get_drive_service() -> DriveStorageService:
    """Get Drive storage singleton"""
    global _drive_service
    if _drive_service is None:
        _drive_service = DriveStorageService()
    return _drive_service
