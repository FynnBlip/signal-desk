"""Workflow integration using isolated state, no inference or paid API calls."""
import copy
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from server import main as app
from server.contracts import LoopRunRequest, LoopListenRequest, LoopApplyRequest

class InlineThread:
    def __init__(self, target, **kwargs): self.target = target
    def start(self): self.target()

class WorkflowTests(unittest.TestCase):
    def test_prepare_run_listen_confirm_and_new_without_deleting_cache(self):
        state = {'config': {}, 'rounds': [], 'evaluated_versions': [], 'workspace_mode': 'blank', 'experiment_id': 'test'}
        def save(value):
            state.clear(); state.update(copy.deepcopy(value)); return copy.deepcopy(state)
        def result(config, progress_cb):
            progress_cb(1, 1, 'AudioBox 评测')
            return {'status':'ok','baseline':'v1','candidate':'v2','rows':[{'stem':'sample','scene_id':'NPARK','baseline_pq':5,'candidate_pq':6}], 'judge':{'promoted':True}}
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            root = Path(temp); audio = root/'cached-tts.wav'; audio.write_bytes(b'cached audio')
            for name, value in [('LOOP_JOB',{'state':'idle'}),('LOOP_BENCHMARK_JOB',{'state':'idle'}),('LOOP_BLIND_ASSIGNMENTS',{}),('LOOP_PREVIEW_SNAPSHOT',root/'preview.json')]:
                stack.enter_context(patch.object(app,name,value))
            stack.enter_context(patch.object(app.loop,'load_status',side_effect=lambda:copy.deepcopy(state)))
            stack.enter_context(patch.object(app.loop,'save_status',side_effect=save))
            stack.enter_context(patch.object(app.loop,'list_versions',return_value=[{'id':'v1'},{'id':'v2'}]))
            stack.enter_context(patch.object(app,'_golden_benchmark_readiness',return_value={'ready':True}))
            stack.enter_context(patch.object(app.loop,'run_round',side_effect=result))
            stack.enter_context(patch.object(app.loop,'decide',return_value={'action':'accept','allowed_actions':{'actions':['accept']}}))
            stack.enter_context(patch.object(app.loop,'load_version_tournament',return_value=None))
            stack.enter_context(patch.object(app.loop,'build_version_summary',return_value={}))
            stack.enter_context(patch.object(app.loop,'LOOP_DIR',root))
            stack.enter_context(patch.object(app.loop,'LISTENING_LOG',root/'listening.jsonl'))
            stack.enter_context(patch.object(app.threading,'Thread',InlineThread))
            app.loop_establish_baseline({'version':'v1'})
            app.loop_config({'baseline':'v1','candidate':'v2'})
            started=app.loop_run(LoopRunRequest())
            self.assertEqual(app.LOOP_JOB['state'],'done')
            self.assertTrue(app.LOOP_JOB['events'])
            self.assertEqual(len(state['rounds']),0)
            recorded=app.loop_listen(LoopListenRequest(run_id=started['run_id'],stem='sample',pick='tie'))
            self.assertEqual(recorded['status'],'ok')
            self.assertEqual(state['baseline'],'v1')
            app.loop_apply(LoopApplyRequest(decision={'action':'accept'}))
            self.assertEqual(state['baseline'],'v2')
            self.assertEqual(len(state['rounds']),1)
            app.loop_new_experiment()
            self.assertEqual(state['workspace_mode'],'blank')
            self.assertEqual(len(state['rounds']),1)
            self.assertEqual(audio.read_bytes(),b'cached audio')
            self.assertIsNone(app.LOOP_JOB['result'])
