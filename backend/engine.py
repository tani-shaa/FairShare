"""
Mathematical Calculation and Reconciliation Engine (Layers 5 & 6)
=================================================================

This module is 100% deterministic, standalone, and completely independent of any
AI vision or OCR APIs. Given validated BillData and Member assignments, it performs:

1. PROBLEM 2: Printed vs Calculated Anomaly Detection
2. PROBLEM 4: Shared Item Fraction Partitioning (sum of shares == 1.0)
3. PROBLEM 6: Unassigned Item Gatekeeping (halts calculation if items unassigned)
4. PROBLEM 3: Proportional Tax, Surcharge, Discount & Tip Allocation
5. PROBLEM 5: Deterministic Rounding Reconciliation (zero rounding drift guarantee)
"""

from typing import List, Dict, Tuple, Optional
import math
from backend.schemas import (
    BillData,
    LineItem,
    Member,
    MemberItemShare,
    MemberSettlement,
    BillSettlementReport,
)


class UnassignedItemsException(Exception):
    """Raised when one or more line items have not been assigned to any member."""
    def __init__(self, unassigned_items: List[LineItem]):
        self.unassigned_items = unassigned_items
        item_names = [f"'{item.name}' (₹{item.total_price:.2f})" for item in unassigned_items]
        msg = f"{len(unassigned_items)} items still need to be assigned: {', '.join(item_names)}"
        super().__init__(msg)


class UnconfirmedBillException(Exception):
    """Raised when calculation is requested before human review confirmation."""
    def __init__(self, message: str = "Bill data must be confirmed by a human before calculation."):
        super().__init__(message)


def validate_bill_math(bill: BillData) -> BillData:
    """
    PROBLEM 2: THE RECEIPT ITSELF MAY CONTAIN A MATHEMATICAL ERROR
    ===============================================================
    Physical receipts printed by restaurant POS machines can contain genuine arithmetic
    errors (misapplied tax rates, manual discounts, missed items, or rounding flaws).
    
    We calculate:
        Calculated Total = sum(item prices) - discount + total taxes + service charge + tip +/- round off
    
    We compare `calculated_total` vs `printed_total`.
    If discrepancy > 0.01:
        - Sets `has_math_discrepancy = True`
        - Computes exact `discrepancy_amount`
        - Formulates a transparent warning message
    
    NEITHER value is silently altered. Both are preserved so the user can review.
    """
    items_sum = sum(item.total_price for item in bill.items)
    bill.subtotal = round(items_sum, 2)
    
    # Calculate taxes total if not already set
    taxes_total = bill.taxes.total_tax
    if taxes_total == 0.0:
        taxes_total = bill.taxes.cgst + bill.taxes.sgst + bill.taxes.vat + bill.taxes.other_tax
        bill.taxes.total_tax = round(taxes_total, 2)
    
    expected_total = (
        bill.subtotal
        - bill.discount
        + bill.taxes.total_tax
        + bill.service_charge
        + bill.tip
        + bill.round_off
    )
    bill.calculated_total = round(expected_total, 2)
    
    # Compare with printed total
    discrepancy = round(bill.calculated_total - bill.printed_total, 2)
    if abs(discrepancy) > 0.01:
        bill.has_math_discrepancy = True
        bill.discrepancy_amount = discrepancy
        diff_str = f"+₹{discrepancy:.2f}" if discrepancy > 0 else f"-₹{abs(discrepancy):.2f}"
        bill.discrepancy_message = (
            f"⚠️ Printed total (₹{bill.printed_total:.2f}) doesn't match the calculated total "
            f"(₹{bill.calculated_total:.2f}). Difference: {diff_str}."
        )
    else:
        bill.has_math_discrepancy = False
        bill.discrepancy_amount = 0.0
        bill.discrepancy_message = None

    return bill


def check_unassigned_items(items: List[LineItem]) -> List[LineItem]:
    """
    PROBLEM 6: UNASSIGNED ITEMS DETECTION
    =====================================
    Scans all items to ensure every line item has at least one assigned member.
    Returns list of unassigned items.
    """
    unassigned = []
    for item in items:
        if not item.assigned_members or len(item.assigned_members) == 0:
            unassigned.append(item)
    return unassigned


