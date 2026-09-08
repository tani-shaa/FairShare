"""
Comprehensive Unit Tests for Engineering Problems 1 - 7
=========================================================

Tests all 7 core engineering problems explicitly:
- PROBLEM 1: Confidence Scoring & Pydantic Validation
- PROBLEM 2: Printed Math Error Detection (Non-destructive)
- PROBLEM 3: True Proportional Tax & Service Charge Distribution
- PROBLEM 4: Shared Items Partition Invariant (sum == 1.0)
- PROBLEM 5: Deterministic Zero-Loss Rounding Reconciliation
- PROBLEM 6: Unassigned Items Gatekeeping
- PROBLEM 7: AI-Independent Deterministic Engine

Additional test added:
- PROBLEM 3 (confirmation lock): UnconfirmedBillException raised when
  is_confirmed_by_user is False [FIX-3]
"""

import pytest
import json
from pathlib import Path
from backend.schemas import (
    BillData,
    LineItem,
    TaxBreakdown,
    Member,
    MemberSettlement,
    BillSettlementReport,
)
from backend.engine import (
    validate_bill_math,
    check_unassigned_items,
    compute_item_shares_for_members,
    calculate_settlement,
    reconcile_rounding,
    UnassignedItemsException,
    UnconfirmedBillException,
)


def test_problem_1_confidence_and_validation():
    """
    PROBLEM 1: AI EXTRACTION IS NOT ALWAYS RELIABLE
    - Every extracted field has a confidence score.
    - Low-confidence fields (<0.75) are detected and flagged.
    - Invalid structures (e.g. negative prices) fail Pydantic validation.
    """
    item1 = LineItem(name="High Conf Item",      quantity=1.0, total_price=200.0, confidence=0.95)
    item2 = LineItem(name="Faded Thermal Item",  quantity=1.0, total_price=80.0,  confidence=0.55)

    bill = BillData(
        restaurant_name="Test Cafe",
        items=[item1, item2],
        subtotal=280.0,
        taxes=TaxBreakdown(total_tax=14.0, confidence=0.90),
        service_charge=28.0,
        printed_total=322.0,
        overall_confidence=0.75,
        low_confidence_fields=["Item 'Faded Thermal Item' (Confidence: 55%)"]
    )

    assert item1.confidence == 0.95
    assert item2.confidence == 0.55
    assert "Item 'Faded Thermal Item' (Confidence: 55%)" in bill.low_confidence_fields

    # Pydantic should reject negative total_price (ge=0 constraint)
    with pytest.raises(Exception):
        LineItem(name="Invalid Item", quantity=1.0, total_price=-50.0)


def test_problem_2_printed_math_error_detection():
    """
    PROBLEM 2: THE RECEIPT ITSELF MAY CONTAIN A MATHEMATICAL ERROR
    - Test against receipt B08 where printed total is ₹980.00,
      but calculated total is ₹1,019.50.
    - Neither value is silently altered.
    - Discrepancy is explicitly flagged.
    """
    dataset_path = Path(__file__).parent / "test_dataset" / "B08_printed_math_error.json"
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    bill = BillData(**data)
    bill = validate_bill_math(bill)

    assert bill.has_math_discrepancy is True
    assert bill.printed_total == 980.00
    assert bill.calculated_total == 1019.50
    assert bill.discrepancy_amount == 39.50
    assert "Printed total (₹980.00) doesn't match the calculated total (₹1019.50)" in bill.discrepancy_message


