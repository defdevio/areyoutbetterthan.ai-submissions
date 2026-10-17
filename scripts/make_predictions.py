#!/usr/bin/env python3
"""Builds a SWE-bench predictions.jsonl with a single prediction.

Usage:
  make_predictions.py --instance-id ID --patch-file path.diff --out predictions.jsonl
  make_predictions.py --instance-id ID --noop --out predictions.jsonl

--noop writes a patch that only adds an untracked marker file, so the harness runs the
tests against the unmodified repository (an empty patch is skipped by the harness).
"""

import argparse
import json
import re
import sys
from pathlib import Path

INSTANCE_RE = re.compile(r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9_.-]*__[A-Za-z0-9][A-Za-z0-9_.-]*-\d+$")
MAX_PATCH_BYTES = 256 * 1024

NOOP_PATCH = (
    "diff --git a/.areyoubetterthan-noop b/.areyoubetterthan-noop\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/.areyoubetterthan-noop\n"
    "@@ -0,0 +1 @@\n"
    "+noop\n"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--patch-file")
    parser.add_argument("--noop", action="store_true")
    parser.add_argument("--model", default="human")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if not INSTANCE_RE.match(args.instance_id):
        print(f"invalid instance id: {args.instance_id!r}", file=sys.stderr)
        return 2

    if args.noop:
        patch = NOOP_PATCH
    elif args.patch_file:
        raw = Path(args.patch_file).read_bytes()
        if len(raw) > MAX_PATCH_BYTES:
            print(f"patch too large: {len(raw)} bytes", file=sys.stderr)
            return 2
        patch = raw.decode("utf-8")
        if patch and not patch.endswith("\n"):
            patch += "\n"
    else:
        print("either --patch-file or --noop is required", file=sys.stderr)
        return 2

    prediction = {
        "instance_id": args.instance_id,
        "model_name_or_path": args.model,
        "model_patch": patch,
    }
    Path(args.out).write_text(json.dumps(prediction) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
