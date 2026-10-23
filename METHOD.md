# Benchmark method

> File and script names (`bench/...`) refer to the benchmark harness, which will be published with
> the accompanying video. Everything needed to check the numbers is in this repository.

This document defines what is measured, how, and what the numbers can and cannot support. Results are in
[RESULTS.md](RESULTS.md), which is regenerated and pushed after every model. Incidents during the runs are summarised in
section 7.

## 1. Question

On one desktop-class machine with 128 GB of unified memory (NVIDIA GB10, the class of the DGX Spark and the
upcoming RTX Spark laptops):

1. How often does an open-weight model, acting as an **autonomous coding agent**, produce a correct fix for
   a real bug it cannot have seen in training?
2. How fast is it, and how much energy and memory does it use?
3. How many agents can share one machine before quality, speed or memory breaks down?
4. How much does a frontier model (Claude Opus) add when it only plans and reviews, while the local model
   does all the coding?

## 2. System under test

| Component | Setting |
|---|---|
| Hardware | ASUS Ascent GX10: NVIDIA GB10 (Grace Blackwell), 128 GB LPDDR5X unified memory (~273 GB/s), ~122 GB visible to Linux |
| Agent | Claude Code 2.1.280, headless (`claude -p`), with every model alias pointed at the local model. Reasoning effort `medium`. Limits: 45 min and 100 turns per task |
| Isolation | Each agent runs in a Docker Sandboxes (`sbx`) microVM. The global network policy is deny-all; the model server's port is the only allowed destination, and Anthropic endpoints are explicitly denied. The agent works on a private clone of the task repository, at 4 vCPU and 4–8 GB RAM |
| Model server | One server container on 127.0.0.1 at a time, chosen per model for its best measured result (vLLM or llama.cpp; [models.yaml](config/models.yaml) holds the exact images, quantization and flags). Context 131,072 tokens; Claude Code is told this window so it compacts instead of overflowing |
| Grader | A container with no network that applies the hidden tests to the agent's diff (`images/grader`) |

### Models

| Model | Type | Served as |
|---|---|---|
| Qwen3.8-27B | dense, 27B | vLLM, NVFP4, MTP speculative decoding (3 tokens) |
| Ornith-1.5-35B-A3B | MoE, 3B active | vLLM, NVFP4, MTP (1 token) |
| Qwen3.8-Flash-Next | MoE, 125B total / 6B active + 51B n-gram table | llama.cpp, GGUF 3-bit (UD-Q3_K_XL); 4-bit pending a memory test |
| Nemotron-3.5-Bolt | MoE, 74B / 9B active | vLLM + DFlash draft model |
| Laguna S 2.1 | MoE | GGUF 4-bit; llama.cpp vs Ollama decided by a bake-off |

Planned references: Claude Opus 5.5 alone and Claude Haiku 5.5 alone, same tasks and grader.

One harness fix applies to every Qwen-family model. Their chat templates reject a system message that is not
the first one. Claude Code sends system reminders mid-conversation, so the server merged them into the first
message. That changed the prompt prefix on every turn and defeated prefix caching (22% hit rate). The
patched templates in [config/templates](config/templates) render those messages in place, which raised the
hit rate to 85–93% and halved task time. Without the fix the timings measure a bug, not the model.

## 3. Task sets

### 3.1 Fresh-PR (main set, 18 tasks)

These are real bug fixes merged **after 2026-09-01**, which is after the models' training cut-offs. That
rules out memorization, the main threat to validity for public benchmarks.

Construction (`bench/mine_prs.py`, `bench/build_tasks.py`):
1. **Mining.** Candidates are merged PRs in 30 pure-Python projects (pallets, pydantic-settings, isort,
   pluggy, tomlkit, sqlfluff, more-itertools, anyio, …). Each must close a linked issue, add or change
   tests, and have a moderate source diff.
2. **Splitting.** Each PR's diff is split into the source change (the answer, hidden) and the test change
   (hidden tests). The agent sees only the repository at the PR's base commit and the issue text
   (`PROBLEM.md`).
3. **Pinned dependencies.** A pinned environment (`requirements.lock`) is shared by the agent's sandbox and
   the grader, so both see the same versions.
4. **Validation.** In the network-less grader, the base commit with the hidden tests must fail, and the
   gold fix with the hidden tests must pass. FAIL_TO_PASS = tests that fail at base and pass with the gold
   fix. PASS_TO_PASS = tests that pass in both.
