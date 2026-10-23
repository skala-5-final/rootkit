"""작성: rootkit · 2026-10-23. JSONL normalization, source evidence and pattern eligibility."""

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from .errors import DomainError
from .models import Document, KnowledgeProposal


def read_jsonl(path: str | Path) -> list[Document]:
    path = Path(path)
    if path.suffix.lower() != ".jsonl":
        raise DomainError("Only UTF-8 .jsonl documents are supported")
    documents = []
    try:
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                documents.append(Document.model_validate(json.loads(line)))
            except (ValueError, ValidationError) as exc:
                raise DomainError(f"Invalid JSONL line {number}: {exc}") from exc
    except (OSError, UnicodeError) as exc:
        raise DomainError(f"Cannot read UTF-8 JSONL file: {path.name}") from exc
    validate_documents(documents)
    return documents


def validate_documents(documents: list[Document]):
    if not documents:
        raise DomainError("Dataset must contain at least one document")
    if len({document.id for document in documents}) != len(documents):
        raise DomainError("Duplicate document IDs are not allowed")


def validate_knowledge(proposal: KnowledgeProposal, documents: list[Document]) -> dict:
    sources = {document.id: document for document in documents}
    terms, patterns, withheld = [], [], []
    if len({term.id for term in proposal.terms}) != len(proposal.terms):
        raise DomainError("Term candidate IDs must be unique")
    if len({pattern.id for pattern in proposal.patterns}) != len(proposal.patterns):
        raise DomainError("Pattern IDs must be unique")
    for term in proposal.terms:
        errors = []
        for evidence in term.evidence:
            source = sources.get(evidence.source_id)
            if not source or evidence.quote not in source.body:
                errors.append("Term quote does not exist in the source body")
            elif term.term not in evidence.quote:
                errors.append("Term itself is absent from quoted evidence")
        if errors:
            withheld.append({"kind": "term", "id": term.id, "reasons": errors})
        else:
            terms.append({**term.model_dump(), "approved": False, "approved_aliases": []})
    for pattern in proposal.patterns:
        errors, cases, bodies, observed_ids = [], set(), set(), set()
        for observation in pattern.observations:
            source = sources.get(observation.source_id)
            if not source:
                errors.append("Pattern references an unknown document")
                continue
            if source.id in observed_ids:
                errors.append("Repeated source is not an independent observation")
            observed_ids.add(source.id)
            if source.kind != "email":
                errors.append("Only complete emails can support composition patterns")
            if (source.recipient_group, source.language, source.situation) != (
                pattern.recipient_group, pattern.language, pattern.situation
            ):
                errors.append("Pattern metadata must match group, language and situation")
            labels = [section.label for section in observation.sections]
            if labels != pattern.sequence:
                errors.append("Conflicting section order: withhold this pattern")
            position = 0
            for section in observation.sections:
                found = source.body.find(section.quote, position)
                if found < 0:
                    errors.append("Pattern section quote is missing or out of order")
                    break
                position = found + len(section.quote)
            cases.add(source.case_id)
            bodies.add(hashlib.sha256(" ".join(source.body.split()).encode()).hexdigest())
        if min(len(cases), len(bodies), len(observed_ids)) < 3:
            errors.append("At least 3 independent relevant emails are required")
        if errors:
            withheld.append({"kind": "pattern", "id": pattern.id, "reasons": sorted(set(errors))})
        else:
            patterns.append(pattern.model_dump())
    # Competing proposals for the same situation are evidence of conflict, not a vote.
    conflicts = set()
    for left in proposal.patterns:
        for right in proposal.patterns:
            if left.id != right.id and (left.recipient_group, left.language, left.situation) == (
                right.recipient_group, right.language, right.situation
            ) and left.sequence != right.sequence:
                conflicts.update([left.id, right.id])
    for pattern in patterns[:]:
        if pattern["id"] in conflicts:
            patterns.remove(pattern)
            withheld.append({"kind": "pattern", "id": pattern["id"], "reasons": ["Conflicting composition patterns in this situation"]})
    return {"terms": terms, "patterns": patterns, "withheld": withheld}


def approved_knowledge(knowledge: dict) -> dict:
    return {
        "terms": [term for term in knowledge.get("terms", []) if term.get("approved")],
        "patterns": knowledge.get("patterns", []),
    }


def retrieve(documents: list[dict], source_ids: list[str]) -> list[dict]:
    """Exact-source retrieval preserves full emails and paragraph order."""
    wanted = set(source_ids)
    return [document for document in documents if document["id"] in wanted]
