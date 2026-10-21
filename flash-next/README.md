# Deep dive: Qwen3.8-Flash-Next on a DGX Spark-class box

Measured data, not vendor numbers: Qwen3.8-Flash-Next (125B total / 6B active, plus a 51B n-gram table)
running **Claude Code as an autonomous coding agent** on an ASUS Ascent GX10 (NVIDIA GB10, 128 GB unified
memory, ~273 GB/s; the same class of machine as the DGX Spark and the RTX Spark laptops), graded with hidden
tests on real bug fixes the model cannot have seen. Part of [dgx-spark-benchmarks](../README.md); the
shared method is in [METHOD.md](../METHOD.md).

The open question this repo is meant to answer: **is the 4th bit worth it for long agent sessions?**
3-bit results are in; the 4-bit run is in progress (see [Status](#status)).

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

## Results so far (3-bit, UD-Q3_K_XL)

| | Qwen3.8-Flash-Next 3-bit | Qwen3.8-27B (dense, NVFP4 + MTP, vLLM) for reference |
|---|---|---|
| Fresh bug fixes resolved (18) | **11** | 12 |
| Same 6-task slice re-run | 5/6 | 5/6 |
| SWE-bench Pro subset | 6 of 10 graded (1 harness error) | 6 of 11 |
| Median wall-clock per task | **10.6 min** | 18.7 min |
| All 18 tasks | **4.1 h** | 6.8 h |
| GPU energy, all 18 tasks | **194 Wh** | 252 Wh |
| Single-stream decode (fixed-length test) | 31 tok/s | 24 tok/s |

Both solved the same 10 tasks; one task apart is noise at n=18. Per-task rows, transcripts-level metrics and
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
  15.6 GiB free during agent work. **The 4-bit build (IQ4_XS, 94 GB) does not fit** this way at all.
- The GB10 exposes ~122 GB to Linux. Machines that cap GPU memory lower (Windows defaults on some 128 GB boxes)
  would not fit the 3-bit build plus an agent either.

## Status

- [x] 3-bit: tuning, 18-task run, variance re-run, SWE-bench Pro subset
- [ ] **4-bit (IQ4_XS) via Strata's trick**: in the GGUF, the n-gram table (`per_layer_token_embd`) is
      **26.8 GiB** and is read a few rows per token. Keeping it on the CPU side, memory-mapped from SSD
      (`-ot per_layer_token_embd\.weight=CPU --load-mode mmap`), should leave ~45 GiB free with the 4-bit
      build. Next: measure it; if it holds memory and speed, run the same 18 tasks + SWE-bench Pro at 4-bit.

## Reproduce

[`scripts/tune_llamacpp.py`](scripts/tune_llamacpp.py) re-runs the config sweep (Docker + the GGUF files; `FLASHNEXT_GGUF_DIR`).
[`scripts/sbx_agent.sh`](scripts/sbx_agent.sh) is the sandbox wrapper the agents run in. The full harness (task setup, grading, Opus
planner arm) will be published with the accompanying video.

## Caveats

One machine; one run per config/task set (plus a 6-task re-run); 18 + 11 tasks is small, so differences of
one or two tasks are noise. Claude Code is the harness, which is not what Qwen tuned for (they report best
results with mini-SWE-agent). Power is GPU-only (`nvidia-smi`); the GB10 has no system power sensor.

License: Apache-2.0 for the scripts; data CC-BY-4.0 (see the [repository README](../README.md#license)).
