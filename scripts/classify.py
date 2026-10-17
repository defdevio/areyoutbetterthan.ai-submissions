#!/usr/bin/env python3
"""Normalizes a SWE-bench harness run into a small, stable result.json.

Outcomes:
  resolved            FAIL_TO_PASS and PASS_TO_PASS all pass.
  unresolved          Tests ran (or the patch broke the test run) and did not all pass.
  patch_apply_failed  The diff did not apply to base_commit. Counts as unresolved.
  infra_error         Docker/harness/environment problem. Not the submitter's fault;
                      the app retries these and never reports them as a failure.

The harness writes logs/run_evaluation/<run_id>/<model>/<instance_id>/{report.json,
run_instance.log,test_output.txt}. report.json is missing when the run raised (patch
apply failure, timeout, docker errors), so those cases are told apart from the logs.
"""

import argparse
import json
import sys
from importlib import metadata
from pathlib import Path

SCHEMA = 1
APPLY_PATCH_FAIL = ">>>>> Patch Apply Failed"
TIMEOUT_MARK = "Timeout error:"
MAX_LIST = 50


def read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except FileNotFoundError:
        return ""


def infra_reason(*paths: Path):
    try:
        from swebench.harness.infra_failure import TIER_ENVIRONMENT, classify_logs
    except Exception:  # older harness without the classifier
        return None
    found = classify_logs(*paths)
    if found and found[1] == TIER_ENVIRONMENT:
        return found[0]
    return None


def summarize_tests(tests_status: dict) -> dict:
    f2p = tests_status.get("FAIL_TO_PASS", {}) or {}
    p2p = tests_status.get("PASS_TO_PASS", {}) or {}
    return {
        "fail_to_pass": {
            "passed": (f2p.get("success") or [])[:MAX_LIST],
            "failed": (f2p.get("failure") or [])[:MAX_LIST],
            "passed_count": len(f2p.get("success") or []),
            "failed_count": len(f2p.get("failure") or []),
        },
        "pass_to_pass": {
            "failed": (p2p.get("failure") or [])[:MAX_LIST],
            "passed_count": len(p2p.get("success") or []),
            "failed_count": len(p2p.get("failure") or []),
        },
    }


def classify(log_dir: Path, instance_id: str) -> dict:
    report_path = log_dir / "report.json"
    instance_log = log_dir / "run_instance.log"
    test_output = log_dir / "test_output.txt"
    result = {"outcome": "infra_error", "resolved": False, "reason": None, "tests": None}

    if report_path.exists():
        try:
            report = json.loads(report_path.read_text())[instance_id]
        except (json.JSONDecodeError, KeyError):
            result["reason"] = "corrupt_report"
            return result
        if report.get("tests_status"):
            result["tests"] = summarize_tests(report["tests_status"])
        if report.get("resolved"):
            result.update(outcome="resolved", resolved=True, reason=None)
        elif report.get("infra_failure"):
            result.update(outcome="infra_error", reason=report.get("infra_failure_reason") or "environment")
        else:
            reason = "tests_failed" if report.get("patch_successfully_applied") else "no_test_results"
            result.update(outcome="unresolved", reason=reason)
        return result

    log_text = read(instance_log)
    if APPLY_PATCH_FAIL in log_text:
        result.update(outcome="patch_apply_failed", reason="patch_apply_failed")
        return result
    if TIMEOUT_MARK in read(test_output):
        # The gold patch is validated to finish in time, so a timeout is caused by the patch.
        result.update(outcome="unresolved", reason="tests_timed_out")
        return result
    result["reason"] = infra_reason(test_output, instance_log) or (
        "no_logs" if not log_text else "harness_error"
    )
    return result


def tail(path: Path, lines: int = 40) -> str:
    text = read(path)
    return "\n".join(text.splitlines()[-lines:])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--model", default="human")
    parser.add_argument("--submission-id", default=None)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    log_dir = Path("logs/run_evaluation") / args.run_id / args.model / args.instance_id
    result = classify(log_dir, args.instance_id)
    try:
        version = metadata.version("swebench")
    except metadata.PackageNotFoundError:
        version = None

    payload = {
        "schema": SCHEMA,
        "instance_id": args.instance_id,
        "submission_id": args.submission_id,
        **result,
        "harness": {"package": "swebench", "version": version, "dataset": args.dataset},
        "duration_s": args.duration,
    }
    if result["outcome"] == "infra_error":
        payload["log_tail"] = tail(log_dir / "run_instance.log")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({k: payload[k] for k in ("instance_id", "outcome", "reason")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
