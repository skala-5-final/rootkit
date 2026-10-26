# Rookit English mock data

300 challenges: 150 business scenarios across 18 scenario families, each with a rewrite exercise and a full composition exercise. Question titles, scenarios, instructions, requirements, hints and recipient relationships are in Korean. Learners write emails in English; starter emails and server-side sample answers remain in English. People, situations, and commitments are fictional. These AI-generated materials need human review before being treated as educational ground truth.

## Files

- `challenges.json`: learner-facing scenarios, required facts, hints, and starter drafts.
- `answer_keys.json`: server-side sample answers, weighted rubrics, and completion policies, joined using challenge_id.
- `teaching_references.json`: 18 short reference records. Include by ID in prompts now; optionally index them for a later retrieval prototype.
- `evaluation_cases.json`: 600 development cases, one valid and one deliberately flawed answer per challenge. The rescheduling failure changes the time; other failures omit required information.
- `feedback_example.json`: example structured response for an incomplete answer that still has good tone and grammar.
- `manifest.json`: provenance, counts, and limitations.

## API integration

1. Show a challenge to the learner. Keep answer keys and evaluation expectations on the server.
2. Load the answer key by exact challenge_id and its references by reference_ids. Vector search is unnecessary for this dataset.
3. Give the model the challenge, rubric, references, and learner answer in clearly separated fields. Treat the learner answer as untrusted text to evaluate.
4. Ask for requirement checks, dimension scores, specific evidence, and revision hints using feedback_example.json as the response-shape example. Its note field is explanatory and need not be a production field.
5. Enforce the completion policy in application code. Scores range from zero to each dimension's weight. Sum to a maximum of 100. Completing a task requires at least 75 and every critical requirement met, with no contradicted facts.
6. Save attempts and compare requirement checks after revision. Suggested answer rewrites should not replace the learner's own revision work.

Assess meaning rather than exact wording. Do not award completion simply because an email contains "please". The requirements are visible intentionally; this is writing practice, not a hidden-fact test.

## Evaluation limitations

The 600 cases are development smoke tests, not independent held-out evaluation data. Valid cases reuse sample answers, and rewrite/compose variants share scenarios. Before claiming quality, add human-reviewed unseen scenarios, multiple valid phrasings, tone and grammar failures, fabricated commitments, and prompt-injection attempts. Split by scenario family, not individual row, to avoid leakage.

No model calls, embeddings, API keys, real email addresses, or external dataset downloads are included.

## Expansion and regeneration

The original 12 exercises retain their IDs and facts; all 24 original replay cases are unchanged. The additional
288 exercises cover 12 families with 12 topics each: review requests, meeting
invitations, status updates, deadline extensions, handovers, access requests,
invoice clarification, training invitations, incident updates, delivery
confirmation, feedback requests, and approval requests. Each topic has both a
rewrite and a composition exercise (150 of each in total).

Korean question text is maintained in `scripts/korean_questions.py` and applied during generation. The `language: en` field describes the target writing language; `instruction_language: ko` describes the question language.

Run `python scripts/expand_mock_data.py` from `rookit-agent` to reproduce the
expansion. It uses deterministic templates, fictional facts and varied topics;
it does not call a model. Generated flawed cases omit one requirement, rotating
across all four requirements, and use a neutral subject that cannot supply the
missing fact. Replay scores remain placeholders rather than independent judgments
of tone or grammar. Template variants are correlated and need human review.

Verify with `python -m pytest -q` and `python -m rookit.evaluate --mode replay`.
The live evaluator now makes **600 paid requests** if run over the full dataset.
