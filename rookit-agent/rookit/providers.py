import json
import os
from openai import OpenAI, OpenAIError
from .prompts import COACH_PROMPT
from .schemas import Assessment


class CoachUnavailable(Exception):
    pass


class OpenAICoach:
    def assess(self, context):
        model = os.getenv('OPENAI_MODEL')
        if not os.getenv('OPENAI_API_KEY') or not model:
            raise CoachUnavailable('Set OPENAI_API_KEY and OPENAI_MODEL on the server.')
        try:
            with OpenAI(timeout=45, max_retries=1) as client:
                response = client.responses.parse(
                    model=model,
                    store=False,
                    input=[{'role': 'system', 'content': COACH_PROMPT},
                           {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}],
                    text_format=Assessment,
                )
            if response.output_parsed is None:
                raise CoachUnavailable('The model refused or returned no assessment. Try again.')
            return response.output_parsed
        except OpenAIError as exc:
            raise CoachUnavailable('The model request failed. Check server configuration or retry.') from exc


class FixtureReplayCoach:
    """Offline wiring demo: replays known dataset cases; never grades arbitrary text."""
    def __init__(self, dataset):
        self.dataset = dataset

    def assess(self, context):
        cid = context['challenge']['id']
        answer = context['learner_answer']
        case = next((c for c in self.dataset.cases
                     if c['challenge_id'] == cid and c['learner_answer'] == answer), None)
        if case is None:
            raise CoachUnavailable('Replay mode only accepts exact evaluation-case answers. Use live mode for your own writing.')
        missing = set(case['expected']['unmet_requirement_ids'])
        reqs = context['challenge']['requirements']
        # shortcut: fixture scores demonstrate plumbing only, use live evaluation for quality measurement.
        return Assessment.model_validate({
            'scores': {'content': round(40 * (len(reqs)-len(missing))/len(reqs)),
                       'tone': 25, 'structure': 20, 'language': 15},
            'requirement_checks': [{'requirement_id': r['id'], 'met': r['id'] not in missing,
                                   'evidence': answer['body'] if r['id'] not in missing else None}
                                  for r in reqs],
            'strengths': [],
            'issues': [{'category': 'content', 'severity': 'critical', 'requirement_id': r['id'],
                        'learner_excerpt': None,
                        'explanation': 'Check this required information.',
                        'revision_hint': r['description']} for r in reqs if r['id'] in missing],
            'contradictions': [],
            'reference_ids': context['answer_key']['reference_ids'],
        })
