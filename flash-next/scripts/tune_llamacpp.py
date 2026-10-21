#!/usr/bin/env python3
"""Measure llama-server configurations for one GGUF model, one at a time, so options are chosen on evidence.

For each config: start llama-server (one container, 127.0.0.1), record load time and TRUE memory headroom
(GB10: MemAvailable - KReclaimable + SReclaimable) once loaded, then measure
  decode    single stream, 1024 output tokens (x3)
  prefill   16k and 64k prompts (unique prefix each, so no cache hit), time to first token
  reuse     the same 16k prompt twice: the 2nd request's TTFT shows whether the prefix cache is reused
and stop it. Results: DATA_ROOT/tuning/<name>/<config>.json and a table on stdout.

  python3 bench/tune_llamacpp.py flashnext      (configs defined below)
"""
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("DATA_ROOT", "results"))
IMAGE = "ghcr.io/ggml-org/llama.cpp:server-cuda"
PORT = 9199
W = Path(os.environ.get("FLASHNEXT_GGUF_DIR", "weights/qwen3.8-flash-next-gguf"))  # holds UD-Q3_K_XL/, UD-IQ4_XS/, mtp-*.gguf

# Qwen's recommended thinking-mode sampling (model card): temp 1.0, top_p 0.95, top_k 20, min_p 0, no penalties
SAMPLING = "--temp 1.0 --top-p 0.95 --top-k 20 --min-p 0 --repeat-penalty 1.0 --presence-penalty 0"
COMMON = (f"--alias m -ngl 99 -fa on --jinja --cache-ram 0 --chat-template-file /templates/qwen3.8-flash-next-inline-system.jinja "
          f"--reasoning-format auto {SAMPLING}")
Q3 = "-m /weights/UD-Q3_K_XL/Qwen3.8-Flash-Next-UD-Q3_K_XL-00001-of-00003.gguf"
IQ4 = "-m /weights/UD-IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf"
SSD = r"--load-mode mmap -ot per_layer_token_embd\.weight=CPU"
MTP = "--spec-type draft-mtp -md /weights/mtp-Qwen3.8-Flash-Next-Q8_0.gguf -ngld 99"
SETS = {"flashnext": {
    "q3-ub512-mtp3": f"{Q3} -c 131072 -np 1 {MTP} --spec-draft-n-max 3",
    "q3-ub2048-mtp3": f"{Q3} -c 131072 -np 1 -b 4096 -ub 2048 {MTP} --spec-draft-n-max 3",
    "q3-ub2048-nomtp": f"{Q3} -c 131072 -np 1 -b 4096 -ub 2048",
    "q3-ub2048-mtp2": f"{Q3} -c 131072 -np 1 -b 4096 -ub 2048 {MTP} --spec-draft-n-max 2",
    "q3-ub2048-mtp4": f"{Q3} -c 131072 -np 1 -b 4096 -ub 2048 {MTP} --spec-draft-n-max 4",
    "q3-ub2048-mtp3-mmap": f"{Q3} -c 131072 -np 1 -b 4096 -ub 2048 {MTP} --spec-draft-n-max 3 --load-mode mmap",
    "iq4-ub2048-mtp3": f"{IQ4} -c 131072 -np 1 -b 4096 -ub 2048 {MTP} --spec-draft-n-max 3",
    # round 2: honest memory accounting (mlock pins mmapped weights) and a medium batch
    "q3-ub2048-mtp2-mlock": f"{Q3} -c 131072 -np 1 -b 4096 -ub 2048 {MTP} --spec-draft-n-max 2 --load-mode mmap+mlock",
    "q3-ub1024-mtp2": f"{Q3} -c 131072 -np 1 -b 4096 -ub 1024 {MTP} --spec-draft-n-max 2",
    "iq4-ub2048-mtp2-mlock": f"{IQ4} -c 131072 -np 1 -b 4096 -ub 2048 {MTP} --spec-draft-n-max 2 --load-mode mmap+mlock",
    # round 3 (Strata's idea): the 26.8 GiB n-gram table (per_layer_token_embd) is read a few rows per token, so
    # keep it on the CPU side, memory-mapped from SSD (reclaimable page cache) instead of resident memory.
    "q3-ssdtable-mtp2": f"{Q3} -c 131072 -np 1 -b 4096 -ub 1024 {MTP} --spec-draft-n-max 2 {SSD}",
    "q3-ssdtable-nomtp": f"{Q3} -c 131072 -np 1 -b 4096 -ub 1024 {SSD}",
    "iq4-ssdtable-mtp2": f"{IQ4} -c 131072 -np 1 -b 4096 -ub 1024 {MTP} --spec-draft-n-max 2 {SSD}",
    "iq4-ssdtable-nomtp": f"{IQ4} -c 131072 -np 1 -b 4096 -ub 1024 {SSD}",
}}


def headroom() -> float:
    m = {k: int(v.split()[0]) for k, v in (l.split(":", 1) for l in open("/proc/meminfo"))}
    return round((m["MemAvailable"] - m.get("KReclaimable", 0) + m.get("SReclaimable", 0)) / 1048576, 2)


