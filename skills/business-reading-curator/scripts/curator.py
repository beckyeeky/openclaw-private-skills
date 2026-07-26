#!/usr/bin/env python3
"""Deterministic registry and pack renderer for business-reading-curator.

The agent performs live research and supplies structured JSON.  This program owns
canonicalization, scoring guardrails, duplicate checks, cooldowns, persistence,
and rendering.  Article bodies are processed in memory and are never stored.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import difflib
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
DEFAULT_HOME = Path("~/.hermes/business-reading-curator").expanduser()
TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}
TRACKING_PREFIXES = ("utm_",)
WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
HARD_ACCESS = {"free", "public", "archived_public"}
PRIMARY_SOURCE_TYPES = {
    "filing",
    "shareholder_letter",
    "earnings_call_transcript",
    "investor_day_transcript",
    "regulatory_document",
    "government_report",
    "court_filing",
    "speech",
    "executive_interview",
    "conference_transcript",
    "independent_editorial",
    "trade_editorial",
    "institutional_research",
    "consulting_report",
}
INDUSTRY_BUCKETS = {
    "pharma_health": 5,
    "chemicals_materials": 1,
    "technology_semiconductors": 1,
    "industrial_logistics": 1,
    "consumer_retail": 1,
    "finance_energy_other": 1,
}


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    parent_company_id INTEGER REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS company_aliases (
    normalized_alias TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_alias_audit (
    id INTEGER PRIMARY KEY,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    previous_company_id INTEGER REFERENCES companies(id),
    new_company_id INTEGER NOT NULL REFERENCES companies(id),
    action TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_alias_suggestions (
    normalized_alias TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    possible_company_id INTEGER REFERENCES companies(id),
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','accepted','rejected')),
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY,
    canonical_url TEXT NOT NULL UNIQUE,
    original_url TEXT NOT NULL,
    research_batch_id TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    publication TEXT NOT NULL,
    publication_date TEXT NOT NULL,
    industry TEXT NOT NULL,
    industry_bucket TEXT NOT NULL,
    event_key TEXT NOT NULL,
    document_id TEXT,
    event_type TEXT,
    asset TEXT,
    geography TEXT,
    approximate_event_date TEXT,
    source_type TEXT NOT NULL,
    source_position TEXT NOT NULL CHECK(source_position IN ('first_party','independent')),
    access_status TEXT NOT NULL,
    access_exception_reason TEXT,
    archive_url TEXT,
    archive_snapshot_date TEXT,
    word_count INTEGER NOT NULL,
    selected_range TEXT,
    length_exception_reason TEXT,
    author_json TEXT NOT NULL,
    origin_evidence_json TEXT NOT NULL,
    advertising_evidence_json TEXT NOT NULL,
    human_origin_confidence INTEGER NOT NULL,
    advertising_risk INTEGER NOT NULL,
    analytical_depth INTEGER NOT NULL,
    evidence_quality INTEGER NOT NULL,
    business_relevance INTEGER NOT NULL,
    english_reading_value INTEGER NOT NULL,
    novelty_score INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('shortlisted','selected','completed','rejected','deferred')),
    rejection_reason TEXT,
    review_after TEXT,
    material_update INTEGER NOT NULL DEFAULT 0,
    exception_reason TEXT,
    text_sha256 TEXT,
    simhash TEXT,
    semantic_topic_fingerprint TEXT NOT NULL,
    embedding_model TEXT,
    embedding_dimensions INTEGER,
    embedding_json TEXT,
    semantic_review_outcome TEXT,
    semantic_review_reason TEXT,
    duplicate_of_id INTEGER REFERENCES candidates(id),
    created_at TEXT NOT NULL,
    reviewed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_companies (
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    role TEXT NOT NULL CHECK(role IN ('primary','secondary')),
    PRIMARY KEY(candidate_id, company_id, role)
);

CREATE TABLE IF NOT EXISTS candidate_themes (
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    theme TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(candidate_id, theme)
);

CREATE TABLE IF NOT EXISTS candidate_authors (
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    author TEXT NOT NULL,
    normalized_author TEXT NOT NULL,
    PRIMARY KEY(candidate_id, normalized_author)
);

CREATE TABLE IF NOT EXISTS evidence_ledger (
    id INTEGER PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    claim TEXT NOT NULL,
    source_url TEXT NOT NULL,
    locator TEXT,
    source_position TEXT NOT NULL,
    evidence_strength TEXT NOT NULL,
    conflict_note TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vocabulary_evidence (
    issue_id TEXT NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    expression TEXT NOT NULL,
    source_context TEXT NOT NULL,
    PRIMARY KEY(issue_id, expression)
);

CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY,
    issue_number INTEGER NOT NULL UNIQUE,
    run_date TEXT NOT NULL,
    primary_candidate_id INTEGER NOT NULL UNIQUE REFERENCES candidates(id),
    primary_theme TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('selected','completed')),
    novelty_result TEXT NOT NULL CHECK(novelty_result IN ('Passed','Exception')),
    pack_path TEXT NOT NULL,
    pack_sha256 TEXT NOT NULL,
    selected_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS pack_versions (
    id INTEGER PRIMARY KEY,
    issue_id TEXT NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    phase TEXT NOT NULL CHECK(phase IN ('prepare','complete')),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(issue_id, version)
);

CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_title ON candidates(normalized_title);
CREATE INDEX IF NOT EXISTS idx_candidates_event ON candidates(event_key);
CREATE INDEX IF NOT EXISTS idx_candidates_fingerprint ON candidates(text_sha256);
CREATE INDEX IF NOT EXISTS idx_issues_number ON issues(issue_number DESC);
"""


class CuratorError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def today_local() -> str:
    return dt.date.today().isoformat()


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_name(value: str) -> str:
    return normalize_spaces(re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE))


def normalize_title(title: str, publication: str = "") -> str:
    value = title.casefold()
    if publication:
        value = value.replace(publication.casefold(), " ")
    value = re.sub(
        r"\b(?:19|20)\d{2}\b|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|"
        r"may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?)\b",
        " ",
        value,
    )
    value = re.sub(r"\b(?:edition|updated|update|report)\b", " ", value)
    return normalize_spaces(re.sub(r"[^a-z0-9]+", " ", value))


