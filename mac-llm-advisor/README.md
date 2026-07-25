# SILICON/FIT — Mac LLM Advisor

A single-file web app that answers two questions:

1. **Which Hugging Face models run best on my Mac?** — pick your Apple silicon
   chip and unified memory, then compare a curated catalog of ~27 popular
   open-weight models (Llama, Qwen3, Gemma 3, Phi-4, Mistral, gpt-oss,
   GLM-4.5-Air, DeepSeek R1…) by memory fit, estimated decode speed, max
   context, and quality tier.
2. **How should I configure LM Studio for it?** — select a model and get a
   generated "tune sheet": runtime (MLX vs GGUF), quantization, context
   length, GPU offload, KV-cache quantization, Flash Attention, CPU threads,
   batch size, mlock, speculative-decoding draft, plus the
   `sysctl iogpu.wired_limit_mb` bump when a model needs more than the
   default Metal wired-memory budget. One click copies the whole sheet.

## Run it

Open `index.html` in any browser — no build, no server, no network calls.

```sh
open mac-llm-advisor/index.html
```

## How the estimates work

- **Weights** = `params × bits-per-weight ÷ 8 × 1.03` (GGUF K-quant effective
  bpw; MLX 4-bit ≈ 4.5 bpw; MoE models keep all experts in memory).
- **KV cache** = `2 × layers × KV-heads × head-dim × 2 bytes × context`,
  from each model's public config (GQA-aware; sliding-window models
  discounted; DeepSeek MLA uses its compressed cache size).
- **GPU budget** = macOS Metal wired limit (~⅔ of RAM up to 36 GB, ~¾ above),
  with a "raised" ceiling for the sysctl override.
- **Decode speed** = memory-bandwidth-bound estimate
  (`bandwidth × efficiency ÷ active bytes per token`), with a GPU-compute cap
  for small models. Treat all speeds as ±30% shortlisting numbers, not
  benchmarks.

Fit statuses: **FITS** (comfortable) / **TIGHT** (loads, close other apps) /
**RAISE LIMIT** (needs the sysctl bump) / **NO FIT**.

Catalog curated early 2026. Not affiliated with Apple, Hugging Face, or
LM Studio.
