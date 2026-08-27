#!/usr/bin/env python3
"""Read-only Phase 3 evidence/invariant checks; not a general JSON Schema engine."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


DOSSIER = Path(__file__).resolve().parent
ROOT = DOSSIER.parent.parent


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")


def read_json(name: str) -> dict:
    return json.loads(
        (DOSSIER / name).read_text(encoding="utf-8"),
        object_pairs_hook=unique_pairs,
        parse_constant=invalid_constant,
    )


def local_path(locator: str) -> Path:
    path = (ROOT / locator.split("#", 1)[0]).resolve()
    require(path.is_relative_to(ROOT), f"Locator outside repository: {locator}")
    require(path.is_file(), f"Missing artifact: {locator}")
    return path


def verify() -> dict:
    baseline = read_json("BASELINE.json")
    intake = read_json("qa-intake.json")
    inventory = read_json("artifact-inventory.json")
    plan = read_json("review-plan.json")
    record = read_json("review-record.json")
    disposition = read_json("disposition.json")
    coverage = read_json("coverage.json")
    executions = read_json("executions.json")["executions"]
    control = read_json("CONTROL.json")
    engagement = intake["engagement_id"]
    for obj in (inventory, plan, record, disposition, coverage, control):
        require(obj["engagement_id"] == engagement, "Engagement ID mismatch")
    for obj in (intake, inventory, plan, record, disposition):
        require(obj["schema_version"] == "1.0.0", "Contract version mismatch")

    require(len(baseline["files"]) == 152, "Unexpected frozen baseline size")
    for entry in baseline["files"]:
        payload = local_path(entry["path"]).read_bytes()
        require(len(payload) == entry["size_bytes"], f"Baseline size changed: {entry['path']}")
        require(hashlib.sha256(payload).hexdigest() == entry["sha256"],
                f"Baseline hash changed: {entry['path']}")

    artifacts = {item["artifact_id"]: item for item in inventory["artifacts"]}
    require(len(artifacts) == len(inventory["artifacts"]), "Duplicate artifact IDs")
    for artifact in artifacts.values():
        path = local_path(artifact["locator"])
        if artifact["integrity"]["verification_status"] == "hash_verified":
            require(hashlib.sha256(path.read_bytes()).hexdigest() == artifact["integrity"]["sha256"],
                    f"Inventory hash changed: {path.name}")
    for item in intake["artifacts"]:
        peer = artifacts[item["artifact_id"]]
        require(item["locator"] == peer["locator"], "Intake/inventory locator mismatch")
        require(item["sha256"] == peer["integrity"]["sha256"], "Intake/inventory hash mismatch")
    require(plan["artifact_inventory_id"] == inventory["inventory_id"], "Inventory linkage mismatch")
    require(record["plan_id"] == plan["plan_id"], "Review plan linkage mismatch")
    require(disposition["review_record_ids"] == [record["review_record_id"]], "Disposition linkage mismatch")
    for artifact_id in plan["scope"]["included_artifact_ids"] + record["artifact_ids_reviewed"]:
        require(artifact_id in artifacts, f"Unresolved artifact ID: {artifact_id}")

    checks = {check["check_id"] for check in plan["check_selection"]}
    results = {result["check_id"] for result in record["check_results"]}
    require(len(checks) == len(plan["check_selection"]), "Duplicate planned check IDs")
    require(len(results) == len(record["check_results"]), "Duplicate result check IDs")
    require(checks == results, "Planned/performed check coverage mismatch")
    for result in record["check_results"]:
        require(result["status"] in {"pass", "fail", "not_applicable", "not_performed", "inconclusive"},
                "Unknown check status")
        if result["status"] in {"pass", "fail"}:
            require(bool(result["evidence"]), "Conclusion without evidence")
        if result["status"] in {"not_performed", "inconclusive"}:
            require(bool(result.get("limitation")), "Incomplete check without limitation")
        for evidence in result["evidence"]:
            require(evidence["artifact_id"] in artifacts, "Evidence artifact ID unresolved")
            local_path(evidence["locator"])

    findings = {finding["finding_id"]: finding for finding in record["findings"]}
    require(len(findings) == len(record["findings"]), "Duplicate finding IDs")
    open_findings = [f for f in findings.values() if f["current_state"] not in {"closed", "rejected", "superseded"}]
    counts = {severity: sum(f.get("severity") == severity for f in open_findings)
              for severity in ("critical", "high", "medium", "low")}
    require(counts == disposition["open_defect_counts"], "Open severity counts do not reconcile")
    blocking = sorted(f["finding_id"] for f in open_findings if f["readiness_impact"] == "blocking")
    require(blocking == sorted(disposition["blocking_open_finding_ids"]), "Blocking findings mismatch")
    nonblocking = sorted(f["finding_id"] for f in open_findings if f["readiness_impact"] == "non_blocking")
    require(nonblocking == sorted(disposition["non_blocking_open_finding_ids"]), "Nonblocking findings mismatch")
    for finding in findings.values():
        require(finding["lifecycle_events"][-1]["state"] == finding["current_state"], "Finding lifecycle mismatch")
        if finding["current_state"] == "closed":
            require(finding["retest"]["status"] == "pass", "Technical closure without successful retest")
            require(bool(finding["retest"].get("evidence")), "Retest without evidence")
        require(finding["current_state"] != "risk_accepted", "No human risk acceptance was authorized")
        for evidence in finding["evidence"]:
            require(evidence["artifact_id"] in artifacts, "Finding evidence artifact ID unresolved")
            local_path(evidence["locator"])

    require(disposition["qa_disposition"] == "ready_with_conditions", "Unintended readiness promotion")
    require(disposition["approval_status"] == "pending_human_approval", "Human approval must not be invented")
    require(bool(disposition["conditions"]), "Conditional readiness without conditions")
    require(not blocking and counts["critical"] == counts["high"] == 0, "Open release blocker")
    require(control["intake_summary"]["release"] == "1.1.0-rc.2", "Unintended release promotion")
    require(control["intake_summary"]["product_status"] == "Testing", "Unintended product-status promotion")

    live = coverage["live_platform_matrix"]
    require(len(live) == 9, "Original live scenario count changed")
    require(len({row["scenario_id"] for row in live}) == 9, "Duplicate live scenario IDs")
    for row in live:
        require(set(row["platform_results"]) == {"Codex", "ChatGPT", "Claude"}, "Live platform columns differ")
        require(set(row["platform_results"].values()) == {"NOT_TESTED"}, "Offline tests must not promote live gates")
    profiles = coverage["matching_profiles"]
    require(len(profiles) == 9 and len({p["profile_id"] for p in profiles}) == 9, "Matching profile count mismatch")
    require(sum(p["packaged_e2e"] == "PASS" for p in profiles) == 7, "Expected seven packaged profile checks")

    exec_by_id = {entry["execution_id"]: entry for entry in executions}
    require(len(exec_by_id) == len(executions), "Duplicate execution IDs")
    required = ("P3-EXEC-FULL-REGRESSION", "P3-EXEC-FINAL-CHECK", "P3-EXEC-SHA256", "P3-EXEC-ZIP")
    for execution_id in required:
        require(exec_by_id[execution_id]["exit_code"] == 0, f"Required execution failed: {execution_id}")
    require(exec_by_id["P3-EXEC-QUICK-VALIDATE"]["exit_code"] != 0, "Do not erase unavailable validator evidence")
    report = local_path("PHASE3-ACCEPTANCE-v1.1.0-rc.2.md").read_text(encoding="utf-8")
    for token in ("PACKAGE_ONLY", "Testing", "READY_FOR_HUMAN_REVIEW", "NOT_TESTED", "PyYAML", "pending_human_approval"):
        require(token in report, f"Report omits required limitation/status: {token}")
    for token in ("engagement_mode", "prior_advisory_involvement", "self_review_risk", "independence_threat", "safeguards", "reviewer_independence"):
        require(token in control and token in report, f"Missing role disclosure: {token}")
    return {"status": "PASS", "method": "strict JSON + cross-record and content invariants; not full JSON Schema validation",
            "original_files_preserved": 152, "artifacts": len(artifacts), "planned_checks": len(checks),
            "live_cells_NOT_TESTED": 27, "matching_profiles": 9, "packaged_profiles_PASS": 7,
            "open_findings_by_severity": counts, "approval_status": disposition["approval_status"]}


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
