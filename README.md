# DGX Spark benchmarks: local coding agents

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23524590.svg)](https://doi.org/10.5281/zenodo.23524590)

Measured results for open-weight models running as **autonomous coding agents** on one ASUS Ascent GX10
(NVIDIA GB10, 128 GB unified memory; the same class as the DGX Spark and the RTX Spark laptops). Each agent
is Claude Code pointed at a local model server, running in an isolated microVM whose only network
destination is that server. It fixes real bugs it cannot have seen in training, and hidden tests grade the
result.

- **[METHOD.md](METHOD.md)**: question, hardware, models, task sets, protocol, metrics, threats to validity
- **[RESULTS.md](RESULTS.md)**: per-model results, generated from `data/`
- **[DATA.md](DATA.md)**: data dictionary: every file and field, units, how each is computed, known limits.
  For analysis start with `data/task_attempts.csv` (one row per agent attempt) and `data/model_summary.csv`
- **[CHANGELOG.md](CHANGELOG.md)**: dataset versions, corrections and excluded runs
- **`data/`**: every run's manifest (server image digest, flags, versions), one row per task attempt
  (resolved, tests passed, turns, tokens, tool calls, wall time, GPU energy, minimum free memory), 1 Hz
  telemetry (GPU power, free memory, server cache stats), plus speed, tuning and load profiles
- **`tasks/`**: the 18 fresh-PR tasks (upstream PR links, test counts, gold/base validation) and the
  SWE-bench Pro subset
- **`config/`**: the model server configurations as run, and the chat-template fix that keeps prefix
  caching working with Claude Code

This repository updates automatically after each model finishes. More models are in progress.

## Summary (updated 2026-10-22)

Fresh-PR = 18 real Python bug fixes merged after 2026-09-01, graded with hidden tests. SWE-bench Pro = 11-task subset (one per repository). Decode = single stream, 1024 output tokens.

| Model | Engine | Fresh-PR solo | Median min/task | GPU Wh (18 tasks) | SWE-bench Pro | Decode tok/s | 16k-prompt request (s) |
|---|---|---|---|---|---|---|---|
| laguna-s-2.1-ollama | ollama | 13/18 | 12.1 | 224 | – | 30.7 | 18.5 |
| nemotron-3.5-bolt | vllm | 8/18 | 12.6 | 404 | 2/11 (3 errored) | 60.7 | 10.2 |
| ornith-1.5-35b | vllm | 10/18 | 10.3 | 160 | 5/11 (2 errored) | 91.1 | 4.5 |
| qwen3.8-27b | vllm | 12/18 | 18.7 | 252 | 6/11 (4 errored) | 23.8 | 9.4 |
| qwen3.8-flash-next-iq4 | llama.cpp | 13/18 | 8.7 | 140 | 7/11 | 32.9 | 23.0 |
| qwen3.8-flash-next-lcpp | llama.cpp | 11/18 | 10.6 | 194 | 6/11 (2 errored) | 31.1 | 21.7 |

Errored SWE-bench Pro trials (timeouts, context overflow, API errors) count as unresolved.

Small samples: 18 and 11 tasks, mostly one attempt each, so a difference of one or two tasks is noise. Power
is GPU-only. See [METHOD.md](METHOD.md#7-threats-to-validity).

## Deep dives

- **[Qwen3.8-Flash-Next](flash-next/)**: which llama.cpp options to use on 128 GB (batch size, MTP draft
  length, mmap vs pinned memory, prompt cache), why memory and not speed is the limit, and 3-bit vs 4-bit.
  This section was previously the separate flash-next-on-dgx-spark repository.

## How to cite

Cite a versioned release so your numbers stay reproducible; `main` keeps changing as models are added. Each
release is archived on Zenodo with its own DOI ([all versions](CHANGELOG.md)).
[10.5281/zenodo.23524590](https://doi.org/10.5281/zenodo.23524590) always resolves to the latest; v0.3.0 is
[10.5281/zenodo.23539595](https://doi.org/10.5281/zenodo.23539595).
GitHub's "Cite this repository" button gives APA and BibTeX from [CITATION.cff](CITATION.cff). For example:

```bibtex
@misc{rajendran_dgx_spark_benchmarks,
  author = {Rajendran, Adithya},
  title  = {{DGX Spark benchmarks: open-weight models as autonomous coding agents on 128 GB unified memory}},
  year   = {2026},
  note   = {Dataset, version 0.3.0},
  publisher = {Zenodo},
  doi    = {10.5281/zenodo.23539595},
  url    = {https://doi.org/10.5281/zenodo.23539595}
}
```

Corrections and questions: please open an issue. Every correction is recorded in CHANGELOG.md.

## License

Data (`data/`, `tasks/`): CC-BY-4.0, see [data/LICENSE-DATA.txt](data/LICENSE-DATA.txt). Task material
belongs to the upstream projects under their own licenses. Configs, templates and scripts: Apache-2.0.