def canonicalize_url(raw_url: str) -> str:
    parsed = urllib.parse.urlsplit(raw_url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise CuratorError(f"invalid HTTP(S) URL: {raw_url!r}")
    host = parsed.hostname.casefold()
    if parsed.port and not (
        (parsed.scheme.lower() == "http" and parsed.port == 80)
        or (parsed.scheme.lower() == "https" and parsed.port == 443)
    ):
        host = f"{host}:{parsed.port}"
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_items = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        low = key.casefold()
        if low in TRACKING_KEYS or any(low.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        query_items.append((key, value))
    query_items.sort()
    query = urllib.parse.urlencode(query_items, doseq=True)
    return urllib.parse.urlunsplit((parsed.scheme.lower(), host, path, query, ""))


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


def sha256_text(text: str) -> str:
    normalized = normalize_spaces(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def simhash64(text: str) -> str:
    tokens = [token.casefold() for token in TOKEN_RE.findall(text)]
    if not tokens:
        return "0" * 16
    weights = [0] * 64
    for token in tokens:
        digest = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += 1 if digest & (1 << bit) else -1
    value = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            value |= 1 << bit
    return f"{value:016x}"


def simhash_similarity(left: str, right: str) -> float:
    distance = (int(left, 16) ^ int(right, 16)).bit_count()
    return 1.0 - distance / 64.0


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CuratorError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise CuratorError(f"{label} must be an array")
    return value


def require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CuratorError(f"{key} must be a non-empty string")
    return value.strip()


def validate_score(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise CuratorError(f"{label} must be an integer from 0 to 100")
    return value


def parse_date(value: str, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise CuratorError(f"{label} must use YYYY-MM-DD") from exc


def load_json(path: str) -> dict[str, Any]:
    if path == "-":
        return require_mapping(json.load(sys.stdin), "stdin")
    with open(path, encoding="utf-8") as handle:
        return require_mapping(json.load(handle), path)


def load_body(path: str | None) -> str | None:
    if not path:
        return None
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def default_config() -> dict[str, Any]:
    return {
        "reading_level": "B2-C1",
        "embedding": {
            "enabled": False,
            "base_url": "https://api.openai.com/v1",
            "model": "text-embedding-3-small",
            "api_key_env": "BUSINESS_READING_EMBEDDING_API_KEY",
            "dimensions": None,
            "timeout_seconds": 30,
        },
    }


def ensure_home(home: Path) -> tuple[Path, Path, Path]:
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    packs = home / "packs"
    packs.mkdir(mode=0o700, exist_ok=True)
    db_path = home / "history.sqlite3"
    config_path = home / "config.json"
    if not config_path.exists():
        config_path.write_text(json.dumps(default_config(), indent=2) + "\n", encoding="utf-8")
        config_path.chmod(0o600)
    return db_path, config_path, packs


def connect(home: Path) -> sqlite3.Connection:
    db_path, _, _ = ensure_home(home)
    conn = sqlite3.connect(db_path)
    db_path.chmod(0o600)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def load_config(home: Path) -> dict[str, Any]:
    _, config_path, _ = ensure_home(home)
    with config_path.open(encoding="utf-8") as handle:
        config = require_mapping(json.load(handle), "config")
    embedding = require_mapping(config.get("embedding", {}), "config.embedding")
    if os.getenv("BUSINESS_READING_EMBEDDING_BASE_URL"):
        embedding["base_url"] = os.environ["BUSINESS_READING_EMBEDDING_BASE_URL"]
    if os.getenv("BUSINESS_READING_EMBEDDING_MODEL"):
        embedding["model"] = os.environ["BUSINESS_READING_EMBEDDING_MODEL"]
    config["embedding"] = embedding
    return config


def request_embedding(text: str, config: dict[str, Any]) -> tuple[str, list[float]] | None:
    embedding = require_mapping(config.get("embedding", {}), "config.embedding")
    if not embedding.get("enabled"):
        return None
    base_url = require_string(embedding, "base_url").rstrip("/")
    model = require_string(embedding, "model")
    api_key_env = require_string(embedding, "api_key_env")
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise CuratorError(f"embedding enabled but environment variable {api_key_env} is unset")
    payload: dict[str, Any] = {"model": model, "input": text}
    if embedding.get("dimensions") is not None:
        payload["dimensions"] = int(embedding["dimensions"])
    request = urllib.request.Request(
        f"{base_url}/embeddings",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    timeout = int(embedding.get("timeout_seconds", 30))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
        raise CuratorError(f"embedding request failed: {type(exc).__name__}") from exc
    try:
        vector = result["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        raise CuratorError("embedding response lacks data[0].embedding") from exc
    if not isinstance(vector, list) or not vector or not all(isinstance(v, (int, float)) for v in vector):
        raise CuratorError("embedding response contains an invalid vector")
    return model, [float(v) for v in vector]


def calculate_human_origin(data: dict[str, Any]) -> tuple[int, list[str]]:
    evidence = require_mapping(data.get("origin_evidence", {}), "origin_evidence")
    provenance_class = evidence.get("provenance_class")
    bases = {
        "signed_filing": 98,
        "named_shareholder_letter": 96,
        "verified_transcript": 95,
        "named_established_journalist": 94,
        "named_trade_journalist": 86,
        "named_researcher": 85,
        "transparent_institutional_report": 80,
        "institutional_unclear_author": 65,
        "anonymous_or_unverifiable": 35,
    }
    if provenance_class not in bases:
        raise CuratorError("origin_evidence.provenance_class is invalid")
    score = bases[provenance_class]
    reasons = [f"base {score}: {provenance_class}"]
    caps: list[tuple[bool, int, str]] = [
        (not evidence.get("original_domain_verified", False), 59, "original domain not verified"),
        (
            evidence.get("syndicated", False) and not evidence.get("original_source_verified", False),
            59,
            "syndication origin not verified",
        ),
        (evidence.get("probable_mass_generated", False), 49, "probable mass-generated content"),
    ]
    for applies, cap, reason in caps:
        if applies and score > cap:
            score = cap
            reasons.append(f"cap {cap}: {reason}")
    adjustment = evidence.get("agent_adjustment", 0)
    if isinstance(adjustment, bool) or not isinstance(adjustment, int) or not -5 <= adjustment <= 5:
        raise CuratorError("origin_evidence.agent_adjustment must be an integer from -5 to 5")
    if adjustment:
        if not evidence.get("adjustment_reason"):
            raise CuratorError("origin_evidence.adjustment_reason is required for an adjustment")
        score = max(0, min(100, score + adjustment))
        reasons.append(f"agent adjustment {adjustment:+d}: {evidence['adjustment_reason']}")
    return score, reasons


def calculate_advertising_risk(data: dict[str, Any]) -> tuple[int, list[str]]:
    evidence = require_mapping(data.get("advertising_evidence", {}), "advertising_evidence")
    weights = {
        "lead_generation": 25,
        "affiliate_links": 25,
        "vendor_solution_pitch": 25,
        "anonymous_commercial_blog": 20,
        "supplier_controlled_customer_story": 20,
        "marketing_claims_only": 15,
        "seo_listicle": 15,
        "repetitive_product_naming": 10,
        "marketing_agency_republication": 30,
        "undisclosed_commercial_relationship": 30,
        "first_party_framing": 25,
    }
    if evidence.get("sponsored_or_partner_content"):
        return 100, ["100: sponsored or partner content"]
    score = 0
    reasons = []
    for key, weight in weights.items():
        applies = evidence.get(key, False)
        if key == "first_party_framing" and data.get("source_position") == "first_party":
            applies = True
        if applies:
            score += weight
            reasons.append(f"+{weight}: {key}")
    if evidence.get("operational_evidence_present", False):
        score -= 5
        reasons.append("-5: operational evidence present")
    score = max(0, min(100, score))
    adjustment = evidence.get("agent_adjustment", 0)
    if isinstance(adjustment, bool) or not isinstance(adjustment, int) or not -5 <= adjustment <= 5:
        raise CuratorError("advertising_evidence.agent_adjustment must be an integer from -5 to 5")
    if adjustment:
        if not evidence.get("adjustment_reason"):
            raise CuratorError("advertising_evidence.adjustment_reason is required for an adjustment")
        score = max(0, min(100, score + adjustment))
        reasons.append(f"agent adjustment {adjustment:+d}: {evidence['adjustment_reason']}")
    return score, reasons or ["0: no listed commercial-influence signal found"]


def get_or_create_company(conn: sqlite3.Connection, name: str) -> int:
    normalized = normalize_name(name)
    alias = conn.execute(
        "SELECT company_id FROM company_aliases WHERE normalized_alias=?", (normalized,)
    ).fetchone()
    if alias:
        return int(alias["company_id"])
    row = conn.execute(
        "SELECT id FROM companies WHERE normalized_name=?", (normalized,)
    ).fetchone()
    if row:
        return int(row["id"])
    cursor = conn.execute(
        "INSERT INTO companies(canonical_name,normalized_name) VALUES(?,?)",
        (normalize_spaces(name), normalized),
    )
    return int(cursor.lastrowid)


def selected_candidates(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT i.issue_number,i.run_date,i.primary_theme,c.*
        FROM issues i JOIN candidates c ON c.id=i.primary_candidate_id
        ORDER BY i.issue_number DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()


def candidate_company_names(conn: sqlite3.Connection, candidate_id: int, role: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT co.canonical_name FROM candidate_companies cc
        JOIN companies co ON co.id=cc.company_id
        WHERE cc.candidate_id=? AND cc.role=? ORDER BY co.canonical_name
        """,
        (candidate_id, role),
    ).fetchall()
    return [str(row["canonical_name"]) for row in rows]


def company_family_ids_for_name(conn: sqlite3.Connection, name: str) -> set[int]:
    company_id = get_or_create_company(conn, name)
    row = conn.execute(
        "SELECT parent_company_id FROM companies WHERE id=?", (company_id,)
    ).fetchone()
    return {company_id, int(row["parent_company_id"])} if row and row["parent_company_id"] else {company_id}


def candidate_company_family_ids(
    conn: sqlite3.Connection, candidate_id: int, role: str
) -> set[int]:
    rows = conn.execute(
        """
        SELECT co.id,co.parent_company_id FROM candidate_companies cc
        JOIN companies co ON co.id=cc.company_id
        WHERE cc.candidate_id=? AND cc.role=?
        """,
        (candidate_id, role),
    ).fetchall()
    result: set[int] = set()
    for row in rows:
        result.add(int(row["id"]))
        if row["parent_company_id"]:
            result.add(int(row["parent_company_id"]))
    return result


def calculate_novelty(
    conn: sqlite3.Connection,
    primary_company: str,
    secondary_companies: list[str],
    event_key: str,
    primary_theme: str,
    publication: str,
    source_type: str,
    authors: list[str],
    asset: str | None,
) -> tuple[int, list[str], dict[str, Any]]:
    recent = selected_candidates(conn, 100)
    company_family = company_family_ids_for_name(conn, primary_company)
    author_norms = {normalize_name(a) for a in authors}

    def row_companies(row: sqlite3.Row, role: str) -> set[int]:
        return candidate_company_family_ids(conn, int(row["id"]), role)

    primary_recent = next(
        (row for row in recent[:8] if company_family & row_companies(row, "primary")), None
    )
    secondary_recent = next(
        (row for row in recent[:4] if company_family & row_companies(row, "secondary")), None
    )
    secondary_families: set[int] = set()
    for company in secondary_companies:
        secondary_families |= company_family_ids_for_name(conn, company)
    current_secondary_recent = next(
        (
            row
            for row in recent[:4]
            if secondary_families
            & (row_companies(row, "primary") | row_companies(row, "secondary"))
        ),
        None,
    )
    cutoff_90 = dt.date.today() - dt.timedelta(days=90)
    same_event = next(
        (
            row
            for row in recent
            if row["event_key"] == event_key and parse_date(row["run_date"], "stored run_date") >= cutoff_90
        ),
        None,
    )
    same_asset = next(
        (
            row
            for row in recent[:12]
            if asset
            and row["asset"]
            and normalize_name(row["asset"]) == normalize_name(asset)
            and company_family
            & (row_companies(row, "primary") | row_companies(row, "secondary"))
        ),
        None,
    )
    previous_theme = bool(recent and normalize_name(recent[0]["primary_theme"]) == normalize_name(primary_theme))
    publication_count_6 = sum(
        1 for row in recent[:6] if normalize_name(row["publication"]) == normalize_name(publication)
    )
    publication_count_10 = sum(
        1 for row in recent[:10] if normalize_name(row["publication"]) == normalize_name(publication)
    )
    type_recent = sum(1 for row in recent[:2] if row["source_type"] == source_type)
    author_count_8 = 0
    for row in recent[:8]:
        old_authors = set(json.loads(row["author_json"]))
        if author_norms & {normalize_name(a) for a in old_authors}:
            author_count_8 += 1

    score = 0
    reasons: list[str] = []
    if not primary_recent and not secondary_recent:
        score += 30
        reasons.append("+30 company not in cooldown")
    else:
        score -= 25
        reasons.append("-25 company in cooldown")
    if not same_event:
        score += 25
        reasons.append("+25 new event key")
    else:
        score -= 40
        reasons.append("-40 same underlying event")
    if not previous_theme:
        score += 20
        reasons.append("+20 primary theme differs from previous issue")
    else:
        score -= 20
        reasons.append("-20 same primary theme as previous issue")
    if publication_count_6 == 0:
        score += 15
        reasons.append("+15 publication diversity")
    else:
        score -= 15
        reasons.append("-15 publication appeared recently")
    if type_recent == 0:
        score += 10
        reasons.append("+10 source-type diversity")
    else:
        score -= 10
        reasons.append("-10 source type repeated")
    score = max(0, min(100, score))
    checks = {
        "primary_company_cooldown": primary_recent["run_date"] if primary_recent else None,
        "secondary_company_cooldown": secondary_recent["run_date"] if secondary_recent else None,
        "current_secondary_company_cooldown": (
            current_secondary_recent["run_date"] if current_secondary_recent else None
        ),
        "same_event_issue": same_event["issue_number"] if same_event else None,
        "same_asset_issue": same_asset["issue_number"] if same_asset else None,
        "same_primary_theme_as_previous": previous_theme,
        "publication_count_last_6": publication_count_6,
        "publication_count_last_10": publication_count_10,
        "author_count_last_8": author_count_8,
    }
    return score, reasons, checks


def cooldown_defer_reasons(
    conn: sqlite3.Connection,
    *,
    primary_theme: str,
    publication: str,
    source_type: str,
    source_position: str,
    industry_bucket: str,
    novelty: int,
    novelty_checks: dict[str, Any],
    material_update: bool,
) -> list[str]:
    reasons: list[str] = []
    company_event_problem = any(
        [
            novelty_checks["primary_company_cooldown"],
            novelty_checks["secondary_company_cooldown"],
            novelty_checks["current_secondary_company_cooldown"],
            novelty_checks["same_event_issue"],
            novelty_checks["same_asset_issue"],
        ]
    )
    diversity_problem = any(
        [
            novelty_checks["same_primary_theme_as_previous"],
            novelty_checks["publication_count_last_6"] >= 2,
            novelty_checks["publication_count_last_10"] >= 2,
            novelty_checks["author_count_last_8"] >= 1,
        ]
    )
    if novelty < 65 and not material_update:
        reasons.append("Novelty Score below 65")
    if company_event_problem and not material_update:
        reasons.append("company, asset, or event cooldown triggered")
    if diversity_problem:
        reasons.append("theme, publication, or author diversity rule triggered")

    recent = selected_candidates(conn, 10)
    same_theme_count_4 = sum(
        1
        for row in recent[:4]
        if normalize_name(row["primary_theme"]) == normalize_name(primary_theme)
    )
    first_party_count_9 = sum(1 for row in recent[:9] if row["source_position"] == "first_party")
    transcript_count_5 = sum(
        1 for row in recent[:5] if row["source_type"] == "earnings_call_transcript"
    )
    consulting_count_9 = sum(
        1 for row in recent[:9] if row["source_type"] == "consulting_report"
    )
    if same_theme_count_4 >= 2:
        reasons.append("primary theme would appear more than twice within five issues")
    if source_position == "first_party" and first_party_count_9 >= 3:
        reasons.append("first-party primary limit of three within ten issues")
    if source_type == "earnings_call_transcript" and transcript_count_5 >= 2:
        reasons.append("earnings-call transcript limit of two within six issues")
    if source_type == "consulting_report" and consulting_count_9 >= 1:
        reasons.append("consulting-report limit of one within ten issues")
    if len(recent) >= 4:
        prospective = recent[:4]
        industry_set = {str(row["industry_bucket"]) for row in prospective} | {industry_bucket}
        source_type_set = {str(row["source_type"]) for row in prospective} | {source_type}
        independent_count = sum(
            1 for row in prospective if row["source_position"] == "independent"
        ) + int(source_position == "independent")
        if len(industry_set) < 3:
            reasons.append("five-issue window would contain fewer than three industries")
        if len(source_type_set) < 3:
            reasons.append("five-issue window would contain fewer than three source types")
        if independent_count < 2:
            reasons.append("five-issue window would contain fewer than two independent readings")
    return reasons


def current_candidate_novelty(
    conn: sqlite3.Connection, candidate: sqlite3.Row
) -> tuple[int, list[str], list[str], dict[str, Any], str]:
    candidate_id = int(candidate["id"])
    primary_companies = candidate_company_names(conn, candidate_id, "primary")
    if not primary_companies:
        raise CuratorError(f"candidate {candidate_id} has no primary company")
    secondary_companies = candidate_company_names(conn, candidate_id, "secondary")
    primary_theme_row = conn.execute(
        "SELECT theme FROM candidate_themes WHERE candidate_id=? AND is_primary=1",
        (candidate_id,),
    ).fetchone()
    if not primary_theme_row:
        raise CuratorError(f"candidate {candidate_id} has no primary theme")
    primary_theme = str(primary_theme_row["theme"])
    authors = list(json.loads(candidate["author_json"]))
    novelty, novelty_reasons, novelty_checks = calculate_novelty(
        conn,
        primary_companies[0],
        secondary_companies,
        candidate["event_key"],
        primary_theme,
        candidate["publication"],
        candidate["source_type"],
        authors,
        candidate["asset"],
    )
    defer_reasons = cooldown_defer_reasons(
        conn,
        primary_theme=primary_theme,
        publication=candidate["publication"],
        source_type=candidate["source_type"],
        source_position=candidate["source_position"],
        industry_bucket=candidate["industry_bucket"],
        novelty=novelty,
        novelty_checks=novelty_checks,
        material_update=bool(candidate["material_update"]),
    )
    return novelty, novelty_reasons, defer_reasons, novelty_checks, primary_theme


def find_duplicates(
    conn: sqlite3.Connection,
    canonical_url: str,
    normalized: str,
    text_sha: str | None,
    simhash: str | None,
    embedding_model: str | None,
    embedding: list[float] | None,
    document_id: str | None = None,
    exclude_id: int | None = None,
) -> list[dict[str, Any]]:
    duplicates: list[dict[str, Any]] = []
    rows = conn.execute("SELECT * FROM candidates ORDER BY id DESC").fetchall()
    semantic_candidate_ids = {
        int(row["primary_candidate_id"])
        for row in conn.execute(
            "SELECT primary_candidate_id FROM issues ORDER BY issue_number DESC LIMIT 100"
        ).fetchall()
    }
    for row in rows:
        if exclude_id is not None and int(row["id"]) == exclude_id:
            continue
        reasons: list[str] = []
        similarities: dict[str, float] = {}
        if row["canonical_url"] == canonical_url:
            reasons.append("same canonical URL")
        if document_id and row["document_id"] and normalize_name(document_id) == normalize_name(row["document_id"]):
            reasons.append("same document identifier")
        title_similarity = difflib.SequenceMatcher(None, normalized, row["normalized_title"]).ratio()
        similarities["title"] = round(title_similarity, 4)
        if title_similarity > 0.90:
            reasons.append("title similarity above 90%")
        if text_sha and row["text_sha256"] == text_sha:
            reasons.append("same normalized full-text fingerprint")
        if simhash and row["simhash"]:
            body_similarity = simhash_similarity(simhash, row["simhash"])
            similarities["simhash"] = round(body_similarity, 4)
            if body_similarity > 0.85:
                reasons.append("near-full-text similarity above 85%")
        if (
            embedding
            and embedding_model
            and int(row["id"]) in semantic_candidate_ids
            and row["embedding_model"] == embedding_model
            and row["embedding_json"]
        ):
            old_embedding = json.loads(row["embedding_json"])
            semantic = cosine_similarity(embedding, old_embedding)
            similarities["semantic"] = round(semantic, 4)
            if semantic > 0.90:
                reasons.append("semantic similarity above 0.90 requires review")
            elif semantic >= 0.82:
                reasons.append("semantic similarity 0.82-0.90 requires review")
        if reasons:
            duplicates.append(
                {
                    "candidate_id": row["id"],
                    "status": row["status"],
                    "title": row["title"],
                    "reasons": reasons,
                    "similarities": similarities,
                }
            )
    return duplicates


def assess_candidate(
    conn: sqlite3.Connection,
    data: dict[str, Any],
    body: str | None,
    config: dict[str, Any],
    strict_embedding: bool,
) -> dict[str, Any]:
    title = require_string(data, "title")
    research_batch_id = require_string(data, "research_batch_id")
    original_url = require_string(data, "url")
    canonical_url = canonicalize_url(original_url)
    publication = require_string(data, "publication")
    publication_date = require_string(data, "publication_date")
    parse_date(publication_date, "publication_date")
    industry = require_string(data, "industry")
    industry_bucket = require_string(data, "industry_bucket")
    if industry_bucket not in INDUSTRY_BUCKETS:
        raise CuratorError(
            "industry_bucket must be one of: " + ", ".join(sorted(INDUSTRY_BUCKETS))
        )
    event_key = require_string(data, "event_key")
    source_type = require_string(data, "source_type")
    if source_type not in PRIMARY_SOURCE_TYPES:
        raise CuratorError(f"unsupported source_type: {source_type}")
    source_position = require_string(data, "source_position")
    if source_position not in {"first_party", "independent"}:
        raise CuratorError("source_position must be first_party or independent")
    access_status = require_string(data, "access_status").casefold()
    access_exception_reason = normalize_spaces(
        str(data.get("access_exception_reason", ""))
    ) or None
    archive_url = data.get("archive_url")
    archive_snapshot_date = data.get("archive_snapshot_date")
    if access_status == "archived_public":
        if not archive_url or not archive_snapshot_date:
            raise CuratorError(
                "archived_public requires archive_url and archive_snapshot_date"
            )
        archive_url = canonicalize_url(str(archive_url))
        parse_date(str(archive_snapshot_date), "archive_snapshot_date")
    authors = [normalize_spaces(str(a)) for a in require_list(data.get("authors"), "authors") if str(a).strip()]
    if not authors:
        raise CuratorError("authors must contain at least one author, speaker, or institution")
    companies = require_mapping(data.get("companies"), "companies")
    primary_company = require_string(companies, "primary")
    secondary_companies = [
        normalize_spaces(str(item))
        for item in require_list(companies.get("secondary", []), "companies.secondary")
        if str(item).strip()
    ]
    themes = [normalize_spaces(str(item)) for item in require_list(data.get("themes"), "themes") if str(item).strip()]
    if not 2 <= len(themes) <= 5:
        raise CuratorError("themes must contain two to five values")
    primary_theme = require_string(data, "primary_theme")
    if normalize_name(primary_theme) not in {normalize_name(theme) for theme in themes}:
        raise CuratorError("primary_theme must appear in themes")
    scores = require_mapping(data.get("scores"), "scores")
    analytical_depth = validate_score(scores.get("analytical_depth"), "scores.analytical_depth")
    evidence_quality = validate_score(scores.get("evidence_quality"), "scores.evidence_quality")
    business_relevance = validate_score(scores.get("business_relevance"), "scores.business_relevance")
    english_reading_value = validate_score(scores.get("english_reading_value"), "scores.english_reading_value")
    human_score, human_reasons = calculate_human_origin(data)
    advertising_score, advertising_reasons = calculate_advertising_risk(data)

    if body is not None:
        word_count = count_words(body)
        text_sha = sha256_text(body)
        simhash = simhash64(body)
    else:
        word_count = int(data.get("word_count", 0))
        text_sha = None
        simhash = None
    if word_count <= 0:
        raise CuratorError("provide --body-file or a positive word_count")
    semantic_topic_fingerprint = sha256_text(
        " | ".join(
            [
                normalize_name(primary_company),
                normalize_name(str(data.get("event_type") or "")),
                normalize_name(str(data.get("asset") or "")),
                normalize_name(str(data.get("geography") or "")),
                *(normalize_name(theme) for theme in themes),
            ]
        )
    )

    embedding_model = None
    embedding_vector = None
    embedding_warning = None
    if body is not None and config.get("embedding", {}).get("enabled"):
        semantic_text = "\n".join(
            [
                title,
                normalize_spaces(body[:4000]),
                primary_company,
                event_key,
                " | ".join(themes),
            ]
        )
        try:
            result = request_embedding(semantic_text, config)
            if result:
                embedding_model, embedding_vector = result
        except CuratorError as exc:
            if strict_embedding:
                raise
            embedding_warning = str(exc)

    existing = conn.execute(
        "SELECT id,status FROM candidates WHERE canonical_url=?", (canonical_url,)
    ).fetchone()
    duplicates = find_duplicates(
        conn,
        canonical_url,
        normalize_title(title, publication),
        text_sha,
        simhash,
        embedding_model,
        embedding_vector,
        data.get("document_id"),
        int(existing["id"]) if existing else None,
    )
    novelty, novelty_reasons, novelty_checks = calculate_novelty(
        conn,
        primary_company,
        secondary_companies,
        event_key,
        primary_theme,
        publication,
        source_type,
        authors,
        data.get("asset"),
    )
    material_update = bool(data.get("material_update", False))
    exception_reason = normalize_spaces(str(data.get("exception_reason", ""))) or None
    if material_update and not exception_reason:
        raise CuratorError("exception_reason is required when material_update is true")
    length_exception = bool(data.get("length_exception", False))
    length_exception_reason = normalize_spaces(str(data.get("length_exception_reason", ""))) or None
    if length_exception and not length_exception_reason:
        raise CuratorError("length_exception_reason is required for a length exception")
    semantic_review_outcome = data.get("semantic_review_outcome")
    semantic_review_reason = normalize_spaces(
        str(data.get("semantic_review_reason", ""))
    ) or None
    if semantic_review_outcome not in {None, "duplicate", "materially_different"}:
        raise CuratorError(
            "semantic_review_outcome must be duplicate, materially_different, or null"
        )
    if semantic_review_outcome and not semantic_review_reason:
        raise CuratorError("semantic_review_reason is required for a semantic review outcome")

    hard_failures: list[str] = []
    defer_reasons: list[str] = []
    if access_status not in HARD_ACCESS:
        if access_status != "registration_required":
            hard_failures.append("primary text is not freely and fully accessible")
    if access_status == "registration_required" and not access_exception_reason:
        defer_reasons.append("free registration wall requires a documented quality exception")
    if human_score < 75:
        hard_failures.append("Human-Origin Confidence below 75")
    if source_position == "independent" and advertising_score > 30:
        hard_failures.append("independent primary Advertising Risk above 30")
    if source_position == "first_party" and advertising_score >= 61:
        hard_failures.append("first-party primary Advertising Risk is 61 or above")
    if analytical_depth < 70:
        hard_failures.append("Analytical Depth below 70")
    if evidence_quality < 70:
        hard_failures.append("Evidence Quality below 70")
    if source_type not in PRIMARY_SOURCE_TYPES:
        hard_failures.append("unsupported primary source type")
    if not (1500 <= word_count <= 6000):
        permitted_exception = length_exception and 1200 <= word_count < 1500
        if not permitted_exception:
            hard_failures.append("word count outside 1,500-6,000 without a permitted exception")
    blocking_duplicates = []
    review_duplicates = []
    for duplicate in duplicates:
        if any("semantic similarity" in reason and "requires review" in reason for reason in duplicate["reasons"]):
            review_duplicates.append(duplicate)
        if any(
            marker in reason
            for reason in duplicate["reasons"]
            for marker in (
                "same canonical URL",
                "same document identifier",
                "same normalized full-text",
                "near-full-text",
                "title similarity above",
            )
        ):
            blocking_duplicates.append(duplicate)
    if blocking_duplicates:
        hard_failures.append("exact or near-duplicate candidate")
    if review_duplicates:
        if semantic_review_outcome == "duplicate":
            hard_failures.append("semantic review confirmed a duplicate topic/article")
        elif semantic_review_outcome != "materially_different":
            defer_reasons.append("semantic similarity requires documented review")

    defer_reasons.extend(
        cooldown_defer_reasons(
            conn,
            primary_theme=primary_theme,
            publication=publication,
            source_type=source_type,
            source_position=source_position,
            industry_bucket=industry_bucket,
            novelty=novelty,
            novelty_checks=novelty_checks,
            material_update=material_update,
        )
    )

    access_only = hard_failures and all(
        failure == "primary text is not freely and fully accessible" for failure in hard_failures
    )
    if access_only:
        status = "deferred"
        rejection_reason = "; ".join(hard_failures)
        review_after = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    elif hard_failures:
        status = "rejected"
        rejection_reason = "; ".join(hard_failures)
        review_after = None
    elif defer_reasons:
        status = "deferred"
        rejection_reason = "; ".join(defer_reasons)
        review_after = (dt.date.today() + dt.timedelta(days=90)).isoformat()
    else:
        status = "shortlisted"
        rejection_reason = None
        review_after = None

    duplicate_of = blocking_duplicates[0]["candidate_id"] if blocking_duplicates else None
    now = utc_now()
    values = (
        canonical_url,
        original_url,
        research_batch_id,
        title,
        normalize_title(title, publication),
        publication,
        publication_date,
        industry,
        industry_bucket,
        event_key,
        data.get("document_id"),
        data.get("event_type"),
        data.get("asset"),
        data.get("geography"),
        data.get("approximate_event_date"),
        source_type,
        source_position,
        access_status,
        access_exception_reason,
        archive_url,
        archive_snapshot_date,
        word_count,
        data.get("selected_range"),
        length_exception_reason,
        json_dump(authors),
        json_dump(data["origin_evidence"]),
        json_dump(data["advertising_evidence"]),
        human_score,
        advertising_score,
        analytical_depth,
        evidence_quality,
        business_relevance,
        english_reading_value,
        novelty,
        status,
        rejection_reason,
        review_after,
        int(material_update),
        exception_reason,
        text_sha,
        simhash,
        semantic_topic_fingerprint,
        embedding_model,
        len(embedding_vector) if embedding_vector else None,
        json_dump(embedding_vector) if embedding_vector else None,
        semantic_review_outcome,
        semantic_review_reason,
        duplicate_of,
        now,
        now,
    )
    if existing:
        candidate_id = int(existing["id"])
        if existing["status"] in {"selected", "completed"}:
            raise CuratorError("cannot reassess a selected or completed candidate")
        conn.execute(
            """
            UPDATE candidates SET
              original_url=?,research_batch_id=?,title=?,normalized_title=?,publication=?,publication_date=?,
              industry=?,industry_bucket=?,event_key=?,document_id=?,event_type=?,asset=?,geography=?,approximate_event_date=?,
              source_type=?,source_position=?,access_status=?,access_exception_reason=?,
              archive_url=?,archive_snapshot_date=?,word_count=?,selected_range=?,
              length_exception_reason=?,author_json=?,
              origin_evidence_json=?,advertising_evidence_json=?,human_origin_confidence=?,
              advertising_risk=?,analytical_depth=?,evidence_quality=?,business_relevance=?,
              english_reading_value=?,novelty_score=?,status=?,rejection_reason=?,review_after=?,
              material_update=?,exception_reason=?,text_sha256=?,simhash=?,
              semantic_topic_fingerprint=?,embedding_model=?,embedding_dimensions=?,
              embedding_json=?,semantic_review_outcome=?,
              semantic_review_reason=?,duplicate_of_id=?,reviewed_at=?
            WHERE id=?
            """,
            values[1:-2] + (now, candidate_id),
        )
        conn.execute("DELETE FROM candidate_companies WHERE candidate_id=?", (candidate_id,))
        conn.execute("DELETE FROM candidate_themes WHERE candidate_id=?", (candidate_id,))
        conn.execute("DELETE FROM candidate_authors WHERE candidate_id=?", (candidate_id,))
        conn.execute("DELETE FROM evidence_ledger WHERE candidate_id=?", (candidate_id,))
    else:
        cursor = conn.execute(
            """
            INSERT INTO candidates(
              canonical_url,original_url,research_batch_id,title,normalized_title,publication,publication_date,
              industry,industry_bucket,event_key,document_id,event_type,asset,geography,approximate_event_date,source_type,
              source_position,access_status,access_exception_reason,archive_url,archive_snapshot_date,
              word_count,selected_range,length_exception_reason,author_json,origin_evidence_json,
              advertising_evidence_json,human_origin_confidence,advertising_risk,
              analytical_depth,evidence_quality,business_relevance,english_reading_value,
              novelty_score,status,rejection_reason,review_after,material_update,exception_reason,
              text_sha256,simhash,semantic_topic_fingerprint,embedding_model,embedding_dimensions,embedding_json,
              semantic_review_outcome,semantic_review_reason,duplicate_of_id,created_at,reviewed_at
            ) VALUES({placeholders})
            """.format(placeholders=",".join("?" for _ in values)),
            values,
        )
        candidate_id = int(cursor.lastrowid)

    for role, names in (("primary", [primary_company]), ("secondary", secondary_companies)):
        for name in names:
            company_id = get_or_create_company(conn, name)
            conn.execute(
                "INSERT OR IGNORE INTO candidate_companies(candidate_id,company_id,role) VALUES(?,?,?)",
                (candidate_id, company_id, role),
            )
    for theme in themes:
        conn.execute(
            "INSERT OR IGNORE INTO candidate_themes(candidate_id,theme,is_primary) VALUES(?,?,?)",
            (candidate_id, theme, int(normalize_name(theme) == normalize_name(primary_theme))),
        )
    for author in authors:
        conn.execute(
            "INSERT OR IGNORE INTO candidate_authors(candidate_id,author,normalized_author) VALUES(?,?,?)",
            (candidate_id, author, normalize_name(author)),
        )
    for item in require_list(data.get("evidence_ledger", []), "evidence_ledger"):
        evidence = require_mapping(item, "evidence_ledger item")
        conn.execute(
            """
            INSERT INTO evidence_ledger(
              candidate_id,claim,source_url,locator,source_position,evidence_strength,
              conflict_note,fetched_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                candidate_id,
                require_string(evidence, "claim"),
                canonicalize_url(require_string(evidence, "source_url")),
                evidence.get("locator"),
                require_string(evidence, "source_position"),
                require_string(evidence, "evidence_strength"),
                evidence.get("conflict_note"),
                evidence.get("fetched_at", now),
            ),
        )
    conn.commit()
    return {
        "candidate_id": candidate_id,
        "canonical_url": canonical_url,
        "status": status,
        "human_origin_confidence": human_score,
        "human_origin_reasons": human_reasons,
        "advertising_risk": advertising_score,
        "advertising_risk_reasons": advertising_reasons,
        "novelty_score": novelty,
        "novelty_reasons": novelty_reasons,
        "novelty_checks": novelty_checks,
        "duplicates": duplicates,
        "hard_failures": hard_failures,
        "defer_reasons": defer_reasons,
        "embedding": {
            "mode": "active" if embedding_vector else "degraded" if embedding_warning else "disabled",
            "model": embedding_model,
            "dimensions": len(embedding_vector) if embedding_vector else None,
            "warning": embedding_warning,
        },
        "word_count": word_count,
    }


def source_block(source: dict[str, Any], label: str) -> list[str]:
    title = require_string(source, "title")
    url = canonicalize_url(require_string(source, "url"))
    publication = require_string(source, "publication")
    date = require_string(source, "publication_date")
    position = require_string(source, "source_position")
    human = validate_score(source.get("human_origin_confidence"), "human_origin_confidence")
    risk = validate_score(source.get("advertising_risk"), "advertising_risk")
    human_evidence = require_string(source, "human_origin_evidence")
    risk_evidence = require_string(source, "advertising_risk_evidence")
    lines = [
        f"**{label}:** [{title}]({url})",
        f"- Publication: {publication}",
        f"- Date: {date}",
        f"- Position: {position}",
        f"- Human-Origin Confidence: {human}/100",
        f"- Human-origin evidence: {human_evidence}",
        f"- Advertising Risk: {risk}/100",
        f"- Advertising-risk evidence: {risk_evidence}",
    ]
    if source.get("commercial_influence_note"):
        lines.append(f"- Commercial-influence note: {source['commercial_influence_note']}")
    return lines


def vocabulary_contexts(data: dict[str, Any], body: str) -> list[tuple[str, str]]:
    lowered = body.casefold()
    contexts: list[tuple[str, str]] = []
    for item in data["vocabulary"]:
        expression = require_string(item, "expression")
        index = lowered.find(expression.casefold())
        if index < 0:
            raise CuratorError(
                f"vocabulary expression does not occur in the supplied source body: {expression!r}"
            )
        start = max(0, index - 100)
        end = min(len(body), index + len(expression) + 100)
        contexts.append((expression, normalize_spaces(body[start:end])))
    return contexts


def validate_pack_input(
    candidate: sqlite3.Row, data: dict[str, Any], body: str | None
) -> list[tuple[str, str]]:
    direction_zh = require_string(data, "direction_zh")
    if "\n" in direction_zh or len(direction_zh) > 180:
        raise CuratorError("direction_zh must be one line and no more than 180 characters")
    why = require_string(data, "why_selected")
    why_words = count_words(why)
    if not 80 <= why_words <= 120:
        raise CuratorError(f"why_selected must contain 80-120 English words; got {why_words}")
    require_string(data, "human_origin_explanation")
    require_string(data, "advertising_risk_explanation")
    require_string(data, "material_difference")
    pre = require_list(data.get("pre_reading_questions"), "pre_reading_questions")
    if len(pre) != 3:
        raise CuratorError("pre_reading_questions must contain exactly three questions")
    vocabulary = require_list(data.get("vocabulary"), "vocabulary")
    if not 8 <= len(vocabulary) <= 12:
        raise CuratorError("vocabulary must contain 8-12 items")
    for item in vocabulary:
        row = require_mapping(item, "vocabulary item")
        for key in ("expression", "definition", "context_meaning", "new_example"):
            require_string(row, key)
    if body is None:
        raise CuratorError("the source body is required to verify vocabulary expressions")
    contexts = vocabulary_contexts(data, body)
    checkpoints = require_mapping(data.get("checkpoints"), "checkpoints")
    if set(checkpoints) != {"25", "50", "75", "100"}:
        raise CuratorError("checkpoints must contain exactly 25, 50, 75, and 100")
    post = require_mapping(data.get("post_reading_questions"), "post_reading_questions")
    expected = {"factual_recall": 2, "inference": 2, "business_judgment": 2}
    for key, count in expected.items():
        if len(require_list(post.get(key), f"post_reading_questions.{key}")) != count:
            raise CuratorError(f"post_reading_questions.{key} must contain {count} questions")
    require_string(post, "challenge_framing")
    require_string(post, "missing_evidence")
    corroborating = require_mapping(data.get("corroborating_source"), "corroborating_source")
    if require_string(corroborating, "source_position") != "independent":
        raise CuratorError("corroborating_source must be independent")
    corroborating_risk = validate_score(
        corroborating.get("advertising_risk"), "corroborating advertising_risk"
    )
    if corroborating_risk > 40:
        raise CuratorError("corroborating source Advertising Risk must be 40 or lower")
    require_string(corroborating, "human_origin_evidence")
    require_string(corroborating, "advertising_risk_evidence")
    if corroborating_risk > 30 and not corroborating.get("commercial_influence_note"):
        raise CuratorError(
            "corroborating source Advertising Risk above 30 requires commercial_influence_note"
        )
    if (
        validate_score(
            corroborating.get("human_origin_confidence"),
            "corroborating human_origin_confidence",
        )
        < 75
    ):
        raise CuratorError("corroborating source Human-Origin Confidence must be at least 75")
    if canonicalize_url(require_string(corroborating, "url")) == candidate["canonical_url"]:
        raise CuratorError("corroborating source must differ from the primary source")
    citations = require_list(data.get("fact_citations"), "fact_citations")
    if not citations:
        raise CuratorError("fact_citations must contain at least one factual citation")
    for citation in citations:
        item = require_mapping(citation, "fact citation")
        require_string(item, "fact")
        canonicalize_url(require_string(item, "url"))
    primary_data = data.get("primary_data_source")
    if primary_data is not None:
        source_block(require_mapping(primary_data, "primary_data_source"), "primary data")
    return contexts


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:72] or "reading"


def version_path(path: Path, version: int, phase: str) -> Path:
    versions = path.parent / ".versions"
    versions.mkdir(mode=0o700, parents=True, exist_ok=True)
    return versions / f"{path.stem}.v{version}.{phase}{path.suffix}"


def render_chat_message(
    issue_id: str,
    candidate: sqlite3.Row,
    companies: list[str],
    data: dict[str, Any],
) -> str:
    reading_minutes = max(1, round(candidate["word_count"] / 220))
    source_position = "独立来源" if candidate["source_position"] == "independent" else "第一方来源"
    displayed_companies = companies[:3]
    company_text = "、".join(displayed_companies)
    if len(companies) > 3:
        company_text += f" 等 {len(companies)} 家"
    lines = [
        f"📚 本期英文商业阅读 · {issue_id}",
        f"标题：{candidate['title']}",
        f"行业：{candidate['industry']}",
        f"公司：{company_text}",
        f"方向：{data['direction_zh']}",
        f"篇幅：约 {candidate['word_count']:,} 词 · {reading_minutes} 分钟",
        (
            f"来源：{candidate['publication']} · {candidate['publication_date']} · "
            f"{source_position}"
        ),
        (
            f"来源判断：人类来源可信度 {candidate['human_origin_confidence']}/100 · "
            f"广告风险 {candidate['advertising_risk']}/100"
        ),
        f"原文：{candidate['canonical_url']}",
        "",
        (
            f"按需查看：回复“词汇 {issue_id}”或“问题 {issue_id}”；"
            f"只有回复“完整导读 {issue_id}”才展开全部。"
        ),
    ]
    message = "\n".join(lines)
    if len(message) > 1000:
        raise CuratorError(
            f"generated chat_message is {len(message)} characters; maximum is 1000"
        )
    return message


def render_prepare(
    issue_id: str,
    candidate: sqlite3.Row,
    companies: list[str],
    themes: list[str],
    data: dict[str, Any],
    novelty_result: str,
    last_company: str,
    last_theme: str,
    duplicate_count: int,
) -> str:
    authors = json.loads(candidate["author_json"])
    reading_minutes = max(1, round(candidate["word_count"] / 220))
    lines = [
        f"# Business Reading Pack — {issue_id}",
        "",
        "> AI-generated reading guidance. The linked primary article is the original source.",
        "",
        "## Original Human-Created Reading / 人类原创阅读",
        "",
        f"> **Original source:** [{candidate['title']}]({candidate['canonical_url']})",
        "",
        f"**Title:** [{candidate['title']}]({candidate['canonical_url']})",
        f"**Author/Speaker:** {', '.join(authors)}",
        f"**Publication:** {candidate['publication']}",
        f"**Date:** {candidate['publication_date']}",
        f"**Industry:** {candidate['industry']}",
        f"**Companies:** {', '.join(companies)}",
        f"**Word count:** approximately {candidate['word_count']:,}",
        f"**Selected range:** {candidate['selected_range'] or 'Complete article'}",
        f"**Estimated reading time:** {reading_minutes} minutes",
        f"**Source type:** {candidate['source_type']}",
        f"**Access status:** {candidate['access_status']}",
        f"**Original link:** {candidate['canonical_url']}",
        "",
        "## AI-Generated Reading Guidance / AI 阅读指导",
        "",
        "### Why this selection",
        "",
        data["why_selected"],
        "",
        "### Provenance and commercial-influence assessment / 来源与商业影响",
        "",
        f"**Human-Origin Confidence:** {candidate['human_origin_confidence']}/100",
        f"**Evidence:** {data['human_origin_explanation']}",
        "",
        f"**Advertising Risk:** {candidate['advertising_risk']}/100",
        f"**Evidence:** {data['advertising_risk_explanation']}",
        "",
        f"**Source position:** {candidate['source_position']}",
        f"**Disclosures or uncertainties:** {data.get('disclosures_or_uncertainties', 'None identified.')}",
        "",
        "### Novelty check / 新颖性检查",
        "",
        f"**Novelty check:** {novelty_result}",
        f"**Novelty Score:** {candidate['novelty_score']}/100",
        f"**Last appearance of this company:** {last_company}",
        f"**Last appearance of this primary theme:** {last_theme}",
        f"**Previous similar articles found:** {duplicate_count}",
        f"**Reason this article is materially different:** {data['material_difference']}",
        f"**Themes:** {', '.join(themes)}",
        "",
        "### Reading order / 阅读顺序",
        "",
        f"1. **Primary reading:** [{candidate['title']}]({candidate['canonical_url']})",
    ]
    if candidate["archive_url"]:
        lines.extend(
            [
                f"**Archive link:** {candidate['archive_url']}",
                f"**Archive snapshot date:** {candidate['archive_snapshot_date']}",
                "",
            ]
        )
    corroborating = data["corroborating_source"]
    lines.append(
        f"2. **Independent corroborating source:** [{corroborating['title']}]"
        f"({canonicalize_url(corroborating['url'])})"
    )
    primary_data = data.get("primary_data_source")
    if primary_data:
        lines.append(
            f"3. **Optional primary-data source:** [{primary_data['title']}]"
            f"({canonicalize_url(primary_data['url'])})"
        )
    else:
        lines.append("3. **Optional primary-data source:** Not found or not applicable.")
    lines.extend(["", "### Pre-reading questions", ""])
    lines.extend(f"{index}. {question}" for index, question in enumerate(data["pre_reading_questions"], 1))
    lines.extend(
        [
            "",
            "### Vocabulary",
            "",
            "| Expression | English definition | Meaning in context | New example |",
            "|---|---|---|---|",
        ]
    )
    for item in data["vocabulary"]:
        cells = [
            str(item[key]).replace("|", "\\|").replace("\n", " ")
            for key in ("expression", "definition", "context_meaning", "new_example")
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "### Reading checkpoints", ""])
    for progress in ("25", "50", "75", "100"):
        lines.append(f"**{progress}%:** {data['checkpoints'][progress]}")
        lines.append("")
    post = data["post_reading_questions"]
    lines.extend(["### Post-reading questions", "", "**Factual recall**", ""])
    lines.extend(f"- {question}" for question in post["factual_recall"])
    lines.extend(["", "**Inference**", ""])
    lines.extend(f"- {question}" for question in post["inference"])
    lines.extend(["", "**Business judgment**", ""])
    lines.extend(f"- {question}" for question in post["business_judgment"])
    lines.extend(
        [
            "",
            f"- **Challenge the framing:** {post['challenge_framing']}",
            f"- **Missing evidence:** {post['missing_evidence']}",
            "",
            "### Source notes",
            "",
        ]
    )
    lines.extend(source_block(corroborating, "Independent corroborating source"))
    if primary_data:
        lines.extend([""] + source_block(primary_data, "Optional primary-data source"))
    lines.extend(["", "### Factual citations / 事实引用", ""])
    for citation in data["fact_citations"]:
        lines.append(f"- {citation['fact']} ([source]({canonicalize_url(citation['url'])}))")
    lines.extend(
        [
            "",
            "> The source-comparison framework and short synthesis remain locked until this issue is marked complete.",
            "",
        ]
    )
    return "\n".join(lines)


def command_prepare(
    conn: sqlite3.Connection, home: Path, data: dict[str, Any], body: str | None
) -> dict[str, Any]:
    candidate_id = int(data.get("candidate_id", 0))
    candidate = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not candidate:
        raise CuratorError(f"candidate {candidate_id} not found")
    if candidate["status"] != "shortlisted":
        raise CuratorError(f"candidate must be shortlisted, got {candidate['status']}")
    vocab_contexts = validate_pack_input(candidate, data, body)
    assessed_count = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM candidates
            WHERE research_batch_id=? AND text_sha256 IS NOT NULL
            """,
            (candidate["research_batch_id"],),
        ).fetchone()[0]
    )
    if assessed_count < 5:
        raise CuratorError(
            f"research batch {candidate['research_batch_id']!r} has only "
            f"{assessed_count} full-text assessments; at least five are required"
        )
    current_novelty, _, current_defer, _, _ = current_candidate_novelty(conn, candidate)
    if current_defer:
        raise CuratorError(
            "candidate no longer satisfies current novelty/cooldowns: "
            + "; ".join(current_defer)
        )
    conn.execute(
        "UPDATE candidates SET novelty_score=? WHERE id=?",
        (current_novelty, candidate_id),
    )
    conn.commit()
    candidate = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    duplicate_count = len(
        find_duplicates(
            conn,
            candidate["canonical_url"],
            candidate["normalized_title"],
            candidate["text_sha256"],
            candidate["simhash"],
            candidate["embedding_model"],
            json.loads(candidate["embedding_json"]) if candidate["embedding_json"] else None,
            candidate["document_id"],
            candidate_id,
        )
    )
    material_update = bool(candidate["material_update"])
    issue_number = int(conn.execute("SELECT COALESCE(MAX(issue_number),0)+1 AS n FROM issues").fetchone()["n"])
    run_date = str(data.get("run_date") or today_local())
    parse_date(run_date, "run_date")
    issue_id = f"BRP-{run_date[:4]}-{issue_number:03d}"
    companies = candidate_company_names(conn, candidate_id, "primary") + candidate_company_names(
        conn, candidate_id, "secondary"
    )
    theme_rows = conn.execute(
        "SELECT theme,is_primary FROM candidate_themes WHERE candidate_id=? ORDER BY is_primary DESC,theme",
        (candidate_id,),
    ).fetchall()
    themes = [str(row["theme"]) for row in theme_rows]
    primary_theme = next(str(row["theme"]) for row in theme_rows if row["is_primary"])
    previous = selected_candidates(conn, 100)
    primary_company = candidate_company_names(conn, candidate_id, "primary")[0]
    primary_company_family = company_family_ids_for_name(conn, primary_company)
    last_company = "never"
    last_theme = "never"
    for row in previous:
        previous_family = {
            company_id
            for role in ("primary", "secondary")
            for company_id in candidate_company_family_ids(conn, int(row["id"]), role)
        }
        if last_company == "never" and primary_company_family & previous_family:
            last_company = row["run_date"]
        if last_theme == "never" and normalize_name(primary_theme) == normalize_name(row["primary_theme"]):
            last_theme = row["run_date"]
    novelty_result = "Exception" if material_update else "Passed"
    content = render_prepare(
        issue_id,
        candidate,
        companies,
        themes,
        data,
        novelty_result,
        last_company,
        last_theme,
        duplicate_count,
    )
    chat_message = render_chat_message(issue_id, candidate, companies, data)
    _, _, packs = ensure_home(home)
    path = packs / f"{run_date}-{issue_id.lower()}-{slugify(candidate['title'])}.md"
    snapshot_path = version_path(path, 1, "prepare")
    digest = hashlib.sha256(content.encode()).hexdigest()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".pack-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        temp_path.chmod(0o600)
        with conn:
            conn.execute(
                """
                INSERT INTO issues(
                  id,issue_number,run_date,primary_candidate_id,primary_theme,status,
                  novelty_result,pack_path,pack_sha256,selected_at
                ) VALUES(?,?,?,?,?,'selected',?,?,?,?)
                """,
                (
                    issue_id,
                    issue_number,
                    run_date,
                    candidate_id,
                    primary_theme,
                    novelty_result,
                    str(path),
                    digest,
                    utc_now(),
                ),
            )
            conn.execute("UPDATE candidates SET status='selected' WHERE id=?", (candidate_id,))
            conn.executemany(
                """
                INSERT INTO vocabulary_evidence(issue_id,expression,source_context)
                VALUES(?,?,?)
                """,
                [(issue_id, expression, context) for expression, context in vocab_contexts],
            )
            conn.execute(
                """
                INSERT INTO pack_versions(issue_id,version,phase,path,sha256,created_at)
                VALUES(?,1,'prepare',?,?,?)
                """,
                (issue_id, str(snapshot_path), digest, utc_now()),
            )
            temp_path.replace(path)
            temp_path = None
            snapshot_path.write_text(content, encoding="utf-8")
            snapshot_path.chmod(0o600)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    return {
        "issue_id": issue_id,
        "status": "selected",
        "path": str(path),
        "sha256": digest,
        "chat_message": chat_message,
    }


def command_revise(
    conn: sqlite3.Connection, data: dict[str, Any], body: str | None
) -> dict[str, Any]:
    issue_id = require_string(data, "issue_id")
    issue = conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    if not issue:
        raise CuratorError(f"issue {issue_id} not found")
    if issue["status"] != "selected":
        raise CuratorError("only an incomplete selected issue can be revised")
    candidate_id = int(data.get("candidate_id", 0))
    if candidate_id != int(issue["primary_candidate_id"]):
        raise CuratorError("candidate_id does not match the issue")
    candidate = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    vocab_contexts = validate_pack_input(candidate, data, body)
    companies = candidate_company_names(conn, candidate_id, "primary") + candidate_company_names(
        conn, candidate_id, "secondary"
    )
    theme_rows = conn.execute(
        "SELECT theme,is_primary FROM candidate_themes WHERE candidate_id=? ORDER BY is_primary DESC,theme",
        (candidate_id,),
    ).fetchall()
    themes = [str(row["theme"]) for row in theme_rows]
    history = [
        row
        for row in selected_candidates(conn, 100)
        if int(row["id"]) != candidate_id
    ]
    primary_company = candidate_company_names(conn, candidate_id, "primary")[0]
    primary_company_family = company_family_ids_for_name(conn, primary_company)
    last_company = "never"
    last_theme = "never"
    for row in history:
        previous_family = {
            company_id
            for role in ("primary", "secondary")
            for company_id in candidate_company_family_ids(conn, int(row["id"]), role)
        }
        if last_company == "never" and primary_company_family & previous_family:
            last_company = row["run_date"]
        if (
            last_theme == "never"
            and normalize_name(issue["primary_theme"]) == normalize_name(row["primary_theme"])
        ):
            last_theme = row["run_date"]
    duplicate_count = len(
        find_duplicates(
            conn,
            candidate["canonical_url"],
            candidate["normalized_title"],
            candidate["text_sha256"],
            candidate["simhash"],
            candidate["embedding_model"],
            json.loads(candidate["embedding_json"]) if candidate["embedding_json"] else None,
            candidate["document_id"],
            candidate_id,
        )
    )
    content = render_prepare(
        issue_id,
        candidate,
        companies,
        themes,
        data,
        issue["novelty_result"],
        last_company,
        last_theme,
        duplicate_count,
    )
    chat_message = render_chat_message(issue_id, candidate, companies, data)
    path = Path(issue["pack_path"])
    version = int(
        conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 AS n FROM pack_versions WHERE issue_id=?",
            (issue_id,),
        ).fetchone()["n"]
    )
    snapshot_path = version_path(path, version, "prepare")
    digest = hashlib.sha256(content.encode()).hexdigest()
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".pack-", suffix=".tmp", delete=False
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        temp_path.chmod(0o600)
        with conn:
            conn.execute(
                "UPDATE issues SET pack_sha256=? WHERE id=?", (digest, issue_id)
            )
            conn.execute("DELETE FROM vocabulary_evidence WHERE issue_id=?", (issue_id,))
            conn.executemany(
                """
                INSERT INTO vocabulary_evidence(issue_id,expression,source_context)
                VALUES(?,?,?)
                """,
                [(issue_id, expression, context) for expression, context in vocab_contexts],
            )
            conn.execute(
                """
                INSERT INTO pack_versions(issue_id,version,phase,path,sha256,created_at)
                VALUES(?,?,'prepare',?,?,?)
                """,
                (issue_id, version, str(snapshot_path), digest, utc_now()),
            )
            temp_path.replace(path)
            temp_path = None
            snapshot_path.write_text(content, encoding="utf-8")
            snapshot_path.chmod(0o600)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    return {
        "issue_id": issue_id,
        "status": "selected",
        "version": version,
        "path": str(path),
        "sha256": digest,
        "chat_message": chat_message,
    }


def validate_complete(data: dict[str, Any]) -> None:
    synthesis = require_string(data, "synthesis")
    words = count_words(synthesis)
    if words > 250:
        raise CuratorError(f"synthesis must be no more than 250 English words; got {words}")
    rows = require_list(data.get("comparison"), "comparison")
    if not rows:
        raise CuratorError("comparison must contain at least one row")
    for row in rows:
        item = require_mapping(row, "comparison item")
        for key in ("claim_or_issue", "primary_source", "corroborating_source", "evidence_assessment"):
            require_string(item, key)
    for key in (
        "supported_by_both",
        "company_only",
        "independent_only",
        "factual_disagreements",
        "framing_differences",
        "unanswered_questions",
    ):
        require_list(data.get(key), key)
    citations = require_list(data.get("fact_citations"), "fact_citations")
    if not citations:
        raise CuratorError("fact_citations must contain at least one citation")
    for citation in citations:
        item = require_mapping(citation, "fact citation")
        require_string(item, "fact")
        canonicalize_url(require_string(item, "url"))


def command_complete(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    issue_id = require_string(data, "issue_id")
    issue = conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    if not issue:
        raise CuratorError(f"issue {issue_id} not found")
    if issue["status"] == "completed":
        raise CuratorError(f"issue {issue_id} is already completed")
    validate_complete(data)
    path = Path(issue["pack_path"])
    if not path.exists():
        raise CuratorError(f"pack file is missing: {path}")
    original = path.read_text(encoding="utf-8")
    lines = [
        original.rstrip(),
        "",
        "## Post-Reading Source Comparison / 读后来源比较",
        "",
        "> AI-generated reading guidance. Evidence quality is assessed without automatically declaring either source correct.",
        "",
        "| Claim or issue | Primary source | Corroborating source | Evidence assessment |",
        "|---|---|---|---|",
    ]
    for row in data["comparison"]:
        cells = [
            str(row[key]).replace("|", "\\|").replace("\n", " ")
            for key in ("claim_or_issue", "primary_source", "corroborating_source", "evidence_assessment")
        ]
        lines.append("| " + " | ".join(cells) + " |")
    sections = [
        ("Claims supported by both sources", "supported_by_both"),
        ("Claims supported only by the company", "company_only"),
        ("Claims supported only by the independent source", "independent_only"),
        ("Areas of factual disagreement", "factual_disagreements"),
        ("Differences in framing", "framing_differences"),
        ("Important unanswered questions", "unanswered_questions"),
    ]
    for heading, key in sections:
        lines.extend(["", f"### {heading}", ""])
        values = data[key]
        lines.extend(f"- {value}" for value in values) if values else lines.append("- None identified.")
    lines.extend(["", "### Short synthesis", "", data["synthesis"], "", "### Factual citations", ""])
    for citation in data["fact_citations"]:
        item = require_mapping(citation, "fact citation")
        lines.append(f"- {require_string(item, 'fact')} ([source]({canonicalize_url(require_string(item, 'url'))}))")
    content = "\n".join(lines) + "\n"
    digest = hashlib.sha256(content.encode()).hexdigest()
    version = int(
        conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 AS n FROM pack_versions WHERE issue_id=?",
            (issue_id,),
        ).fetchone()["n"]
    )
    snapshot_path = version_path(path, version, "complete")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".pack-", suffix=".tmp", delete=False
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        temp_path.chmod(0o600)
        with conn:
            conn.execute(
                "UPDATE issues SET status='completed',completed_at=?,pack_sha256=? WHERE id=?",
                (utc_now(), digest, issue_id),
            )
            conn.execute(
                "UPDATE candidates SET status='completed' WHERE id=?",
                (issue["primary_candidate_id"],),
            )
            conn.execute(
                """
                INSERT INTO pack_versions(issue_id,version,phase,path,sha256,created_at)
                VALUES(?,?,'complete',?,?,?)
                """,
                (issue_id, version, str(snapshot_path), digest, utc_now()),
            )
            temp_path.replace(path)
            temp_path = None
            snapshot_path.write_text(content, encoding="utf-8")
            snapshot_path.chmod(0o600)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    return {
        "issue_id": issue_id,
        "status": "completed",
        "version": version,
        "path": str(path),
        "sha256": digest,
    }


def command_history(conn: sqlite3.Connection, limit: int) -> dict[str, Any]:
    issues = conn.execute(
        """
        SELECT i.*,c.title,c.canonical_url,c.publication,c.industry,c.source_type,
               c.human_origin_confidence,c.advertising_risk,c.novelty_score
        FROM issues i JOIN candidates c ON c.id=i.primary_candidate_id
        ORDER BY i.issue_number DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=180)).replace(
        microsecond=0
    ).isoformat()
    rejected = conn.execute(
        """
        SELECT id,title,canonical_url,status,rejection_reason,review_after,reviewed_at
        FROM candidates WHERE status IN ('rejected','deferred')
          AND reviewed_at >= ?
        ORDER BY reviewed_at DESC
        """,
        (cutoff,),
    ).fetchall()
    return {
        "issues": [dict(row) for row in issues],
        "recent_rejected_or_deferred": [dict(row) for row in rejected],
    }


def command_state(conn: sqlite3.Connection) -> dict[str, Any]:
    recent = selected_candidates(conn, 20)
    total_selected = int(conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0])
    last_ten = recent[:10]
    bucket_counts = {bucket: 0 for bucket in INDUSTRY_BUCKETS}
    for row in last_ten:
        bucket = str(row["industry_bucket"])
        if bucket in bucket_counts:
            bucket_counts[bucket] += 1
    deficits = {
        bucket: max(0, target - bucket_counts[bucket])
        for bucket, target in INDUSTRY_BUCKETS.items()
    }
    suggested = sorted(
        INDUSTRY_BUCKETS,
        key=lambda bucket: (
            -(deficits[bucket] / INDUSTRY_BUCKETS[bucket]),
            list(INDUSTRY_BUCKETS).index(bucket),
        ),
    )
    company_cooldowns: list[dict[str, Any]] = []
    seen_companies: set[str] = set()
    for index, row in enumerate(recent[:8]):
        for role, window in (("primary", 8), ("secondary", 4)):
            if index >= window:
                continue
            for company in candidate_company_names(conn, int(row["id"]), role):
                normalized = normalize_name(company)
                if normalized in seen_companies:
                    continue
                seen_companies.add(normalized)
                company_cooldowns.append(
                    {
                        "company": company,
                        "last_role": role,
                        "last_issue": row["issue_number"],
                        "last_run_date": row["run_date"],
                        "issues_remaining": window - index - 1,
                    }
                )
    theme_counts_5: dict[str, int] = {}
    publication_counts_10: dict[str, int] = {}
    source_type_counts_6: dict[str, int] = {}
    author_counts_8: dict[str, int] = {}
    for index, row in enumerate(recent[:10]):
        if index < 5:
            theme_counts_5[row["primary_theme"]] = theme_counts_5.get(row["primary_theme"], 0) + 1
        publication_counts_10[row["publication"]] = (
            publication_counts_10.get(row["publication"], 0) + 1
        )
        if index < 6:
            source_type_counts_6[row["source_type"]] = (
                source_type_counts_6.get(row["source_type"], 0) + 1
            )
        if index < 8:
            for author in json.loads(row["author_json"]):
                author_counts_8[author] = author_counts_8.get(author, 0) + 1
    return {
        "selected_count": total_selected,
        "last_20": [
            {
                "issue_number": row["issue_number"],
                "run_date": row["run_date"],
                "title": row["title"],
                "industry_bucket": row["industry_bucket"],
                "primary_theme": row["primary_theme"],
                "publication": row["publication"],
                "source_type": row["source_type"],
                "source_position": row["source_position"],
            }
            for row in recent
        ],
        "rotation": {
            "target_over_ten": INDUSTRY_BUCKETS,
            "actual_last_ten": bucket_counts,
            "deficits": deficits,
            "suggested_search_order": suggested,
        },
        "cooldowns": {
            "companies": company_cooldowns,
            "themes_last_5": theme_counts_5,
            "publications_last_10": publication_counts_10,
            "source_types_last_6": source_type_counts_6,
            "authors_last_8": author_counts_8,
        },
    }


def command_shortlist(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT * FROM candidates WHERE status='shortlisted'
        ORDER BY (
          analytical_depth * 0.25 +
          evidence_quality * 0.25 +
          business_relevance * 0.20 +
          english_reading_value * 0.15 +
          novelty_score * 0.15
        ) DESC, reviewed_at DESC
        """
    ).fetchall()
    candidates = []
    for row in rows:
        novelty, _, defer_reasons, _, _ = current_candidate_novelty(conn, row)
        if defer_reasons:
            continue
        conn.execute(
            "UPDATE candidates SET novelty_score=? WHERE id=?", (novelty, row["id"])
        )
        composite = (
            row["analytical_depth"] * 0.25
            + row["evidence_quality"] * 0.25
            + row["business_relevance"] * 0.20
            + row["english_reading_value"] * 0.15
            + novelty * 0.15
        )
        candidates.append(
            {
                "candidate_id": row["id"],
                "title": row["title"],
                "canonical_url": row["canonical_url"],
                "publication": row["publication"],
                "industry": row["industry"],
                "industry_bucket": row["industry_bucket"],
                "source_type": row["source_type"],
                "source_position": row["source_position"],
                "human_origin_confidence": row["human_origin_confidence"],
                "advertising_risk": row["advertising_risk"],
                "novelty_score": novelty,
                "quality_score": round(composite, 2),
            }
        )
    conn.commit()
    candidates.sort(key=lambda item: (-item["quality_score"], item["candidate_id"]))
    return {"shortlisted": candidates}


def command_export(conn: sqlite3.Connection, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        """
        SELECT c.*,i.id AS issue_id,i.run_date,i.status AS issue_status,i.pack_path
        FROM candidates c LEFT JOIN issues i ON i.primary_candidate_id=c.id
        ORDER BY c.id
        """
    ).fetchall()
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            item = dict(row)
            for key in (
                "author_json",
                "origin_evidence_json",
                "advertising_evidence_json",
                "embedding_json",
            ):
                if item.get(key):
                    item[key.removesuffix("_json")] = json.loads(item.pop(key))
            item["companies"] = {
                "primary": candidate_company_names(conn, row["id"], "primary"),
                "secondary": candidate_company_names(conn, row["id"], "secondary"),
            }
            item["themes"] = [
                dict(theme)
                for theme in conn.execute(
                    "SELECT theme,is_primary FROM candidate_themes WHERE candidate_id=?",
                    (row["id"],),
                ).fetchall()
            ]
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    output.chmod(0o600)
    return {"path": str(output), "records": len(rows)}


def command_alias(conn: sqlite3.Connection, canonical: str, alias: str, parent: str | None) -> dict[str, Any]:
    with conn:
        company_id = get_or_create_company(conn, canonical)
        if parent:
            parent_id = get_or_create_company(conn, parent)
            conn.execute("UPDATE companies SET parent_company_id=? WHERE id=?", (parent_id, company_id))
        normalized_alias = normalize_name(alias)
        existing = conn.execute(
            "SELECT company_id FROM company_aliases WHERE normalized_alias=?", (normalized_alias,)
        ).fetchone()
        if existing and int(existing["company_id"]) != company_id:
            raise CuratorError("alias already belongs to another company")
        previous_company_id = int(existing["company_id"]) if existing else None
        conn.execute(
            """
            INSERT OR REPLACE INTO company_aliases(
              normalized_alias,alias,company_id,source,created_at
            ) VALUES(?,?,?,'manual',?)
            """,
            (normalized_alias, alias, company_id, utc_now()),
        )
        conn.execute(
            """
            INSERT INTO company_alias_audit(
              alias,normalized_alias,previous_company_id,new_company_id,action,created_at
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                alias,
                normalized_alias,
                previous_company_id,
                company_id,
                "set_alias_and_parent" if parent else "set_alias",
                utc_now(),
            ),
        )
        conn.execute(
            """
            UPDATE company_alias_suggestions
            SET status='accepted',resolved_at=?
            WHERE normalized_alias=? AND status='pending'
            """,
            (utc_now(), normalized_alias),
        )
    return {"canonical": canonical, "alias": alias, "company_id": company_id}


def command_alias_suggest(
    conn: sqlite3.Connection, alias: str, possible_canonical: str | None, reason: str
) -> dict[str, Any]:
    normalized_alias = normalize_name(alias)
    company_id = (
        get_or_create_company(conn, possible_canonical) if possible_canonical else None
    )
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO company_alias_suggestions(
              normalized_alias,alias,possible_company_id,reason,status,created_at,resolved_at
            ) VALUES(?,?,?,?,'pending',?,NULL)
            """,
            (normalized_alias, alias, company_id, reason, utc_now()),
        )
    return {
        "alias": alias,
        "possible_canonical": possible_canonical,
        "status": "pending",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        type=Path,
        default=Path(os.getenv("BUSINESS_READING_HOME", str(DEFAULT_HOME))).expanduser(),
        help="runtime data directory",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="initialize config and SQLite registry")
    assess = sub.add_parser("assess", help="assess and persist one candidate")
    assess.add_argument("--candidate", required=True, help="candidate JSON path")
    assess.add_argument("--body-file", help="UTF-8 article body path; use - for stdin")
    assess.add_argument(
        "--strict-embedding",
        action="store_true",
        help="fail instead of degrading when the embedding API is unavailable",
    )
    prepare = sub.add_parser("prepare", help="render and select a spoiler-free reading pack")
    prepare.add_argument("--input", required=True, help="prepare JSON path")
    prepare.add_argument("--body-file", required=True, help="temporary UTF-8 source body")
    revise = sub.add_parser("revise", help="revise an incomplete pack without selecting again")
    revise.add_argument("--input", required=True, help="revision JSON path")
    revise.add_argument("--body-file", required=True, help="temporary UTF-8 source body")
    complete = sub.add_parser("complete", help="append post-reading comparison and synthesis")
    complete.add_argument("--input", required=True, help="completion JSON path")
    history = sub.add_parser("history", help="show selected history and recent rejected candidates")
    history.add_argument("--limit", type=int, default=20)
    sub.add_parser("state", help="show rotation deficits and active cooldowns")
    sub.add_parser("shortlist", help="rank currently shortlisted candidates")
    export = sub.add_parser("export", help="export the registry as read-only JSON Lines")
    export.add_argument("--output", type=Path, required=True)
    alias = sub.add_parser("alias", help="add an audited company alias")
    alias.add_argument("--canonical", required=True)
    alias.add_argument("--alias", required=True)
    alias.add_argument("--parent")
    alias_suggest = sub.add_parser(
        "alias-suggest", help="record an uncertain alias without merging companies"
    )
    alias_suggest.add_argument("--alias", required=True)
    alias_suggest.add_argument("--possible-canonical")
    alias_suggest.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        conn = connect(args.home)
        with contextlib.closing(conn):
            if args.command == "init":
                db_path, config_path, packs = ensure_home(args.home)
                emit(
                    {
                        "status": "ok",
                        "database": str(db_path),
                        "config": str(config_path),
                        "packs": str(packs),
                    }
                )
            elif args.command == "assess":
                data = load_json(args.candidate)
                body = load_body(args.body_file)
                emit(
                    assess_candidate(
                        conn,
                        data,
                        body,
                        load_config(args.home),
                        args.strict_embedding,
                    )
                )
            elif args.command == "prepare":
                emit(
                    command_prepare(
                        conn, args.home, load_json(args.input), load_body(args.body_file)
                    )
                )
            elif args.command == "revise":
                emit(
                    command_revise(
                        conn, load_json(args.input), load_body(args.body_file)
                    )
                )
            elif args.command == "complete":
                emit(command_complete(conn, load_json(args.input)))
            elif args.command == "history":
                emit(command_history(conn, args.limit))
            elif args.command == "state":
                emit(command_state(conn))
            elif args.command == "shortlist":
                emit(command_shortlist(conn))
            elif args.command == "export":
                emit(command_export(conn, args.output))
            elif args.command == "alias":
                emit(command_alias(conn, args.canonical, args.alias, args.parent))
            elif args.command == "alias-suggest":
                emit(
                    command_alias_suggest(
                        conn, args.alias, args.possible_canonical, args.reason
                    )
                )
            else:
                raise CuratorError(f"unsupported command: {args.command}")
        return 0
    except (CuratorError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
