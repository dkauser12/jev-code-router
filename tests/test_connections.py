# HTTPS/HTTP connection reuse (keep-alive): line mode keeps one connection per
# worker thread, a silently-dropped pooled connection is retried once without
# spending a --retries attempt, a `Connection: close` response opens a fresh
# connection next time, JEV_DEBUG announces new/reused per request, and the
# --verbose line-mode summary reports the connection counts. All against the
# offline HTTP mock (loopback is always bypassed for any proxy, so these tests
# are unaffected by proxy env vars or macOS system proxy settings).
from __future__ import annotations

import json

from base import JevTestCase
from mock_server import MockDecisionsServer


class KeepAliveConnectionCountTests(JevTestCase):
    def test_single_worker_reuses_one_connection_across_eight_lines(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            lines = "\n".join(f"YES line-{i}" for i in range(8))
            proc = self.run_jev(["yes", "q", "-l", "-j", "1"], input=lines + "\n", env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(mock.request_count, 8)
            self.assertEqual(mock.connection_count, 1)

    def test_four_workers_use_at_most_four_connections_and_preserve_order(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            lines = [f"YES line-{i}" for i in range(40)]
            proc = self.run_jev(
                ["yes", "q", "-l", "-j", "4"], input="\n".join(lines) + "\n", env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(mock.request_count, 40)
            self.assertLessEqual(mock.connection_count, 4)
            printed = [line.split("\t")[-1] for line in proc.stdout.strip().splitlines()]
            self.assertEqual(printed, lines)

    def test_single_shot_call_uses_one_connection(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(mock.connection_count, 1)


class StaleConnectionRetryTests(JevTestCase):
    def test_stale_pooled_connection_is_retried_without_spending_retry_budget(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            # -j 1 keeps every line on the same worker/connection. The 3rd
            # line tells the mock to silently close the socket right after
            # answering it (no Connection: close header, so the client has no
            # way to know) -- the classic "server dropped an idle pooled
            # connection" case. --retries 0 proves the retry-once-on-stale
            # path does not consume the normal retry budget.
            lines = [
                "YES line-0",
                "YES line-1",
                "TRIGGER_STALE_CLOSE:line-2",
                "YES line-3",
                "YES line-4",
            ]
            proc = self.run_jev(
                ["yes", "q", "-l", "-j", "1", "--retries", "0"],
                input="\n".join(lines) + "\n",
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            printed = [line.split("\t")[-1] for line in proc.stdout.strip().splitlines()]
            self.assertEqual(printed, lines)
            self.assertEqual(mock.request_count, 5)
            self.assertEqual(mock.connection_count, 2)

    def test_stale_retry_shows_as_a_second_new_connection_in_debug_output(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url, JEV_DEBUG="1")
            lines = ["YES a", "TRIGGER_STALE_CLOSE:b", "YES c"]
            proc = self.run_jev(
                ["yes", "q", "-l", "-j", "1", "--retries", "0"],
                input="\n".join(lines) + "\n",
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            new_count = proc.stderr.count("[jev][debug] connection: new")
            reused_count = proc.stderr.count("[jev][debug] connection: reused")
            # 1st line: new. 2nd line: reused, then fails stale and retries on
            # a 2nd new connection. 3rd line: reused (the 2nd connection).
            self.assertEqual(new_count, 2)
            self.assertEqual(reused_count, 2)


class ConnectionCloseHeaderTests(JevTestCase):
    def test_connection_close_response_opens_a_new_connection_next_time(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            lines = ["TRIGGER_CONN_CLOSE:a", "YES b", "YES c"]
            proc = self.run_jev(
                ["yes", "q", "-l", "-j", "1"], input="\n".join(lines) + "\n", env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(mock.request_count, 3)
            # line 1 gets its own connection; the server told the client to
            # close after that response, so line 2 must open a 2nd one; line
            # 3 reuses that 2nd connection (no further Connection: close).
            self.assertEqual(mock.connection_count, 2)


class DebugConnectionLineTests(JevTestCase):
    def test_debug_prints_new_then_reused_for_a_single_worker(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url, JEV_DEBUG="1")
            proc = self.run_jev(
                ["yes", "q", "-l", "-j", "1"], input="YES a\nYES b\n", env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("[jev][debug] connection: new", proc.stderr)
            self.assertIn("[jev][debug] connection: reused", proc.stderr)
            # Never leaks headers or keys on the connection debug line.
            for raw_line in proc.stderr.splitlines():
                if raw_line.startswith("[jev][debug] connection:"):
                    self.assertNotIn("Authorization", raw_line)
                    self.assertNotIn("Bearer", raw_line)

    def test_debug_off_by_default(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("[jev][debug]", proc.stderr)


class VerboseConnectionSummaryTests(JevTestCase):
    def test_line_mode_verbose_summary_reports_connection_counts(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            lines = "\n".join(f"YES {i}" for i in range(4))
            proc = self.run_jev(
                ["yes", "q", "-l", "-j", "1", "--verbose"], input=lines + "\n", env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("连接 新建 1 / 复用 3", proc.stderr)

    def test_single_call_verbose_is_unaffected(self):
        # Single-shot --verbose output is unchanged by this feature (only the
        # line-mode summary gains connection stats).
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case", "--verbose"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("连接", proc.stderr)


class ServerDownErrorTests(JevTestCase):
    def test_server_down_gives_the_same_network_error_and_exit_code(self):
        with MockDecisionsServer() as mock:
            base_url = mock.base_url
        # The mock is stopped now (context manager exited); the port is free
        # again, so this is a real connection-refused case, not a timeout.
        env = self.base_env(JEV_BASE_URL=base_url)
        proc = self.run_jev(["yes", "q", "-s", "YES case"], env=env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("jev: 网络错误:", proc.stderr)


if __name__ == "__main__":
    import unittest

    unittest.main()
