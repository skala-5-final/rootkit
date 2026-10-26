import json
import re
from collections import Counter
from rookit.data import Dataset, ROOT


def test_expanded_dataset_integrity():
    data = Dataset()
    manifest = json.loads((ROOT / 'data/mock-data-english/manifest.json').read_text())
    assert manifest['counts'] == {'challenges': len(data.challenges), 'answer_keys': len(data.keys),
                                  'teaching_references': len(data.references), 'evaluation_cases': len(data.cases)}
    assert len(data.challenges) >= 300
    assert Counter(c['exercise_type'] for c in data.challenges.values()) == {'rewrite': 150, 'compose': 150}
    assert len({c['scenario'] for c in data.challenges.values()}) == 150
    assert len({c['id'] for c in data.cases}) == len(data.cases)
    assert Counter(c['challenge_id'] for c in data.cases) == {cid: 2 for cid in data.challenges}
    for cid, challenge in data.challenges.items():
        assert challenge['language'] == 'en'
        assert challenge['instruction_language'] == 'ko'
        fields = [challenge[k] for k in ('title', 'scenario', 'instructions', 'hint', 'scenario_label')]
        fields += [challenge['recipient']['relationship']] + [r['description'] for r in challenge['requirements']]
        assert all(re.search('[가-힣]', text) for text in fields), cid
        if challenge['starter_email']:
            assert not re.search('[가-힣]', challenge['starter_email']['body'])
        requirements = {r['id'] for r in challenge['requirements']}
        assert len(requirements) == len(challenge['requirements'])
        assert all(r['critical'] for r in challenge['requirements'])
        assert bool(challenge['starter_email']) == (challenge['exercise_type'] == 'rewrite')
        cases = [c for c in data.cases if c['challenge_id'] == cid]
        assert {c['expected']['complete'] for c in cases} == {True, False}
        for case in cases:
            missing = set(case['expected']['unmet_requirement_ids'])
            assert missing <= requirements
            assert bool(missing) != case['expected']['complete']
            assert 0 < len(case['learner_answer']['subject']) <= 200
            assert 0 < len(case['learner_answer']['body']) <= 10000
        valid = next(c for c in cases if c['expected']['complete'])
        flawed = next(c for c in cases if not c['expected']['complete'])
        assert valid['learner_answer'] in data.keys[cid]['sample_answers']
        assert valid['learner_answer'] != flawed['learner_answer']
        if int(cid.split('_')[1]) >= 7:
            omitted = flawed['expected']['feedback_must_mention'][0]
            assert omitted in valid['learner_answer']['body']
            assert omitted not in flawed['learner_answer']['body']
            assert flawed['learner_answer']['subject'] == 'Follow-up'
