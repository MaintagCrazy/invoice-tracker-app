"""
Google Drive Storage Service
Saves invoice PDFs to the local Google Drive sync folder.
Google Drive for Desktop handles the cloud sync automatically —
files appear on iPhone via the Drive app and in Finder on Mac.
"""
import os
import shutil
import logging
import re
from typing import Optional

from config import config

logger = logging.getLogger(__name__)

# Local Google Drive sync folder
LOCAL_DRIVE_FOLDER = os.path.expanduser("~/Documents/GOOGLE DRIVE")
INVOICES_SUBFOLDER = "Faktury Correct"


class DriveStorageService:
    """Save invoice PDFs to the local Google Drive sync folder"""

    def __init__(self):
        self.folder_path = os.path.join(LOCAL_DRIVE_FOLDER, INVOICES_SUBFOLDER)
        self._ensure_folder()

    def _ensure_folder(self):
        """Ensure the invoice folder exists"""
        if not os.path.isdir(LOCAL_DRIVE_FOLDER):
            raise FileNotFoundError(
                f"Google Drive folder not found at {LOCAL_DRIVE_FOLDER}. "
                "Install Google Drive for Desktop and set it to sync to this path."
            )
        os.makedirs(self.folder_path, exist_ok=True)
        logger.info(f"Drive storage folder: {self.folder_path}")

    def upload_pdf(self, content: bytes, filename: str, mime_type: str = 'application/pdf') -> str:
        """Save PDF bytes to the Drive sync folder. Returns the local file path.
        If a file with the same name exists, overwrites it."""
        filepath = os.path.join(self.folder_path, filename)
        with open(filepath, 'wb') as f:
            f.write(content)
        logger.info(f"Saved to Drive folder: {filename} ({len(content)} bytes)")
        return filepath

    def upload_from_local_file(self, path: str, filename: Optional[str] = None) -> str:
        """Copy a local PDF file to the Drive sync folder. Returns the destination path."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        if not filename:
            filename = os.path.basename(path)

        dest = os.path.join(self.folder_path, filename)
        shutil.copy2(path, dest)
        logger.info(f"Copied to Drive folder: {filename}")
        return dest

    def file_exists(self, filename: str) -> bool:
        """Check if a file exists in the Drive folder"""
        return os.path.isfile(os.path.join(self.folder_path, filename))

    def get_file_link(self, filepath: str) -> str:
        """Return the local file path (Google Drive for Desktop syncs it)"""
        return filepath

    def get_folder_link(self) -> str:
        """Return the local folder path"""
        return self.folder_path

    def list_files(self) -> list:
        """List all PDF files in the invoice folder"""
        files = []
        for f in sorted(os.listdir(self.folder_path)):
            if f.endswith('.pdf'):
                full_path = os.path.join(self.folder_path, f)
                stat = os.stat(full_path)
                files.append({
                    'name': f,
                    'path': full_path,
                    'size': stat.st_size,
                    'modified': stat.st_mtime
                })
        return files

    def get_file_count(self) -> int:
        """Get count of PDF files in the invoice folder"""
        return len([f for f in os.listdir(self.folder_path) if f.endswith('.pdf')])

    @property
    def is_connected(self) -> bool:
        """Check if the Drive sync folder is accessible"""
        return os.path.isdir(self.folder_path)


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
