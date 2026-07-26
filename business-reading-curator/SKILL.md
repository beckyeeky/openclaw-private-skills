---
name: business-reading-curator
description: Curate recurring, source-verified English long-form business reading packs from identifiable human authors, transcripts, filings, regulatory documents, and established editorial publications. Use when asked to find an English business article, create a pharma/biotech/CDMO/API/healthcare or cross-industry reading issue, preview candidates, inspect reading history or cooldowns, mark an issue complete, or compare its primary and corroborating sources.
---

# Business Reading Curator

Select original human-created reading; do not write a replacement business review. Keep the
intellectual encounter between the reader and the linked source.

## Runtime

Use the deterministic registry CLI for every run:

```bash
python3 {baseDir}/scripts/curator.py init
python3 {baseDir}/scripts/curator.py state
python3 {baseDir}/scripts/curator.py history --limit 20
```

Runtime data defaults to `~/.hermes/business-reading-curator/`. Override it only with
`BUSINESS_READING_HOME` or `--home`. Never put reading history, fetched article bodies, API
keys, or user configuration in the skill repository.

Read these references as directed:

- For a new issue or candidate preview, read [references/workflow.md](references/workflow.md)
  and [references/scoring-and-cooldowns.md](references/scoring-and-cooldowns.md).
- Before calling a script with structured input, read
  [references/input-contracts.md](references/input-contracts.md).
- Before constructing or completing a pack, read
  [references/output-contract.md](references/output-contract.md).

## Decide the operation

### Create an issue

1. Load `state` and `history` before searching.
2. Research live sources. Never generate candidates from model memory.
3. Discover 8–15 leads and fully inspect at least five viable candidates.
4. Pass each inspected candidate and its temporary extracted body to `assess`.
5. Run `shortlist`; in automatic mode choose the highest-ranked eligible candidate.
6. Refetch the selected source body, build the spoiler-free guidance JSON, and call `prepare`
   with the temporary body so the CLI can verify every vocabulary expression.
7. Return the complete Markdown pack content or split it without omitting sections if the
   chat transport has a length limit.

Do not publish an issue when fewer than five candidates received a real full-text assessment.
Record rejected and deferred candidates anyway.

### Preview candidates

Perform the same live research and assessment, then run:

```bash
python3 {baseDir}/scripts/curator.py shortlist
```

Show at most the top three. Do not call `prepare`; previewing must not consume an issue number
or mark a candidate selected.

### Select a requested candidate

Honor the user's candidate choice only if the script reports `shortlisted`. User choice may
create a clearly labeled cooldown/novelty exception when there is a documented material
update, but it cannot bypass provenance, access, duplicate, or advertising hard gates.

### Revise an incomplete pack

Use `revise` with the same prepare contract plus `issue_id` and a freshly retrieved temporary
body. It creates a new immutable version snapshot, updates the canonical Markdown, and does
not create another selected record or consume another issue number. Do not revise a completed
issue back into a spoiler-free state.

### Complete a reading

When exactly one selected issue is incomplete, “I finished it” may resolve to that issue.
When several are incomplete, ask for the stable `BRP-YYYY-NNN` identifier rather than guess.
Refetch live sources where possible, combine them with the saved evidence ledger, construct
the comparison JSON, and call `complete`. Do not provide interactive coaching.

### Inspect or maintain history

Use `history`, `state`, `shortlist`, `export`, `alias`, and `alias-suggest`; never edit SQLite
by hand. JSONL exports are read-only audit artifacts and must not be imported back as a
source of truth.

## Non-negotiable source boundaries

- The primary article must be freely and fully accessible. Do not use paywalled text.
- Do not bypass login, subscription, CAPTCHA, or access controls.
- A normal browser user agent, JavaScript rendering, and ordinary Cloudflare browser
  verification are allowed for public pages.
- Use an archive only for an originally public page that disappeared. Preserve the canonical
  original URL, archive URL, and snapshot date; reject unverifiable or incomplete snapshots.
- Link the original source, not a search snippet, aggregator, AI summary, or marketing repost.
- Never persist or reproduce the full article. A pack contains links and limited short
  quotations only.
- Treat linguistic style as no evidence of human authorship. Score provenance.
- Never invent facts, quotations, financial figures, author identities, access results, or
  article text.
- If live retrieval or verification fails, report the failure and do not fabricate a pack.

## Output behavior

Keep titles, vocabulary definitions, reading questions, and the short post-reading synthesis
in English. Keep provenance, advertising, access, and deduplication notes concise and in
Chinese; bilingual fixed headings are acceptable. Default to B2–C1 and adjust only after
reader feedback.

`prepare` is intentionally spoiler-free. Do not add a conclusion, reconstructed narrative,
or full summary around its output. `complete` may add one evidence-based synthesis of at most
250 English words.
