"""
Data Models and Validation Layer (Layer 2)
=========================================
Implements strict Pydantic v2 models with per-field confidence scoring,
anomaly detection, member assignments, and settlement breakdown structures.

Addresses:
- PROBLEM 1: Per-field confidence scoring & schema validation
- PROBLEM 2: Printed vs Calculated discrepancy representation
- PROBLEM 4: Shared item assignment fractions
- PROBLEM 5: Deterministic rounded member shares
- PROBLEM 6: Unassigned items detection
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional, Dict, Any
from enum import Enum
import uuid


class ConfidenceLevel(str, Enum):
    HIGH = "high"       # >= 0.85
    MEDIUM = "medium"   # 0.60 - 0.84
    LOW = "low"         # < 0.60


def get_confidence_level(score: float) -> ConfidenceLevel:
    if score >= 0.85:
        return ConfidenceLevel.HIGH
    elif score >= 0.60:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


class FieldConfidence(BaseModel):
    """Encapsulates confidence metadata for individual fields."""
    value: Any
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_low_confidence: bool = False

    @model_validator(mode="after")
    def compute_low_flag(self):
        self.is_low_confidence = self.confidence < 0.75
        return self


class LineItem(BaseModel):
    """
    Represents a single line item on the bill.
    Each item has a unique ID, item name, quantity, unit price, total price,
    and a confidence rating (0.0 to 1.0) for visual review.
    """
    id: str = Field(default_factory=lambda: f"item_{uuid.uuid4().hex[:8]}")
    name: str = Field(..., min_length=1, description="Item name / description")
    quantity: float = Field(default=1.0, gt=0, description="Quantity of item")
    unit_price: Optional[float] = Field(default=None, ge=0, description="Unit price if available")
    total_price: float = Field(..., ge=0, description="Total price for this line item")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction confidence")
    raw_ocr_text: Optional[str] = Field(default=None, description="Original raw snippet from OCR")

    # Member assignment IDs (e.g. ['m1', 'm2'])
    assigned_members: List[str] = Field(default_factory=list, description="IDs of members assigned to this item")
    # Custom fractional split if non-equal (e.g. {'m1': 0.7, 'm2': 0.3})
    custom_shares: Optional[Dict[str, float]] = Field(default=None, description="Explicit share weights per member")

    @model_validator(mode="after")
    def infer_unit_price(self):
        if self.unit_price is None and self.quantity > 0:
            self.unit_price = round(self.total_price / self.quantity, 2)
        return self


class TaxBreakdown(BaseModel):
    """
    Itemized tax charges on the receipt.
    Handles CGST, SGST, VAT, and general sales taxes.
    """
    cgst: float = Field(default=0.0, ge=0.0)
    sgst: float = Field(default=0.0, ge=0.0)
    vat: float = Field(default=0.0, ge=0.0)
    other_tax: float = Field(default=0.0, ge=0.0)
    total_tax: float = Field(default=0.0, ge=0.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def compute_total_tax(self):
        itemized = self.cgst + self.sgst + self.vat + self.other_tax
        if self.total_tax == 0.0 and itemized > 0.0:
            self.total_tax = round(itemized, 2)
        elif self.total_tax > 0.0 and itemized == 0.0:
            # If only total tax is specified, leave it
            pass
        return self


class BillData(BaseModel):
    """
    Layer 2 Validated Bill Schema.
    Contains raw extracted data, per-field confidence, and anomaly check flags.
    """
    id: str = Field(default_factory=lambda: f"bill_{uuid.uuid4().hex[:8]}")
    restaurant_name: Optional[str] = Field(default="Restaurant", description="Name of the restaurant/venue")
    bill_number: Optional[str] = Field(default=None, description="Invoice or receipt number")
    date: Optional[str] = Field(default=None, description="Date of receipt")
    currency: str = Field(default="₹", description="Currency symbol (₹, $, €, etc.)")
    
    # Items
    items: List[LineItem] = Field(default_factory=list, description="Extracted line items")
    
    # Aggregate Financials
    subtotal: float = Field(default=0.0, ge=0.0, description="Subtotal of all line items")
    taxes: TaxBreakdown = Field(default_factory=TaxBreakdown, description="Taxes breakdown")
    service_charge: float = Field(default=0.0, ge=0.0, description="Service charge / hospitality fee")
    discount: float = Field(default=0.0, ge=0.0, description="Total discount applied")
    tip: float = Field(default=0.0, ge=0.0, description="Optional tip")
    round_off: float = Field(default=0.0, description="Round off adjustment (+/-)")
    printed_total: float = Field(default=0.0, ge=0.0, description="Total printed on the physical bill")
    
    # Confidence metrics
    overall_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    low_confidence_fields: List[str] = Field(default_factory=list)
    
    # PROBLEM 2: Mathematical discrepancy detection
    calculated_total: float = Field(default=0.0, description="Computed: items_subtotal + taxes + SC + tip - discount +/- round_off")
    has_math_discrepancy: bool = Field(default=False, description="True if printed_total != calculated_total")
    discrepancy_amount: float = Field(default=0.0, description="calculated_total - printed_total")
    discrepancy_message: Optional[str] = None
    
    # Layer 3 Review confirmation lock
    is_confirmed_by_user: bool = Field(default=False, description="Human review lock before calculation")


class Member(BaseModel):
    """A person participating in the bill split."""
    id: str = Field(default_factory=lambda: f"m_{uuid.uuid4().hex[:6]}")
    name: str = Field(..., min_length=1)
    avatar_color: str = Field(default="#6366f1", description="Hex color for UI avatar badge")


class MemberItemShare(BaseModel):
    """Detailed record of an item share consumed by a member."""
    item_id: str
    item_name: str
    item_total_price: float
    share_fraction: float = Field(..., ge=0.0, le=1.0, description="e.g. 0.5 for 50% share")
    share_amount: float = Field(..., ge=0.0, description="item_total_price * share_fraction")


class MemberSettlement(BaseModel):
    """
    Calculated and reconciled breakdown for a single member.
    """
    member_id: str
    member_name: str
    avatar_color: str
    
    # Consumption
    assigned_items: List[MemberItemShare] = Field(default_factory=list)
    base_subtotal: float = Field(default=0.0, description="Sum of member's individual item shares")
    consumption_weight: float = Field(default=0.0, ge=0.0, le=1.0, description="BaseSubtotal / TotalBase")
    
    # Proportional allocations
    discount_share: float = Field(default=0.0, description="Proportion of total discount")
    service_charge_share: float = Field(default=0.0, description="Proportion of service charge")
    tax_share: float = Field(default=0.0, description="Proportion of total taxes")
    tip_share: float = Field(default=0.0, description="Proportion of tip")
    
    # Final settlement
    raw_total: float = Field(default=0.0, description="Unrounded calculated total")
    final_total: float = Field(default=0.0, description="Rounded and reconciled final payable amount")
    rounding_adjustment: float = Field(default=0.0, description="Paise/cent adjustment applied during reconciliation")


class BillSettlementReport(BaseModel):
    """
    Complete settlement summary for all members.
    Guarantees exact conservation invariant: sum(member.final_total) == target_total.
    """
    bill_id: str
    target_total: float
    total_base_subtotal: float
    total_taxes: float
    total_service_charge: float
    total_discount: float
    total_tip: float
    
    members: List[MemberSettlement]
    
    # Invariant Verification
    reconciled_sum: float
    is_zero_loss_exact: bool = Field(default=True, description="True if reconciled_sum == target_total")
    rounding_reconciliation_details: List[str] = Field(default_factory=list)
    unassigned_items_count: int = 0
