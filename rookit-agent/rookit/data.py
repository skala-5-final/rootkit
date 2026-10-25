import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Dataset:
    def __init__(self, root=ROOT / 'data'):
        self.challenges, self.keys, self.references, self.cases = {}, {}, {}, []
        for folder in [Path(root) / 'mock-data-english']:
            def read(name):
                return json.loads((folder / name).read_text(encoding='utf-8'))
            for filename, target, field in [
                ('challenges.json', self.challenges, 'id'),
                ('answer_keys.json', self.keys, 'challenge_id'),
                ('teaching_references.json', self.references, 'id'),
            ]:
                for item in read(filename):
                    if item[field] in target:
                        raise ValueError(f'Duplicate dataset ID: {item[field]}')
                    target[item[field]] = item
            self.cases.extend(read('evaluation_cases.json'))
        if not self.challenges or set(self.challenges) != set(self.keys):
            raise ValueError('Challenges and answer keys must match')
        for cid, key in self.keys.items():
            if not set(key['reference_ids']) <= self.references.keys():
                raise ValueError(f'Missing reference for {cid}')
            weights = {r['id']: r['weight'] for r in key['rubric']}
            if weights != dict(content=40, tone=25, structure=20, language=15):
                raise ValueError('Update score schema for changed rubric weights')

    def get_challenge(self, challenge_id):
        return copy.deepcopy(self.challenges[challenge_id])

    def get_answer_key(self, challenge_id):
        return copy.deepcopy(self.keys[challenge_id])

    def get_references(self, reference_ids):
        return [copy.deepcopy(self.references[r]) for r in reference_ids]
