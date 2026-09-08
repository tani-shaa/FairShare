# FairShare — Smart Bill Splitter

A full-stack restaurant bill splitting application that extracts structured data from receipt images using Google Gemini Vision AI, validates the arithmetic, and distributes costs proportionally among diners. Built for the ITgeeks contest.

---

## The Problem

Splitting a restaurant bill fairly is harder than it looks. Equal division ignores who ordered what. Taxes and service charges should be proportional to consumption, not divided by headcount. Printed receipts can contain arithmetic errors. Photos of receipts are often blurry, faded, or crumpled. This application solves all of it.

---

## Engineering Problems Solved

| # | Problem | Solution |
|---|---------|----------|
| 1 | Per-field OCR confidence scoring | Each extracted line item and tax entry carries a confidence score (0.0–1.0). Fields below 0.75 are flagged for human review before calculation proceeds. |
| 2 | Printed total may contain a POS arithmetic error | Calculated total is derived independently from line items. If it diverges from the printed total by more than ₹0.01, both values are preserved and the discrepancy is surfaced to the user. Neither value is silently altered. |
| 3 | Tax and service charge must be distributed proportionally | Each person's share of taxes, service charge, discount, and tip is weighted by their base consumption relative to the table total, not divided equally by headcount. |
| 4 | Items shared by multiple people | Each shared item is split into fractional shares. The sum of all shares for any item is guaranteed to equal 1.0. Custom unequal splits are also supported. |
| 5 | Floating-point rounding drift | After proportional allocation, individual amounts are rounded to two decimal places. Any residual drift (typically ±0.01) is assigned deterministically to the largest consumer using the Largest Remainder algorithm, guaranteeing `sum(final_totals) == target_total` exactly. |
| 6 | Unassigned items must block calculation | The settlement engine raises `UnassignedItemsException` if any line item has no assigned member. The API returns a structured error listing the unassigned item IDs. |
| 7 | AI extraction failure must not crash the application | If the Gemini API call fails, times out, or returns malformed JSON, the system falls back silently to a manual-entry template. The user can then type in the bill data themselves. |

---

## Architecture

```
ITgeeks/
├── backend/
│   ├── main.py          FastAPI application, REST endpoints
│   ├── engine.py        Deterministic math engine (Problems 2-6)
│   ├── extraction.py    Gemini Vision AI extraction layer (Problems 1, 7)
│   ├── schemas.py       Pydantic v2 data models
│   └── requirements.txt
├── frontend/
│   ├── index.html       Single-page application
│   ├── app.js           Client-side logic and state management
│   └── style.css        Styles
├── tests/
│   ├── test_engine.py   Unit tests for all 7 problems
│   ├── run_benchmark.py Benchmark runner for all 12 test cases
│   └── test_dataset/
│       ├── B01_dim_light.json         Ground truth data
│       ├── ...                        (12 test cases total)
│       └── images/
│           ├── B01.jpg                Synthetic bill photo
│           └── ...                   (12 images total)
├── ground_truth.json    Master reference for benchmark evaluation
├── generate_bill_images.py  Regenerates synthetic bill images
├── conftest.py          Pytest path configuration
└── .env.example         Environment variable template
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | AI extraction status and active model |
| POST | `/api/extract` | Extract bill data from a receipt image |
| POST | `/api/validate` | Validate bill arithmetic (Problem 2) |
| POST | `/api/calculate` | Run full settlement calculation (Problems 3–6) |
| GET | `/api/benchmarks` | List all 12 benchmark test cases with image URLs |
| GET | `/api/benchmarks/{id}` | Fetch a specific benchmark by ID (B01–B12) |
| GET | `/api/images/{filename}` | Serve a test case bill image |

---

## Test Dataset

12 synthetic test cases covering the edge conditions most likely to cause failures in real-world bill splitting.

| ID | Condition | Description |
|----|-----------|-------------|
| B01 | Dim lighting | Low ambient light, shadow across totals |
| B02 | Crumpled paper | Pocket-crushed receipt with diagonal creases |
| B03 | Steep angle | Receipt photographed at a sharp perspective |
| B04 | Faded thermal | Degraded thermal paper, low contrast text |
| B05 | Handwritten annotation | Tip and notes added by hand after printing |
| B06 | Dual script | Bilingual receipt with English and Hindi text |
| B07 | Long receipt (2 photos) | Banquet bill spanning two stitched photographs |
| B08 | Printed arithmetic error | POS-printed total does not match line item sum |
| B09 | Heavy promotional discount | Item-level and order-level discounts combined |
| B10 | Split GST + service charge | Explicit CGST (2.5%) + SGST (2.5%) + 10% service |
| B11 | Seven-person dinner | Complex shared item assignment across 7 members |
| B12 | High-density cafe bill | 14 line items on a single receipt |

Each test case includes ground truth JSON and a corresponding synthetic receipt image with a visual effect matching the condition (brightness reduction, crease lines, perspective skew, grayscale fading, etc.).

**Important:** These 12 bill images are synthetically generated using Pillow from the ground truth JSON data. They are rendered programmatically to simulate real-world capture conditions — they are not photographs of actual restaurant bills. The purpose is reproducible, deterministic testing of the extraction and math pipeline across known edge cases. To test with real photographs, replace the images in `tests/test_dataset/images/` with your own and run the benchmark.

---

## Setup

### Prerequisites

- Python 3.10 or higher
- A Google Gemini API key (free tier available at [aistudio.google.com](https://aistudio.google.com))

### Installation

```bash
# Clone the repository
git clone https://github.com/tani-shaa/FairShare.git
cd FairShare

