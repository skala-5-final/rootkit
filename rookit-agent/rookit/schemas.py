from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Submission(StrictModel):
    subject: str = Field(min_length=1, max_length=250)
    body: str = Field(min_length=1, max_length=10000)

    @field_validator('subject', 'body')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Must contain text')
        return value.strip()


class Scores(StrictModel):
    content: int = Field(ge=0, le=40)
    tone: int = Field(ge=0, le=25)
    structure: int = Field(ge=0, le=20)
    language: int = Field(ge=0, le=15)


class RequirementCheck(StrictModel):
    requirement_id: str
    met: bool
    evidence: str | None


class Issue(StrictModel):
    category: Literal['content', 'tone', 'structure', 'language']
    severity: Literal['critical', 'minor']
    requirement_id: str | None
    learner_excerpt: str | None
    explanation: str
    revision_hint: str


class Contradiction(StrictModel):
    learner_excerpt: str
    explanation: str


class Assessment(StrictModel):
    scores: Scores
    requirement_checks: list[RequirementCheck]
    strengths: list[str]
    issues: list[Issue]
    contradictions: list[Contradiction]
    reference_ids: list[str]
