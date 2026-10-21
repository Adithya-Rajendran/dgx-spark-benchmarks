# Changelog

Dataset versions follow `MAJOR.MINOR.PATCH`:
- **MINOR**: new models or runs added.
- **PATCH**: corrections to existing data. Each one is listed here with what changed and why.
- **MAJOR**: a change to the method that makes earlier numbers incomparable.

Cite a tagged release (or its DOI) so your numbers stay reproducible. `main` changes as models are added.

## Unreleased

Added automatically as runs finish: see the commit history and [RESULTS.md](RESULTS.md).

## 0.1.0 (2026-10-21)

First public version.
- **Models:**
  - Qwen3.8-27B (vLLM, NVFP4 + MTP)
  - Qwen3.8-Flash-Next (llama.cpp, 3-bit UD-Q3_K_XL)
  - Ornith-1.5-35B-A3B (vLLM, NVFP4 + MTP): solo, parallel and variance; its SWE-bench Pro run was in
    progress at release and arrives in the next version
- **Data:**
  - 18-task fresh-PR set
  - 11-task SWE-bench Pro subset
  - speed, tuning and load profiles
  - 1 Hz telemetry per run
- Includes the Qwen3.8-Flash-Next deep dive (previously the separate repository flash-next-on-dgx-spark).

### Known issues and corrections in this version

- **Ornith solo: 3 rows recovered.** `pallets__werkzeug-3298`, `pallets__werkzeug-3327` and
  `pydantic__pydantic-settings-1038` in `20261020T1700Z_ornith-1.5-35b_solo` carry a `recovered` field. The
  agent sessions finished normally, but a sandbox auto-stop bug lost the step that fetched the result. The
  diffs were then fetched from the surviving sandboxes and graded unchanged. The run ended early because of a
  reboot, and its remaining 8 tasks are in `…_solo_part2`.
- **Per-attempt energy in parallel runs overlaps** (see DATA.md). Use run-level telemetry for totals.
- **Runs excluded from results** (listed in RESULTS.md):
  - **Smoke and cache checks:** short diagnostic runs.
  - **`xhigh-partial`:** reasoning effort "xhigh" hit the time limit; the study uses "medium".
  - **`nocache-partial`:** recorded before the chat-template fix restored prefix caching. Timings are not
    comparable.
  - **`par2_INVALID-sandboxes-removed`:** the sandboxes were removed mid-run by an operator error.
  - **`INVALID-server-killed`:** the memory guard stopped the model server.
  - **`INVALID-internet-open`:** the SWE-bench Pro network allowlist was not in effect, so the agent had
    internet access.
  - **`calibrate_ABORTED`.**
- **Qwen3.8-27B speed results:** the first speed run is not published. Its harness ignored the server's
  reasoning stream, so thinking tokens were counted as errors. The published speed files are from the fixed
  harness.
