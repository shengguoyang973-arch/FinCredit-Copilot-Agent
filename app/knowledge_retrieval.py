from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain import PolicyClause


@dataclass(frozen=True)
class PolicyHit:
    policy: PolicyClause
    score: float
    matched_terms: tuple[str, ...]
    citation: str


def retrieve_policy_hits(query: str, policies: list[PolicyClause], limit: int = 10) -> list[PolicyHit]:
    terms = _terms(query)
    if not terms:
        return []
    hits: list[PolicyHit] = []
    for policy in policies:
        title = set(_terms(policy.title))
        keywords = set(_terms(" ".join(policy.keywords)))
        content = set(_terms(policy.content))
        matched = sorted(terms & (title | keywords | content))
        if not matched:
            continue
        score = sum(4 for term in matched if term in title)
        score += sum(3 for term in matched if term in keywords)
        score += sum(1 for term in matched if term in content)
        hits.append(PolicyHit(policy, float(score), tuple(matched), f"{policy.id}（版本 {policy.version}）"))
    return sorted(hits, key=lambda hit: (-hit.score, hit.policy.id))[:limit]


def chunk_policy(policy: PolicyClause, max_chars: int = 180) -> list[dict]:
    """Create stable, citation-bearing chunks before a vector adapter is added."""
    paragraphs = [part.strip() for part in re.split(r"[。；\n]", policy.content) if part.strip()]
    chunks: list[dict] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 1 > max_chars:
            chunks.append(_chunk(policy, len(chunks) + 1, current))
            current = ""
        current = f"{current}；{paragraph}" if current else paragraph
    if current:
        chunks.append(_chunk(policy, len(chunks) + 1, current))
    return chunks


def _chunk(policy: PolicyClause, index: int, text: str) -> dict:
    return {
        "id": f"{policy.id}#chunk-{index}",
        "policy_id": policy.id,
        "version": policy.version,
        "text": text,
        "citation": f"{policy.id}（版本 {policy.version}，片段 {index}）",
    }


def _terms(text: str) -> set[str]:
    normalized = text.lower().replace("，", " ").replace("。", " ")
    words = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", normalized))
    words.update(token for token in re.findall(r"[a-z0-9]{2,}", normalized) if token)
    return {word for word in words if word.strip()}
