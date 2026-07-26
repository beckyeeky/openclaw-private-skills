# Live Research Workflow

## Contents

1. Run modes
2. Beginning-of-run checks
3. Industry rotation
4. Candidate discovery
5. Full assessment
6. Selection and publication
7. Completion
8. Retrieval and archive boundaries
9. Failure behavior

## 1. Run modes

- **Automatic issue:** assess at least five candidates, choose the highest eligible ranked
  candidate, and prepare one pack.
- **Preview:** assess candidates and display the top three; do not select or publish.
- **Manual selection:** prepare the user's shortlisted candidate. Never override a hard gate.
- **Complete:** unlock the comparison and short synthesis for an existing selected issue.

Scheduling is external to this skill. Every scheduled invocation performs the same on-demand
workflow and is safe to retry.

## 2. Beginning-of-run checks

Always initialize and load durable state:

```bash
python3 {baseDir}/scripts/curator.py init
python3 {baseDir}/scripts/curator.py state
python3 {baseDir}/scripts/curator.py history --limit 20
```

The history database is the source of truth. Load:

- all selected history needed by `state`;
- the latest 20 selected readings;
- rejected or deferred candidates reviewed in the last 180 days;
- active company, product, transaction, regulatory, theme, publication, author, and
  source-type cooldowns.

Do not rely on conversational memory for deduplication.

## 3. Industry rotation

Use rolling ten-issue targets:

| Bucket | Target |
|---|---:|
| `pharma_health` | 5 |
| `chemicals_materials` | 1 |
| `technology_semiconductors` | 1 |
| `industrial_logistics` | 1 |
| `consumer_retail` | 1 |
| `finance_energy_other` | 1 |

Within `pharma_health`, prioritize pharmaceuticals and biotechnology, then CDMO, API,
life-science tools, medical devices, healthcare services, and insurance.

Follow `state.rotation.suggested_search_order`. Quality remains a hard constraint: if the
most underrepresented bucket has no eligible candidate, move to the next bucket. User-requested
industry overrides are allowed and should be recorded as intentional.

## 4. Candidate discovery

Search developments from the previous 12 months. Prioritize the latest 90 days for financial
results, regulatory decisions, and transaction updates. If needed, expand to 18 and then
24 months. Use material older than 24 months only as an explicitly labeled classic reading.

Look for strategy changes, M&A, capacity investment, launches, pipeline decisions,
manufacturing and supply chains, pricing, regulation, patent expiry, market entry,
restructuring, profitability, and competitive repositioning.

Discover 8–15 leads. Prefer, in order:

1. Independent long-form editorial reporting with a named author.
2. Filings, signed shareholder letters, verified transcripts, regulatory or government
   documents, court filings, named speeches, and named interviews.
3. Named trade or institutional research.

Company presentations, product pages, press releases, consulting reports, and vendor research
may support a pack but normally cannot be the primary reading. Sponsored or partner content
cannot be the primary or independent corroborating source.

For each lead, record the canonical URL, title, author/speaker/institution, publication,
publication date, access state, source position and type, companies, event key, themes, and
approximate word count.

Do not count a search snippet as an assessment. Fully open and inspect at least five viable
candidates. Assign all candidates in the run one stable `research_batch_id`; the CLI enforces
five full-text fingerprints before publication.

## 5. Full assessment

For every full assessment:

1. Verify free full-text access.
2. Verify the original publication domain and date.
3. Verify the named author, speaker, editor, or responsible institution.
4. Inspect author/editorial profiles and AI/sponsorship disclosures when available.
5. Determine whether it is original, syndicated, shortened, translated, or republished.
6. Extract the full accessible text into a temporary UTF-8 file.
7. Supply structured evidence and the temporary file to `assess`.
8. Delete the temporary body after the command returns.

Example:

```bash
python3 {baseDir}/scripts/curator.py assess \
  --candidate /tmp/candidate.json \
  --body-file /tmp/article.txt
```

The CLI computes word count, SHA-256, SimHash, optional embedding, duplicate results,
provenance score, advertising score, novelty score, hard gates, and defer reasons. It stores
metadata and compact evidence only.

PDF sources are acceptable when the official file has a reliable text layer. Preserve
chapter/page locators. If a scan cannot be reliably OCRed, defer it. Do not infer missing
text from page images.

## 6. Selection and publication

Run:

```bash
python3 {baseDir}/scripts/curator.py shortlist
```

The ranking is:

- Analytical Depth: 25%
- Evidence Quality: 25%
- Business Relevance: 20%
- English Reading Value: 15%
- Novelty: 15%

For automatic mode, choose the first eligible result. Ensure there is:

- one independent corroborating source that adds evidence, challenge, or context;
- one optional primary-data source when useful;
- a compact internal evidence ledger with claim, URL, locator, source position, evidence
  strength, conflict note, and retrieval time.

The corroborating source must not be a syndication, summary, or related-publication rewrite
of the primary source. If the primary source is first-party, the corroborating source must
be independent. If no qualified corroborating source exists, do not publish.

Construct the prepare input only after reading `input-contracts.md` and
`output-contract.md`, then call:

```bash
python3 {baseDir}/scripts/curator.py prepare \
  --input /tmp/prepare.json \
  --body-file /tmp/selected-article.txt
```

The command first verifies that every vocabulary expression occurs in the supplied body. It
stores only a short context around each expression. It then writes a temporary file, starts
a database transaction, marks the candidate selected, creates the issue, and moves the pack
into place. Delete the temporary body after the command returns. A failed validation must not
consume an issue number or leave a selected row.

Send only the returned `chat_message` to Telegram or another chat transport. It is a compact
Chinese notice with the article direction, industry, company, reading time, source assessment,
and original link. Do not read and relay the saved Markdown unless the user explicitly asks
for a section or the complete guide.

## 7. Completion

`prepare` deliberately omits source comparison and conclusions. On completion:

1. Resolve the issue identifier safely.
2. Refetch both sources when available.
3. Use live text plus the saved evidence ledger.
4. Compare agreement, company-only claims, independent-only claims, factual conflict,
   framing, and missing evidence.
5. Avoid automatically declaring either source correct.
6. Keep the synthesis at or below 250 English words.
7. Call `complete` with the structured JSON.

The original spoiler-free version is retained alongside the completed pack.

## 8. Retrieval and archive boundaries

- Never use paywalled or partially visible text as the primary reading.
- Normal public-page browser rendering, a standard UA, and ordinary Cloudflare verification
  are allowed.
- Never bypass login, subscription, CAPTCHA, robots-enforced authorization, or other access
  controls.
- Use archive services only to recover a formerly public page. Record the canonical original,
  archive URL, and snapshot date using `access_status: archived_public`.
- Reject an archive when provenance, publication date, or completeness cannot be verified.
- Never publish or retain an independent publisher's full article.

## 9. Failure behavior

Do not relax provenance or advertising gates merely to publish on schedule.

When no candidate meets both quality and novelty:

1. search the next underrepresented industry;
2. expand the date window;
3. search less-covered regions;
4. search regulatory, academic, government, and trade sources;
5. consider an older, never-selected high-quality article.

If the run still fails, give a concise run report. Candidate rejection/defer records remain
useful; no issue is selected.
