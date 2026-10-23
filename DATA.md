# Data dictionary

Every file under `data/` and `tasks/`, what each field means, how it is computed, and where its limits are.
Method and rationale: [METHOD.md](METHOD.md). Changes to the data, including corrections, are logged in
[CHANGELOG.md](CHANGELOG.md).

## Quick start for analysis

- **[`data/task_attempts.csv`](data/task_attempts.csv)** has one row per graded agent attempt, across every
  counted run, with the columns below plus `run_kind`. It is the file most analyses need.
- **[`data/model_summary.csv`](data/model_summary.csv)** has one row per model: the numbers in the README
  table.
- The JSON and JSONL files are the primary records; both CSVs are generated from them.

**Identifiers.**
- A task attempt is identified by (`run_id`, `task`, `attempt`).
- A run is identified by `run_id` = `<UTC start, YYYYMMDDTHHMMZ>_<model>_<arm>[_<tag>]`.
- Model ids (`qwen3.8-27b`, …) are this study's labels. `config/models.yaml` maps each label to the exact
  checkpoint, quantization, server image and flags.

**Times** are UTC ISO-8601 (`started_at`, `ended_at`) or unix seconds (`ts` in telemetry).

## `data/runs/<run_id>/`: fresh-PR agent runs

### `tasks.jsonl`: one row per task attempt

