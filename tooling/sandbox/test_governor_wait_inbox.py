import tempfile, threading, time, unittest
from pathlib import Path
from governor.wait_inbox import wait


class WaitInboxTests(unittest.TestCase):
    def test_returns_only_lines_appended_after_start(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = Path(d) / 'inbox.jsonl'
            inbox.write_text('{"old":1}\n')
            def append():
                time.sleep(0.3)
                with inbox.open('a') as f:
                    f.write('{"new":1}\n')
            threading.Thread(target=append).start()
            self.assertEqual(wait(inbox), '{"new":1}\n')


if __name__ == '__main__':
    unittest.main()
