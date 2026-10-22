# Release review for docx-engineer 0.1.0

## Scope and method

The implementation was followed by a separate skeptical review phase in the same Codex session. No subagents were used. Baseline tests were not accepted as sufficient: a separate adversarial test module exercised preservation, false success, unsupported inputs and cache/evidence failure paths. This is a self-review performed under a separate adversarial role, not an external human certification.

Two major correction cycles were used, then regression tests and a real DOCX render comparison. Only synthetic fixtures were generated. No BusGo files, source code, original user documents, screenshots, private evidence, caches or raw test outputs are included in this repository.

## Findings and corrections

| Severity | Observed defect before correction | Correction and regression evidence |
|---|---|---|
| Major | Text patching normalized untouched numeric XML entities. No lost visible text was observed, but the byte-preservation contract was violated. | Only changed text nodes are patched; `test_untouched_entity_bytes_not_normalized` compares the entire document part against an exact expected byte patch. |
| Major | Move revisions and bookmark boundaries were eligible for narrow edits. | Complex inline objects are rejected; protected-field, move-revision and bookmark-boundary tests pass. |
| Major | Ordinary prose references could masquerade as captions, one label could cover two distinct images, sequence gaps and VML figures were missed. | Restrict caption candidates, consume labels once, check simple sequence gaps and VML objects. Five adversarial cases pass. |
| Major | Relationships referenced by headers were not checked, and bookmark ranges/names were not validated. | Check per-part relationship IDs, bookmark pairing and duplicate names. Missing-header-link, unclosed-bookmark and duplicate-bookmark tests pass. |
| Major | UTF-16 could bypass the DTD restriction; a non-UTF-8 declaration could produce incorrect patched text. | Encoding-aware parser rejects DTDs; narrow editor rejects non-UTF-8 declarations. Both adversarial tests pass. |
| Major | A complete cached payload digest did not imply valid payload shape/statuses. | Validate cached schema and status vocabulary before reuse; invalid JSON, invalid findings and wrong payload type all recompute. |
| Major | Destination writing did not protect against a partial output on I/O failure. | Fully write a sibling temporary file, publish using an exclusive hard link, always clean the temporary file. Simulated publication failure leaves no output or temporary file. Original and existing outputs are never overwritten. |
| Minor | A cache hit still parsed the package, and repeated claims reread the same source. | Fast cache-only CLI path skips parsing after hash/schema checks; one source read per ledger snapshot. Dedicated tests pass. |
| Minor | The initial visual fixture split a table row across pages and inherited a title rule. | Adjust the synthetic authoring fixture, re-render both documents, inspect final pages. No core-engine correction cycle was added for this fixture layout adjustment. |

No Critical defect or observed loss of document text was found. No unresolved Critical/Major defect remains **within the stated 0.1 scope**. The findings above are bounded observations, not proof that no other defects exist.

## Tests and observable results

- Baseline: **38/38 PASS**.
- Adversarial cycle 1: **10 failures among 12 cases**, reproduced before correction; full regression **50/50 PASS** afterward.
- Adversarial cycle 2: **6 failures and 1 error among 19 cases**, reproduced before correction; full regression **57/57 PASS** afterward.
- Final recorded run: **57 tests, 0 failures, 0 errors**. Each test's expected outcome and actual result was recorded in a local machine-readable test ledger; raw generated test outputs stay outside Git. Assertions and fixture generators are committed and reproducible.
- Valid ACADEMIC and HANDOVER fixtures have no structural FAIL findings. Semantic, bibliography and visual checks remain UNVERIFIED where not performed by the CLI. Matching source quotes never pass claim semantics.
- Covered: invalid hierarchy; missing sections; manual/automatic numbering defects; duplicate/missing captions; repeated paragraphs; missing/split REF fields; broken relationships/bookmarks; long and merged tables; conflicting ledger assertions; missing/stale source evidence; symlink escapes; corrupt/unsupported packages; DTDs; conservative edits; stale plans; protected objects; no-overwrite behavior; cache invalidation; publication failure cleanup; read-only audit; result truncation.
- Codex skill validator: **PASS**, using an existing Python interpreter with existing PyYAML. The bundled artifact interpreter lacked PyYAML; nothing was installed. UI metadata and local reference links were checked separately.

