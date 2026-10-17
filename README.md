# areyoubetterthan.ai submissions

Public scoring pipeline and audit trail for [areyoubetterthan.ai](https://areyoubetterthan.ai),
the human control group for [SWE-bench Verified](https://www.swebench.com/).

Every human attempt that produces a patch becomes a pull request here. The
[`score`](.github/workflows/score.yml) workflow grades it with the **official SWE-bench
harness** (`swebench==5.0.2`, dataset `SWE-bench/SWE-bench_Verified`), using the same
prebuilt `swebench/sweb.eval.x86_64.*` Docker images and tests the AI leaderboard uses.
The app then reads the result and closes the PR. PRs are never merged.

## How a submission is scored

1. The areyoubetterthan.ai GitHub App pushes a branch `feat/<user>-<instance>-<id>` that
   adds exactly two files:
   - `submissions/<instance_id>/<submission_id>.diff`: the human's unified diff
   - `submissions/<instance_id>/<submission_id>.meta.json`: ids and timing metadata
2. It opens a PR titled `[score] <instance_id> by @user`.
3. [`score.yml`](.github/workflows/score.yml) runs on a GitHub-hosted runner:
   - **guard**: only bot-authored, same-repo PRs that add exactly those two files are scored
   - frees disk space, installs the pinned harness
   - runs `swebench.harness.run_evaluation` for that one instance
   - [`classify.py`](scripts/classify.py) turns the harness output into `result.json`
     (`resolved`, `unresolved`, `patch_apply_failed`, or `infra_error`)
   - uploads `result` and `logs` artifacts and writes a job summary
4. The app receives the `workflow_run` webhook, downloads `result.json`, records the
   outcome, and closes the PR. `infra_error` is retried; it is never reported as a failed
   attempt.

## Security model

- The diff is **data**. It is only applied inside the SWE-bench container on an ephemeral
  runner. It is never applied to this repository or executed by the workflow itself.
- `score.yml` has **no secrets** and `permissions: contents: read`.
- The job only runs when the PR author is the bot (`vars.BOT_LOGIN`) and the head branch
  lives in this repository.
- Required repository settings:
  - Branch protection on `main` (PRs required, no force pushes). Only the app can push `feat/*`.
  - *Settings → Actions → Fork pull request workflows*: require approval for all external
    contributors.
  - Repository variable `BOT_LOGIN` = the app's bot login, e.g. `areyoubetterthan-ai[bot]`.

## Task validation

[`validate.yml`](.github/workflows/validate.yml) is run once per task-set refresh. For each
candidate it checks that the gold patch resolves, that a no-op patch does not, and that
the image fits a hosted runner. Only tasks that pass are offered on the site.

## Local tests

```sh
python3 -m unittest discover -s tests -v
```
