"""Run development fixtures. Live mode makes one paid model call per selected case."""
import argparse
import json
from .agent import finalize
from .data import Dataset
from .providers import OpenAICoach, FixtureReplayCoach


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['replay','live'],default='replay')
    args=parser.parse_args()
    dataset=Dataset()
    provider=OpenAICoach() if args.mode=='live' else FixtureReplayCoach(dataset)
    results=[]
    for case in dataset.cases:
        c=dataset.get_challenge(case['challenge_id'])
        k=dataset.get_answer_key(c['id'])
        context={'challenge':c,'answer_key':k,'references':dataset.get_references(k['reference_ids']),
                 'learner_answer':case['learner_answer'],'previous_attempts':[]}
        try:
            f=finalize(provider.assess(context),c,k,case['learner_answer'])
            missing={r['requirement_id'] for r in f['requirement_checks'] if not r['met']}
            ok=f['complete']==case['expected']['complete'] and missing==set(case['expected']['unmet_requirement_ids'])
            results.append({'id':case['id'],'matched_expected':ok,'feedback':f})
        except Exception as exc:
            results.append({'id':case['id'],'matched_expected':False,'error_type':type(exc).__name__})
    print(json.dumps({'mode':args.mode,'language':'en',
                      'note':'Replay results measure wiring only. These fixtures are not held-out quality tests. Free-text feedback correctness requires human review.',
                      'matched':sum(r['matched_expected'] for r in results),'total':len(results),
                      'results':results},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
