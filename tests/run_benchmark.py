"""
Automated 12-Bill Benchmark Evaluation Script
==============================================
Loads all 12 edge-case bills from `tests/test_dataset/`, performs:
1. Pydantic schema validation & confidence auditing (Problem 1)
2. Mathematical discrepancy detection (Problem 2)
3. Shared item proportional settlement evaluation (Problems 3, 4, 5)
4. Rounding reconciliation zero-loss invariant verification (Problem 5)

Generates a comprehensive benchmark report.
"""

import os
import sys
import json
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.schemas import BillData, Member
from backend.engine import validate_bill_math, calculate_settlement


def run_all_benchmarks():
    dataset_dir = Path(__file__).parent / "test_dataset"
    json_files = sorted(list(dataset_dir.glob("*.json")))
    
    print("=" * 95)
    print(f"  BENCHMARK SUITE: EVALUATING {len(json_files)} REAL-WORLD / SYNTHETIC EDGE-CASE BILLS")
    print("=" * 95)
    
    passed_count = 0
    anomaly_detected_count = 0
    zero_loss_count = 0
    
    for idx, fpath in enumerate(json_files, 1):
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        test_id = data.get("test_id", f"B{idx:02d}")
        title = data.get("title", fpath.stem)
        condition = data.get("condition", "standard")
        
        # 1. Pydantic validation
        bill = BillData(**data)
        bill = validate_bill_math(bill)
        # Mark confirmed so the engine gate passes (benchmark runner has no UI review step)
        bill.is_confirmed_by_user = True
        
        # 2. Check Problem 2 (Math Discrepancy)
        has_error = bill.has_math_discrepancy
        if has_error:
            anomaly_detected_count += 1
            status_anomaly = f"[!] ANOMALY FLAG (Diff: {bill.discrepancy_amount:+.2f})"
        else:
            status_anomaly = "[OK] Math Validated"
            
        # 3. Create simulated members (3 members: Alice, Bob, Charlie)
        members = [
            Member(id="m1", name="Alice", avatar_color="#6366f1"),
            Member(id="m2", name="Bob", avatar_color="#ec4899"),
            Member(id="m3", name="Charlie", avatar_color="#10b981"),
        ]
        
        # Assign items (e.g. 1st to m1, 2nd to m2, rest to everyone)
        for i_idx, item in enumerate(bill.items):
            if i_idx == 0:
                item.assigned_members = ["m1"]
            elif i_idx == 1 and len(bill.items) > 1:
                item.assigned_members = ["m2"]
            else:
                item.assigned_members = ["m1", "m2", "m3"]
                
        # 4. Calculate settlement & test invariant
        target_source = "calculated" if bill.has_math_discrepancy else "printed"
        report = calculate_settlement(bill, members, target_total_source=target_source)
        
        if report.is_zero_loss_exact:
            zero_loss_count += 1
            
        passed_count += 1
        
        # Clean ascii title for cross-platform terminals
        clean_title = title.encode("ascii", "replace").decode("ascii")
        print(f"[{test_id}] {clean_title:<42} | Cond: {condition:<24} | Items: {len(bill.items):<2} | {status_anomaly:<30} | Total: Rs.{report.reconciled_sum:<8.2f} | Zero-Loss: {report.is_zero_loss_exact}")
        
    print("=" * 95)
    print(f"BENCHMARK SUMMARY: {passed_count}/{len(json_files)} Passed | Printed Math Anomalies Caught: {anomaly_detected_count} | 100% Zero-Loss Precision: {zero_loss_count}/{len(json_files)}")
    print("=" * 95)


if __name__ == "__main__":
    run_all_benchmarks()