def post(body: dict, timeout=900) -> tuple[float, dict]:
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", json.dumps(body).encode(),
                                 {"content-type": "application/json"})
    t = time.time()
    d = json.load(urllib.request.urlopen(req, timeout=timeout))
    return time.time() - t, d


def stream_ttft(prompt: str, max_tokens: int) -> float:
    """Time to the first streamed token (content or reasoning)."""
    body = {"model": "m", "stream": True, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", json.dumps(body).encode(),
                                 {"content-type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        for line in r:
            if line.startswith(b"data: ") and b'"delta"' in line and (b'"content"' in line or b'"reasoning' in line):
                return round(time.time() - t, 2)
    return -1.0


def filler(tokens: int, tag: str) -> str:
    base = ("def handler(request):\n    data = parse(request.body)\n    if not data.valid:\n        raise ValueError"
            "('bad input')\n    return Response(status=200, body=render(data))\n# The service keeps a cache. ")
    return f"[{tag}] Summarize this code base.\n" + (base * (tokens * 4 // len(base) + 1))[: tokens * 4]


def measure(name: str, cfg: str, args: str) -> dict:
    cname = f"tune-{name}"
    subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
    subprocess.run(["sudo", "-n", "/usr/local/sbin/drop-caches", "3"], capture_output=True)
    before, t0 = headroom(), time.time()
    cmd = ["docker", "run", "-d", "--name", cname, "--network", "host", "--gpus", "all", "-v", f"{W}:/weights:ro",
           "--ulimit", "memlock=-1:-1",
           "-v", f"{ROOT / 'templates'}:/templates:ro", "--entrypoint", "/app/llama-server", IMAGE,
           "--host", "127.0.0.1", "--port", str(PORT), "--metrics", *shlex.split(COMMON), *shlex.split(args)]
    subprocess.run(cmd, check=True, capture_output=True)
    res = {"config": cfg, "args": args, "common": COMMON, "headroom_before_gib": before}
    try:
        while True:
            try:
                if urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=3).status == 200:
                    break
            except Exception:  # noqa: BLE001
                pass
            st = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", cname], capture_output=True, text=True).stdout.strip()
            if st != "running":
                raise RuntimeError("exited: " + subprocess.run(["docker", "logs", "--tail", "15", cname], capture_output=True, text=True).stderr[-1500:])
            if headroom() < 12:
                raise RuntimeError(f"headroom fell to {headroom()} GiB while loading - aborted")
            time.sleep(5)
        res["load_s"] = round(time.time() - t0, 1)
        time.sleep(5)
        res["headroom_loaded_gib"] = headroom()
        dec = []
        for i in range(3):
            dt, d = post({"model": "m", "max_tokens": 1024, "messages": [{"role": "user", "content": f"[{i}{time.time()}] Write a "
                          "thorough Python module that parses ISO-8601 durations, with tests and docstrings."}]})
            n = d["usage"]["completion_tokens"]
            tm = d.get("timings") or {}
            dec.append(tm.get("predicted_per_second") or n / dt)
        res["decode_tok_s"] = round(sorted(dec)[1], 1)
        res["draft_accept"] = (d.get("timings") or {}).get("draft_n_accepted"), (d.get("timings") or {}).get("draft_n")
        for k in (16384, 65536):
            ttft = stream_ttft(filler(k, f"u{k}{time.time()}"), 16)
            res[f"ttft_{k // 1024}k_s"] = ttft
            res[f"prefill_{k // 1024}k_tok_s"] = round(k / ttft) if ttft > 0 else None
        p = filler(16384, "reuse-fixed")
        stream_ttft(p, 8)
        res["ttft_16k_repeat_s"] = stream_ttft(p + "\nAnd one more line.", 8)   # same prefix, small suffix
        res["min_headroom_gib"] = headroom()
    except Exception as e:  # noqa: BLE001
        res["error"] = str(e)[-800:]
    finally:
        log = subprocess.run(["docker", "logs", cname], capture_output=True, text=True)
        res["log_tail"] = (log.stdout + log.stderr)[-3000:]
        subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
    return res


def main():
    name = sys.argv[1]
    only = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    out = DATA_ROOT / "tuning" / name
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for cfg, args in SETS[name].items():
        if only and cfg not in only:
            continue
        if "IQ4_XS" in args and not (W / "UD-IQ4_XS").exists():
            print(f"{cfg}: skipped (weights not downloaded)", flush=True)
            continue
        r = measure(name, cfg, args)
        (out / f"{cfg}.json").write_text(json.dumps(r, indent=1))
        rows.append(r)
        print(f"{cfg:22s} load={r.get('load_s')}s headroom={r.get('headroom_loaded_gib')}GiB "
              f"decode={r.get('decode_tok_s')} tok/s ttft16k={r.get('ttft_16k_s')}s ttft64k={r.get('ttft_64k_s')}s "
              f"reuse16k={r.get('ttft_16k_repeat_s')}s {('ERR ' + r['error'][:150]) if r.get('error') else ''}", flush=True)
    small = ROOT / "data/tuning" / name
    small.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.json"):
        d = json.loads(f.read_text()); d.pop("log_tail", None)
        (small / f.name).write_text(json.dumps(d, indent=1))


if __name__ == "__main__":
    main()
