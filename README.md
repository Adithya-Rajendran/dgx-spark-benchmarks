# DGX Spark benchmarks: local coding agents

Measured results for open-weight models running as **autonomous coding agents** on one ASUS Ascent GX10
(NVIDIA GB10, 128 GB unified memory; the same class as the DGX Spark and the RTX Spark laptops). Each agent
is Claude Code pointed at a local model server, running in an isolated microVM whose only network
destination is that server. It fixes real bugs it cannot have seen in training, and hidden tests grade the
result.

- **[METHOD.md](METHOD.md)**: question, hardware, models, task sets, protocol, metrics, threats to validity
- **[RESULTS.md](RESULTS.md)**: per-model results, generated from `data/`
- **`data/`**: every run's manifest (server image digest, flags, versions), one row per task attempt
  (resolved, tests passed, turns, tokens, tool calls, wall time, GPU energy, minimum free memory), plus
  speed, tuning and load profiles
- **`tasks/`**: the 18 fresh-PR tasks (upstream PR links, test counts, gold/base validation) and the
  SWE-bench Pro subset
- **`config/`**: the model server configurations as run, and the chat-template fix that keeps prefix
  caching working with Claude Code

This repository updates automatically after each model finishes. More models are in progress.

## Summary (updated 2026-10-21)

Fresh-PR = 18 real Python bug fixes merged after 2026-09-01, graded with hidden tests. SWE-bench Pro = 11-task subset (one per repository). Decode = single stream, 1024 output tokens.

| Model | Engine | Fresh-PR solo | Median min/task | GPU Wh (18 tasks) | SWE-bench Pro | Decode tok/s | 16k-prompt request (s) |
|---|---|---|---|---|---|---|---|
| ornith-1.5-35b | vllm | 10/18 | 10.3 | 160 | – | 91.1 | 4.5 |
| qwen3.8-27b | vllm | 12/18 | 18.7 | 252 | 6/11 (4 errored) | 23.8 | 9.4 |
| qwen3.8-flash-next-lcpp | llama.cpp | 11/18 | 10.6 | 194 | 6/11 (2 errored) | 31.1 | 21.7 |

Errored SWE-bench Pro trials (timeouts, context overflow, API errors) count as unresolved.

Small samples: 18 and 11 tasks, mostly one attempt each, so a difference of one or two tasks is noise. Power
is GPU-only. See [METHOD.md](METHOD.md#7-threats-to-validity).

## Related

- [flash-next-on-dgx-spark](https://github.com/Adithya-Rajendran/flash-next-on-dgx-spark): a deep dive into
  Qwen3.8-Flash-Next's llama.cpp options (3-bit vs 4-bit, MTP, memory) on the same machine.

## License

Data (`data/`, `tasks/`): CC-BY-4.0, see [data/LICENSE-DATA.txt](data/LICENSE-DATA.txt). Task material
belongs to the upstream projects under their own licenses. Configs and templates: Apache-2.0.
