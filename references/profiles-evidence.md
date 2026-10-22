# Profiles and evidence

## Coverage

Coverage checks match headings, not the substance beneath them. Default aliases cover English and Vietnamese. Override using `--requirements requirements.json` when the brief mandates a different structure: `{"required_sections":{"methods":["Methods","Methodology"]}}`. Missing headings are FAIL under that explicit profile; a present heading only passes the heading-coverage check.

ACADEMIC: introduction, methods, results, discussion, references. Review research question, study design, dataset/sample provenance, reproducibility, units, denominators, uncertainty, limitations and appropriate citations. Do not invent results, identifiers, citations or bibliographic details. Check in-text citations against a supplied bibliography; automated numeric citation resolution is not provided. Distinguish hypotheses and proposed work from measured findings. Adapt coverage to a proposal/review/thesis brief; do not demand results from a proposal.

HANDOVER: overview, architecture, setup, workflows, API, testing, limitations, handover. Review build/run steps, versions, config, data ownership/storage, failures/retries, permissions, operational dependencies and acceptance boundaries. Database internals belong only when in scope; a Frontend handover needs the integration contract, not an invented server architecture. Do not infer E2E from mock tests or illustrative screens. Record known issues with severity, evidence, owner/next action and closure criteria where available.

## Evidence ledger

Pass `--evidence ledger.json --source-root SOURCE_ROOT`. A ledger uses schema version 1:

```json
{"schema_version":1,"claims":[{"id":"C1","text":"The client calls lookup","subject":"lookup","value":"implemented","sources":[{"path":"lib/client.py","sha256":"<64 lowercase hex>","start_line":10,"end_line":12,"quote":"lookup("}]}]}
```

`text` must occur in the document. Paths are relative to source root and must resolve inside it. Each source pins the entire file's SHA256 and a bounded line range containing the quote. Missing source, stale hashes, wrong quotes, escaping paths and malformed ledgers cannot pass. Pin Git commit and working-tree diff separately in the review narrative; whole-file hashes also catch uncommitted changes. Source files above 2 MiB are unsupported by this helper; use a smaller exported evidence slice with provenance or targeted independent review.

The helper validates evidence **integrity**, not whether a quote proves a claim. Codex must inspect the referenced caller/data flow and negative paths. The semantic check remains UNVERIFIED until that reasoning is performed. Two entries with the same explicit `subject` and different `value` are reported as conflicting ledger assertions; this is not general natural-language contradiction detection. Review prose for contradictions, dates, scope and units separately. No evidence ledger means source correctness UNVERIFIED, not FAIL or PASS by guesswork.

For each important claim, retain status, implementation state, source locator/hash, verification scope, date and remaining uncertainty. Keep identifiers stable across revisions. A standalone constant can be preparation only; a mock response cannot prove a real server contract. Never execute repository tests blindly: inspect their side effects first.

## Cache and context

`--cache-dir DIR` opts into a **local, private, integrity-checked structural cache**. Key: document bytes, engine implementation hash, profile and requirement content. Cache contains metadata/findings, not full document text. Every evidence file is checked afresh; semantic and visual conclusions are never reused by the structural cache. Corrupt cache entries are recomputed. The cache is not a security boundary against someone who can replace both payload and digest.

Keep cache outside repositories and user deliverables. Do not persist private document metadata without permission. Source unavailable, changed renderer/fonts, edited DOCX bytes, moved page numbering or changed requirements invalidate their respective dependent reviews. Cache rendered pages by final document/renderer/font provenance plus actual image hash; never assume page N is unchanged after repagination.

Use symbol searches and Git diff for changed claims; do not re-read every unchanged file. Deterministic checks handle package links, headings, duplicates, captions, numbering definitions, hashes and evidence anchors. LLM review handles meaning, scientific validity, implementation status, ambiguity and writing. Visual review handles clipping, pagination, glyphs and table readability.
