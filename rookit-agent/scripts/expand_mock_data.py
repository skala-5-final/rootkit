"""Rebuild 288 synthetic exercises while preserving the original 12 records."""
import copy
import json
from datetime import date, timedelta
from pathlib import Path
from korean_questions import localize

ROOT = Path(__file__).resolve().parents[1] / 'data/mock-data-english'

# Each topic changes the requested work, not just the recipient's name.
TOPICS = {
    'review_request': ['supplier onboarding checklist', 'customer refund policy', 'mobile checkout design', 'warehouse safety guide', 'partner launch announcement', 'employee travel policy', 'subscription renewal workflow', 'support escalation guide', 'annual survey questionnaire', 'data retention proposal', 'product release notes', 'branch opening plan'],
    'meeting_invitation': ['customer handoff process', 'inventory forecasting', 'website accessibility', 'regional hiring plan', 'supplier quality review', 'new starter orientation', 'billing workflow', 'service reliability', 'marketing attribution', 'knowledge base ownership', 'quarterly budget planning', 'office relocation'],
    'status_update': ['help center migration', 'mobile app pilot', 'vendor assessment', 'customer survey rollout', 'warehouse audit', 'website translation', 'training portal refresh', 'expense system rollout', 'product catalog cleanup', 'partner certification', 'office network upgrade', 'recruitment campaign'],
    'deadline_extension': ['competitor analysis', 'quarterly cost forecast', 'customer interview summary', 'vendor comparison', 'accessibility audit report', 'inventory reconciliation', 'contract renewal summary', 'website content review', 'user testing findings', 'training evaluation', 'regional sales analysis', 'service capacity plan'],
    'handover': ['shared support inbox', 'weekly stock report', 'supplier follow-up queue', 'onboarding schedule', 'campaign dashboard', 'renewal reminder list', 'expense review queue', 'release checklist', 'translation requests', 'office supply orders', 'customer demo calendar', 'training attendance log'],
    'access_request': ['analytics workspace', 'design library', 'training portal', 'inventory dashboard', 'customer research folder', 'project planning board', 'support knowledge base', 'expense reporting tool', 'content calendar', 'supplier directory', 'release documentation', 'sales reporting workspace'],
    'invoice_clarification': ['translation services', 'equipment rental', 'training facilitation', 'website maintenance', 'event catering', 'courier services', 'design consultation', 'software support', 'printing services', 'office cleaning', 'research recruitment', 'storage services'],
    'training_invitation': ['secure file sharing', 'inclusive meeting facilitation', 'expense report submission', 'customer complaint handling', 'inventory dashboard basics', 'accessible document writing', 'project estimation', 'new hire mentoring', 'presentation skills', 'data quality checks', 'remote collaboration', 'support ticket triage'],
    'incident_update': ['customer portal', 'booking system', 'reporting dashboard', 'internal search', 'order tracking page', 'training platform', 'document upload service', 'inventory lookup', 'partner login', 'invoice download page', 'notification service', 'expense portal'],
    'delivery_confirmation': ['conference badges', 'training workbooks', 'product brochures', 'display stands', 'sample packaging', 'welcome packs', 'office monitors', 'meeting room microphones', 'shipping labels', 'demo devices', 'safety posters', 'printed survey cards'],
    'feedback_request': ['onboarding workshop', 'customer demo', 'support training session', 'partner briefing', 'product discovery workshop', 'team planning session', 'accessibility seminar', 'sales enablement session', 'supplier orientation', 'leadership roundtable', 'research presentation', 'cross-team retrospective'],
    'approval_request': ['customer research pilot', 'training materials update', 'conference booth design', 'website copy refresh', 'supplier trial order', 'internal newsletter redesign', 'accessibility testing session', 'new hire welcome event', 'support handbook revision', 'product photography session', 'team knowledge-sharing event', 'regional partner workshop'],
}
GUIDANCE = {
    'review_request': 'Identify the document, focus the review, give a deadline and explain how to return comments.',
    'meeting_invitation': 'Explain the purpose, give the meeting time and location, and ask for attendance confirmation.',
    'status_update': 'Distinguish completed work, remaining work and the next update without implying the project is finished.',
    'deadline_extension': 'Acknowledge the original commitment, explain the constraint, propose a new date and ask for agreement.',
    'handover': 'State the coverage period, where instructions are kept, the expected action and the escalation contact.',
    'access_request': 'Ask for the minimum required permission, explain its business use and state when it is needed.',
    'invoice_clarification': 'Identify the invoice and discrepancy precisely. Ask for clarification without assuming misconduct or promising payment.',
    'training_invitation': 'State the topic, schedule, attendance location and required preparation. Ask for registration.',
    'incident_update': 'Separate observed impact from investigation status, provide a workaround and commit to an update, not an unsupported recovery time.',
    'delivery_confirmation': 'Confirm the item and quantity, state the delivery location, identify the receiving contact and ask for confirmation.',
    'feedback_request': 'Name the activity, ask focused questions, explain how to respond and provide a deadline.',
    'approval_request': 'Explain the proposal, state the spending ceiling, clarify that work is awaiting approval and request an explicit decision.',
}
NAMES = ['Alex', 'Jamie', 'Morgan', 'Taylor', 'Jordan', 'Casey', 'Riley', 'Avery', 'Robin', 'Drew', 'Cameron', 'Quinn']


