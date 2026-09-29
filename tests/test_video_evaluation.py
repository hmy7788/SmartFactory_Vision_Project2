import json
import tempfile
import unittest
from pathlib import Path
from scripts.evaluate_video import evaluate, cause_matches
from src.app.evaluation_log import EvaluationLog


def sample(i, status='NG', code='WRONG_BOLT'):
    return {'frame_index':i, 'video_timestamp_ms':i*100, 'processing_ms':10,
            'snapshot':{'recipe_id':'recipe_1', 'phase':'ASSEMBLING', 'status':status,
                        'candidate':{'status':'NG'}, 'events':[],
                        'confirmed':{'status':status,'issues':[{'code':code,'hole_id':3,'observed':'bolt_1','expected':'bolt_2'}]}}}


def truth():
    return {'schema_version':1,'video_id':'test','recipe_id':'recipe_1','annotated_range_ms':[0,1000],
            'segments':[{'id':'S1','description':'test','start_ms':0,'end_ms':1000,
                         'expected_status':'NG','expected_phase':'ASSEMBLING','scoring':'status'}],
            'error_events':[{'event_id':'A1','error_type':'WRONG_BOLT','must_detect_window_ms':[0,1000],
                             'observable_error_start_ms':None}]}


def metadata(n):
    return {'schema_version':1,'recipe_id':'recipe_1','frame_count':n,'video_fps':10,'completed':True}


class EvaluationTests(unittest.TestCase):
    def test_full_success_unknown_latency(self):
        result=evaluate(truth(),[sample(i) for i in range(10)],metadata(10))
        self.assertEqual(result['display_status_accuracy'],1)
        self.assertEqual(result['event_summary']['cause_match_rate'],1)
        self.assertIsNone(result['events'][0]['latency_ms'])

    def test_missing_log_not_bridged(self):
        result=evaluate(truth(),[sample(0),sample(9)],metadata(2))
        self.assertEqual(result['covered_ms'],200)
        self.assertTrue(result['provisional'])
        self.assertIsNone(result['event_summary']['cause_match_rate'])

    def test_variable_pts(self):
        rows=[sample(i) for i in range(3)]
        rows[1]['video_timestamp_ms']=250
        rows[2]['video_timestamp_ms']=900
        self.assertEqual(evaluate(truth(),rows,metadata(3))['covered_ms'],1000)

    def test_retained_status_does_not_use_candidate_cause(self):
        r=sample(0,code='WRONG_PART')
        r['snapshot']['candidate']['issues']=[{'code':'WRONG_BOLT'}]
        self.assertFalse(cause_matches(truth()['error_events'][0],r))

    def test_grace_and_unlabeled(self):
        rows=[sample(i,'HOLD' if i<4 else 'NG') for i in range(10)]
        self.assertAlmostEqual(evaluate(truth(),rows,metadata(10))['display_status_accuracy'],.6)
        self.assertEqual(evaluate(truth(),rows,metadata(10),400)['display_status_accuracy'],1)
        a=truth(); a['segments'][0].update(expected_status=None,scoring='transition')
        self.assertIsNone(evaluate(a,rows,metadata(10))['display_status_accuracy'])

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            evaluate(truth(),[sample(0),sample(0)],metadata(2))

    def test_logger_exception_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'run'
            with self.assertRaises(RuntimeError):
                with EvaluationLog(target,{}) as log:
                    raise RuntimeError('test failure')
            data=json.loads((target/'metadata.json').read_text())
            self.assertFalse(data['completed'])
            self.assertEqual(data['stop_reason'],'exception')
            with self.assertRaises(FileExistsError):
                EvaluationLog(target,{})


if __name__=='__main__':
    unittest.main()
