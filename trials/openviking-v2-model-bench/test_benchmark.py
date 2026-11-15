"""External harness acceptance checks; no live service or model calls."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name+'.py'))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


evaluate = module('evaluate')
runner = module('run_bench')
blind = module('summarize_blind')


class SchemaTests(unittest.TestCase):
    def valid(self):
        return {'items': [{'source_ids': ['n1', 'n2'], 'text': '/tmp/a #23 240'}], 'ejected': []}

    def test_valid(self):
        obj = self.valid()
        self.assertEqual(evaluate.parse_output(json.dumps(obj), ['n1','n2'], 'dedup'), obj)

    def test_invalid_coverage_extra_fields_and_markdown(self):
        malformed = []
        a = self.valid()
        a['items'][0]['source_ids'] = ['n1','n1']
        malformed.append(json.dumps(a))
        a = self.valid()
        a['items'][0]['source_ids'] = ['n1','n3']
        malformed.append(json.dumps(a))
        a = self.valid()
        a['surprise'] = 3
        malformed.append(json.dumps(a))
        a = self.valid()
        a['items'][0]['text'] = ''
        malformed.append(json.dumps(a))
        a = self.valid()
        a['items'][0]['text'] = 0
        malformed.append(json.dumps(a))
        malformed.append('```json\n'+json.dumps(self.valid())+'\n```')
        for text in malformed:
            with self.subTest(text=text):
                with self.assertRaises((AssertionError, ValueError)):
                    evaluate.parse_output(text, ['n1','n2'], 'dedup')

    def test_ejection_only_allowed_in_sweep(self):
        obj = {'items': [{'source_ids': ['n2'], 'text': 'keep'}],
               'ejected': [{'source_id':'n1','reason':'superseded'}]}
        evaluate.parse_output(json.dumps(obj), ['n1','n2'], 'sweep')
        with self.assertRaises(AssertionError):
            evaluate.parse_output(json.dumps(obj), ['n1','n2'], 'dedup')


class ScoringTests(unittest.TestCase):
    def fixture(self):
        return {'id':'D01','task':'dedup','notes':[{'id':'n1','text':'/tmp/a #23 240'}, {'id':'n2','text':'/tmp/a #23 240'}],
                'expected':{'groups':[['n1','n2']], 'ejected':[], 'verbatim':['/tmp/a','#23','240']}}

    def result(self, output):
        return {'id':'D01--x--r1','case':'D01','model':'x','repeat':1,'ok':True,
                'latency_s':1,'input_tokens':None,'output_tokens':None,'total_tokens':None,
                'output':json.dumps(output)}

    def test_known_merge_pass_and_false_split_fail(self):
        obj = {'items':[{'source_ids':['n1','n2'],'text':'/tmp/a #23 240'}], 'ejected':[]}
        good = evaluate.score(self.fixture(), self.result(obj))
        self.assertTrue(good['correct'])
        self.assertEqual(good['tp'],1)
        obj['items'] = [{'source_ids':['n1'],'text':'/tmp/a #23 240'}, {'source_ids':['n2'],'text':'/tmp/a #23 240'}]
        bad = evaluate.score(self.fixture(), self.result(obj))
        self.assertFalse(bad['correct'])
        self.assertEqual(bad['fn'],1)

    def test_omission_and_schema_failure_not_zero_false_negatives(self):
        obj = {'items':[{'source_ids':['n1','n2'],'text':'/tmp/a #23'}], 'ejected':[]}
        row = evaluate.score(self.fixture(), self.result(obj))
        self.assertEqual(row['missing_sentinels'], ['240'])
        obj['items'][0]['source_ids'] = ['n1']
        row = evaluate.score(self.fixture(), self.result(obj))
        self.assertFalse(row['schema'])
        self.assertEqual(row['fn'],1)

    def test_math_and_unknowns(self):
        self.assertEqual(evaluate.kappa([0,0,1,1], [0,0,1,1]),1)
        self.assertIsNone(evaluate.kappa([0,0], [0,0]))
        self.assertIsNone(evaluate.rate(0,0))
        self.assertEqual(evaluate.quantile([1,2,3,4],.9),3.7)


class BlindGradeTests(unittest.TestCase):
    def test_complete_blind_key_join_and_missing_grade_refusal(self):
        grade = {'blind_id':'D01-r1-A', **{f:1 for f in blind.FIELDS},
                 'corruption':False,'gradable':True,'defect':''}
        key = {'D01-r1-A':'D01--gpt-6.1-sol--r1'}
        result = blind.summarize([grade],key)
        self.assertEqual(result['gpt-6.1-sol']['mean_rubric_out_of_5'],5)
        with self.assertRaises(AssertionError):
            blind.summarize([],key)
        with self.assertRaises(AssertionError):
            blind.summarize([grade,grade],key)


class SafetyAndResumeTests(unittest.TestCase):
    def test_guard_rejects_live_port_and_mutations(self):
        with self.assertRaises(PermissionError):
            runner.guard('socket.connect', (object(), ('127.0.0.1',1933)))
        with self.assertRaises(PermissionError):
            runner.guard('open', ('/home/shinelay/.openviking/test', 'w', 0))
        with self.assertRaises(PermissionError):
            runner.guard('os.rename', ('/tmp/a', '/home/shinelay/.openviking/test'))
        runner.guard('open', ('/home/shinelay/.openviking/test', 'r', 0))

    def test_matching_job_skips_and_conflicting_hash_refuses(self):
        old = runner.ROOT
        try:
            with tempfile.TemporaryDirectory(prefix='ov-bench-unit-') as tmp:
                runner.ROOT = Path(tmp)
                (runner.ROOT/'results').mkdir()
                job = {'id':'fixture','case':'D01','model':'fake','repeat':1}
                p = runner.ROOT/'results/fixture.json'
                p.write_text(json.dumps({'plan_hash':'abc','ok':True}))
                self.assertEqual(runner.run_job(job, {}, 'abc')['state'], 'skip')
                with self.assertRaises(AssertionError):
                    runner.run_job(job, {}, 'different')
        finally:
            runner.ROOT = old

    def test_all_real_results_and_largest_case_closed(self):
        root = Path('/tmp/ov-v2-model-bench')
        plan = json.loads((root/'plan.json').read_text())
        self.assertEqual(len(plan['jobs']),144)
        results = [json.loads(p.read_text()) for p in (root/'results').glob('*.json')]
        self.assertEqual({r['id'] for r in results}, {r['id'] for r in plan['jobs']})
        self.assertTrue(all(r['ok'] and all(r[k] is not None for k in ['input_tokens','output_tokens','latency_s']) for r in results))
        self.assertTrue(all(r['plan_hash']==runner.digest(plan) for r in results))
        largest = max(results, key=lambda r:r['input_tokens'])
        self.assertEqual(sum(r['case']==largest['case'] for r in results),6)


if __name__ == '__main__':
    unittest.main()