def scenario(family, topic, i):
    day = date(2027, 1, 11) + timedelta(days=i * 7)
    fmt = lambda d: f'{d:%B} {d.day}, {d.year}'
    deadline, later = fmt(day), fmt(day + timedelta(days=3))
    at = f'{deadline}, at 3:00 p.m. KST'
    amount = 600 + i * 75
    quantity = 20 + i * 5
    # Each sentence carries one independent requirement so omission fixtures are unambiguous.
    templates = {
        'review_request': (
            f'Review requested: {topic}', 'internal colleague',
            [f'Please review the {topic} before we circulate it to the wider team.',
             'Please focus your review on whether the responsibilities and next steps are clear.',
             f'Could you return your comments by {at}?',
             'Please add comments directly to the shared document rather than sending a separate version.']),
        'meeting_invitation': (
            f'Planning discussion: {topic}', 'internal colleague',
            [f'I would like to invite you to a planning discussion about {topic}.',
             f'The meeting is proposed for {deadline}, from 10:00 to 10:30 a.m. KST, in Room B.',
             'Our goal is to agree on the next two actions and assign an owner to each.',
             f'Please confirm whether you can attend by {fmt(day - timedelta(days=2))}.']),
        'status_update': (
            f'Progress update: {topic}', 'internal manager',
            [f'For the {topic}, we have completed the initial requirements review.',
             'The operations team is still checking the implementation plan, so delivery has not started.',
             f'We plan to share the reviewed implementation plan by {deadline}.',
             f'I will send another status update by {later}, even if the review is still in progress.']),
        'deadline_extension': (
            f'Extension request: {topic}', 'internal manager',
            [f'The {topic} is currently due on {deadline}.',
             'The source data arrived two days late, and I need additional time to verify it.',
             f'Would it be possible to move the deadline to {later}?',
             'Please confirm whether the revised deadline is acceptable before I change the project schedule.']),
        'handover': (
            f'Coverage request: {topic}', 'internal colleague',
            [f'Could you cover the {topic} from {deadline} through {later} while I am away?',
             f'The latest instructions are in the shared Operations folder under "{topic}".',
             'Please check for new requests once each morning and record any action in the handover log.',
             'Please contact the team lead, Lee, if an urgent issue cannot wait until I return.']),
        'access_request': (
            f'Read-only access request: {topic}', 'internal IT support colleague',
            [f'Could you grant me read-only access to the {topic}?',
             'I need to consult the existing materials while preparing the monthly team summary.',
             f'Access is needed by {at}.',
             'Please let me know which approval steps I should complete; I do not need editing permissions.']),
        'invoice_clarification': (
            f'Clarification on invoice INV-2027-{i + 101}: {topic}', 'external supplier',
            [f'I am reviewing invoice INV-2027-{i + 101} for {topic}.',
             f'The invoice lists USD {amount + 150}, while the agreed quote lists USD {amount}.',
             'Could you explain the difference or send a corrected invoice if the amount is an error?',
             f'Please send your clarification by {deadline} so our finance team can complete its review.']),
        'training_invitation': (
            f'Training invitation: {topic}', 'internal colleague',
            [f'You are invited to a practical training session on {topic}.',
             f'The session will take place on {deadline}, from 2:00 to 3:00 p.m. KST, in Training Room 2.',
             'Please bring a laptop and read the one-page introduction in the shared Training folder beforehand.',
             f'Please register through the internal training calendar by {fmt(day - timedelta(days=2))}.']),
        'incident_update': (
            f'Service update: {topic}', 'external client',
            [f'The {topic} has been responding slowly since 9:00 a.m. KST on {deadline}.',
             'Our technical team is investigating; we have not yet confirmed the cause or a recovery time.',
             'For urgent requests, please contact your account representative so we can help you directly.',
             f'We apologize for the disruption and will provide another update by 11:00 a.m. KST on {deadline}.']),
        'delivery_confirmation': (
            f'Delivery details: {topic}', 'external supplier',
            [f'Please confirm delivery of {quantity} {topic} on {deadline}.',
             'The delivery location is the reception desk on the second floor of our East Office.',
             'Our receiving contact is Lee from the operations team; please ask reception to contact Lee on arrival.',
             f'Please confirm these arrangements by {fmt(day - timedelta(days=2))}, or let us know if changes are needed.']),
        'feedback_request': (
            f'Feedback requested: {topic}', 'internal colleague',
            [f'Thank you for taking part in the {topic} on {fmt(day - timedelta(days=4))}.',
             'Could you tell us which part was most useful and suggest one specific improvement?',
             'Please reply directly to this email with your comments; no separate form is required.',
             f'Please send your feedback by {deadline} so we can use it when planning the next session.']),
        'approval_request': (
            f'Approval needed: {topic}', 'internal manager',
            [f'I am requesting approval to proceed with the {topic}.',
             f'The proposed spending ceiling is USD {amount}, including all materials and service fees.',
             'No orders have been placed, and the work will begin only after approval.',
             f'Could you approve the proposal or let me know what changes are needed by {deadline}?']),
    }
    title, relationship, sentences = templates[family]
    requirements = {
        'review_request': [f'Request a review of the {topic} before wider circulation.', 'Ask the reviewer to focus on responsibilities and next steps.', f'Specify the review deadline as {at}.', 'Ask for comments in the shared document, not a separate version.'],
        'meeting_invitation': [f'Invite the recipient to discuss {topic}.', f'Propose {deadline}, 10:00–10:30 a.m. KST, in Room B.', 'Explain that the goal is to agree on two next actions and their owners.', f'Request attendance confirmation by {fmt(day - timedelta(days=2))}.'],
        'status_update': [f'State that the initial requirements review for the {topic} is complete.', 'Explain that operations is checking the implementation plan and delivery has not started.', f'Plan to share the reviewed implementation plan by {deadline}.', f'Commit to another update by {later}, including if the review is unfinished.'],
        'deadline_extension': [f'Identify the original deadline for the {topic} as {deadline}.', 'Explain that source data arrived two days late and still needs verification.', f'Propose a revised deadline of {later}.', 'Ask for agreement before changing the project schedule.'],
        'handover': [f'Request coverage of the {topic} from {deadline} through {later} during your absence.', f'Locate the instructions in the shared Operations folder under "{topic}".', 'Ask for a daily morning request check and an action record in the handover log.', 'Identify team lead Lee as the contact for urgent issues that cannot wait.'],
        'access_request': [f'Request read-only access to the {topic}.', 'Explain that existing materials are needed for the monthly team summary.', f'State that access is needed by {at}.', 'Ask about required approval steps and clarify that editing permission is unnecessary.'],
        'invoice_clarification': [f'Identify invoice INV-2027-{i + 101} for {topic}.', f'Compare the invoiced USD {amount + 150} with the quoted USD {amount}.', 'Request an explanation or a corrected invoice if the amount is an error.', f'Request clarification by {deadline} for finance review.'],
        'training_invitation': [f'Invite the recipient to practical training on {topic}.', f'State {deadline}, 2:00–3:00 p.m. KST, Training Room 2.', 'Ask participants to bring a laptop and read the introduction in the shared Training folder.', f'Request registration through the internal training calendar by {fmt(day - timedelta(days=2))}.'],
        'incident_update': [f'Report slow responses from the {topic} since 9:00 a.m. KST on {deadline}.', 'Explain that investigation is ongoing and neither the cause nor recovery time is confirmed.', 'Direct urgent requests to the account representative for assistance.', f'Apologize and commit to an update by 11:00 a.m. KST on {deadline}.'],
        'delivery_confirmation': [f'Request confirmation of {quantity} {topic} for delivery on {deadline}.', 'Specify the second-floor reception desk at the East Office.', 'Identify operations colleague Lee as the receiving contact and ask reception to contact Lee.', f'Ask for confirmation or needed changes by {fmt(day - timedelta(days=2))}.'],
        'feedback_request': [f'Thank the recipient for attending the {topic} on {fmt(day - timedelta(days=4))}.', 'Ask for the most useful part and one specific improvement.', 'Request a direct email reply and clarify that no separate form is needed.', f'Specify {deadline} as the feedback deadline to inform planning for the next session.'],
        'approval_request': [f'Request approval for the {topic}.', f'State a spending ceiling of USD {amount}, including materials and service fees.', 'Clarify that no orders have been placed and work awaits approval.', f'Request approval or required changes by {deadline}.'],
    }
    return title, relationship, sentences, requirements[family]


