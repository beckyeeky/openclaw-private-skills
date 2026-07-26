# CLI Input Contracts

## Contents

1. Configuration
2. Candidate assessment
3. Prepare phase
4. Complete phase
5. Other commands

All JSON is UTF-8. Use temporary files with mode `0600` when they contain extracted evidence.
Never include API keys or a full article body in JSON.

## 1. Configuration

`init` creates:

`~/.hermes/business-reading-curator/config.json`

Default:

```json
{
  "reading_level": "B2-C1",
  "embedding": {
    "enabled": false,
    "base_url": "https://api.openai.com/v1",
    "model": "text-embedding-3-small",
    "api_key_env": "BUSINESS_READING_EMBEDDING_API_KEY",
    "dimensions": null,
    "timeout_seconds": 30
  }
}
```

The endpoint must implement OpenAI-compatible `POST <base_url>/embeddings`. Store the key
only in the environment variable named by `api_key_env`.

Optional environment overrides:

- `BUSINESS_READING_HOME`
- `BUSINESS_READING_EMBEDDING_BASE_URL`
- `BUSINESS_READING_EMBEDDING_MODEL`

If embeddings are enabled but fail, `assess` records `degraded` mode and continues with
URL/title/SHA-256/SimHash/Event Key checks. Use `--strict-embedding` only when the user
explicitly wants embedding failure to abort. Compare vectors only when model and dimensions
match.

## 2. Candidate assessment

Call:

```bash
python3 {baseDir}/scripts/curator.py assess \
  --candidate /tmp/candidate.json \
  --body-file /tmp/article.txt
```

Candidate JSON:

```json
{
  "research_batch_id": "2026-07-26T080000Z-pharma-health",
  "title": "Exact original title",
  "url": "https://publication.example/article?utm_source=x",
  "publication": "Publication Name",
  "publication_date": "2026-07-20",
  "industry": "Biotechnology",
  "industry_bucket": "pharma_health",
  "companies": {
    "primary": "Example Bio, Inc.",
    "secondary": ["Example Pharma plc"]
  },
  "event_key": "Example Bio | restructuring | oncology unit | United States | 2026-Q3",
  "document_id": null,
  "event_type": "restructuring",
  "asset": "oncology unit",
  "geography": "United States",
  "approximate_event_date": "2026-Q3",
  "themes": ["Restructuring", "Pipeline prioritization"],
  "primary_theme": "Restructuring",
  "source_type": "independent_editorial",
  "source_position": "independent",
  "access_status": "free",
  "access_exception_reason": null,
  "archive_url": null,
  "archive_snapshot_date": null,
  "authors": ["Named Author"],
  "origin_evidence": {
    "provenance_class": "named_established_journalist",
    "original_domain_verified": true,
    "original_source_verified": true,
    "syndicated": false,
    "probable_mass_generated": false,
    "author_profile_url": "https://publication.example/authors/named-author",
    "editorial_policy_url": "https://publication.example/editorial-policy",
    "ai_disclosure_url": null,
    "agent_adjustment": 0,
    "adjustment_reason": null
  },
  "advertising_evidence": {
    "sponsored_or_partner_content": false,
    "lead_generation": false,
    "affiliate_links": false,
    "vendor_solution_pitch": false,
    "anonymous_commercial_blog": false,
    "supplier_controlled_customer_story": false,
    "marketing_claims_only": false,
    "seo_listicle": false,
    "repetitive_product_naming": false,
    "marketing_agency_republication": false,
    "undisclosed_commercial_relationship": false,
    "first_party_framing": false,
    "operational_evidence_present": true,
    "agent_adjustment": 0,
    "adjustment_reason": null
  },
  "scores": {
    "analytical_depth": 84,
    "evidence_quality": 88,
    "business_relevance": 86,
    "english_reading_value": 82
  },
  "material_update": false,
  "exception_reason": null,
  "semantic_review_outcome": null,
  "semantic_review_reason": null,
  "length_exception": false,
  "length_exception_reason": null,
  "selected_range": "Complete article",
  "evidence_ledger": [
    {
      "claim": "Compact internal claim statement.",
      "source_url": "https://publication.example/article",
      "locator": "paragraph 18",
      "source_position": "independent",
      "evidence_strength": "documented",
      "conflict_note": null,
      "fetched_at": "2026-07-26T08:00:00+00:00"
    }
  ]
}
```