def test_problem_3_proportional_tax_service_charge():
    """
    PROBLEM 3: TAX AND SERVICE CHARGE MUST NOT BE DIVIDED EQUALLY
    - Scenario:
      Person A orders ₹60 Diet Coke.
      Person B orders ₹600 Biryani.
      Bill has 5% GST (₹33.00) and 10% Service Charge (₹66.00). Total = ₹759.00.
    - Under TRUE PROPORTIONAL formula:
      Person A weight = 60 / 660 = 1/11 (~9.09%)
      Person A Tax Share = 33 * (1/11) = ₹3.00
      Person A Service Charge = 66 * (1/11) = ₹6.00
      Person A Final Total = ₹60 + ₹3 + ₹6 = ₹69.00

      Person B weight = 600 / 660 = 10/11 (~90.91%)
      Person B Final Total = ₹600 + ₹30 + ₹60 = ₹690.00
    """
    member_a = Member(id="m_a", name="Alice (Coke Only)")
    member_b = Member(id="m_b", name="Bob (Biryani)")
    members  = [member_a, member_b]

    item_coke    = LineItem(id="i1", name="Diet Coke",           quantity=1.0, total_price=60.0,  assigned_members=["m_a"])
    item_biryani = LineItem(id="i2", name="Hyderabadi Biryani",  quantity=1.0, total_price=600.0, assigned_members=["m_b"])

    bill = BillData(
        restaurant_name="Proportional Test Restaurant",
        items=[item_coke, item_biryani],
        subtotal=660.0,
        taxes=TaxBreakdown(total_tax=33.0),
        service_charge=66.0,
        printed_total=759.0,
        is_confirmed_by_user=True,
    )

    report = calculate_settlement(bill, members)

    settlement_a = next(m for m in report.members if m.member_id == "m_a")
    settlement_b = next(m for m in report.members if m.member_id == "m_b")

    assert settlement_a.base_subtotal        == 60.0
    assert settlement_a.tax_share            == 3.00
    assert settlement_a.service_charge_share == 6.00
    assert settlement_a.final_total          == 69.00

    assert settlement_b.base_subtotal        == 600.0
    assert settlement_b.tax_share            == 30.00
    assert settlement_b.service_charge_share == 60.00
    assert settlement_b.final_total          == 690.00

    # Conservation check
    assert settlement_a.final_total + settlement_b.final_total == 759.00


def test_problem_3_confirmation_lock():
    """
    PROBLEM 3 (confirmation gate / Layer 3 Review Lock) [FIX-3]:
    - calculate_settlement() MUST raise UnconfirmedBillException when
      is_confirmed_by_user is False.
    - This ensures no arithmetic ever runs on unreviewed AI-extracted data.
    """
    member = Member(id="m1", name="Alice")
    item   = LineItem(id="i1", name="Dish", total_price=200.0, assigned_members=["m1"])

    # is_confirmed_by_user defaults to False — engine must refuse
    bill_unconfirmed = BillData(
        restaurant_name="Confirmation Gate Test",
        items=[item],
        printed_total=200.0,
        # is_confirmed_by_user intentionally NOT set (defaults to False)
    )

    with pytest.raises(UnconfirmedBillException) as exc_info:
        calculate_settlement(bill_unconfirmed, [member])

    assert "confirmed by a human" in str(exc_info.value).lower()

    # Once the user confirms, calculation must succeed
    bill_unconfirmed.is_confirmed_by_user = True
    report = calculate_settlement(bill_unconfirmed, [member])
    assert report.reconciled_sum == 200.00


def test_problem_4_shared_items_sum_to_one():
    """
    PROBLEM 4: SHARED ITEMS
    - ₹600 Biryani shared by Alice and Bob -> ₹300 each (share = 0.5).
    - ₹300 Appetizer split across 3 people -> ₹100 each (share = 1/3).
    - Invariant: sum of shares for each item == 1.0.
    """
    m1 = Member(id="m1", name="M1")
    m2 = Member(id="m2", name="M2")
    m3 = Member(id="m3", name="M3")
    members = [m1, m2, m3]

    item_shared_2   = LineItem(id="i1", name="Biryani",           total_price=600.0, assigned_members=["m1", "m2"])
    item_shared_all = LineItem(id="i2", name="Appetizer Platter", total_price=300.0, assigned_members=["m1", "m2", "m3"])

    shares_map = compute_item_shares_for_members([item_shared_2, item_shared_all], members)

    m1_shares = shares_map["m1"]
    assert len(m1_shares) == 2
    assert m1_shares[0].share_fraction == 0.5
    assert m1_shares[0].share_amount   == 300.0
    assert pytest.approx(m1_shares[1].share_fraction, 0.001) == 1.0 / 3.0
    assert m1_shares[1].share_amount == 100.0

    # Check invariant: sum of fractions for item i1 across all members == 1.0
    i1_fraction_sum = sum(
        share.share_fraction
        for m_shares in shares_map.values()
        for share in m_shares
        if share.item_id == "i1"
    )
    assert pytest.approx(i1_fraction_sum, 0.0001) == 1.0


