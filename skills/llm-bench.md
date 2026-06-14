---
name: llm-bench
description: Benchmark the local Qwen model with a test prompt and report timing and response quality. Use when the user wants to test, time, or compare local model performance.
exposes: cc
trigger: /bench
locked: false
source: owner
---

Run a benchmark against the local Ollama model (qwen2.5:3b by default — use another model tag if the user specifies).

Steps:
1. Record start time
2. Send the user's prompt (or a default test prompt if none given) to Ollama via the local API
3. Record end time and token count if available
4. Report back:
   - Model used
   - Time to first token (ms) if measurable, otherwise total response time
   - Total elapsed time (seconds, 2 decimal places)
   - Approximate tokens/sec if token count is available
   - First 200 characters of the response (to confirm it's coherent)

Default test prompt if none provided:
  "Explain what a Python decorator is in two sentences."

Keep the report compact — one short paragraph. If the model is unreachable or times out, report that plainly with the error.