#!/usr/bin/env python3
"""Fails unless a PR is a well-formed scoring submission.

A valid submission PR adds exactly two files and changes nothing else:

  submissions/<instance_id>/<submission_id>.diff
  submissions/<instance_id>/<submission_id>.meta.json

The diff is treated as data: it is never applied to this repository, only handed to
the SWE-bench harness, which applies it inside the task's Docker container.

Writes instance_id / submission_id / diff_path to $GITHUB_OUTPUT.
"""

import argparse
import json
import os
import re
import subprocess
import sys

INSTANCE_RE = re.compile(r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9_.-]*__[A-Za-z0-9][A-Za-z0-9_.-]*-\d+$")
SUBMISSION_RE = re.compile(r"^[a-z0-9]{8,40}$")
PATH_RE = re.compile(
    r"^submissions/(?P<iid>[^/]+)/(?P<sid>[^/]+)\.(?P<kind>diff|meta\.json)$"
)
MAX_DIFF_BYTES = 256 * 1024


def fail(msg: str) -> int:
    print(f"::error::guard: {msg}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()

    out = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", args.base, args.head],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    changes = [line.split("\t", 1) for line in out.splitlines() if line.strip()]
    if len(changes) != 2:
        return fail(f"expected exactly 2 changed files, got {len(changes)}: {changes}")

    found = {}
    for status, path in changes:
        if status != "A":
            return fail(f"only added files are allowed ({status} {path})")
        m = PATH_RE.match(path)
        if not m:
            return fail(f"unexpected path {path}")
        found[m["kind"]] = m

    if set(found) != {"diff", "meta.json"}:
        return fail("need one .diff and one .meta.json")
    iid, sid = found["diff"]["iid"], found["diff"]["sid"]
    if (found["meta.json"]["iid"], found["meta.json"]["sid"]) != (iid, sid):
        return fail("diff and meta.json must share instance and submission id")
    if not INSTANCE_RE.match(iid):
        return fail(f"invalid instance id {iid!r}")
    if not SUBMISSION_RE.match(sid):
        return fail(f"invalid submission id {sid!r}")

    diff_path = f"submissions/{iid}/{sid}.diff"
    meta_path = f"submissions/{iid}/{sid}.meta.json"
    if os.path.getsize(diff_path) > MAX_DIFF_BYTES:
        return fail("diff too large")
    try:
        meta = json.load(open(meta_path))
    except json.JSONDecodeError as e:
        return fail(f"meta.json is not valid JSON: {e}")
    if meta.get("instance_id") != iid or meta.get("submission_id") != sid:
        return fail("meta.json ids do not match its path")

    with open(os.environ.get("GITHUB_OUTPUT", "/dev/stdout"), "a") as fh:
        fh.write(f"instance_id={iid}\nsubmission_id={sid}\ndiff_path={diff_path}\n")
    print(f"guard ok: {iid} / {sid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
