import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import classify  # noqa: E402

IID = "psf__requests-2317"


def write_logs(base: Path, report=None, instance_log="", test_output=""):
    d = base / "logs/run_evaluation/run/human" / IID
    d.mkdir(parents=True, exist_ok=True)
    if report is not None:
        (d / "report.json").write_text(json.dumps({IID: report}))
    (d / "run_instance.log").write_text(instance_log)
    (d / "test_output.txt").write_text(test_output)
    return d


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_resolved(self):
        d = write_logs(
            self.tmp,
            report={
                "resolved": True,
                "patch_successfully_applied": True,
                "tests_status": {
                    "FAIL_TO_PASS": {"success": ["t1"], "failure": []},
                    "PASS_TO_PASS": {"success": ["a", "b"], "failure": []},
                },
            },
        )
        r = classify.classify(d, IID)
        self.assertEqual(r["outcome"], "resolved")
        self.assertTrue(r["resolved"])
        self.assertEqual(r["tests"]["pass_to_pass"]["passed_count"], 2)

    def test_unresolved_tests_failed(self):
        d = write_logs(
            self.tmp,
            report={
                "resolved": False,
                "patch_successfully_applied": True,
                "tests_status": {
                    "FAIL_TO_PASS": {"success": [], "failure": ["t1"]},
                    "PASS_TO_PASS": {"success": [], "failure": []},
                },
            },
        )
        r = classify.classify(d, IID)
        self.assertEqual((r["outcome"], r["reason"]), ("unresolved", "tests_failed"))
        self.assertEqual(r["tests"]["fail_to_pass"]["failed"], ["t1"])

    def test_report_with_infra_failure(self):
        d = write_logs(
            self.tmp,
            report={"resolved": False, "infra_failure": True, "infra_failure_reason": "out_of_memory"},
        )
        r = classify.classify(d, IID)
        self.assertEqual((r["outcome"], r["reason"]), ("infra_error", "out_of_memory"))

    def test_patch_apply_failed(self):
        d = write_logs(self.tmp, instance_log="...\n>>>>> Patch Apply Failed:\nerror: patch failed\n")
        r = classify.classify(d, IID)
        self.assertEqual(r["outcome"], "patch_apply_failed")

    def test_timeout_counts_as_unresolved(self):
        d = write_logs(self.tmp, instance_log="x", test_output="...\n\nTimeout error: 1200 seconds exceeded.")
        r = classify.classify(d, IID)
        self.assertEqual((r["outcome"], r["reason"]), ("unresolved", "tests_timed_out"))

    def test_missing_logs_is_infra_error(self):
        d = self.tmp / "nothing"
        r = classify.classify(d, IID)
        self.assertEqual((r["outcome"], r["reason"]), ("infra_error", "no_logs"))

    def test_docker_error_is_infra_error(self):
        d = write_logs(self.tmp, instance_log="Error creating container: Error response from daemon: no space")
        r = classify.classify(d, IID)
        self.assertEqual(r["outcome"], "infra_error")


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        (self.repo / "README.md").write_text("x")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def commit(self, files: dict):
        for path, content in files.items():
            p = self.repo / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        self.git("add", ".")
        self.git("commit", "-qm", "sub")
        return self.git("rev-parse", "HEAD").strip()

    def run_guard(self, head):
        out = self.repo / "gh_output"
        env = {**os.environ, "GITHUB_OUTPUT": str(out)}
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts/guard.py"), "--base", self.base, "--head", head],
            cwd=self.repo, env=env, capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout, out.read_text() if out.exists() else ""

    def meta(self, iid=IID, sid="abc12345"):
        return json.dumps({"instance_id": iid, "submission_id": sid})

    def test_valid(self):
        head = self.commit({
            f"submissions/{IID}/abc12345.diff": "diff --git a/x b/x\n",
            f"submissions/{IID}/abc12345.meta.json": self.meta(),
        })
        code, stdout, outputs = self.run_guard(head)
        self.assertEqual(code, 0, stdout)
        self.assertIn(f"instance_id={IID}", outputs)
        self.assertIn("submission_id=abc12345", outputs)

    def test_rejects_extra_files(self):
        head = self.commit({
            f"submissions/{IID}/abc12345.diff": "d",
            f"submissions/{IID}/abc12345.meta.json": self.meta(),
            ".github/workflows/evil.yml": "x",
        })
        self.assertEqual(self.run_guard(head)[0], 1)

    def test_rejects_workflow_change(self):
        head = self.commit({
            f"submissions/{IID}/abc12345.diff": "d",
            "scripts/guard.py": "print('pwned')",
        })
        self.assertEqual(self.run_guard(head)[0], 1)

    def test_rejects_modification(self):
        head = self.commit({"README.md": "changed", f"submissions/{IID}/abc12345.diff": "d"})
        self.assertEqual(self.run_guard(head)[0], 1)

    def test_rejects_mismatched_meta(self):
        head = self.commit({
            f"submissions/{IID}/abc12345.diff": "d",
            f"submissions/{IID}/abc12345.meta.json": self.meta(sid="zzz99999"),
        })
        self.assertEqual(self.run_guard(head)[0], 1)

    def test_rejects_bad_instance_id(self):
        head = self.commit({
            "submissions/..__x-1/abc12345.diff": "d",
            "submissions/..__x-1/abc12345.meta.json": self.meta(iid="..__x-1"),
        })
        self.assertEqual(self.run_guard(head)[0], 1)


class PredictionsTest(unittest.TestCase):
    def test_noop_and_patch(self):
        tmp = Path(tempfile.mkdtemp())
        out = tmp / "p.jsonl"
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/make_predictions.py"), "--instance-id", IID, "--noop", "--out", str(out)],
            check=True,
        )
        pred = json.loads(out.read_text())
        self.assertEqual(pred["instance_id"], IID)
        self.assertIn("new file mode", pred["model_patch"])

        diff = tmp / "x.diff"
        diff.write_text("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-x\n+y")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/make_predictions.py"), "--instance-id", IID,
             "--patch-file", str(diff), "--out", str(out)],
            check=True,
        )
        pred = json.loads(out.read_text())
        self.assertTrue(pred["model_patch"].endswith("+y\n"))
        self.assertEqual(pred["model_name_or_path"], "human")


if __name__ == "__main__":
    unittest.main()