# Install dependencies
pip install -r backend/requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=your_key_here
```

### Running the Application

```bash
uvicorn backend.main:app --reload
```

Open `http://localhost:8000` in a browser.

If no API key is configured, the application runs in manual entry mode — the user types in the bill data directly. All downstream math (Problems 2–6) works identically regardless of how the data was entered.

---

## Running Tests

```bash
# Unit tests (Problems 1–7)
pytest tests/test_engine.py -v

# Benchmark against all 12 test cases
python tests/run_benchmark.py
```

All 8 unit tests pass against the current codebase.

---

## Regenerating Bill Images

The synthetic receipt images in `tests/test_dataset/images/` are generated programmatically from the ground truth JSON data using Pillow. To regenerate them:

```bash
python generate_bill_images.py
```

Each image has a visual effect applied that matches its test condition (e.g. B04 is rendered in grayscale with reduced contrast to simulate faded thermal paper).

---

## Key Design Decisions

**Separation of extraction and calculation.** The AI extraction layer (`extraction.py`) and the math engine (`engine.py`) are entirely independent. The engine has no knowledge of Gemini or any API. This means the calculation logic can be tested exhaustively without any network calls, and it degrades gracefully when AI is unavailable.

**Non-destructive discrepancy handling.** When the calculated total differs from the printed total, both values are stored on the bill object. The user chooses which to use as the settlement target. The system never silently corrects the bill.

**Confirmation gate.** The `calculate_settlement` function raises `UnconfirmedBillException` if `is_confirmed_by_user` is `False`. This prevents the engine from running calculations on unreviewed AI-extracted data.

**Deterministic rounding.** Rounding adjustments are applied in a fixed order (largest consumer first, breaking ties by member ID). Given the same inputs, the output is always identical.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | No | Enables AI receipt extraction. Without it, the app runs in manual entry mode. |
| `GEMINI_MODEL` | No | Overrides the Gemini model used for extraction. Defaults to `gemini-3.5-flash`. Useful if a specific model is unavailable in your region. |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| fastapi | REST API framework |
| uvicorn | ASGI server |
| pydantic | Data validation and serialisation |
| python-multipart | Multipart file upload support |
| python-dotenv | `.env` file loading |
| `google-generativeai` | Gemini Vision API client (legacy SDK, retained for compatibility) |
| `google-genai` | Gemini Vision API client (current SDK, used for extraction) |
| pillow | Image optimisation before API call, synthetic image generation |
| pytest | Test runner |
| httpx | HTTP client for tests |
