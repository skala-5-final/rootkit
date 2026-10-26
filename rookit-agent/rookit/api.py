import os
from typing import Literal
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from .agent import InvalidAssessment, WritingCoach
from .data import Dataset, ROOT
from .providers import CoachUnavailable, FixtureReplayCoach, OpenAICoach
from .schemas import Submission
from .storage import Store


def create_app(mode=None, db_path=None, provider=None):
    mode = mode or os.getenv('ROOKIT_MODE', 'live')
    if mode not in ('live', 'replay'):
        raise ValueError('ROOKIT_MODE must be live or replay')
    dataset = Dataset()
    store = Store(db_path or os.getenv('ROOKIT_DB_PATH', str(ROOT / 'runtime' / 'attempts.sqlite3')))
    provider = provider or (FixtureReplayCoach(dataset) if mode == 'replay' else OpenAICoach())
    coach = WritingCoach(dataset, provider, store, mode)
    app = FastAPI(title='Rookit Writing Coach', version='0.1.0')
    auth = HTTPBearer(auto_error=False)

    def session(credentials: HTTPAuthorizationCredentials | None = Depends(auth)):
        if not credentials or not store.exists(credentials.credentials):
            raise HTTPException(401, 'Create a session and provide its bearer token.')
        return credentials.credentials

    def challenge(cid):
        try:
            return dataset.get_challenge(cid)
        except KeyError:
            raise HTTPException(404, 'Unknown challenge') from None

    @app.get('/health')
    def health():
        return {'status': 'ok', 'mode': mode,
                'model_configured': bool(os.getenv('OPENAI_API_KEY') and os.getenv('OPENAI_MODEL'))}

    @app.post('/sessions', status_code=201)
    def new_session():
        return {'token': store.new_session(), 'token_type': 'bearer'}

    @app.get('/challenges')
    def challenges(language: Literal['en'] = Query('en')):
        return [dataset.get_challenge(cid) for cid, c in dataset.challenges.items() if c['language'] == language]

    @app.get('/challenges/{challenge_id}')
    def get_challenge(challenge_id: str):
        return challenge(challenge_id)

    @app.get('/challenges/{challenge_id}/hint')
    def hint(challenge_id: str):
        c = challenge(challenge_id)
        return {'challenge_id': challenge_id, 'hint': c['hint']}

    @app.post('/challenges/{challenge_id}/attempts')
    def submit(challenge_id: str, answer: Submission, token: str = Depends(session)):
        challenge(challenge_id)
        try:
            return coach.submit(token, challenge_id, answer.model_dump())
        except CoachUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except (InvalidAssessment, ValidationError):
            raise HTTPException(502, 'Invalid model assessment; no attempt was saved. Please retry.') from None

    @app.get('/challenges/{challenge_id}/attempts')
    def attempts(challenge_id: str, token: str = Depends(session)):
        challenge(challenge_id)
        return store.history(token, challenge_id)

    return app
