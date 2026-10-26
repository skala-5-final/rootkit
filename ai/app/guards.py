"""작성: rootkit · 2026-10-23. Deterministic evidence and conditional feedback checks."""

from .models import (EvaluationProposal, ExerciseDraft, FactsReview, Feedback,
                     SemanticReview)


def exercise_errors(exercise: ExerciseDraft, documents: list[dict], knowledge: dict) -> list[str]:
    sources = {document["id"]: document for document in documents}
    terms = {term["id"]: term for term in knowledge.get("terms", []) if term.get("approved")}
    patterns = {pattern["id"]: pattern for pattern in knowledge.get("patterns", [])}
    facts = {fact.id: fact for fact in exercise.facts}
    errors = []
    if not set(exercise.source_ids) <= sources.keys():
        errors.append("Exercise references sources outside its dataset revision")
    for fact in exercise.facts:
        if fact.origin == "source":
            if (not fact.source_ids or not set(fact.source_ids) <= set(exercise.source_ids)
                    or not set(fact.source_ids) <= sources.keys()):
                errors.append(f"Source fact {fact.id} has missing or unrelated evidence")
            elif any(fact.value not in sources[source_id]["body"] for source_id in fact.source_ids):
                errors.append(f"Source fact {fact.id} value is absent from source body")
        elif fact.source_ids:
            errors.append(f"Practice fact {fact.id} cannot claim historical source evidence")
    for criterion in exercise.criteria:
        prefix = f"Criterion {criterion.criterion_id}: "
        if not set(criterion.fact_ids) <= facts.keys():
            errors.append(prefix + "unknown/undisclosed fact")
        if any(index < 0 or index >= len(exercise.requirements) for index in criterion.requirement_indexes):
            errors.append(prefix + "unknown/undisclosed requirement")
        if not set(criterion.evidence_ids) <= sources.keys():
            errors.append(prefix + "unknown source evidence")
        if criterion.category == "company":
            if criterion.kind == "term":
                term = terms.get(criterion.term_id)
                if not term:
                    errors.append(prefix + "term has not been human-approved for this dataset version")
                elif not criterion.evidence_ids or not set(criterion.evidence_ids) <= {
                    evidence["source_id"] for evidence in term["evidence"]
                }:
                    errors.append(prefix + "term evidence does not support this rule")
            elif criterion.kind == "pattern":
                pattern = patterns.get(criterion.pattern_id)
                if not pattern:
                    errors.append(prefix + "composition pattern is unsupported or withheld")
                elif (pattern["recipient_group"], pattern["language"], pattern["situation"]) != (
                    exercise.recipient_group, exercise.language, exercise.situation
                ):
                    errors.append(prefix + "pattern is not applicable to this exercise")
                elif not criterion.evidence_ids or not set(criterion.evidence_ids) <= {
                    observation["source_id"] for observation in pattern["observations"]
                }:
                    errors.append(prefix + "pattern evidence does not support this rule")
            else:
                errors.append(prefix + "company criteria must derive from approved terms or supported patterns")
        elif criterion.category == "task":
            if criterion.kind not in {"fact", "requirement"} or not (criterion.fact_ids or criterion.requirement_indexes):
                errors.append(prefix + "task criteria must reference disclosed facts or requirements")
            if criterion.term_id or criterion.pattern_id:
                errors.append(prefix + "company rules cannot be hidden in task criteria")
        elif criterion.kind != "general" or criterion.evidence_ids or criterion.term_id or criterion.pattern_id:
            errors.append(prefix + "general advice must not claim company evidence")
    return errors


def validate_decisions(exercise: dict, proposal: EvaluationProposal) -> list[str]:
    criteria = {criterion["criterion_id"]: criterion for criterion in exercise["criteria"]}
    ids = [decision.criterion_id for decision in proposal.decisions]
    errors = []
    if len(ids) != len(set(ids)) or set(ids) != set(criteria):
        return [f"Evaluation must contain exactly one decision for every pinned criterion; expected={sorted(criteria)}, received={ids}"]
    for decision in proposal.decisions:
        criterion = criteria[decision.criterion_id]
        if not set(decision.evidence_ids) <= set(criterion["evidence_ids"]):
            errors.append("Evaluation cites evidence not allowed by its pinned criterion")
        if decision.applies and (not decision.explanation.strip() or not decision.suggestion.strip()):
            errors.append("Applicable feedback requires a concrete explanation and suggestion")
        if decision.applies and criterion["category"] == "company" and not decision.evidence_ids:
            errors.append("Company feedback requires company evidence")
    return errors


def emitted_feedback(exercise: dict, proposal: EvaluationProposal) -> list[Feedback]:
    criteria = {criterion["criterion_id"]: criterion for criterion in exercise["criteria"]}
    feedback = [
        Feedback(criterion_id=decision.criterion_id,
                 category=criteria[decision.criterion_id]["category"],
                 explanation=decision.explanation, suggestion=decision.suggestion,
                 evidence_ids=decision.evidence_ids)
        for decision in proposal.decisions if decision.applies
    ]
    feedback.extend(
        Feedback(criterion_id=f"general-advice-{index}", category="general",
                 explanation=advice.explanation,
                 suggestion=advice.suggestion, evidence_ids=[])
        for index, advice in enumerate(proposal.general_feedback, 1)
    )
    for item in feedback:
        if item.category == "general" and not item.explanation.startswith("일반 조언:"):
            item.explanation = "일반 조언: " + item.explanation
    return feedback


def feedback_review_errors(proposal: EvaluationProposal, semantics: SemanticReview,
                           facts: FactsReview, feedback: list[Feedback], answer: dict | None = None) -> list[str]:
    errors = []
    if not semantics.passed:
        errors.extend(semantics.reasons or ["Feedback semantic review rejected the proposal"])
    if not facts.passed:
        errors.extend(facts.reasons or ["Feedback suggestion fact review rejected the proposal"])
    proposed = {decision.criterion_id: decision for decision in proposal.decisions}
    ids = [decision.criterion_id for decision in semantics.decisions]
    if len(ids) != len(set(ids)) or set(ids) != set(proposed):
        errors.append(f"Semantic review did not cover every criterion exactly once; expected={sorted(proposed)}, received={ids}")
    for decision in semantics.decisions:
        if (answer is not None and decision.answer_evidence
                and not any(decision.answer_evidence in answer.get(field, "") for field in ("subject", "body"))):
            errors.append(f"Semantic review cites text absent from the submitted answer: {decision.criterion_id}")
        original = proposed.get(decision.criterion_id)
        if not original or decision.applies != original.applies or not decision.semantic_equivalent:
            errors.append(f"Feedback applicability/meaning mismatch: {decision.criterion_id}")
    expected = {item.criterion_id for item in feedback}
    if len(facts.checked_feedback_ids) != len(set(facts.checked_feedback_ids)) or set(facts.checked_feedback_ids) != expected:
        errors.append(f"Fact review did not cover every emitted suggestion exactly once; expected={sorted(expected)}, received={facts.checked_feedback_ids}")
    return errors