| Field | Type / unit | Meaning |
|---|---|---|
| `run_id`, `model`, `arm` | str | Run, model label, arm (`solo`: issue text only; `opus-best`: Opus writes a spec and reviews) |
| `attempt` | int | 1 = first attempt at this task by this model; 2 = the variance re-run |
| `parallel_n` | int | Number of agents running at once in this run (1 = alone on the machine) |
| `task` | str | Task id, see `tasks/fresh-pr.csv` |
| `resolved` | bool | **Headline metric.** All FAIL_TO_PASS tests pass and no PASS_TO_PASS test fails |
| `f2p`, `p2p` | "passed/total" | FAIL_TO_PASS and PASS_TO_PASS counts after applying the agent's diff and the hidden tests |
| `f2p_failing`, `p2p_failing` | list[str] | Test ids that did not pass |
| `failure_class` | str or null | Why an unresolved attempt failed: see [METHOD.md §5](METHOD.md#5-metrics); null if resolved |
| `status` | str | Claude Code's end state: `success`, `error_max_turns`, `timeout` (45 min), `harness_error` |
| `is_error` | bool | Claude Code's own error flag for the session |
| `turns` | int | Agent turns (model responses) |
| `wall_s` | s | Agent session wall-clock time (excludes setup and grading) |
| `setup_s`, `grade_s`, `total_s` | s | Sandbox creation and setup; grading; whole attempt end to end |
| `first_turn_s` | s | From session start to the first model response (time to first token plus first decode) |
| `input_tokens` | tokens | Input tokens summed over every request in the session, **including** tokens served from the prefix cache (each turn re-sends the conversation) |
| `output_tokens` | tokens | Output tokens summed over the session, including reasoning |
| `tool_calls` | int | Tool-use blocks the model emitted |
| `tool_errors` | int | Tool results returned as errors (failed commands, bad paths, invalid calls) |
| `malformed_tool_calls` | int | The subset of `tool_errors` caused by an invalid call: unknown tool, wrong or missing parameter |
| `diff_lines` | int | Added plus removed lines in the agent's final diff (tests the agent wrote count too) |
| `summary` | str | The agent's own final report (model output, unverified) |
| `energy_wh` | Wh | GPU energy over the attempt's window, from 1 Hz `gpu_power_w` (left Riemann sum). **In parallel runs the windows overlap**, so per-attempt values double-count shared power; use run-level telemetry for totals |
| `avg_power_w`, `peak_power_w` | W | Mean and maximum GPU power over the window |
| `min_headroom_gib` | GiB | Minimum true free memory over the window (definition below) |
| `retries`, `status_retry` | int, str | opus-best only: 1 if Opus sent the work back once, and the second session's status |
| `opus_*` | tokens, s | opus-best only: the **planner's** tokens and time, kept separate from the local model's. The planner is Opus unless the run's `manifest.json` says otherwise (`planner_model`, `planner_effort`; e.g. runs tagged `sonnet55-high` use Claude Sonnet 5.5 at effort high) |
| `skill_change`, `retro_*` | str, tokens, s | Learning-skill practice runs only: the planner's one-line summary of how it changed its notes after this task, and the retrospective's tokens and time |
| `recovered` | str | Present only on rows re-fetched after an infrastructure fault. The agent session itself was unchanged; see CHANGELOG |
| `error`, `grade_error` | str | Harness exception text (`failure_class` = `harness_error`) |

### `manifest.json`

The configuration this run actually used:
- `model_config`: the model entry from `config/models.yaml` at run time;
- `server_profile`: the server's load measurement, including the image digest;
- `versions`: sbx, Claude Code, kernel and the grader image digest;
- the arm's settings, effort, timeouts and turn limit.

### `summary.json`

Run totals: tasks, resolved, median `wall_s`, energy and a count of failure classes. It is written when a run
completes. A run without one was interrupted or is still in progress (`1700Z_ornith…` was interrupted by a
reboot and finished as `…_part2`).

### `telemetry.csv`: 1 Hz samples for the whole run

| Column | Unit | Meaning |
|---|---|---|
| `ts` | unix s | Sample time |
| `gpu_power_w` | W | GPU power from `nvidia-smi` (`power.draw`). The GB10 has no CPU, DRAM or whole-system sensor, so this is a **lower bound** on system power |
| `gpu_util_pct`, `gpu_temp_c`, `sm_clock_mhz` | %, °C, MHz | From `nvidia-smi` |
| `throttle` | hex bitmask | `clocks_event_reasons.active`; 0x0 = no throttling |
| `headroom_gib` | GiB | **True free memory** = MemAvailable − KReclaimable + SReclaimable. On the GB10, GPU allocations are booked as KReclaimable, so MemAvailable alone overstates free memory by tens of GiB |
| `mem_free_gib`, `kreclaimable_gib`, `swap_used_gib` | GiB | From `/proc/meminfo` |
| `cpu_util_pct`, `load1` | %, – | Host CPU utilisation (from /proc/stat deltas) and 1-minute load |
| `sandboxes` | int | Running agent sandboxes (sampled every 10 s, carried forward) |
| `vllm_running`, `vllm_waiting` | int | Requests running or queued at the model server (vLLM, or llama.cpp's equivalents) |
| `kv_usage_pct` | % | KV-cache occupancy |
| `prompt_tokens_total`, `gen_tokens_total` | tokens, cumulative | Server counters; difference consecutive rows for tok/s |
| `prefix_hits_total`, `prefix_queries_total` | tokens, cumulative | vLLM prefix-cache counters; hit rate = Δhits / Δqueries. Empty for llama.cpp |
| `preemptions_total` | cumulative | vLLM sequence preemptions (KV-cache pressure) |

Empty cells mean the source did not report that value at that moment.

## `data/swepro/<run>/`: SWE-bench Pro runs (Harbor)

| File | Content |
|---|---|
| `trials.jsonl` | One row per task: `task`, `reward` (1.0 = resolved by the benchmark's own tests, 0.0 = not), `exception` (Harbor exception type if the trial errored, e.g. `AgentTimeoutError`, `UnknownApiError`; errored trials count as unresolved), `input_tokens`, `output_tokens`, `started_at`, `finished_at` |
| `result.json` | Harbor's job-level result (reward lists, exception lists, mean reward) |
| `manifest.json`, `subset.json` | Model, port and Claude Code version; the exact task subset |
| `telemetry.csv` | As above |

**Reruns.** A task that errored before the agent ran (an infrastructure failure, such as a Docker Hub timeout while
pulling the task image) may be rerun later. The rerun is stored as its own run, `<UTC>_<model>_rerun-<name>`, and
RESULTS.md / `model_summary.csv` count its result in place of the errored row. Only errored rows are replaced; a task
the agent attempted is never rerun. The full run's own `trials.jsonl` stays exactly as recorded.

## `data/speed/<model>/<model>__<engine>__<IN>x<OUT>.json`: throughput and latency

Synthetic requests with unique prompts, so no prefix-cache reuse between requests. `IN`x`OUT` is input by
output tokens. `levels[]` has one entry per concurrency level:
- `agg_output_tok_s`: output tokens per second across all streams;
- `wall_s`, `ok`, `errors`;
- the mean prompt and output lengths.

Single-stream decode is `256x1024` at concurrency 1. Prompt-processing latency is `16384x64` and `65536x64`,
where `wall_s / ok` is the time per request. The `engine` field in the file name is the harness's
OpenAI-compatible client label, not the server engine.

## `data/tuning/<model>/<config>.json`: engine-option sweeps

One file per server configuration tried before the scored runs. Each configuration is started fresh.

| Field | Meaning |
|---|---|
| `config` | Configuration name |
| `args`, `common` | The exact server flags: per configuration and shared |
| `load_s` | Load time |
| `headroom_before_gib`, `headroom_loaded_gib` | Free memory before loading and right after |
| `min_headroom_gib` | Minimum free memory over the whole test |
| `decode_tok_s` | Single-stream decode |
| `draft_accept` | Speculative-draft acceptance samples, when MTP is on |
| `ttft_16k_s`, `ttft_64k_s` | Time to first token on a fresh prompt of 16k and 64k tokens |
| `prefill_*_tok_s` | Prompt-processing speed for the same prompts |
| `ttft_16k_repeat_s` | The same 16k prompt again (prefix reuse) |
| `error` | Present if the configuration failed or was aborted for memory |
| `log_tail` | The end of the server log |

See [flash-next/](flash-next/) for how the results were read.

## `data/models/<model>/profile.json`: load profile

- weights size, load time, server image and digest, and flags;
- true free memory before and after loading;
- KV-cache size and the server's reported maximum concurrency.

## `tasks/`

| File | Content |
|---|---|
| `fresh-pr.csv` | The 18 scored tasks: id, upstream repository, PR URL and title, merge time (all after 2026-09-01), and the number of FAIL_TO_PASS and PASS_TO_PASS tests |
| `grader_validation.json` | Per task: the base commit fails, and the gold fix passes all FAIL_TO_PASS and PASS_TO_PASS tests, in the network-less grader |
| `swepro-subset.json` | The SWE-bench Pro draw (seed 42, 2 per repository) and `half_a`, the 11 tasks run per model |

## What is not here

- Full agent transcripts and diffs (~GBs, and they contain upstream code), raw server logs, and Harbor job
  directories. These are kept by the author. Ask if your research needs them.
- Runs that were invalidated or aborted. They are listed in RESULTS.md, and the reasons are in
  CHANGELOG.md and METHOD.md §7.
