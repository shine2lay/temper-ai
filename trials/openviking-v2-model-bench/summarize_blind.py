"""Join frozen independent grades to the sealed key only after review completion."""
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/ov-v2-model-bench')
FIELDS = ['topic_separation','fact_retention','no_invention','history_handling','concise']


def summarize(grades, key):
    if isinstance(grades, dict):
        grades = grades['grades']
    assert isinstance(grades, list)
    assert len(grades)==len(key) and {g['blind_id'] for g in grades}==set(key), 'incomplete/duplicate blind grades'
    totals = {}
    for grade in grades:
        for field in FIELDS:
            assert type(grade[field]) is int and grade[field] in [0,1], (grade['blind_id'],field)
        assert type(grade['corruption']) is bool
        assert type(grade['gradable']) is bool
        assert isinstance(grade['defect'],str)
        rid = key[grade['blind_id']]
        model = rid.split('--')[1]
        bucket = totals.setdefault(model, {'n':0,'criterion_passes':{f:0 for f in FIELDS},
                                           'corruption_calls':0,'ungradable_calls':0,'full_score_calls':0,'defects':[]})
        bucket['n'] += 1
        for field in FIELDS:
            bucket['criterion_passes'][field] += grade[field]
        bucket['corruption_calls'] += int(grade['corruption'])
        bucket['ungradable_calls'] += int(not grade['gradable'])
        bucket['full_score_calls'] += int(all(grade[f] for f in FIELDS))
        if not all(grade[f] for f in FIELDS) or grade['corruption']:
            bucket['defects'].append(dict(grade, result_id=rid))
    for value in totals.values():
        value['mean_rubric_out_of_5'] = sum(value['criterion_passes'].values())/value['n']
    return totals


def main():
    grade_bytes = (ROOT/'blind-grades.json').read_bytes()
    grades = json.loads(grade_bytes)
    key = json.loads((ROOT/'blind-key.json').read_text())
    totals = summarize(grades,key)
    receipt = {'grades_sha256':hashlib.sha256(grade_bytes).hexdigest(),
               'n_grades':sum(t['n'] for t in totals.values()), 'models':totals}
    (ROOT/'semantic-metrics.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({m:{k:v for k,v in t.items() if k!='defects'} for m,t in totals.items()},indent=2))


if __name__ == '__main__':
    main()
