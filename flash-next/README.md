# Deep dive: Qwen3.8-Flash-Next on a DGX Spark-class box

Measured data, not vendor numbers: Qwen3.8-Flash-Next (125B total / 6B active, plus a 51B n-gram table)
running **Claude Code as an autonomous coding agent** on an ASUS Ascent GX10 (NVIDIA GB10, 128 GB unified
memory, ~273 GB/s; the same class of machine as the DGX Spark and the RTX Spark laptops), graded with hidden
tests on real bug fixes the model cannot have seen. Part of [dgx-spark-benchmarks](../README.md); the
shared method is in [METHOD.md](../METHOD.md).

The question this section answers: **is the 4th bit worth it for long agent sessions?** Yes. Keeping the
model's n-gram table memory-mapped from SSD made room for the 4-bit build. It then resolved more tasks, ran
faster per task, used less energy and left 2.5× more free memory than the 3-bit build (see [Results](#results)).

## Setup

- **Agent:** Claude Code 2.1.280, headless, one task at a time, in a [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/)
  microVM whose only network destination is the model server (deny-all policy + one allow rule).
- **Model server:** llama.cpp `llama-server` (ghcr.io/ggml-org/llama.cpp:server-cuda, build 11723, arm64),
  [unsloth/Qwen3.8-Flash-Next-GGUF](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF) `UD-Q3_K_XL`.
  vLLM with NVIDIA's NVFP4 checkpoint would have been the first choice, but the only single-Spark recipe
  depends on a vLLM nightly image that has since been pruned from Docker Hub.
- **Sampling:** Qwen's recommended thinking-mode settings (temp 1.0, top_p 0.95, top_k 20, min_p 0). llama.cpp's
  defaults differ (top_k 40, min_p 0.05), so they are set explicitly.
- **Tasks:** 18 Python bug fixes merged upstream after 2026-09-01 ([list](../tasks/fresh-pr.csv)), graded
  SWE-bench style with the PR's own tests, hidden from the agent; plus 11 SWE-bench Pro tasks (one per repo,
  [subset](../tasks/swepro-subset.json)) on native arm64 images, network allowlisted to the model only.
- **Limits:** 45 min / 100 turns per task; reasoning effort `medium`; 131k context with Claude Code told the
  real window (`CLAUDE_CODE_AUTO_COMPACT_WINDOW`) so it compacts instead of overflowing.

## Results

| | Flash-Next 3-bit (UD-Q3_K_XL) | **Flash-Next 4-bit (UD-IQ4_XS)** | Qwen3.8-27B (dense, NVFP4 + MTP, vLLM) for reference |
|---|---|---|---|
| Fresh bug fixes resolved (18) | 11 | **13** | 12 |
| Same 6-task slice re-run | 5/6 | **6/6** | 5/6 |
| SWE-bench Pro subset (11) | 6 (2 errored) | **7** | 6 (4 errored) |
| Median wall-clock per task | 10.6 min | **8.7 min** | 18.7 min |
| All 18 tasks | 4.2 h | **3.2 h** | 6.8 h |
| GPU energy, all 18 tasks | 194 Wh | **140 Wh** | 252 Wh |
| Single-stream decode (fixed-length test) | 31 tok/s (no MTP) | **33 tok/s** (MTP 2) | 24 tok/s |
| Lowest free memory during agent work | 15.6 GiB | **39.6 GiB** | 33.4 GiB |
| Server options | n-gram table in GPU memory, no MTP | table memory-mapped from SSD, MTP draft 2 | – |

The 4-bit build solved three tasks the 3-bit missed (werkzeug-3298, pydantic-settings-1038, tomlkit-610) and
missed one the 3-bit solved (pydantic-settings-1069). At n=18 with sampling at temperature 1.0, ±1–2 tasks is
within run-to-run noise, but every measure moved in the same direction. MTP and placing the table on SSD change
speed, not the model's outputs, so the quality difference comes from the quantization. Per-task rows, transcripts-level metrics and
1 Hz telemetry (GPU power, memory headroom) are in [`data/runs/`](../data/runs) (the
`qwen3.8-flash-next-lcpp` runs); all models side by side: [RESULTS.md](../RESULTS.md).

## What we measured to pick the llama.cpp options

Each config started fresh; decode = single stream, 1024 tokens; TTFT = time to first token on a fresh 16k/64k
prompt; "repeat 16k" = the same 16k prompt again (prefix-cache reuse); headroom = memory still free once
loaded (GB10: `MemAvailable - KReclaimable + SReclaimable`). Raw: [`data/tuning/flashnext/`](../data/tuning/flashnext).

| Config (Q3_K_XL unless noted) | Decode tok/s | TTFT 16k | TTFT 64k | Repeat 16k | Free after load |
|---|---|---|---|---|---|
| ubatch 512, MTP draft 3 | 28.7 | 26.0 s | 101 s | 2.2 s | 18.0 GiB |
| ubatch 2048, no MTP | 31.7 | 18.9 s | 72 s | 3.4 s | 13.7 GiB |
| ubatch 2048, MTP 2 | 34.2 | 20.1 s | 74 s | 3.6 s | 16.8 GiB |
| ubatch 2048, MTP 4 | 25.4 | 20.1 s | 74 s | 3.6 s | 16.6 GiB |
| ubatch 1024, MTP 2 | **36.9** | 22.1 s | 83 s | 2.6 s | 16.6 GiB |
| ubatch 2048, MTP 3, mmap | 23.2 | 20.6 s | 74 s | 3.6 s | 43.7 GiB (misleading, see below) |
| ubatch 2048, MTP 2, mmap+mlock | 32.5 | 20.5 s | 74 s | 3.6 s | 15.5 GiB |
| ubatch 2048, MTP 3 | – | – | – | – | aborted: fell to 8.9 GiB while loading |
| IQ4_XS, ubatch 2048, MTP 2, mmap+mlock | – | – | – | – | aborted: fell to 8.8 GiB while loading |
| n-gram table on SSD, no MTP | 24.0 | 21.0 s | 77 s | 2.5 s | 54.3 GiB |
| n-gram table on SSD, MTP 2 | 31.1 | 21.6 s | 81 s | 2.6 s | 50.3 GiB |
| IQ4_XS, n-gram table on SSD, no MTP | 24.2 | 21.4 s | 78 s | 2.5 s | 51.6 GiB |
| **IQ4_XS, n-gram table on SSD, MTP 2** (used for the 4-bit run) | 27.1 | 22.7 s | 83 s | 2.7 s | 45.3 GiB |

Findings:
- **MTP draft length 2** is the sweet spot (~44% draft acceptance on this test); 3-4 drafts get rejected more
  and end up slower.
- **ubatch 1024-2048** cuts prefill ~25-30% vs the default 512.
- **mmap makes free memory look larger than it is**: the weights count as reclaimable page cache while the
  GPU is using them, and decode drops (23 vs 32-34 tok/s). Pinned (mlock) shows the honest ~15.5 GiB.
- **llama.cpp's host prompt cache (`--cache-ram`, 8 GiB by default) fills under real use**: headroom went
  from ~22 GiB to ~14 GiB with the server just answering requests. With one slot it adds nothing here, so it is
  disabled (`--cache-ram 0`).
- **Memory, not speed, is the wall on 128 GB.** With MTP and a single 4 GB agent sandbox, free memory fell to
  ~6 GiB; the production 3-bit run therefore uses no MTP (~32 tok/s instead of ~37) and bottoms out around
  15.6 GiB free during agent work. The 4-bit build (IQ4_XS, 94 GB) does not fit this way at all.
- **Keeping the n-gram table on SSD fixes that.** The table (`per_layer_token_embd`, 26.8 GiB in the 3-bit file)
  is read only a few rows per token, so it can be memory-mapped from NVMe instead of held in GPU memory
  (`-ot per_layer_token_embd\.weight=CPU --load-mode mmap`, the idea came from a comment by Strata). At
  3-bit with MTP 2, free memory after loading rose from 16.6–16.8 GiB to 50.3 GiB. Prefill was unchanged, and
  decode dropped from 34–37 to 31 tok/s because the table's rows are now read from SSD. That was enough for the
  4-bit build with MTP and a ~40 GiB margin while an agent works. Unlike the plain mmap row above, this is real free memory: only the
  rarely-read table is file-backed, and the minimum stayed near 40 GiB through 3 hours of agent runs.
- The GB10 exposes ~122 GB to Linux. Machines that cap GPU memory lower (Windows defaults on some 128 GB boxes)
  would not fit the 3-bit build plus an agent either.

## Status

- [x] 3-bit: tuning, 18-task run, variance re-run, SWE-bench Pro subset (dataset v0.1.0)
- [x] 4-bit with the n-gram table on SSD: tuning, 18-task run, variance re-run, SWE-bench Pro subset
      (dataset v0.3.0, [10.5281/zenodo.23539595](https://doi.org/10.5281/zenodo.23539595))
- [ ] Parallel agents at 4-bit (not run yet; the ~40 GiB margin suggests 2–4 agents fit)

## Reproduce

[`scripts/tune_llamacpp.py`](scripts/tune_llamacpp.py) re-runs the config sweep (Docker + the GGUF files; `FLASHNEXT_GGUF_DIR`).
[`scripts/sbx_agent.sh`](scripts/sbx_agent.sh) is the sandbox wrapper the agents run in. The full harness (task setup, grading, Opus
planner arm) will be published with the accompanying video.

## Caveats

One machine; one run per config/task set (plus a 6-task re-run); 18 + 11 tasks is small, so differences of
one or two tasks are noise. Claude Code is the harness, which is not what Qwen tuned for (they report best
results with mini-SWE-agent). Power is GPU-only (`nvidia-smi`); the GB10 has no system power sensor.

License: Apache-2.0 for the scripts; data CC-BY-4.0 (see the [repository README](../README.md#license)).
