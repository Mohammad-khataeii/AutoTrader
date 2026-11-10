"""One-hunk live broker patch tests; broker credentials and network are not needed."""
import ast
import hashlib
import unittest

from deploy.stockswatch.patch_runtime_paper import OLD, NEW, patch_source, git_blob_sha

STUB = '''def _preview_and_submit(client, snapshot, signals, day, now):
    result = {"status": "NO_APPROVED_BROKER_SIGNAL"}
''' + OLD + '''
    return result
'''


class LiveBrokerPatchTests(unittest.TestCase):
    def test_preserves_unrelated_code_and_only_replaces_one_hunk(self):
        source = 'PREFIX = 1\n' + STUB + '\nSUFFIX = 2\n'
        result = patch_source(source)
        ast.parse(result)
        self.assertEqual(result.replace(NEW, OLD, 1), source)
        self.assertIn('entry_window_closed_remaining_broker_gates_not_evaluated', result)

    def test_fails_closed_if_runtime_broker_has_diverged(self):
        with self.assertRaises(ValueError):
            patch_source(STUB.replace('WAITING_FOR_NEXT_CORE_OPEN_WINDOW', 'CUSTOM_RELEASE'))

    def test_fails_closed_if_hunk_outside_target_function(self):
        with self.assertRaises(ValueError):
            patch_source(STUB.replace('_preview_and_submit(', 'another_function(')
                         + '\ndef _preview_and_submit():\n    pass\n')

    def test_git_sha_computed_without_shell_dependencies(self):
        data = b'test'
        self.assertEqual(git_blob_sha(data), hashlib.sha1(b'blob 4\x00test').hexdigest())


if __name__ == '__main__':
    unittest.main()
