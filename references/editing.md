# Editing and final verification

## Narrow, conservative text edit

Run audit first; paragraph indexes in its compact inventory include body, nested-table and other document paragraphs in XML order. A plan must pin the exact input hash:

```json
{"input_sha256":"<input SHA256>","replacements":[{"paragraph":4,"old":"previous wording","new":"revised wording"}]}
```

Run `python3 scripts/docx_engineer.py edit INPUT.docx --plan PLAN.json --output CANDIDATE.docx`. The source and any existing destination are never overwritten. Every replacement must match once in the specified paragraph. The patcher changes text nodes only; spanning text inherits the first affected run's format. Other run/paragraph properties and untouched XML bytes stay intact; all other ZIP member contents are identical. Space preservation is made explicit on changed nodes when needed. Multiple replacements are validated before publication. Newline/tab/control-character insertion is outside this patcher's scope.

Paragraphs with fields, hyperlinks, drawings, revisions, content controls or other complex inline objects are rejected. Signed documents and unsupported packages are rejected. This is a safe subset, not a general-purpose Word editor. To change a complex paragraph, use existing document-editing capabilities and verify affected parts/fields/anchors. Never silently flatten it. Work on a copy and retain the original.

## Creating and structural editing

Use the existing `documents` skill and bundled workspace runtime when available; load only its relevant guides. Do not vendor that skill or assume a machine-specific path. When unavailable, inspect the available document tooling and report missing rendering/authoring capability. Do not install a large stack automatically. A suitable existing Python DOCX library can author headings, tables, styles and captions; direct OOXML is appropriate for narrowly understood structures. Respect template geometry/styles and preserve comments, revisions, bookmarks, relationships, drawings and fields unless intentionally changed.

For academic output, preserve citation/reference semantics and numerical uncertainty. For handover output, anchor technical claims to a source snapshot and make acceptance boundaries explicit. Keep status metadata separate from prose when the user's style excludes repeated status labels.

## Verification sequence

1. Compare source/output content and package part hashes; enumerate intentional changes. Check all sections, tables, text boxes, headers/footers, footnotes/endnotes and citations affected by the operation. The helper flags text boxes/notes for extra review; it does not guarantee their semantic completeness.
2. Run `verify`; resolve structural failures. The helper does not execute macros, remote links, source code or render commands.
3. Perform targeted factual/writing review. Numeric citations and cross-document references require review against supplied sources. Contradictions not represented in ledger assertions require semantic review.
4. Render the exact final DOCX via the existing document pipeline to PDF and page images. Record input hash, renderer/version/fonts, page count, render exit result and reviewed pages. If renderer fails, diagnose before retrying and keep layout UNVERIFIED. Do not substitute the user's desktop converter when the available document skill requires its bundled converter.
5. Inspect every final page at readable resolution: title/TOC, typography, glyphs, heading orphans, numbering, captions, split/merged/long tables, repeated headers, images, cross-references and footer pagination. Compare unchanged image hashes with a known reviewed render only with explicit page mapping. Any change after QA requires revalidation of dependent pages.
6. Update fields/TOC with a capable Word/conversion tool, re-render, verify cached display and inspect again. A field's presence does not prove it updates correctly in Word; say when native Word field updating has not been exercised. Never add a fake cached value to conceal missing evidence.

Keep render intermediates/cache local. Report unresolved checks visibly; neither XML parsing nor a successful render proves all-page visual quality.
