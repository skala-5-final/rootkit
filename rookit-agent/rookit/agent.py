from .schemas import Assessment


class InvalidAssessment(Exception):
    pass


def finalize(assessment, challenge, key, answer, previous=None):
    a = Assessment.model_validate(assessment) if isinstance(assessment, dict) else assessment
    requirements = {r['id']: r for r in challenge['requirements']}
    checks = a.requirement_checks
    ids = [c.requirement_id for c in checks]
    if len(ids) != len(set(ids)) or set(ids) != set(requirements):
        raise InvalidAssessment('Model must check every requirement exactly once')
    allowed_refs = set(key['reference_ids'])
    if not set(a.reference_ids) <= allowed_refs:
        raise InvalidAssessment('Unknown reference ID')
    def quoted(text):
        return bool(text and text.strip()) and (text in answer['subject'] or text in answer['body'])
    for c in checks:
        if c.met and not quoted(c.evidence):
            raise InvalidAssessment('Met requirement needs exact learner evidence')
        if c.evidence is not None and not quoted(c.evidence):
            raise InvalidAssessment('Fabricated learner evidence')
    for i in a.issues:
        if i.requirement_id is not None and i.requirement_id not in requirements:
            raise InvalidAssessment('Unknown issue requirement')
        if i.learner_excerpt is not None and not quoted(i.learner_excerpt):
            raise InvalidAssessment('Fabricated issue excerpt')
    for c in a.contradictions:
        if not quoted(c.learner_excerpt):
            raise InvalidAssessment('Fabricated contradiction excerpt')
    unmet = {c.requirement_id for c in checks if not c.met}
    if not unmet <= {i.requirement_id for i in a.issues}:
        raise InvalidAssessment('Missing revision guidance for unmet requirements')
    scores = a.scores.model_dump()
    total = sum(scores.values())
    policy = key['completion_policy']
    critical_missing = any(requirements[c]['critical'] for c in unmet)
    complete = (total >= policy['minimum_total_score']
                and (not policy['all_critical_requirements_must_be_met'] or not critical_missing)
                and (not policy['no_contradicted_facts'] or not a.contradictions))
    result = a.model_dump()
    result.update(challenge_id=challenge['id'], complete=complete, scores={**scores, 'total': total})
    previous_checks = {c['requirement_id']: c['met'] for c in (previous or {}).get('requirement_checks', [])}
    result['revision'] = {
        'resolved_requirement_ids': [c.requirement_id for c in checks if c.met and previous_checks.get(c.requirement_id) is False],
        'regressed_requirement_ids': [c.requirement_id for c in checks if not c.met and previous_checks.get(c.requirement_id) is True],
    }
    return result


class WritingCoach:
    def __init__(self, dataset, provider, store, mode):
        self.dataset, self.provider, self.store, self.mode = dataset, provider, store, mode

    def submit(self, token, challenge_id, answer):
        challenge = self.dataset.get_challenge(challenge_id)
        key = self.dataset.get_answer_key(challenge_id)
        history = self.store.history(token, challenge_id, limit=3)
        context = {'challenge': challenge, 'answer_key': key,
                   'references': self.dataset.get_references(key['reference_ids']),
                   'learner_answer': answer, 'previous_attempts': history}
        assessment = self.provider.assess(context)
        feedback = finalize(assessment, challenge, key, answer,
                            history[-1]['feedback'] if history else None)
        feedback['mode'] = self.mode
        aid = self.store.save(token, challenge_id, answer, feedback)
        return {'attempt_id': aid, 'feedback': feedback}
