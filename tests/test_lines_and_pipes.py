# Line-mode concurrency (-l -j N): input order is preserved even when earlier
# lines answer slower than later ones, and a downstream reader closing the
# pipe early (`| head -1`) must not print a traceback.
from __future__ import annotations

import subprocess
import os
import time
import unittest

from base import JevTestCase
from mock_server import MockDecisionsServer


class LineOrderTests(JevTestCase):
    def test_order_preserved_when_early_lines_are_slow(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            lines = [
                "SLOW:400:L1",
                "SLOW:0:L2",
                "SLOW:0:L3",
                "SLOW:0:L4",
            ]
            start = time.time()
            proc = self.run_jev(
                ["yes", "q", "-l", "-j", "4"], input="\n".join(lines) + "\n", env=env
            )
            elapsed = time.time() - start
            self.assertEqual(proc.returncode, 0, proc.stderr)
            printed = [line.split("\t")[-1] for line in proc.stdout.strip().splitlines()]
            self.assertEqual(printed, lines)
            # L2-L4 finish almost immediately; if the consumer didn't block on
            # L1's future in submission order it could return well under 400ms.
            self.assertGreaterEqual(elapsed, 0.35)


class BrokenPipeTests(JevTestCase):
    @unittest.skipIf(os.name == "nt", "POSIX broken-pipe exit semantics differ on Windows")
    def test_downstream_closing_early_does_not_traceback(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            # Each line costs ~15ms at the mock server, well-paced across -j 8
            # workers, so most of the 40 lines are still in flight -- not yet
            # written -- when the pipe closes after line 1. A truncated buffer
            # full of unwritten output would make this test pass trivially.
            lines = "\n".join(f"SLOW:15:line-{i}" for i in range(40)) + "\n"
            proc = self.popen_jev(
                ["yes", "q", "-l", "-j", "8"],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            proc.stdin.write(lines)
            proc.stdin.close()
            first_line = proc.stdout.readline()
            self.assertTrue(first_line)
            proc.stdout.close()
            stderr = proc.stderr.read()
            proc.stderr.close()
            proc.wait(timeout=30)
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("Traceback", stderr)


if __name__ == "__main__":
    import unittest

    unittest.main()