def compute_item_shares_for_members(
    items: List[LineItem],
    members: List[Member]
) -> Dict[str, List[MemberItemShare]]:
    """
    PROBLEM 4: SHARED ITEMS ALLOCATION
    ==================================
    An item may belong to:
    - One person (share = 1.0)
    - Multiple people (e.g. Biryani split between A and B -> share = 0.5 each)
    - Everyone (share = 1/N each)
    
    Invariant: For each assigned item i:
        sum(shares for all assigned members) == 1.0
    
    Example:
        ₹600 Biryani shared by A and B:
        A share = 0.5 -> pays ₹300
        B share = 0.5 -> pays ₹300
    """
    member_map = {m.id: m for m in members}
    member_shares: Dict[str, List[MemberItemShare]] = {m.id: [] for m in members}
    
    for item in items:
        assigned_ids = [m_id for m_id in item.assigned_members if m_id in member_map]
        num_assigned = len(assigned_ids)
        
        if num_assigned == 0:
            continue
            
        # Determine fractional share per assigned member
        if item.custom_shares and len(item.custom_shares) > 0:
            # Normalize custom shares so they sum to 1.0
            custom_total = sum(item.custom_shares.get(mid, 0.0) for mid in assigned_ids)
            if custom_total > 0:
                shares = {mid: item.custom_shares.get(mid, 0.0) / custom_total for mid in assigned_ids}
            else:
                shares = {mid: 1.0 / num_assigned for mid in assigned_ids}
        else:
            # Equal division among assigned members
            shares = {mid: 1.0 / num_assigned for mid in assigned_ids}
            
        for mid in assigned_ids:
            fraction = shares[mid]
            share_amt = round(item.total_price * fraction, 4)
            member_shares[mid].append(
                MemberItemShare(
                    item_id=item.id,
                    item_name=item.name,
                    item_total_price=item.total_price,
                    share_fraction=fraction,
                    share_amount=share_amt
                )
            )
            
    return member_shares


def calculate_settlement(
    bill: BillData,
    members: List[Member],
    target_total_source: str = "calculated"  # "calculated" or "printed"
) -> BillSettlementReport:
    """
    CORE MATHEMATICAL ENGINE (Problems 3, 4, 5, 6)
    =============================================
    
    PROBLEM 3 — PROPORTIONAL TAX AND SERVICE CHARGE ALLOCATION:
    -----------------------------------------------------------
    Taxes and service charges MUST NOT be divided equally (1/N).
    
    Step 1: Calculate each person's consumption (BaseShare):
        BaseShare(person) = sum(item_price * share_fraction for all assigned items)
        
    Step 2: Calculate consumption weight:
        weight(person) = BaseShare(person) / TotalBase
        
    Step 3: Distribute surcharges and deductions proportionally:
        TaxShare(person) = TotalTax * weight(person)
        ServiceChargeShare(person) = TotalServiceCharge * weight(person)
        DiscountShare(person) = TotalDiscount * weight(person)
        TipShare(person) = TotalTip * weight(person)
        
    PROBLEM 5 — DETERMINISTIC ROUNDING RECONCILIATION:
    --------------------------------------------------
    Rounding individual raw amounts creates fractional cent/paise drift.
    We guarantee:
        sum(person.final_total for person in members) == TargetTotal
    Any residual discrepancy (+/- 0.01) is distributed deterministically to the
    largest shareholder(s).
    """
    # 0. Confirmation gate (PROBLEM 1 / Layer 3 Review Lock)
    # The bill MUST be confirmed by a human before any arithmetic is performed.
    # This prevents calculations running on unreviewed AI-extracted data.
    if not bill.is_confirmed_by_user:
        raise UnconfirmedBillException()

    # 1. Gatekeeping: Check unassigned items (PROBLEM 6)
    unassigned = check_unassigned_items(bill.items)
    if unassigned:
        raise UnassignedItemsException(unassigned)
        
    if not members or len(members) == 0:
        raise ValueError("At least one member must be defined.")

    # 2. Refresh math and totals (PROBLEM 2)
    bill = validate_bill_math(bill)
    
    target_total = bill.calculated_total if target_total_source == "calculated" else bill.printed_total

    # 3. Compute item shares (PROBLEM 4)
    member_item_shares = compute_item_shares_for_members(bill.items, members)
    
    # 4. Calculate individual BaseShare and TotalBase
    base_subtotals: Dict[str, float] = {}
    for m in members:
        base_subtotals[m.id] = sum(s.share_amount for s in member_item_shares[m.id])
        
    total_base = sum(base_subtotals.values())
    
    # 5. Calculate proportional weights (PROBLEM 3)
    member_settlements: List[MemberSettlement] = []
    
    total_tax = bill.taxes.total_tax
    total_sc = bill.service_charge
    total_disc = bill.discount
    total_tip = bill.tip
    
    for m in members:
        base = base_subtotals[m.id]
        weight = (base / total_base) if total_base > 0 else (1.0 / len(members))
        
        tax_share = total_tax * weight
        sc_share = total_sc * weight
        disc_share = total_disc * weight
        tip_share = total_tip * weight
        
        raw_total = base - disc_share + sc_share + tax_share + tip_share
        
        member_settlements.append(
            MemberSettlement(
                member_id=m.id,
                member_name=m.name,
                avatar_color=m.avatar_color,
                assigned_items=member_item_shares[m.id],
                base_subtotal=round(base, 2),
                consumption_weight=round(weight, 4),
                discount_share=round(disc_share, 2),
                service_charge_share=round(sc_share, 2),
                tax_share=round(tax_share, 2),
                tip_share=round(tip_share, 2),
                raw_total=round(raw_total, 4),
                final_total=round(raw_total, 2), # Initial rounded total before reconciliation
                rounding_adjustment=0.0
            )
        )

    # 6. Reconcile Rounding (PROBLEM 5)
    reconciled_settlements, reconciliation_notes = reconcile_rounding(
        member_settlements,
        target_total=target_total
    )
    
    reconciled_sum = round(sum(m.final_total for m in reconciled_settlements), 2)
    is_exact = abs(reconciled_sum - target_total) < 0.001
    
    return BillSettlementReport(
        bill_id=bill.id,
        target_total=round(target_total, 2),
        total_base_subtotal=round(total_base, 2),
        total_taxes=round(total_tax, 2),
        total_service_charge=round(total_sc, 2),
        total_discount=round(total_disc, 2),
        total_tip=round(total_tip, 2),
        members=reconciled_settlements,
        reconciled_sum=reconciled_sum,
        is_zero_loss_exact=is_exact,
        rounding_reconciliation_details=reconciliation_notes,
        unassigned_items_count=0
    )


