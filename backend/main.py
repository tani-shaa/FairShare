"""
FastAPI Server for Smart Bill Splitter (FairShare)
=================================================

Exposes endpoints for:
- Vision/OCR extraction & Fallback ingestion (Layer 1)
- Math validation & Anomaly detection (Layer 2)
- Human Review & Confirmation (Layer 3)
- Member Assignment & Fraction engine (Layer 4)
- Deterministic Proportional Calculation & Rounding Reconciliation (Layers 5 & 6)
- 12 Benchmark Test Dataset exploration
"""

import os
import json
from pathlib import Path
from typing import List, Optional

# Load .env file automatically if present (python-dotenv)
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.schemas import (
    BillData,
    Member,
    BillSettlementReport,
)
from backend.engine import (
    validate_bill_math,
    calculate_settlement,
    UnassignedItemsException,
    UnconfirmedBillException,
)
from backend.extraction import extract_bill_from_image_bytes
from backend.extraction import GEMINI_MODEL

app = FastAPI(
    title="Smart Bill Splitter (FairShare) API",
    description="Mathematical bill splitting engine with proportional tax distribution and printed anomaly detection.",
    version="1.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATASET_DIR = Path(__file__).parent.parent / "tests" / "test_dataset"
IMAGES_DIR = DATASET_DIR / "images"
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


class CalculationRequest(BaseModel):
    bill: BillData
    members: List[Member]
    target_total_source: str = "calculated"  # "calculated" or "printed"


@app.get("/api/status")
def api_status():
    """Returns whether Gemini AI extraction is configured and active."""
    key = os.getenv("GEMINI_API_KEY", "")
    ai_enabled = bool(key and key != "your_gemini_api_key_here")
    return {
        "ai_extraction": ai_enabled,
        "model": GEMINI_MODEL if ai_enabled else None,
        "message": f"{GEMINI_MODEL} - Image extraction active" if ai_enabled else "No API key — manual entry only",
        "average_response_time": "3-8 seconds" if ai_enabled else "N/A"
    }


@app.get("/api/benchmarks")
def get_benchmarks():
    """Returns the list of 12 benchmark edge-case test bills with ground truth."""
    benchmarks = []
    if DATASET_DIR.exists():
        for fpath in sorted(DATASET_DIR.glob("*.json")):
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                # Include image path if available
                image_path = data.get("image_path", None)
                image_url = None
                if image_path:
                    # Convert relative path to API URL
                    rel_path = Path(image_path).as_posix()
                    image_url = f"/api/images/{data.get('test_id', fpath.stem[:3])}.jpg"
                
                benchmarks.append({
                    "test_id": data.get("test_id", fpath.stem),
                    "title": data.get("title", fpath.stem),
                    "condition": data.get("condition", "standard"),
                    "description": data.get("description", ""),
                    "image_url": image_url,
                    "bill_data": data
                })
    return {"benchmarks": benchmarks}


@app.get("/api/benchmarks/{test_id}")
def get_benchmark_by_id(test_id: str):
    """Fetches a specific benchmark bill by ID (e.g. B01, B08, B11)."""
    for fpath in DATASET_DIR.glob("*.json"):
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("test_id") == test_id or fpath.stem.startswith(test_id):
                bill = BillData(**data)
                return validate_bill_math(bill)
    raise HTTPException(status_code=404, detail=f"Benchmark {test_id} not found")


@app.get("/api/images/{filename}")
def get_bill_image(filename: str):
    """Serves bill images for the test dataset."""
    image_path = IMAGES_DIR / filename
    if not image_path.exists():
        raise HTTPException(status_code=404, detail=f"Image {filename} not found")
    return FileResponse(image_path, media_type="image/jpeg")


@app.post("/api/extract", response_model=BillData)
async def extract_receipt(
    file: Optional[UploadFile] = File(None),
    api_key: Optional[str] = Form(None)
):
    """
    Ingests receipt image and runs Vision extraction with per-field confidence.
    Key resolution order:
      1. GEMINI_API_KEY environment variable (set in .env)
      2. api_key form field sent by the client
    PROBLEM 7: Falls back gracefully to manual-entry template if AI fails or no key.
    
    PERFORMANCE: Optimized for speed with image compression and faster model.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    # Prefer env var over anything sent from client
    resolved_key = os.getenv("GEMINI_API_KEY") or api_key or None

    if file:
        content = await file.read()
        mime = file.content_type or "image/jpeg"
        
        # Run extraction in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            bill = await loop.run_in_executor(
                pool,
                extract_bill_from_image_bytes,
                content,
                mime,
                resolved_key
            )
    else:
        bill = extract_bill_from_image_bytes(b"", mime_type="image/jpeg", api_key=None)

    return validate_bill_math(bill)


@app.post("/api/validate", response_model=BillData)
def validate_bill(bill: BillData):
    """
    PROBLEM 2: Mathematical discrepancy validator.
    Compares printed vs calculated totals and detects POS math errors.
    """
    return validate_bill_math(bill)


@app.post("/api/calculate", response_model=BillSettlementReport)
def calculate_bill_settlement(req: CalculationRequest):
    """
    Executes Layers 4, 5, 6:
    - Verifies all items assigned (PROBLEM 6)
    - Distributes shared items (PROBLEM 4)
    - Proportional tax/service charge allocation (PROBLEM 3)
    - Zero-loss deterministic rounding reconciliation (PROBLEM 5)
    """
    try:
        report = calculate_settlement(
            bill=req.bill,
            members=req.members,
            target_total_source=req.target_total_source
        )
        return report
    except UnassignedItemsException as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error_type": "UNASSIGNED_ITEMS",
                "message": str(e),
                "unassigned_item_ids": [item.id for item in e.unassigned_items]
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Mount static frontend if available
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