def test_problem_5_rounding_reconciliation_exact_zero_loss():
    """
    PROBLEM 5: DETERMINISTIC ROUNDING RECONCILIATION
    - 3 people split ₹100.00.
    - Each raw = 33.333... -> Rounded = 33.33 -> Sum = 99.99 (missing 1 paise).
    - Engine assigns the +₹0.01 to the largest shareholder deterministically.
    - Invariant: sum(individual totals) == 100.00 EXACTLY.
    """
    m1 = Member(id="m1", name="Alice")
    m2 = Member(id="m2", name="Bob")
    m3 = Member(id="m3", name="Charlie")
    members = [m1, m2, m3]

    item = LineItem(id="i1", name="Shared Meal", total_price=100.0, assigned_members=["m1", "m2", "m3"])
    bill = BillData(
        restaurant_name="Rounding Test",
        items=[item],
        subtotal=100.0,
        taxes=TaxBreakdown(total_tax=0.0),
        printed_total=100.0,
        is_confirmed_by_user=True,
    )

    report = calculate_settlement(bill, members)

    assert report.is_zero_loss_exact is True
    assert report.reconciled_sum == 100.00

    totals = [m.final_total for m in report.members]
    assert sum(totals) == 100.00
    assert sorted(totals) == [33.33, 33.33, 33.34]
    assert len(report.rounding_reconciliation_details) > 0


def test_problem_6_unassigned_items_blocked():
    """
    PROBLEM 6: UNASSIGNED ITEMS MUST BLOCK CALCULATION
    - If any item has no assigned person, calculate_settlement raises
      UnassignedItemsException and lists the offending items.
    """
    m1 = Member(id="m1", name="Alice")
    members = [m1]

    item1 = LineItem(id="i1", name="Assigned Dish",       total_price=150.0, assigned_members=["m1"])
    item2 = LineItem(id="i2", name="Forgotten Appetizer", total_price=220.0, assigned_members=[])
    item3 = LineItem(id="i3", name="Unclaimed Soda",      total_price=40.0,  assigned_members=[])

    bill = BillData(
        restaurant_name="Unassigned Test",
        items=[item1, item2, item3],
        subtotal=410.0,
        printed_total=410.0,
        is_confirmed_by_user=True,
    )

    with pytest.raises(UnassignedItemsException) as exc_info:
        calculate_settlement(bill, members)

    assert len(exc_info.value.unassigned_items) == 2
    assert "2 items still need to be assigned" in str(exc_info.value)
    assert "'Forgotten Appetizer'" in str(exc_info.value)
    assert "'Unclaimed Soda'"      in str(exc_info.value)


def test_problem_7_ai_independence_and_determinism():
    """
    PROBLEM 7: AI FAILURE & ENGINE INDEPENDENCE
    - The calculation engine runs 100% deterministically without any AI API.
    - Testing with the 7-person full benchmark case (B11).
    - Running 20 times produces identical results every single time.
    """
    dataset_path = Path(__file__).parent / "test_dataset" / "B11_seven_people_full_dinner.json"
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    bill = BillData(**data)
    bill.is_confirmed_by_user = True

    # 7 Members
    members = [
        Member(id="m1", name="Alice"),
        Member(id="m2", name="Bob"),
        Member(id="m3", name="Charlie (Coke only)"),
        Member(id="m4", name="David (Left early)"),
        Member(id="m5", name="Emma"),
        Member(id="m6", name="Frank"),
        Member(id="m7", name="Grace"),
    ]

    # Assignments:
    bill.items[0].assigned_members = ["m1", "m2"]                                    # Biryani -> Alice & Bob
    bill.items[1].assigned_members = ["m3"]                                           # Diet Coke -> Charlie
    bill.items[2].assigned_members = ["m4"]                                           # Paneer Starter -> David
    bill.items[3].assigned_members = ["m5"]                                           # Butter Chicken -> Emma
    bill.items[4].assigned_members = ["m6"]                                           # Dal Makhani -> Frank
    bill.items[5].assigned_members = ["m7"]                                           # Grilled Fish -> Grace
    bill.items[6].assigned_members = ["m1", "m2", "m3", "m4", "m5", "m6", "m7"]     # Shared Appetizer -> all

    report = calculate_settlement(bill, members)

    assert report.is_zero_loss_exact is True
    assert report.reconciled_sum == 3151.00
    assert sum(m.final_total for m in report.members) == 3151.00

    # Charlie: Coke (₹60) + 1/7 appetizer (₹40) = ₹100 base
    # weight = 100 / 2740 ≈ 3.6496%
    # Tax share  = 137 × 3.6496% = ₹5.00
    # SC share   = 274 × 3.6496% = ₹10.00
    # Final      = ₹100 + ₹5 + ₹10 = ₹115.00
    charlie = next(m for m in report.members if m.member_id == "m3")
    assert charlie.base_subtotal        == 100.00
    assert charlie.tax_share            == 5.00
    assert charlie.service_charge_share == 10.00
    assert charlie.final_total          == 115.00

    # Determinism loop — same inputs must always produce identical outputs
    for _ in range(20):
        repeat = calculate_settlement(bill, members)
        assert repeat.reconciled_sum == 3151.00
        assert [m.final_total for m in repeat.members] == [m.final_total for m in report.members]
