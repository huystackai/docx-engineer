# docx-engineer

A small Codex Skill for academic documents, software handovers and technical Word reports. One skill, one standard-library Python CLI, two profile references, no agents or service backend. Version 0.1.0.

## Install and invoke

Install the repository as a skill directory, using an authenticated account with access to this private repository. Do not overwrite an existing installation without reviewing it.

```bash
gh repo clone huystackai/docx-engineer "${CODEX_HOME:-$HOME/.codex}/skills/docx-engineer" -- --branch feat/docx-engineer-v0.1 --single-branch
```

The folder must contain `SKILL.md`. If the current chat does not discover a newly installed skill, start a new chat. The repository follows the [official skill conventions](https://learn.chatgpt.com/docs/build-skills).

Example requests:

```text
$docx-engineer AUDIT HANDOVER /absolute/path/handover.docx against the supplied repository; read-only, no report file.
$docx-engineer EDIT ACADEMIC /absolute/path/manuscript.docx using these reviewer comments; preserve the template and render the final output.
$docx-engineer VERIFY HANDOVER /absolute/path/candidate.docx; distinguish source-backed implementation from unverified claims.
```

## Layout

```text
SKILL.md                      Short workflow and quality gate
agents/openai.yaml            Codex discovery metadata
scripts/docx_engineer.py       AUDIT / VERIFY / narrow EDIT
references/editing.md          Preservation and visual verification
references/profiles-evidence.md Profiles, evidence schema and cache rules
tests/test_engine.py           Baseline synthetic OOXML fixtures
tests/test_adversarial.py      Separate adversarial cases
tests/visual_fixture.py        Optional real-DOCX renderer smoke fixture
REVIEW.md                     Release review, corrections and limitations
```

## CLI

Python 3.10+; the CLI has no third-party dependency and makes no network requests. In Codex artifact work, prefer the bundled workspace Python/runtime. No package installation is performed.

```bash
python3 scripts/docx_engineer.py AUDIT input.docx --profile HANDOVER
python3 scripts/docx_engineer.py VERIFY input.docx --profile ACADEMIC --paragraphs 10:20
python3 scripts/docx_engineer.py VERIFY input.docx --evidence ledger.json --source-root /path/to/source
python3 scripts/docx_engineer.py AUDIT input.docx --cache-dir /private/local/cache
python3 scripts/docx_engineer.py EDIT input.docx --plan plan.json --output new-candidate.docx
python3 -m unittest discover -s tests -v
```

JSON exit codes: **0** all reported checks resolved; **1** failure; **2** unverified work remains. A successful EDIT intentionally returns 2 because visual/semantic review is still required. Structural scans normally return 2 even for valid fixtures. Never treat exit 2 as full verification or discard a successfully patched candidate merely because more QA remains. JSON inventory contains paragraph indexes; `--paragraphs START:END` returns at most 40 bounded snippets.

The patcher accepts only exact, hash-bound text replacements into a new DOCX. It retains unchanged XML bytes, ZIP member content and formatting properties; inserted text inherits the first affected run's formatting. Complex paragraphs are rejected. Full document creation, structural edits and advanced Word objects use existing document-editing capabilities under the skill's workflow, followed by independent checks and all-page visual QA.

Details and schemas are loaded progressively from the references. AUDIT/VERIFY do not write unless local caching is explicitly enabled. Even with a cache, claim source hashes are validated again for each invocation. A cache-only CLI hit avoids package parsing after confirming the whole input hash, engine implementation hash and requirement content.

## Validation boundaries

The CLI checks bounded OOXML packages, relationships, heading coverage/hierarchy, simple manual numbering, numbering definitions, nearby captions, duplicate labels, simple sequence gaps, internal bookmarks/REF fields, repeated long paragraphs and evidence integrity. It does not prove factual truth, implementation completeness, arbitrary prose contradictions, scientific validity, bibliography correctness or visual layout. Those checks remain UNVERIFIED until Codex performs the appropriate source/editorial/visual review. File and object limits and complex caption/numbering limitations are documented in the release review.

Rendering is an external document capability, not a dependency silently installed by this skill. The optional visual fixture generator uses an already-available `python-docx`; run it with `python3 tests/visual_fixture.py --output-dir /path/to/private/work`, then use the existing document renderer on both DOCX files. If conversion fails, layout remains UNVERIFIED and readiness cannot pass.

User documents, evidence, screenshots, caches and generated test artifacts stay outside the repository. This release adds no permission to publish future edited documents or mutate their source repositories.