Allowed `industry_bucket` values:

- `pharma_health`
- `chemicals_materials`
- `technology_semiconductors`
- `industrial_logistics`
- `consumer_retail`
- `finance_energy_other`

Allowed primary `source_type` values:

- `filing`
- `shareholder_letter`
- `earnings_call_transcript`
- `investor_day_transcript`
- `regulatory_document`
- `government_report`
- `court_filing`
- `speech`
- `executive_interview`
- `conference_transcript`
- `independent_editorial`
- `trade_editorial`
- `institutional_research`
- `consulting_report`

Allowed provenance classes and advertising flags are defined in
`scoring-and-cooldowns.md`.

The body file must contain the full accessible text or selected coherent document section.
It is used in memory for word count, SHA-256, SimHash, and optional embeddings. The script
does not persist it. The registry always stores a deterministic semantic topic fingerprint
derived from company, event, asset, geography, and themes; an embedding vector is an optional
additional fingerprint. Without `--body-file`, `word_count` may be supplied for metadata-only
testing, but such an assessment is too weak to publish and should not be used in a live run.

Use one stable `research_batch_id` for every candidate fully assessed during one issue
research run. `prepare` queries SQLite and refuses to publish unless that batch contains at
least five candidates with real full-text fingerprints.

Allowed access states:

- `free` or `public`: normal eligible access;
- `registration_required`: deferred unless `access_exception_reason` explains why it is
  materially stronger than accessible alternatives;
- `archived_public`: allowed only with a verified canonical original URL plus `archive_url`
  and `archive_snapshot_date`;
- `paywalled` or other inaccessible states: not eligible and normally reconsidered after
  30 days.

## 3. Prepare phase

Call:

```bash
python3 {baseDir}/scripts/curator.py prepare \
  --input /tmp/prepare.json \
  --body-file /tmp/selected-article.txt
```

Input:

```json
{
  "candidate_id": 7,
  "run_date": "2026-07-26",
  "why_selected": "An 80–120 English-word rationale that does not reveal the conclusion.",
  "human_origin_explanation": "中文证据说明，并在 fact_citations 中提供链接。",
  "advertising_risk_explanation": "中文商业影响说明，并在 fact_citations 中提供链接。",
  "disclosures_or_uncertainties": "No known sponsorship; AI policy was not explicitly stated.",
  "material_difference": "This source adds newly reported operating evidence rather than repeating the earlier event.",
  "corroborating_source": {
    "title": "Independent source title",
    "url": "https://other.example/report",
    "publication": "Other Publication",
    "publication_date": "2026-07-22",
    "source_position": "independent",
    "human_origin_confidence": 92,
    "human_origin_evidence": "A named journalist and original publication were verified.",
    "advertising_risk": 8,
    "advertising_risk_evidence": "No sponsorship or lead-generation signals were found.",
    "commercial_influence_note": null
  },
  "primary_data_source": {
    "title": "Official filing",
    "url": "https://regulator.example/document",
    "publication": "Regulator",
    "publication_date": "2026-07-18",
    "source_position": "first_party",
    "human_origin_confidence": 98,
    "human_origin_evidence": "The official filing and document identifier were verified.",
    "advertising_risk": 10,
    "advertising_risk_evidence": "This is first-party primary data."
  },
  "pre_reading_questions": [
    "Question one?",
    "Question two?",
    "Question three?"
  ],
  "vocabulary": [
    {
      "expression": "expression from the article",
      "definition": "Concise English definition.",
      "context_meaning": "Its business meaning in this article.",
      "new_example": "An AI-created sentence in another business situation."
    }
  ],
  "checkpoints": {
    "25": "Question about argument structure?",
    "50": "Question about evidence?",
    "75": "Question about causality?",
    "100": "Question about stakeholder incentives?"
  },
  "post_reading_questions": {
    "factual_recall": ["Question?", "Question?"],
    "inference": ["Question?", "Question?"],
    "business_judgment": ["Question?", "Question?"],
    "challenge_framing": "Question?",
    "missing_evidence": "Question?"
  },
  "fact_citations": [
    {
      "fact": "A factual statement used in the guide.",
      "url": "https://original.example/source"
    }
  ]
}
```

