# anchr-eval

Offline evaluation over the Anchr App REST API. The first evaluation round is in place: the
source material, 10 cases, ingestion, evidence binding, resumable batch execution, and offline
scoring driven by explicit review annotations. The first 10-case baseline is saved; version
comparison and optimisation experiments are not implemented yet.

Start with the [evaluation dataset notes](datasets/anchr-seed-v1/README.md), or go straight to
the [10 cases and their reference answers](datasets/anchr-seed-v1/review/questions.md).

The PDFs used for upload live in `output/pdf/`. Cases, reference answers, annotations, and the
full source snapshot stay on the evaluation side only — they must never be uploaded into the
knowledge base under test.

## Install and configure

Python 3.11 or newer:

```bash
uv sync
```

Set `ANCHR_BASE_URL` and `ANCHR_ACCESS_TOKEN` in `.env` at the project root; see `.env.example`
for the format. A local configuration has already been saved: the file is readable and writable
by the current user only, and is excluded by `.gitignore`. Environment variables take precedence
over `.env`; the token is never written into reports.

## Commands that exist today

```bash
uv run anchr-eval validate
uv run anchr-eval doctor
uv run anchr-eval ingest
uv run anchr-eval status
uv run anchr-eval bind
uv run anchr-eval review-bindings
uv run anchr-eval smoke --case-id ANCHR-010-001
uv run anchr-eval batch --name baseline-v1
uv run anchr-eval score --name baseline-v1
uv run pytest -q
```

Run these from the project root, or point at the project explicitly with `--root`.

- `validate` checks case IDs and the SHA-256 of the four uploaded PDFs.
- `doctor` performs a read-only check of the token role and session capabilities, and writes the
  result to `runs/setup/doctor.json`.
- `ingest` creates or reuses a knowledge base marked with a dedicated description tag, uploads
  the four PDFs to the OSS configured by the service using temporary STS credentials, then
  submits an ingestion task carrying a `clientRequestId`.
- `status` queries task and document status once; it does not retry failed tasks automatically.
- `bind` runs evidence retrieval once all four documents are `ANSWERABLE`, and verifies every
  candidate by calling the preview endpoint for each one. It accepts only full-excerpt matches
  on the same page; cross-chunk hits, reflowed tables, and parsed-text differences stay marked
  `needs_review`. At most three concurrent read-only probes; a probe may trigger the service's
  internal query rewriting and follow-up generation, but that is not counted in the evaluation
  result.
- `review-bindings` applies the per-item source review written in `runs/setup/binding-review.json`
  locally. After validating the service, document hash, source-text hash, page number, chunk-text
  hash, and the actual excerpt, it writes `bindings.reviewed.json` plus a derived
  `cases.bound.jsonl`; the original `cases.jsonl` is left untouched. Evidence that was located
  but is missing key characters stays marked `located_text_partial` and is never upgraded to
  full-text.
- `smoke` runs one retrieval and one plain RAG question for a given case, explicitly scoped to
  documents, in a fresh session each time. The raw response, latency, scope, and binding snapshot
  are saved under their own `runs/smoke-.../`. Nothing is scored automatically, and missing token
  usage or cost is not recorded as zero.
- `batch` runs all ten cases in order, saving each case's execution intent and result. Complete
  results are reused; if a write request has an uncertain result it stops and asks you to check
  first rather than blindly repeating the call. The baseline was first established with
  `--reuse-run runs/smoke-20f868cf-6889-45c7-b686-eedec5370822` to reuse the already-finished
  first case; running a batch under the same name afterwards reuses all results.
- `score` checks that `runs/<batch-name>/review.json` matches the actual answer hashes, the case
  facts, and the citation counts, then aggregates `scores.json` offline. Scoring follows an
  explicit per-case review and never treats a successful API response as a correct answer;
  invalid experiment samples are listed separately, and clarification cases and unanswerable
  cases are aggregated separately.
- `retry-failed` is run explicitly by the user only after the failure cause has been cleared and
  the ingestion task has reached a terminal state. It retries the failed items by reusing the
  original task and does not re-upload the material.

Ingestion progress is saved in `runs/setup/ingestion.json`, which contains no access token or
STS secret. If a submission's result is uncertain, running `ingest` again first looks the task up
by the same `clientRequestId` instead of blindly re-submitting; if that lookup fails, you need to
check the server state before proceeding. Objects that were uploaded but never submitted are not
deleted automatically.

The client distinguishes errors at two layers — the HTTP status and the business response `code`
— does not follow redirects that carry the token, and does not automatically retry write requests
such as creating sessions, knowledge bases, or messages. The current REST contract is based on
the local anchr-app code; the full online ingestion flow still needs to be verified for real.

## Current progress and limitations

The Docling Tailscale access path has been fixed, all four PDFs from the original task ingested
successfully, for 24 chunks in total. All 17 evidence items were located against real chunks:
6 exact matches, 8 confirmed equivalent by source review, and 3 with missing parsed text. Actual
IDs and current status are in `runs/setup/`; the derived cases carrying real IDs are in
[cases.bound.jsonl](runs/setup/cases.bound.jsonl). The source review was performed by Codex and
has not been through independent human review.

All ten cases in the first round completed a plain RAG call, and all ten persisted answers match
the immediate responses. Under Codex-driven strict source review, 2 of the 9 valid cases passed;
case 010 is listed separately because adversarial text in the document corrupted it. That review
is not an independent human blind review. See the [full baseline report](reports/baseline-v1.md),
the [first trial-run report](reports/seed-smoke-001.md), and the
[incident write-up](docs/first-ingestion-incident.md). Ten cases is a small sample, so the latency
percentiles describe this run only.

The existing `AssetDTO` and chunk preview DTO do not expose generation values. Bindings
deliberately keep `index_generation=null` and do not pass `versionNo` off as an index generation.
In the current local implementation the preview endpoint checks whether a chunk belongs to the
active generation, but that is only evidence of validity at the moment of binding; strict version
reproducibility still needs a server version and index configuration snapshot. Official chunk
metrics must not treat trial-run results as a verified baseline.

The index model / dimensions / fingerprint, chunking parameters, retrieval parameters, and
generation model name for this run are saved in `runs/setup/server-snapshot.json`, which contains
no credentials; the online Git commit is still unavailable. The existing review applies only to
the chunk text as captured at that moment — after re-chunking or re-parsing, binding and review
must be redone.
