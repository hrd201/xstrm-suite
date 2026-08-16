import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'task_lib.sh'


class TaskLibTests(unittest.TestCase):
    def test_status_write_accepts_python_and_shell_sensitive_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / 'scripts'
            scripts.mkdir()
            copied = scripts / 'task_lib.sh'
            shutil.copy2(SOURCE, copied)
            wrapper = scripts / 'test_wrapper.sh'
            wrapper.write_text(
                '#!/usr/bin/env bash\n'
                'source "$(dirname "$0")/task_lib.sh"\n'
                'status_write scan_recent false false "$1" /tmp/task.log start finish\n',
                encoding='utf-8',
            )
            message = "PermissionError: '/mnt/Show {2026}' and $HOME"

            subprocess.run(
                ['bash', str(wrapper), message],
                check=True,
            )

            status = json.loads((root / 'data' / 'tasks' / 'status.json').read_text(encoding='utf-8'))
            self.assertEqual(status['message'], message)
            self.assertFalse(status['running'])
            self.assertFalse(status['success'])


if __name__ == '__main__':
    unittest.main()