`vocabulary` must contain 8–12 entries; the shortened example above shows one only for
readability. `why_selected` is measured with an English-token word counter and must contain
80–120 words. Each `expression` must occur in the temporary body. The CLI saves only a short
source context for audit and never persists the body.

Omit `primary_data_source` when none exists. Never omit `corroborating_source`.

The CLI validates structure and hard source limits, atomically writes Markdown, marks the
candidate selected, and allocates a stable issue ID.

To revise an incomplete pack, add its stable identifier to the same input and call:

```json
{
  "issue_id": "BRP-2026-001",
  "candidate_id": 7
}
```

```bash
python3 {baseDir}/scripts/curator.py revise \
  --input /tmp/revise.json \
  --body-file /tmp/selected-article.txt
```

The real revision input retains every required prepare field; the shortened JSON above shows
only the identifying fields. Revision creates a new immutable version snapshot and does not
consume an issue number or create another selected record.

## 4. Complete phase

Call:

```bash
python3 {baseDir}/scripts/curator.py complete --input /tmp/complete.json
```

Input:

```json
{
  "issue_id": "BRP-2026-001",
  "comparison": [
    {
      "claim_or_issue": "Claim or issue",
      "primary_source": "What the primary source says",
      "corroborating_source": "What the corroborating source says",
      "evidence_assessment": "Relative evidence quality without declaring a winner"
    }
  ],
  "supported_by_both": ["Item"],
  "company_only": ["Item"],
  "independent_only": ["Item"],
  "factual_disagreements": [],
  "framing_differences": ["Item"],
  "unanswered_questions": ["Item"],
  "synthesis": "No more than 250 English words.",
  "fact_citations": [
    {
      "fact": "A factual statement used in the comparison.",
      "url": "https://original.example/source"
    }
  ]
}
```

The CLI preserves a `.prepare.md` copy, appends the comparison to the canonical pack,
creates version 2, and marks the issue and candidate completed.

## 5. Other commands

```bash
# Ranked eligible candidates
python3 {baseDir}/scripts/curator.py shortlist

# Rolling allocation and active cooldowns
python3 {baseDir}/scripts/curator.py state

# Selected issues plus 180-day rejected/deferred working set
python3 {baseDir}/scripts/curator.py history --limit 20

# Read-only audit export
python3 {baseDir}/scripts/curator.py export --output /secure/path/history.jsonl

# Audited manual alias; parent is optional
python3 {baseDir}/scripts/curator.py alias \
  --canonical "Eli Lilly and Company" \
  --alias "Lilly"

# Record uncertainty without merging
python3 {baseDir}/scripts/curator.py alias-suggest \
  --alias "Ambiguous Holdings" \
  --possible-canonical "Possible Parent plc" \
  --reason "The article does not identify the legal entity."
```

Every alias command appends an audit row. It never silently reassigns an alias already owned
by a different canonical company. `alias-suggest` keeps the name pending and unmerged until
it is explicitly resolved with `alias`.

When multiple incomplete issues exist, resolve the intended issue outside the CLI before
calling `complete`.