5. **Admission.** A task is admitted only if FAIL_TO_PASS is non-empty. All 18 admitted tasks pass this
   check ([tasks/grader_validation.json](tasks/grader_validation.json)). `tasks/` also holds candidates
   that failed validation (`task.json: valid=false`); they are never run.

### 3.2 SWE-bench Pro subset (public comparison, 11 tasks)

These come from Scale AI's SWE-bench Pro public set: multi-language (Python, Go, JS/TS), larger repositories
and harder tasks. Tasks are drawn with a fixed seed (42), two per repository. The run uses the first of each
pair: 11 tasks, one per repository ([tasks/swepro-subset.json](tasks/swepro-subset.json), `half_a`).

They run through Harbor's Claude Code agent inside each task's own container, using native arm64 images.
During the agent phase the container may reach only the model relay; this allowlist was checked by
confirming that PyPI and GitHub are blocked. Grading uses the benchmark's own tests. Treat this set as a
sanity anchor against public numbers, not as a precise score: at n=11, one task is 9 points.

### 3.3 Calibration set (7 tasks, never scored)

These are held-out fresh-PR tasks from projects that are not in the scored set. Only the Opus-planned arm
uses them: Opus tunes its guidance on them, so it never tunes on the tasks that are scored.

## 4. Protocol per model

Runs are strictly serial. One model server is loaded at a time, and nothing else runs on the GPU. The steps
run in this order (`run_model.sh`):

| # | Step | What happens | Main outputs |
|---|---|---|---|
| 0 | **Load and profile** | Start the server, then record load time, weights size, KV-cache size and free memory before and after loading | `models/<m>/profile.json` |
| 1 | **Speed** | Single-stream decode (256 tokens in, 1024 out); prompt processing and time to first token at 16k and 64k tokens of context; total throughput at 1, 2, 4 and 8 concurrent streams | `speed/<m>/*.json` |
| 2 | **Solo agent** | All 18 fresh-PR tasks, one agent at a time; the agent gets only the issue text | `runs/*_solo/` |
| 3 | **Parallel agents** | A fixed 6-task slice with N = 2, 4 and 8 agents at once. The sweep stops when free memory falls below 14 GiB, because the memory guard stops the server at 8 GiB | `runs/*_parN/` |
| 4 | **Variance** | The same 6-task slice again, solo, as a second attempt | `runs/*_rep2/` |
| 5 | **SWE-bench Pro** | The 11-task subset, solo | `swepro/<run>/` |
| 6 | **Opus at its best** (two models only) | Opus calibrates on the held-out set and writes a guide for that model. Per task, Opus writes a spec, the local model codes, and Opus reviews (it can run tests in the sandbox) and may send the work back once | `runs/*_opus-best/` |

Step 7, **the learning skill** (Ornith-1.5, planner Claude Sonnet 5.5 at effort high): the planner keeps its own
notes on how to work with the model. The notes have four sections: how it behaves, how to write specs for it, how
to review its work, and standing instructions that are installed into the model's CLAUDE.md. It reads them before
every spec and every review.

*Practice.* The planner works through up to 24 held-out tasks in a fixed, seeded order. These come from
repositories that are not among the 18 scored tasks. After each task it writes a retrospective and updates its
notes. The retrospective uses only what it observed during the task: the issue, its spec, the sandbox test
output, its review, the agent's tool errors, its timing and the diff. The notes have a hard budget, enforced in code: at most 3,000 characters (about 750 tokens), with at most 600 for
the executor section. They are loaded before every task, so every update must merge points, keep what matters
most and drop the rest. An update that breaks a rule gets one fix pass, and is rejected if it still breaks one. The rules are: the
size budget; the four-section structure; and generality (no repository names, file paths, file names or issue/PR
numbers). The skill's own `scripts/notes.py` enforces them, and the same script validates and versions updates
in everyday use.
It never sees hidden tests or the grade,
because in real use there are none. Every version of the notes is kept.

*Scoring.* Frozen snapshots of the notes are scored on the 18 tasks with learning off:
- the final version;
- the empty starting version (v000);
- the halfway version.

If the notes improve with use, the scores rise across these checkpoints. The calibrate-once Opus guide (step 6)
is the static baseline.

Step 6 runs only on two models, chosen after steps 0–5: the best performer and the one most useful for
comparison. In this arm Opus never edits code, and its tokens and time are logged separately.

