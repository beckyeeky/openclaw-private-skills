#!/usr/bin/env python3
"""Unit and lifecycle tests for curator.py."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("curator.py")
SPEC = importlib.util.spec_from_file_location("business_reading_curator", MODULE_PATH)
assert SPEC and SPEC.loader
curator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(curator)

VOCAB_EXPRESSIONS = [f"curatorvocab{index}" for index in range(8)]


def article_body(seed: str) -> str:
    words = []
    for index in range(340):
        words.extend(
            [
                seed,
                "company",
                "strategy",
                "evidence",
                f"marker{index}",
            ]
        )
    return " ".join(words + VOCAB_EXPRESSIONS)


def unique_body(seed: str) -> str:
    return " ".join([f"{seed}{index}" for index in range(1700)] + VOCAB_EXPRESSIONS)


def candidate(
    *,
    title: str = "A documented shift in biotechnology strategy",
    url: str = "https://news.example.com/analysis?utm_source=test",
    company: str = "Example Bio, Inc.",
    event_key: str = "Example Bio | restructuring | oncology unit | US | 2026-Q3",
    origin_class: str = "named_established_journalist",
) -> dict:
    return {
        "research_batch_id": "test-batch-2026-07-26",
        "title": title,
        "url": url,
        "publication": "Example Business Review",
        "publication_date": "2026-07-20",
        "industry": "Biotechnology",
        "industry_bucket": "pharma_health",
        "companies": {"primary": company, "secondary": ["Example Pharma plc"]},
        "event_key": event_key,
        "event_type": "restructuring",
        "asset": "oncology unit",
        "geography": "United States",
        "approximate_event_date": "2026-Q3",
        "themes": ["Restructuring", "Pipeline prioritization"],
        "primary_theme": "Restructuring",
        "source_type": "independent_editorial",
        "source_position": "independent",
        "access_status": "free",
        "authors": ["Named Author"],
        "origin_evidence": {
            "provenance_class": origin_class,
            "original_domain_verified": True,
            "original_source_verified": True,
            "syndicated": False,
            "probable_mass_generated": False,
            "agent_adjustment": 0,
        },
        "advertising_evidence": {
            "sponsored_or_partner_content": False,
            "operational_evidence_present": True,
            "agent_adjustment": 0,
        },
        "scores": {
            "analytical_depth": 84,
            "evidence_quality": 88,
            "business_relevance": 86,
            "english_reading_value": 82,
        },
        "material_update": False,
        "length_exception": False,
        "evidence_ledger": [
            {
                "claim": "The company disclosed an operating change.",
                "source_url": "https://news.example.com/analysis",
                "locator": "paragraph 18",
                "source_position": "independent",
                "evidence_strength": "documented",
            }
        ],
    }


def seed_batch(
    conn: sqlite3.Connection,
    home: Path,
    count: int,
    batch_id: str = "test-batch-2026-07-26",
) -> None:
    titles = [
        "Supply networks reshape a regional device maker",
        "Retail inventory discipline during volatile demand",
        "A semiconductor producer revises capacity allocation",
        "A chemical group tests a different market entry",
    ]
    for index in range(count):
        data = candidate(
            title=titles[index],
            url=f"https://batch{index}.example.com/article",
            company=f"Batch Company {index}",
            event_key=f"Batch Company {index} | strategy | unit {index} | Region {index} | 2026-Q3",
        )
        data["research_batch_id"] = batch_id
        data["publication"] = f"Batch Publication {index}"
        data["authors"] = [f"Batch Author {index}"]
        curator.assess_candidate(
            conn,
            data,
            unique_body(f"batchuniquetoken{index}"),
            curator.load_config(home),
            False,
        )


def pack_input(candidate_id: int) -> dict:
    rationale = " ".join(
        [
            "This",
            "reading",
            "examines",
            "a",
            "strategic",
            "business",
            "question",
            "through",
            "operating",
            "evidence",
        ]
        * 9
    )
    vocabulary = [
        {
            "expression": VOCAB_EXPRESSIONS[index],
            "definition": "A concise English definition.",
            "context_meaning": "A specific meaning in the article.",
            "new_example": "Another manufacturer reconsidered its capital plan.",
        }
        for index in range(8)
    ]
    return {
        "candidate_id": candidate_id,
        "run_date": "2026-07-26",
        "direction_zh": "文章围绕一家生物技术公司的战略调整，关注经营约束、资源配置与利益相关者之间的权衡。",
        "why_selected": rationale,
        "human_origin_explanation": "具名记者、原始域名和作者页均已核验。",
        "advertising_risk_explanation": "未发现赞助、导流或供应商推销。",
        "disclosures_or_uncertainties": "The publication did not state an article-level AI policy.",
        "material_difference": "It introduces new operating evidence and a distinct event key.",
        "corroborating_source": {
            "title": "Independent corroboration",
            "url": "https://other.example.com/report",
            "publication": "Other Publication",
            "publication_date": "2026-07-22",
            "source_position": "independent",
            "human_origin_confidence": 92,
            "human_origin_evidence": "A named journalist and original publication were verified.",
            "advertising_risk": 8,
            "advertising_risk_evidence": "No sponsorship or lead-generation signals were found.",
        },
        "primary_data_source": {
            "title": "Official filing",
            "url": "https://regulator.example.gov/document",
            "publication": "Regulator",
            "publication_date": "2026-07-18",
            "source_position": "first_party",
            "human_origin_confidence": 98,
            "human_origin_evidence": "The official filing and document identifier were verified.",
            "advertising_risk": 10,
            "advertising_risk_evidence": "This is primary data rather than an independent claim.",
        },
        "pre_reading_questions": ["Question one?", "Question two?", "Question three?"],
        "vocabulary": vocabulary,
        "checkpoints": {
            "25": "How is the core problem introduced?",
            "50": "Which evidence changes the argument?",
            "75": "Which causal link is weakest?",
            "100": "Whose incentives matter most?",
        },
        "post_reading_questions": {
            "factual_recall": ["Recall one?", "Recall two?"],
            "inference": ["Infer one?", "Infer two?"],
            "business_judgment": ["Judge one?", "Judge two?"],
            "challenge_framing": "Which assumption should be challenged?",
            "missing_evidence": "What evidence remains missing?",
        },
        "fact_citations": [
            {
                "fact": "The source and its publication date were verified.",
                "url": "https://news.example.com/analysis",
            }
        ],
    }


def complete_input(issue_id: str) -> dict:
    return {
        "issue_id": issue_id,
        "comparison": [
            {
                "claim_or_issue": "Operating change",
                "primary_source": "Reports the change.",
                "corroborating_source": "Confirms the filing date.",
                "evidence_assessment": "The filing supports timing; motives remain interpretive.",
            }
        ],
        "supported_by_both": ["The operating change occurred."],
        "company_only": ["Management described its intended benefit."],
        "independent_only": ["The report emphasized execution risk."],
        "factual_disagreements": [],
        "framing_differences": ["The sources emphasize different stakeholders."],
        "unanswered_questions": ["The long-term cost remains unknown."],
        "synthesis": "The sources overlap on the disclosed event but frame its implications differently.",
        "fact_citations": [
            {
                "fact": "The filing date is stated in the official document.",
                "url": "https://regulator.example.gov/document",
            }
        ],
    }


class CuratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.conn = curator.connect(self.home)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp.cleanup()

    def test_url_title_and_fingerprints(self) -> None:
        self.assertEqual(
            curator.canonicalize_url(
                "HTTPS://Example.COM:443/a//b/?utm_source=x&b=2&a=1#section"
            ),
            "https://example.com/a/b?a=1&b=2",
        )
        self.assertEqual(
            curator.normalize_title("Example Review: 2026 Strategy Update", "Example Review"),
            "strategy",
        )
        body = article_body("alpha")
        self.assertEqual(curator.simhash_similarity(curator.simhash64(body), curator.simhash64(body)), 1)

    def test_cli_init_and_assess_contract(self) -> None:
        cli_home = self.home / "cli-home"
        initialized = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--home", str(cli_home), "init"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(initialized.stdout)["status"], "ok")
        candidate_path = self.home / "candidate.json"
        body_path = self.home / "article.txt"
        candidate_path.write_text(json.dumps(candidate()), encoding="utf-8")
        body_path.write_text(article_body("cli"), encoding="utf-8")
        assessed = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "--home",
                str(cli_home),
                "assess",
                "--candidate",
                str(candidate_path),
                "--body-file",
                str(body_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(assessed.stdout)
        self.assertEqual(result["status"], "shortlisted")
        self.assertEqual(result["embedding"]["mode"], "disabled")

    def test_full_lifecycle_and_no_body_persistence(self) -> None:
        body = article_body("privatebodytoken")
        result = curator.assess_candidate(
            self.conn, candidate(), body, curator.load_config(self.home), False
        )
        self.assertEqual(result["status"], "shortlisted")
        self.assertGreaterEqual(result["novelty_score"], 65)
        db_bytes = (self.home / "history.sqlite3").read_bytes()
        self.assertNotIn(b"privatebodytoken", db_bytes)

        shortlist = curator.command_shortlist(self.conn)
        self.assertEqual(shortlist["shortlisted"][0]["candidate_id"], result["candidate_id"])
        state = curator.command_state(self.conn)
        self.assertEqual(state["rotation"]["target_over_ten"]["pharma_health"], 5)

        seed_batch(self.conn, self.home, 4)
        prepared = curator.command_prepare(
            self.conn, self.home, pack_input(result["candidate_id"]), body
        )
        self.assertIn("chat_message", prepared)
        self.assertLessEqual(len(prepared["chat_message"]), 1000)
        self.assertIn("行业：", prepared["chat_message"])
        self.assertIn("方向：", prepared["chat_message"])
        self.assertIn("原文：https://", prepared["chat_message"])
        self.assertNotIn("Vocabulary", prepared["chat_message"])
        self.assertNotIn("Post-reading questions", prepared["chat_message"])
        self.assertNotIn("/tmp/", prepared["chat_message"])
        pack_path = Path(prepared["path"])
        first = pack_path.read_text(encoding="utf-8")
        self.assertIn("**Original source:**", first)
        self.assertIn("locked until this issue is marked complete", first)
        self.assertNotIn("Post-Reading Source Comparison", first)
        self.assertNotIn("privatebodytoken", first)

        revision = pack_input(result["candidate_id"])
        revision["issue_id"] = prepared["issue_id"]
        revision["material_difference"] = "This revised guide clarifies the newly documented evidence."
        revised = curator.command_revise(self.conn, revision, body)
        self.assertEqual(revised["version"], 2)

        completed = curator.command_complete(
            self.conn, complete_input(prepared["issue_id"])
        )
        self.assertEqual(completed["version"], 3)
        final = Path(completed["path"]).read_text(encoding="utf-8")
        self.assertIn("Post-Reading Source Comparison", final)
        self.assertFalse(pack_path.with_suffix(".prepare.md").exists())
        versions = self.conn.execute(
            "SELECT version,phase,path FROM pack_versions WHERE issue_id=? ORDER BY version",
            (prepared["issue_id"],),
        ).fetchall()
        self.assertEqual(
            [(row["version"], row["phase"]) for row in versions],
            [(1, "prepare"), (2, "prepare"), (3, "complete")],
        )
        self.assertTrue(all(Path(row["path"]).exists() for row in versions))
        self.assertTrue(
            all(Path(row["path"]).parent.name == ".versions" for row in versions)
        )
        self.assertEqual(list(pack_path.parent.glob("*.md")), [pack_path])
        issue = self.conn.execute(
            "SELECT status FROM issues WHERE id=?", (prepared["issue_id"],)
        ).fetchone()
        self.assertEqual(issue["status"], "completed")

        export_path = self.home / "audit" / "history.jsonl"
        exported = curator.command_export(self.conn, export_path)
        self.assertEqual(exported["records"], 5)
        exported_records = [
            json.loads(line)
            for line in export_path.read_text(encoding="utf-8").splitlines()
        ]
        selected_record = next(
            item for item in exported_records if item["issue_id"] == prepared["issue_id"]
        )
        self.assertEqual(selected_record["issue_status"], "completed")
        self.assertEqual(len(selected_record["semantic_topic_fingerprint"]), 64)

    def test_duplicate_body_is_rejected(self) -> None:
        body = article_body("samebody")
        first = curator.assess_candidate(
            self.conn, candidate(), body, curator.load_config(self.home), False
        )
        second_data = candidate(
            title="A separate headline about a different strategic choice",
            url="https://second.example.com/story",
            company="Another Bio",
            event_key="Another Bio | capacity | plant | Europe | 2026-Q3",
        )
        second = curator.assess_candidate(
            self.conn, second_data, body, curator.load_config(self.home), False
        )
        self.assertEqual(first["status"], "shortlisted")
        self.assertEqual(second["status"], "rejected")
        self.assertIn("exact or near-duplicate", "; ".join(second["hard_failures"]))

    def test_low_provenance_is_rejected(self) -> None:
        low = candidate(origin_class="anonymous_or_unverifiable")
        result = curator.assess_candidate(
            self.conn, low, article_body("loworigin"), curator.load_config(self.home), False
        )
        self.assertEqual(result["status"], "rejected")
        self.assertLess(result["human_origin_confidence"], 75)

    def test_openai_compatible_embedding_and_safe_degradation(self) -> None:
        config = {
            "embedding": {
                "enabled": True,
                "base_url": "https://embedding.example/v1",
                "model": "example-embedding",
                "api_key_env": "CURATOR_TEST_API_KEY",
                "dimensions": None,
                "timeout_seconds": 3,
            }
        }
        response = io.BytesIO(
            json.dumps({"data": [{"embedding": [0.1, 0.2, 0.3]}]}).encode()
        )
        with mock.patch.dict(os.environ, {"CURATOR_TEST_API_KEY": "secret-value"}):
            with mock.patch.object(
                curator.urllib.request, "urlopen", return_value=response
            ) as urlopen:
                model, vector = curator.request_embedding("topic text", config)
        self.assertEqual(model, "example-embedding")
        self.assertEqual(vector, [0.1, 0.2, 0.3])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://embedding.example/v1/embeddings")
        self.assertNotIn("secret-value", request.data.decode())

        missing_config = {
            "embedding": {
                **config["embedding"],
                "api_key_env": "CURATOR_DEFINITELY_MISSING_KEY",
            }
        }
        os.environ.pop("CURATOR_DEFINITELY_MISSING_KEY", None)
        degraded = curator.assess_candidate(
            self.conn,
            candidate(),
            article_body("degraded"),
            missing_config,
            False,
        )
        self.assertEqual(degraded["embedding"]["mode"], "degraded")
        self.assertEqual(degraded["status"], "shortlisted")

    def test_document_identifier_duplicate_and_access_retry(self) -> None:
        first_data = candidate()
        first_data["document_id"] = "DOC-2026-001"
        curator.assess_candidate(
            self.conn,
            first_data,
            article_body("documentone"),
            curator.load_config(self.home),
            False,
        )
        duplicate = candidate(
            title="A completely different title",
            url="https://different.example.com/document",
            company="Different Company",
            event_key="Different Company | filing | unit | Asia | 2026-Q3",
        )
        duplicate["document_id"] = "doc 2026 001"
        duplicate_result = curator.assess_candidate(
            self.conn,
            duplicate,
            article_body("documenttwo"),
            curator.load_config(self.home),
            False,
        )
        self.assertEqual(duplicate_result["status"], "rejected")
        self.assertTrue(
            any(
                "same document identifier" in reason
                for item in duplicate_result["duplicates"]
                for reason in item["reasons"]
            )
        )

        inaccessible = candidate(
            title="An inaccessible but otherwise qualified analysis",
            url="https://paywall.example.com/article",
            company="Paywall Bio",
            event_key="Paywall Bio | launch | asset | Europe | 2026-Q3",
        )
        inaccessible["access_status"] = "paywalled"
        access_result = curator.assess_candidate(
            self.conn,
            inaccessible,
            unique_body("uniquepaywalltoken"),
            curator.load_config(self.home),
            False,
        )
        self.assertEqual(access_result["status"], "deferred")
        row = self.conn.execute(
            "SELECT review_after FROM candidates WHERE id=?",
            (access_result["candidate_id"],),
        ).fetchone()
        self.assertIsNotNone(row["review_after"])

    def test_alias_maps_to_canonical_company(self) -> None:
        pending = curator.command_alias_suggest(
            self.conn,
            "Lilly",
            "Eli Lilly and Company",
            "The short name may refer to the parent company.",
        )
        self.assertEqual(pending["status"], "pending")
        result = curator.command_alias(
            self.conn, "Eli Lilly and Company", "Lilly", None
        )
        company_id = curator.get_or_create_company(self.conn, "Lilly")
        self.assertEqual(company_id, result["company_id"])
        audit = self.conn.execute(
            "SELECT action,new_company_id FROM company_alias_audit"
        ).fetchone()
        self.assertEqual(audit["action"], "set_alias")
        self.assertEqual(audit["new_company_id"], company_id)
        suggestion = self.conn.execute(
            "SELECT status FROM company_alias_suggestions WHERE normalized_alias='lilly'"
        ).fetchone()
        self.assertEqual(suggestion["status"], "accepted")

    def test_parent_company_cooldown_and_first_party_risk(self) -> None:
        curator.command_alias(
            self.conn, "Example Bio Subsidiary", "Example Sub", "Example Parent"
        )
        parent_data = candidate(
            title="Parent company changes its manufacturing plan",
            url="https://parent.example.com/story",
            company="Example Parent",
            event_key="Example Parent | capacity | plant | US | 2026-Q3",
        )
        parent_body = unique_body("parentuniquetoken")
        parent = curator.assess_candidate(
            self.conn,
            parent_data,
            parent_body,
            curator.load_config(self.home),
            False,
        )
        seed_batch(self.conn, self.home, 4)
        curator.command_prepare(
            self.conn, self.home, pack_input(parent["candidate_id"]), parent_body
        )

        child_data = candidate(
            title="Subsidiary makes a distinct portfolio decision",
            url="https://child.example.com/story",
            company="Example Bio Subsidiary",
            event_key="Example Bio Subsidiary | portfolio | asset | Europe | 2026-Q3",
        )
        child_data["publication"] = "Different Review"
        child_data["authors"] = ["Different Author"]
        child_data["themes"] = ["Portfolio strategy", "Market access"]
        child_data["primary_theme"] = "Portfolio strategy"
        child = curator.assess_candidate(
            self.conn,
            child_data,
            unique_body("childuniquetoken"),
            curator.load_config(self.home),
            False,
        )
        self.assertIsNotNone(child["novelty_checks"]["primary_company_cooldown"])

        first_party = candidate(
            title="A signed letter explains a separate allocation decision",
            url="https://issuer.example.com/letter",
            company="Issuer Company",
            event_key="Issuer Company | allocation | division | Asia | 2026-Q3",
            origin_class="named_shareholder_letter",
        )
        first_party["source_position"] = "first_party"
        first_party["source_type"] = "shareholder_letter"
        first_party["publication"] = "Issuer Company"
        first_party["authors"] = ["Named Chief Executive"]
        first_party["themes"] = ["Capital allocation", "Commercial launch"]
        first_party["primary_theme"] = "Capital allocation"
        assessed = curator.assess_candidate(
            self.conn,
            first_party,
            unique_body("letteruniquetoken"),
            curator.load_config(self.home),
            False,
        )
        self.assertEqual(assessed["advertising_risk"], 20)

    def test_registration_exception_and_archive_requirements(self) -> None:
        registration = candidate(
            title="A registration-gated but free analysis",
            url="https://registration.example.com/article",
            company="Registration Bio",
            event_key="Registration Bio | strategy | unit | US | 2026-Q3",
        )
        registration["access_status"] = "registration_required"
        body = unique_body("registrationtoken")
        deferred = curator.assess_candidate(
            self.conn, registration, body, curator.load_config(self.home), False
        )
        self.assertEqual(deferred["status"], "deferred")
        registration["access_exception_reason"] = (
            "The complete article is free after registration and materially stronger than alternatives."
        )
        reconsidered = curator.assess_candidate(
            self.conn, registration, body, curator.load_config(self.home), False
        )
        self.assertEqual(reconsidered["status"], "shortlisted")

        archived = candidate(
            title="A recovered public report",
            url="https://publisher.example.com/removed-report",
            company="Archive Bio",
            event_key="Archive Bio | report | asset | US | 2026-Q3",
        )
        archived["access_status"] = "archived_public"
        with self.assertRaises(curator.CuratorError):
            curator.assess_candidate(
                self.conn,
                archived,
                unique_body("archivetoken"),
                curator.load_config(self.home),
                False,
            )

    def test_shortlist_rechecks_cooldowns_after_another_selection(self) -> None:
        first_body = unique_body("firstcurrenttoken")
        first = curator.assess_candidate(
            self.conn,
            candidate(),
            first_body,
            curator.load_config(self.home),
            False,
        )
        second_data = candidate(
            title="The same company makes a later but distinct operating choice",
            url="https://fresh.example.com/second",
            event_key="Example Bio | capacity | second plant | Europe | 2026-Q3",
        )
        second_data["publication"] = "Fresh Publication"
        second_data["authors"] = ["Fresh Author"]
        second_data["themes"] = ["Manufacturing capacity", "Supply-chain resilience"]
        second_data["primary_theme"] = "Manufacturing capacity"
        second = curator.assess_candidate(
            self.conn,
            second_data,
            unique_body("secondcurrenttoken"),
            curator.load_config(self.home),
            False,
        )
        self.assertEqual(first["status"], "shortlisted")
        self.assertEqual(second["status"], "shortlisted")
        seed_batch(self.conn, self.home, 3)
        curator.command_prepare(
            self.conn, self.home, pack_input(first["candidate_id"]), first_body
        )
        current_ids = {
            item["candidate_id"]
            for item in curator.command_shortlist(self.conn)["shortlisted"]
        }
        self.assertNotIn(second["candidate_id"], current_ids)

    def test_semantic_similarity_requires_documented_human_review(self) -> None:
        first_body = article_body("semanticfirst")
        first = curator.assess_candidate(
            self.conn,
            candidate(),
            first_body,
            curator.load_config(self.home),
            False,
        )
        self.conn.execute(
            """
            UPDATE candidates
            SET embedding_model='semantic-model',embedding_dimensions=3,
                embedding_json='[1.0,0.0,0.0]'
            WHERE id=?
            """,
            (first["candidate_id"],),
        )
        self.conn.commit()
        seed_batch(self.conn, self.home, 4)
        curator.command_prepare(
            self.conn, self.home, pack_input(first["candidate_id"]), first_body
        )

        second_data = candidate(
            title="A distinct investigation with potentially related strategic implications",
            url="https://semantic.example.com/new-investigation",
            company="Semantic Company",
            event_key="Semantic Company | market entry | product | Asia | 2026-Q3",
        )
        second_data["companies"]["secondary"] = []
        second_data["publication"] = "Semantic Review"
        second_data["authors"] = ["Semantic Author"]
        second_data["themes"] = ["Market entry", "Pricing pressure"]
        second_data["primary_theme"] = "Market entry"
        embedding_config = {"embedding": {"enabled": True}}
        with mock.patch.object(
            curator,
            "request_embedding",
            return_value=("semantic-model", [1.0, 0.0, 0.0]),
        ):
            pending = curator.assess_candidate(
                self.conn,
                second_data,
                unique_body("semanticsecond"),
                embedding_config,
                False,
            )
        self.assertEqual(pending["status"], "deferred")
        self.assertTrue(
            any("semantic similarity" in reason for reason in pending["defer_reasons"])
        )

        second_data["semantic_review_outcome"] = "materially_different"
        second_data["semantic_review_reason"] = (
            "The article documents a different company, event, evidence base, and market."
        )
        with mock.patch.object(
            curator,
            "request_embedding",
            return_value=("semantic-model", [1.0, 0.0, 0.0]),
        ):
            reviewed = curator.assess_candidate(
                self.conn,
                second_data,
                unique_body("semanticsecond"),
                embedding_config,
                False,
            )
        self.assertEqual(reviewed["status"], "shortlisted", reviewed)

    def test_prepare_validation_rejects_spoiler_rationale_length(self) -> None:
        validation_body = article_body("validation")
        result = curator.assess_candidate(
            self.conn,
            candidate(),
            validation_body,
            curator.load_config(self.home),
            False,
        )
        data = pack_input(result["candidate_id"])
        data["why_selected"] = "Too short."
        with self.assertRaises(curator.CuratorError):
            curator.command_prepare(self.conn, self.home, data, validation_body)
        count = self.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        self.assertEqual(count, 0)

        data = pack_input(result["candidate_id"])
        data["direction_zh"] = "方向\n不应换行"
        with self.assertRaisesRegex(curator.CuratorError, "direction_zh"):
            curator.command_prepare(self.conn, self.home, data, validation_body)

    def test_prepare_requires_five_full_text_assessments(self) -> None:
        body = article_body("singlecandidate")
        result = curator.assess_candidate(
            self.conn,
            candidate(),
            body,
            curator.load_config(self.home),
            False,
        )
        with self.assertRaisesRegex(curator.CuratorError, "at least five"):
            curator.command_prepare(
                self.conn, self.home, pack_input(result["candidate_id"]), body
            )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
