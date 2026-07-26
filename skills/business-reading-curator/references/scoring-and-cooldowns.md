# Scoring, Quality Gates, and Cooldowns

## Contents

1. Provenance
2. Advertising risk
3. Quality gates
4. Duplicate detection
5. Novelty
6. Cooldowns and diversity
7. Material-update exceptions
8. Reconsideration

## 1. Provenance

Human-Origin Confidence measures traceable provenance, not linguistic humanness.

The CLI assigns a base:

| Provenance class | Base |
|---|---:|
| `signed_filing` | 98 |
| `named_shareholder_letter` | 96 |
| `verified_transcript` | 95 |
| `named_established_journalist` | 94 |
| `named_trade_journalist` | 86 |
| `named_researcher` | 85 |
| `transparent_institutional_report` | 80 |
| `institutional_unclear_author` | 65 |
| `anonymous_or_unverifiable` | 35 |

Hard caps:

- unverified original domain: 59;
- syndicated content without a verified original: 59;
- probable mass-generated content: 49.

The agent may adjust by at most ±5 and must provide a reason. The primary reading must score
at least 75.

Evidence can include the byline, speaker identity, official document ID, author profile,
editorial policy, AI disclosure, syndication notice, citations, named interviews, and
documentary evidence. Never infer human origin from prose style.

## 2. Advertising risk

The CLI adds documented signals:

| Signal | Points |
|---|---:|
| sponsored or partner content | 100 total |
| lead generation | +25 |
| affiliate links | +25 |
| vendor solution pitch | +25 |
| anonymous commercial blog | +20 |
| supplier-controlled customer story | +20 |
| marketing-only claims | +15 |
| SEO listicle | +15 |
| repetitive product naming | +10 |
| marketing-agency republication | +30 |
| undisclosed commercial relationship | +30 |
| first-party framing | +25 |
| operational evidence present | −5 |

The agent may adjust by at most ±5 with a reason.

Limits:

- independent primary: ≤30;
- independent corroborating source: ≤40, with an explanation when above 30;
- first-party primary: below 61;
- sponsored/partner content: never primary or independent corroboration.

Promotional supporting sources may support only clearly labeled first-party facts.

## 3. Quality gates

The primary reading normally requires:

- free/public complete access;
- 1,500–6,000 English words;
- Human-Origin Confidence ≥75;
- applicable Advertising Risk threshold;
- Analytical Depth ≥70;
- Evidence Quality ≥70;
- clear publication date and provenance;
- enough operating or financial detail for close reading.

A 1,200–1,499 word exception requires high evidence density, at least 10–15 minutes of
expected reading, and a written reason. For a document over 6,000 words, extract one coherent
2,000–6,000 word chapter/page range as the assessment body and record `selected_range`.
Do not edit or stitch unrelated passages to manufacture length.

The primary source type must be one of the types accepted by the CLI. Press releases,
presentations, product pages, marketing pages, and generic summaries are supporting sources,
not primary readings.

## 4. Duplicate detection

Immediate rejection applies to:

- same canonical URL;
- normalized title similarity above 90%;
- same normalized full-text SHA-256;
- SimHash near-full-text similarity above 85%;
- same document identifier or report edition;
- embedding similarity above 0.90 under the same model and dimensions.

Embedding similarity 0.82–0.90 requires review. A score above 0.90 is presumptively duplicate,
but still requires confirmation. Set `semantic_review_outcome` to `duplicate` or
`materially_different` and provide `semantic_review_reason`. Never reject solely on semantic
similarity without confirming whether the article adds materially new evidence, framing, or
developments. Semantic comparison uses the latest 100 selected readings with the same model
and dimensions.

Canonical URLs remove fragments, default ports, common tracking parameters, repeated slashes,
and trailing slashes. Normalize titles by lowercasing, removing punctuation, publication
names, dates, edition labels, and repeated spaces.

An Event Key contains:

`Primary company | event type | product/asset/unit | geography | approximate event date`

Avoid the same Event Key within 90 days unless a material update exists.

## 5. Novelty

The CLI starts with:

- +30: company outside cooldown;
- +25: new event key;
- +20: primary theme differs from the previous issue;
- +15: publication diversity;
- +10: source-type diversity.

It applies:

- −40: same event;
- −25: company inside cooldown;
- −20: same primary theme as previous issue;
- −15: publication appeared recently;
- −10: source type repeated.

Clamp to 0–100. Normal selection requires at least 65.

## 6. Cooldowns and diversity

Default cooldowns:

- primary company: 8 issues;
- company previously secondary: 4 issues;
- same pharmaceutical product or clinical asset: 12 issues;
- same M&A transaction: 12 issues;
- same regulatory event: 8 issues;
- same author: at most once within 8 issues;
- same publication: at most twice within 10 issues;
- earnings-call transcripts: at most twice within 6 issues;
- consulting-firm primary: at most once within 10 issues;
- first-party primary: at most three within 10 issues.

Theme and five-issue rules:

- do not repeat the same primary theme in consecutive issues;
- no primary theme more than twice within five issues;
- at least three industry buckets within five issues;
- at least three source types within five issues;
- at least two independent primary readings within five issues.

Ten-issue rules:

- at least half the primary readings are independent (the first-party maximum makes this
  stricter in normal operation);
- no publication supplies more than two primary readings;
- keep the target industry allocation described in `workflow.md`.

## 7. Material-update exceptions

The agent may create a labeled exception only for:

- new financial results;
- regulatory approval, rejection, or major review action;
- transaction completion or termination;
- revised guidance;
- new clinical data;
- capacity becoming operational;
- confirmed delay or cancellation;
- major competitor response;
- credible evidence contradicting the original reporting.

Set `material_update: true`, provide `exception_reason`, and distinguish the new evidence.
Ordinary follow-up coverage, repeated management statements, or reframed old facts do not
qualify. The pack must say `Novelty check: Exception`.

Material updates may override novelty/cooldown gates. They never override access, provenance,
advertising, or duplicate-body gates.

## 8. Reconsideration

- soft advertising: never reconsider the same article;
- paywall/access failure: review after 30 days only if free access may change;
- too short: never reconsider unless the source expands;
- duplicate event: review after 90 days;
- low authorship confidence: reconsider only if provenance improves;
- company cooldown: reconsider when the cooldown expires.

Keep rejected and deferred candidates in SQLite. Query only the latest 180 days during normal
research, but do not delete older history automatically.
