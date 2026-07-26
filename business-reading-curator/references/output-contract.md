# Reading-Pack Output Contract

## Prepare phase

The Markdown pack must contain, in order:

1. `# Business Reading Pack — BRP-YYYY-NNN`
2. A label that the guide is AI-generated and the linked article is the original source.
3. Original reading metadata:
   - linked title;
   - author/speaker;
   - publication and date;
   - industry and companies;
   - approximate word count and reading time;
   - source type and access state;
   - canonical original URL.
4. An 80–120 English-word selection rationale that states the business question, significance,
   required reasoning, and reading value without revealing the conclusion.
5. Provenance and commercial-influence assessment.
6. Novelty transparency:
   - Passed or Exception;
   - last company appearance;
   - last primary-theme appearance;
   - number of similar articles;
   - material difference.
7. Reading order:
   - primary;
   - independent corroborating source;
   - optional primary-data source or an explicit not-applicable note.
8. Three pre-reading questions.
9. Eight to twelve original expressions, with:
   - concise English definition;
   - article-specific business meaning;
   - an AI-created example from another business context.
10. One non-summary checkpoint at 25%, 50%, 75%, and 100%.
11. Post-reading questions:
   - two factual recall;
   - two inference;
   - two business judgment;
   - one challenge to the author's framing;
   - one missing-evidence question.
12. Source notes and nearby factual citations.
13. A locked-comparison notice.

Do not add the article's conclusion, a complete summary, a rewritten article, fabricated
quotation, or simulated interview.

## Complete phase

Append:

1. A source-comparison table.
2. Claims supported by both.
3. Claims supported only by the company.
4. Claims supported only by the independent source.
5. Factual disagreements.
6. Differences in framing.
7. Important unanswered questions.
8. An evidence-based synthesis of at most 250 English words.
9. Nearby factual citations.

Do not automatically decide which source is correct. Compare evidence quality.

## Citation rules

Cite factual statements about companies, events, finance, regulation, authorship, editorial
policy, AI disclosure, commercial relationships, access, or provenance at the point of use.
Use original publications. Do not cite search-result snippets, AI summaries, aggregators,
unverified reposts, or marketing material as proof of an independent claim.

Vocabulary definitions do not require dictionary citations. Each listed expression must
actually occur in the temporary source body; the CLI verifies this and retains only a short
internal context for audit.
AI-created example sentences and questions are labeled guidance rather than sourced facts.

Use brief quotations only. Never reconstruct the article through accumulated excerpts.

## Language

- English: original metadata values, rationale, vocabulary, questions, and short synthesis.
- Chinese: concise provenance, advertising, access, and deduplication explanations.
- Bilingual fixed headings are allowed.
- Default reading level: B2–C1, adjustable after reader feedback.

## Delivery

The Markdown file in the runtime `packs/` directory is canonical. Send its complete contents
in chat; split into multiple messages if required by the transport. Do not publish it to a
third-party service automatically.