Reproduce core tests with `python3 -m unittest discover -s tests -v` on Python 3.10+. No third-party test framework is needed.

## Real DOCX preservation and layout

An optional `python-docx` fixture generator produced a real three-page handover containing headings, mixed bold/italic runs, a 34-row table with a merged summary cell, repeated header and footer PAGE field. The engine replaced text across two runs into a distinct candidate. Unchanged ZIP part contents and formatting properties were verified; no original file was modified. Only `word/document.xml` changed.

Both original and candidate were rendered with the available bundled document renderer/LibreOffice to PDF and page images. All three original pages were inspected individually, the changed candidate page 1 was inspected, and candidate pages 2–3 were pixel-identical to those inspected original pages under an explicit page mapping. Text bounds and all footer values were also checked. The first render exposed an awkward split row; the final fixture prevented row splitting and was re-rendered and inspected again. This validates this fixture's final formatting and bounded preservation, not arbitrary Word documents.

The visual review is an agent observation with locally retained hashes and provenance; it is not independent attestation or a universal layout detector. Native Microsoft Word field updating was not exercised.

## Explicit limitations and accepted scope

- The helper is a structural/evidence-integrity tool. Factual truth, arbitrary prose contradictions, academic validity, bibliography resolution, writing and implementation status require targeted Codex review. Explicit ledger conflicts are detected; free-text semantic contradictions are not automatically detected.
- Headings/section coverage is lexical. Numeric heading/caption inference, continuation captions, chapter-based numbering, logos/decorative images, complex galleries, floating drawings and captions inside tables need contextual review. Nested images and complex objects are not comprehensively classified by the nearby-caption heuristic. Conservative warnings/false positives may require a documented NOT APPLICABLE decision; do not silently erase them.
- Word's full numbering semantics, field refresh, TOC pagination and page layout require the existing document tool/rendering pipeline and final all-page inspection. A renderer failure leaves visual checks UNVERIFIED. The helper never executes a renderer or accepts a renderer exit as proof of layout.
- Narrow EDIT handles exact text only in uncomplicated UTF-8 main-document paragraphs. It rejects signed packages and complex inline objects; new/structural edits use existing document capabilities. It cannot guarantee arbitrary third-party editor fidelity. New text inherits the first affected run's format. Exclusive publication requires filesystem hard-link support and fails safely when unavailable.
- Transitional WordprocessingML DOCX only. Legacy DOC, strict OOXML, encrypted and macro-enabled main document types are unsupported. ZIP/member limits: 256 MiB total expanded/raw, 32 MiB per member, 10,000 members, 100,000 paragraphs; source anchor files at most 2 MiB. No extraction to arbitrary disk paths or external-link execution occurs.
- CLI output lists at most 100 findings/100 headings and 40 requested paragraph snippets, with truncation flags for findings. Overall status is calculated before findings are truncated. Local caches are trusted performance aids with digest/schema checks, not a defense against an attacker controlling both payload and digest.
- No automatic citation retrieval, source-code execution, package installation, multi-agent service, Git mutation or publishing permission is embedded in the skill.
- Tests were run on macOS with existing Python 3.12. Windows/Linux filesystem behavior and other office renderers were not exercised. No token-saving percentage or universal accuracy claim is made.

## Token-efficiency decisions

The entrypoint is 35 lines and routes to two short references. Scripts run without loading implementation source into model context. Input inventory precedes selective reading; Git diff and symbol searches scope source review. Hash keys include document, engine, profile and requirements. Evidence is fresh per invocation but each source is read once per snapshot. Cache-only hits avoid OOXML reparsing. Deterministic checks replace repeated reasoning over headings, captions, links and hashes; semantics and all-page visual QA remain required.

## Release decision

Technical quality gate: **PASS for the bounded 0.1 skill and helper scope**. Required capabilities are implemented through the helper plus the existing document workflow or explicitly scoped out above. Relevant tests pass; observed preservation and final fixture layout checks pass; the separate adversarial review has no unresolved Critical/Major issue. Publishing additionally requires a clean intended staged diff, secret/artifact screening, authenticated `huystackai`, verified private target and write permission. These checks must be completed before pushing; no force push or unrelated branch update is permitted.