Telemetry is sampled at 1 Hz throughout every step: GPU power, true free memory, server cache and queue
statistics, and the number of active sandboxes (`bench/telemetry.py`).

Engine and quantization choices are made **before** the scored runs, in a separate tuning sweep.
`bench/tune_llamacpp.py` and `bench/tune_vllm.py` each measure several configurations. The winner is chosen
on decode speed, prompt-processing speed and free memory, and the full results are kept in `data/tuning/`.

## 5. Metrics

**Correctness (per task).**
- **Resolved:** every FAIL_TO_PASS test passes and every PASS_TO_PASS test still passes. This is the
  headline metric, as in SWE-bench.
- `f2p` and `p2p` are recorded as passed/total counts.
- Every unresolved task gets a failure class:

  | Class | Meaning |
  |---|---|
  | `wrong_fix` | no target test passes, nothing broken |
  | `partial_fix` | some target tests pass |
  | `broke_existing` | all target tests pass but PASS_TO_PASS tests regress |
  | `wrong_fix_and_broke_existing` | no target test passes and PASS_TO_PASS tests regress |
  | `no_change` | the agent produced no diff |
  | `timeout` | the 45-minute limit was hit |
  | `max_turns` | the 100-turn limit was hit |
  | `tool_call_errors` | 5 or more malformed tool calls |
  | `harness_error` | an infrastructure failure, not the model's |

**Effort and speed (per task).**
- Wall-clock time, setup and grading time, and agent turns
- Input, cached input and output tokens
- Tool calls, tool errors and malformed tool calls
- Time to the first turn

**Cost (per task, from telemetry).**
- GPU energy (Wh), average and peak GPU power
- Minimum true free memory during the task

**Machine.** Decode tok/s, prompt-processing time at 16k and 64k tokens, prefix-cache reuse, load time and
memory headroom.

**Parallel.** Tasks per hour, per-task slowdown against solo, quality under load, and the reason the sweep
stopped.

## 6. Data and reproducibility

- **Raw data** is written to a separate share and is too large for git. It includes:
  - each agent's full transcript (Claude Code stream-json with timestamps) and diff;
  - grader output;
  - 1 Hz telemetry;
  - server metric snapshots and logs;
  - Harbor job directories.
- **The repository keeps the small per-run files** under `data/`: `manifest.json`, `tasks.jsonl` (one row
  per task attempt) and `summary.json`, plus the speed, tuning and profile results. Every chart and table
  can be rebuilt from `data/` alone.
- **Each run's `manifest.json` pins** the server image digest, server flags, the sbx and Claude Code
  versions, the grader image digest and the kernel.
- **`bench/publish.py` runs automatically** at the end of each model's plan, each SWE-bench Pro run and each
  tuning sweep. It mirrors those files, rebuilds RESULTS.md, and commits and pushes. Run names that contain
  INVALID, ABORTED, smoke or partial are kept on the share but excluded from results; RESULTS.md lists them,
  and section 7 summarises why.

## 7. Threats to validity

- **Small samples.** n=18 and n=11, mostly one attempt per task. A difference of one or two tasks is noise.
  The 6-task variance re-run gives a rough per-model stability check, not a confidence interval.
- **One harness.** Claude Code is not the harness these models were tuned for; Qwen, for example, reports
  its best results with mini-SWE-agent. Scores measure "model + Claude Code", which is the realistic
  setup this study targets.
- **Engines and quantization differ across models.** Each model runs on the engine and quantization that
  measured best for it on this machine (some 3–4 bit). These are not reference full-precision scores.
  Planned engine checks (the same model on vLLM, llama.cpp and Ollama) bound this effect.
- **Python only for fresh-PR.** SWE-bench Pro adds Go and JS/TS, but only 11 tasks.
- **Power is GPU-only.** The GB10 reports GPU power through `nvidia-smi`, with no CPU, DRAM or
  whole-system sensor and no wall meter. Energy figures are therefore lower bounds. The RTX Spark laptops
  will run at a lower power limit, so speeds here are an upper bound for them.
- **Incidents.** Infrastructure failures during the week are documented, not hidden: a sandbox auto-stop
  bug, a server stopped by the memory guard, and an allowlist that was briefly ineffective. Affected runs
  are either marked INVALID and re-run, or, where the agent's work survived intact, re-fetched and graded,
  with a `recovered` field on the row.

## 8. Status

Live, per model: [RESULTS.md](RESULTS.md).
