"""
Extraction Layer (Layer 1) & Fallback Engine
============================================

Extracts structured bill data from images using Multimodal Vision AI or local heuristic
OCR fallback, applying per-field confidence scoring and graceful error recovery.

Addresses:
- PROBLEM 1: Per-field confidence score assignment & low-confidence highlighting
- PROBLEM 7: AI Failure handling with seamless fallback to Manual Entry Mode
"""

import os
import json
import base64
import logging
from typing import Optional, List, Dict, Any
from backend.schemas import BillData, LineItem, TaxBreakdown
from backend.engine import validate_bill_math

logger = logging.getLogger("ExtractionLayer")

# Keep the default on a stable model. It is still overrideable for a
# deployment that has access to a different Gemini model.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")


EXTRACTION_SYSTEM_PROMPT = """
You are an expert receipt extraction engine. Analyze the provided receipt image(s) and output a clean, strict JSON object.
Extract all line items, their individual quantities, unit prices, and total prices.
Extract financial totals: subtotal, taxes (CGST, SGST, VAT, or general tax), service charge, discounts, tips, round off, and printed total.

Assign an estimated extraction confidence score (between 0.00 and 1.00) to:
- each line item (if text is faded, blurry, or folded, lower the confidence < 0.70)
- the overall extraction

Return ONLY a JSON object matching this schema:
{
  "restaurant_name": "string",
  "bill_number": "string or null",
  "date": "string or null",
  "currency": "₹",
  "items": [
    {
      "name": "string",
      "quantity": 1.0,
      "unit_price": 100.0,
      "total_price": 100.0,
      "confidence": 0.95
    }
  ],
  "subtotal": 100.0,
  "taxes": {
    "cgst": 2.5,
    "sgst": 2.5,
    "vat": 0.0,
    "other_tax": 0.0,
    "total_tax": 5.0,
    "confidence": 0.95
  },
  "service_charge": 10.0,
  "discount": 0.0,
  "tip": 0.0,
  "round_off": 0.0,
  "printed_total": 115.0,
  "overall_confidence": 0.92
}
"""


def extract_bill_from_image_bytes(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    api_key: Optional[str] = None
) -> BillData:
    """
    Attempts extraction via Multimodal Vision AI (Gemini / Claude / OpenAI if key available)
    or falls back gracefully to deterministic rule-based heuristic extraction.
    
    PROBLEM 7: AI FAILURE RESILIENCE
    ================================
    If the API call fails or model returns invalid/truncated JSON, this function
    catches the exception, initializes a clean editable BillData model with warning flags,
    and allows the user to perform manual entry or correction.
    
    PERFORMANCE OPTIMIZATIONS:
    - Image compression before API call
    - Current multimodal model (configurable with GEMINI_MODEL)
    - Reduced temperature for faster convergence
    - Timeout handling
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    
    if api_key:
        try:
            # Optimize image size before sending to API
            optimized_bytes = _optimize_image_for_api(image_bytes, mime_type)
            bill = _call_gemini_vision(optimized_bytes, mime_type, api_key)
            bill.extraction_source = "vision"
            return bill
        except Exception as e:
            # Keep the actual provider error in server logs, but return a safe,
            # actionable message to the browser instead of silently showing a
            # fake receipt as if it had been read successfully.
            logger.exception("Vision API extraction failed; using manual mode")
            return _heuristic_fallback_extraction(
                image_bytes,
                warning="AI could not read this image. Check the Gemini model/API key, then try uploading again.",
            )
            
    # Fallback to smart heuristic / template extraction
    return _heuristic_fallback_extraction(
        image_bytes,
        warning="Image reading is not enabled yet. Add GEMINI_API_KEY to enable automatic receipt extraction.",
    )


def _optimize_image_for_api(image_bytes: bytes, mime_type: str) -> bytes:
    """
    Optimize image size for faster API processing while maintaining quality.
    - Resize large images to max 1024px on longest side
    - Compress to reduce payload size
    - Convert to JPEG if needed
    """
    try:
        from PIL import Image
        from io import BytesIO
        
        # Load image
        img = Image.open(BytesIO(image_bytes))
        
        # Convert RGBA to RGB if needed
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        
        # Resize if too large (max 1024px on longest side for speed)
        max_size = 1024
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            logger.info(f"Resized image from {image_bytes.__sizeof__()} to {new_size} for faster processing")
        
        # Compress to JPEG with good quality
        output = BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        optimized_bytes = output.getvalue()
        
        # Log compression ratio
        original_size = len(image_bytes) / 1024
        optimized_size = len(optimized_bytes) / 1024
        logger.info(f"Image optimized: {original_size:.1f}KB → {optimized_size:.1f}KB ({optimized_size/original_size*100:.1f}%)")
        
        return optimized_bytes
        
    except Exception as e:
        logger.warning(f"Image optimization failed: {e}, using original")
        return image_bytes


def _call_gemini_vision(image_bytes: bytes, mime_type: str, api_key: str) -> BillData:
    """Calls Gemini Multimodal API to parse receipt image.
    
    Uses Google's current google-genai SDK. The API key stays server-side;
    the browser only uploads the image.
    
    PERFORMANCE OPTIMIZATIONS:
    - Uses a configurable current multimodal model
    - Lower temperature (0.05) for faster convergence
    - Strict JSON mode for faster parsing
    - Request timeout handling
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError(
            "google-genai package not installed. "
            "Run: pip install google-genai"
        )

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=30_000),
    )

    # Build the multimodal prompt: text instruction + image bytes
    image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
    
    # Generate with timeout
    logger.info("Calling Gemini Vision API...")
    start_time = __import__('time').time()
    
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[EXTRACTION_SYSTEM_PROMPT, image_part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.05,
            top_p=0.95,
            top_k=40,
            max_output_tokens=2048,
        ),
    )
    
    elapsed = __import__('time').time() - start_time
    logger.info(f"Gemini API responded in {elapsed:.2f}s")

    parsed_json = json.loads(response.text)

    # Construct and validate BillData
    bill = BillData(**parsed_json)

    # Identify low confidence fields (PROBLEM 1)
    low_conf = []
    for item in bill.items:
        if item.confidence < 0.75:
            low_conf.append(f"Item '{item.name}' (Confidence: {int(item.confidence * 100)}%)")
    if bill.taxes.confidence < 0.75:
        low_conf.append("Taxes Breakdown (Low Confidence)")

    bill.low_confidence_fields = low_conf
    return validate_bill_math(bill)


def _heuristic_fallback_extraction(
    image_bytes: bytes,
    warning: Optional[str] = None,
) -> BillData:
    """
    Fallback parser when no external AI API key is configured.
    Returns a structured starter template with confidence flags.
    """
    # Never invent receipt contents. An empty editable bill is safer than
    # presenting unrelated sample items as the result of reading the photo.
    bill = BillData(
        restaurant_name="",
        bill_number="",
        date=None,
        currency="₹",
        items=[],
        subtotal=0.0,
        taxes=TaxBreakdown(),
        service_charge=0.0,
        discount=0.0,
        tip=0.0,
        round_off=0.0,
        printed_total=0.0,
        overall_confidence=0.0,
        low_confidence_fields=["All fields need manual entry"],
        extraction_source="fallback",
        extraction_warning=warning,
    )
    
    return validate_bill_math(bill)
