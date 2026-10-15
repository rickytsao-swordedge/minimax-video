import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import minimax_video as m


class VideoTests(unittest.TestCase):
    def setUp(self):
        # A network call missed by a mock fails rather than reaching the internet.
        self.net = patch('socket.socket', side_effect=AssertionError('offline only'))
        self.net.start()
        self.addCleanup(self.net.stop)

    def run_cli(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = m.main(argv)
        return code, out.getvalue()

    def test_default_never_reads_key_or_network(self):
        with patch.object(m.os, 'environ') as env, patch.object(m, 'api') as api:
            self.assertEqual(self.run_cli(['submit', '--prompt', '海浪'])[0], 0)
            self.assertFalse(any(call.args and call.args[0] == 'MINIMAX_API_KEY'
                                 for call in env.get.call_args_list))
            api.assert_not_called()

    def test_invalid_parameters(self):
        for args in [['--prompt', ' '], ['--prompt', 'x'*2001],
                     ['--prompt', '海浪', '--duration', '10', '--resolution', '1080P']]:
            with patch.object(m, 'api') as api:
                self.assertEqual(self.run_cli(['submit', *args])[0], 1)
                api.assert_not_called()

    def test_submit_then_duplicate_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)/'submission.json'
            args = ['submit', '--prompt', '海浪', '--execute', '--journal', str(journal)]
            with patch.object(m, 'api', return_value={'task_id': '123'}) as api:
                self.assertEqual(self.run_cli(args)[0], 0)
                self.assertEqual(self.run_cli(args)[0], 1)
                api.assert_called_once_with('/v1/video_generation', {
                    'model': 'MiniMax-Hailuo-2.3', 'prompt': '海浪', 'duration': 6, 'resolution': '768P'})
            self.assertEqual(json.loads(journal.read_text())['task_id'], '123')

    def test_unknown_outcome_preserves_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)/'submission.json'
            args = ['submit', '--prompt', '海浪', '--execute', '--journal', str(journal)]
            with patch.object(m, 'api', side_effect=m.SafeError('未知结果')) as api:
                self.assertEqual(self.run_cli(args)[0], 1)
                self.assertEqual(self.run_cli(args)[0], 1)
                self.assertEqual(api.call_count, 1)
            self.assertIn('unknown', json.loads(journal.read_text())['state'])

    def test_query_all_documented_states(self):
        for status in ['Preparing', 'Queueing', 'Processing', 'Success', 'Fail']:
            with patch.object(m, 'api', return_value={'status': status, 'file_id': '456'}) as api:
                result = m.query('123')
                self.assertEqual(result['status'], status)
                self.assertEqual('file_id' in result, status == 'Success')
                api.assert_called_once_with('/v1/query/video_generation?task_id=123')

    def test_download_separates_auth_and_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'video.mp4'
            with patch.object(m, 'api', return_value={'file': {'download_url': 'https://cdn.example/video?signature=fake'}}) as api, patch.object(m, 'open_request', return_value=io.BytesIO(b'fake-video')) as transport:
                with contextlib.redirect_stdout(io.StringIO()):
                    m.download('456', output)
                api.assert_called_once_with('/v1/files/retrieve?file_id=456')
                self.assertFalse(transport.call_args.args[0].has_header('Authorization'))
                self.assertEqual(output.read_bytes(), b'fake-video')
                self.assertFalse(output.with_suffix('.mp4.part').exists())
                with self.assertRaises(m.SafeError):
                    m.download('456', output)

    def test_download_rejects_http(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(m, 'api', return_value={'file': {'download_url': 'http://cdn.example/video'}}), patch.object(m, 'open_request') as transport:
            with self.assertRaises(m.SafeError):
                m.download('456', Path(directory)/'video.mp4')
            transport.assert_not_called()

    def test_api_errors_redacted_and_not_retried(self):
        for error in [urllib.error.HTTPError(m.BASE_URL, 401, 'sensitive-body', {}, None), OSError('sensitive-body')]:
            with patch.object(m.os, 'environ', {'MINIMAX_API_KEY': 'offline-fake-value'}), patch.object(m, 'open_request', side_effect=error) as transport:
                with self.assertRaises(m.SafeError) as caught:
                    m.api('/v1/video_generation', {})
                self.assertNotIn('sensitive-body', str(caught.exception))
                self.assertNotIn('offline-fake-value', str(caught.exception))
                self.assertEqual(transport.call_count, 1)

    def test_api_request_shape_and_business_failure(self):
        body = {'base_resp': {'status_code': 1004, 'status_msg': 'sensitive-body'}}
        with patch.object(m.os, 'environ', {'MINIMAX_API_KEY': 'offline-fake-value'}), patch.object(m, 'open_request', return_value=io.BytesIO(json.dumps(body).encode())) as transport:
            with self.assertRaisesRegex(m.SafeError, '1004') as caught:
                m.api('/v1/video_generation', {'prompt': '海浪'})
            request = transport.call_args.args[0]
            self.assertEqual(request.full_url, m.BASE_URL+'/v1/video_generation')
            self.assertEqual(request.get_method(), 'POST')
            self.assertNotIn('sensitive-body', str(caught.exception))

    def test_redirect_rejected(self):
        with self.assertRaises(m.SafeError):
            m.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example')

    def test_missing_key(self):
        with patch.object(m.os, 'environ', {}), patch.object(m, 'open_request') as transport:
            with self.assertRaises(m.SafeError):
                m.api('/v1/query/video_generation?task_id=123')
            transport.assert_not_called()

    def test_invalid_id(self):
        with patch.object(m, 'api') as api:
            with self.assertRaises(m.SafeError):
                m.query('123&injected=1')
            api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