def main():
    def read(name):
        return json.loads((ROOT / f'{name}.json').read_text())

    originals = {f'en_{i:03}_{kind}' for i in range(1, 7) for kind in ('rewrite', 'compose')}
    known = {f'en_{i:03}_{kind}' for i in range(1, 151) for kind in ('rewrite', 'compose')}
    existing = read('challenges')
    assert {c['id'] for c in existing} <= known, 'Refusing to overwrite an unknown challenge'
    challenges = [c for c in existing if c['id'] in originals]
    keys = [k for k in read('answer_keys') if k['challenge_id'] in originals]
    cases = [c for c in read('evaluation_cases') if c['challenge_id'] in originals]
    references = [r for r in read('teaching_references') if r['id'] in {f'ref_en_{i:03}' for i in range(1, 7)}]
    assert len(challenges) == len(keys) == 12 and len(cases) == 24 and len(references) == 6
    key_template = keys[0]
    number = 7
    for family, topics in TOPICS.items():
        ref_id = f'ref_en_{family}'
        references.append({'id': ref_id, 'language': 'en', 'scenario_type': family,
                           'title': family.replace('_', ' ').title() + ' guidance', 'text': GUIDANCE[family],
                           'source': 'Original AI-generated fictional teaching guidance', 'review_status': 'not_human_reviewed'})
        for i, topic in enumerate(topics):
            title, relationship, sentences, descriptions = scenario(family, topic, i)
            recipient = NAMES[i]
            missing = i % len(sentences)
            body = f'Hi {recipient},\n\n' + '\n'.join(sentences) + '\n\nBest regards,\nSam'
            flawed = f'Hi {recipient},\n\n' + '\n'.join(s for j, s in enumerate(sentences) if j != missing) + '\n\nBest regards,\nSam'
            for kind in ('rewrite', 'compose'):
                cid = f'en_{number:03}_{kind}'
                requirements = [{'id': f'{cid}_r{j + 1}', 'description': descriptions[j], 'critical': True} for j, s in enumerate(sentences)]
                challenge = {'id': cid, 'language': 'en', 'scenario_type': family, 'exercise_type': kind,
                             'difficulty': 'beginner' if kind == 'rewrite' else 'intermediate', 'title': title,
                             'recipient': {'name': recipient, 'relationship': relationship}, 'sender_name': 'Sam',
                             'scenario': f'You are Sam, writing to {recipient}, an {relationship}, about {topic}. Use the required facts below; do not invent additional commitments.',
                             'instructions': 'Rewrite the draft as a clear, courteous business email. Preserve the required facts.' if kind == 'rewrite' else 'Write a complete business email using the scenario and requirements.',
                             'requirements': requirements,
                             'starter_email': {'subject': 'Update', 'body': f'{recipient},\n' + ' '.join(sentences) + '\nSam'} if kind == 'rewrite' else None,
                             'hint': GUIDANCE[family], 'synthetic': True}
                challenges.append(challenge)
                key = copy.deepcopy(key_template)
                key.update(challenge_id=cid, reference_ids=[ref_id], sample_answers=[{'subject': title, 'body': body}])
                keys.append(key)
                for valid in (True, False):
                    cases.append({'id': f'eval_{cid}_' + ('valid' if valid else 'flawed'), 'challenge_id': cid,
                                  'learner_answer': {'subject': title if valid else 'Follow-up', 'body': body if valid else flawed},
                                  'expected': {'complete': valid, 'unmet_requirement_ids': [] if valid else [requirements[missing]['id']],
                                               'feedback_must_mention': [] if valid else [sentences[missing]],
                                               'feedback_must_not_claim': ['A specific politeness keyword is mandatory.', 'Only the sample answer is acceptable.']},
                                  'use': 'development_smoke_test', 'synthetic': True})
            number += 1
    assert len(challenges) == 300 and len(keys) == 300 and len(cases) == 600
    localize(challenges)
    outputs = {'challenges': challenges, 'answer_keys': keys, 'evaluation_cases': cases, 'teaching_references': references}
    manifest = read('manifest')
    manifest.update(version='0.3.0', instruction_language='ko', counts={name: len(rows) for name, rows in outputs.items()})
    manifest['scenario_count'] = 150
    manifest['scenario_family_count'] = len({c['scenario_type'] for c in challenges})
    manifest['generation'] = 'Original 12 exercise IDs and facts preserved; Korean question text applied; 288 deterministic template-based exercises generated by scripts/expand_mock_data.py. Paired rewrite/compose exercises share a scenario.'
    for name, value in {**outputs, 'manifest': manifest}.items():
        (ROOT / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(manifest['counts']))


if __name__ == '__main__':
    main()
