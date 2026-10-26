"""Run against local Docker services: .venv/bin/python tests/check_web_integration.py."""
import json
from pathlib import Path
import httpx

base = 'http://localhost:3000'
cases = json.loads((Path(__file__).resolve().parents[1] / 'data/mock-data-english/evaluation_cases.json').read_text())
cid = 'en_001_compose'
flawed = next(c for c in cases if c['challenge_id'] == cid and not c['expected']['complete'])
complete = next(c for c in cases if c['challenge_id'] == cid and c['expected']['complete'])
with httpx.Client(base_url=base, timeout=120) as client:
    assert client.get('/api/agent/challenges').status_code == 401
    assert client.post('/api/agent/evaluations', json={}).status_code == 401
    assert client.post('/api/auth/login', json={'loginId': 'rookie', 'password': 'rootkit1234'}).status_code == 200
    catalogue = client.get('/api/agent/challenges')
    assert catalogue.status_code == 200, catalogue.text
    data = catalogue.json()
    assert data['mode'] == 'replay'
    assert len(data['exercises']) >= 300
    assert {e['stage'] for e in data['exercises']} == {1, 2}
    assert client.post('/api/agent/evaluations', json={'exerciseId': '../../sessions'}).status_code == 422
    assert client.post('/api/agent/evaluations', content='{').status_code == 422
    for case in (flawed, complete):
        response = client.post('/api/agent/evaluations', json={'exerciseId': cid, 'answer': case['learner_answer']})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['mode'] == 'replay'
        assert result['complete'] == case['expected']['complete']
        assert len(result['checks']) == 4
    assert any(f.startswith('개선됨:') for f in result['feedback']), result
    assert 'HttpOnly' in response.headers['set-cookie']
    for kind in ('rewrite', 'compose'):
        new_case = next(c for c in cases if c['challenge_id'] == f'en_150_{kind}' and c['expected']['complete'])
        response = client.post('/api/agent/evaluations', json={'exerciseId': new_case['challenge_id'], 'answer': new_case['learner_answer']})
        assert response.status_code == 200 and response.json()['complete'], response.text
    response = client.post('/api/agent/evaluations', json={'exerciseId': cid, 'answer': {'subject': 'New', 'body': 'Arbitrary writing.'}})
    assert response.status_code == 503 and 'replay' in response.json()['error']
    response = client.post('/api/demo/evaluations', json={'exerciseId': 'b-sales-report', 'blankMode': 'choice', 'answer': {'subject': 'Request', 'body': '', 'blanks': ['Could you please', 'by', 'Please let me know']}})
    assert response.status_code == 200 and response.json()['total'] == 100
    assert client.post('/api/auth/logout').status_code == 200
    assert 'rootkit_agent' not in client.cookies
    assert client.post('/api/auth/login', json={'loginId': 'rookie', 'password': 'rootkit1234'}).status_code == 200
    response = client.post('/api/agent/evaluations', json={'exerciseId': cid, 'answer': complete['learner_answer']})
    assert response.status_code == 200
    assert not any(f.startswith('개선됨:') for f in response.json()['feedback'])
print('PASS: auth, catalogue, validation, grading, revision session, replay errors, blanks, logout isolation')
