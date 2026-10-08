# Hindsight shadow evaluation

This evaluates Hindsight alongside the existing retriever using the same labeled queries. It does not change production retrieval or prompt injection.

The runner exports only records that pass the plugin's visibility and ACL checks for each evaluated session. Visibility defaults mirror production: raw events are excluded, pending review is hidden, private/group scopes remain isolated, and ACL rules are enabled. If the plugin uses different visibility settings, pass the corresponding flags. Each session gets a separate temporary Hindsight bank. Banks are deleted when the run finishes; `--keep-banks` retains the uploaded data for inspection. The default retain mode is `verbatim`, so this focuses on recall over the plugin's already-curated memories rather than testing Hindsight's memory extraction or observation consolidation.

## Run

Start a Hindsight server and configure its LLM provider there. The default endpoint is `http://127.0.0.1:8888`; set `HINDSIGHT_API_KEY` if the server requires an API key. Create labeled cases with the existing evaluator, then run:

```powershell
python benchmarks/run_recall_evaluation.py export --db <memory.db> --out eval_cases.jsonl
python benchmarks/run_hindsight_shadow_evaluation.py --db <memory.db> --cases eval_cases.jsonl --base-url http://127.0.0.1:8888 --out hindsight_report.json
```

Fill `relevant_ids` in the exported JSONL before evaluating. The report compares the local pipeline and Hindsight with Recall@K, MRR, Hit@1, per-query IDs, and mean query latency. Hindsight bank seeding time is reported separately from recall latency.

The script sends the visible memory text and evidence to the configured Hindsight endpoint only when you run it. Use a local Hindsight instance for private data. Avoid `--keep-banks` unless the retained test banks are needed, and remove them after inspection.