def reconcile_rounding(
    settlements: List[MemberSettlement],
    target_total: float
) -> Tuple[List[MemberSettlement], List[str]]:
    """
    PROBLEM 5: DETERMINISTIC ZERO-LOSS ROUNDING RECONCILIATION
    =========================================================
    Due to floating point cents/paise divisions, sum(round(final_total, 2))
    may differ from target_total by +/- 0.01 or 0.02.
    
    Algorithm (Largest Remainder / Shareholder Allocation):
    1. Calculate difference delta = round(target_total - sum(rounded_totals), 2).
    2. If delta == 0: Perfect match!
    3. If delta != 0:
       - Convert delta to integer units of currency precision (e.g. cents/paise: delta_cents = round(delta * 100)).
       - Sort members by (base_subtotal DESC, member_id ASC) to give priority deterministically to the largest consumer.
       - Add/subtract 0.01 iteratively until delta_cents is fully resolved.
       - Record explicit audit trail in reconciliation notes.
    
    Guarantee: sum(settlement.final_total) == target_total down to exact 0.00.
    """
    current_sum = round(sum(m.final_total for m in settlements), 2)
    diff = round(target_total - current_sum, 2)
    
    notes: List[str] = []
    
    if abs(diff) < 0.001:
        notes.append("Rounding check passed: Sum matches bill total exactly without adjustments.")
        return settlements, notes
        
    diff_cents = int(round(diff * 100)) # e.g. +2 paise or -1 paise
    step = 0.01 if diff_cents > 0 else -0.01
    steps_needed = abs(diff_cents)
    
    # Sort deterministically: highest consumption first
    sorted_indices = sorted(
        range(len(settlements)),
        key=lambda idx: (settlements[idx].base_subtotal, settlements[idx].member_id),
        reverse=True
    )
    
    for i in range(steps_needed):
        target_idx = sorted_indices[i % len(sorted_indices)]
        member = settlements[target_idx]
        
        member.final_total = round(member.final_total + step, 2)
        member.rounding_adjustment = round(member.rounding_adjustment + step, 2)
        
        direction_str = "added to" if step > 0 else "deducted from"
        notes.append(
            f"Deterministic rounding: ₹{abs(step):.2f} {direction_str} {member.member_name} "
            f"(largest shareholder) to reconcile fractional rounding drift."
        )
        
    return settlements, notes
