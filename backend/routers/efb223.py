"""
EFB 223 Generator Router
Upload 2 PDFs → Claude API extracts data → generates Excel + PDF → download ZIP.
"""
import os
import uuid
import shutil
import zipfile
import logging
import traceback
from datetime import datetime

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse

from services.efb223_service import parse_pdfs, generate_all_excel, generate_all_pdfs, generate_221_pdfs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/efb223", tags=["efb223"])

OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "efb223_outputs")


@router.post("/generate")
async def generate_efb223(
    efb_pdf: UploadFile = File(...),
    lv_pdf: UploadFile = File(...),
    bieter: str = Form("Bauceram GmbH"),
    nachlass: float = Form(0),
    password: str = Form("Bauceram2026"),
    form221_pdf: UploadFile = File(None),
):
    """Generate EFB 223 files from uploaded PDFs. Returns a ZIP."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured on server.")

    efb_bytes = await efb_pdf.read()
    lv_bytes = await lv_pdf.read()
    form221_bytes = await form221_pdf.read() if form221_pdf and form221_pdf.filename else None

    if len(efb_bytes) == 0 or len(lv_bytes) == 0:
        raise HTTPException(status_code=400, detail="Both EFB 223 and LV PDF files are required.")

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    job_id = uuid.uuid4().hex[:8]
    job_dir = os.path.join(OUTPUTS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    try:
        # Step 1: Parse PDFs with Claude API
        data = parse_pdfs(efb_bytes, lv_bytes, api_key)
        project = data.get("project", {})
        positions = data["positions"]

        # Step 2: Generate Excel files
        excel_files = generate_all_excel(positions, project, bieter, nachlass, job_dir)

        # Step 3: Generate PDF files
        pwd = password.strip() or None
        pdf_files = generate_all_pdfs(excel_files, project, bieter, pwd)

        # Step 4: Generate 221 PDFs (if template uploaded)
        form221_files = {}
        if form221_bytes and len(form221_bytes) > 0:
            datum = datetime.now().strftime("%d.%m.%Y")
            total_orig = excel_files.get("total_original", 0)
            form221_files = generate_221_pdfs(
                form221_bytes, total_orig, nachlass, bieter, datum, job_dir
            )

        # Step 5: Create ZIP
        vergabenummer = project.get("vergabenummer", "output")
        zip_name = f"EFB_223_{vergabenummer}.zip"
        zip_path = os.path.join(OUTPUTS_DIR, f"{job_id}.zip")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            all_files = {}
            all_files.update(excel_files)
            all_files.update(pdf_files)
            all_files.update(form221_files)
            for key_name, fpath in all_files.items():
                if isinstance(fpath, str) and os.path.isfile(fpath):
                    zf.write(fpath, os.path.basename(fpath))

        # Cleanup job directory (but keep the ZIP)
        shutil.rmtree(job_dir, ignore_errors=True)

        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=zip_name,
            headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"EFB 223 generation failed: {e}\n{traceback.format_exc()}")
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))
