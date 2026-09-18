# API error rendering: the three error-body shapes, the 401 hint, automatic
# 429 retry, and the no-key message (which must never reach the network).
from __future__ import annotations

import json

from base import JevTestCase
from mock_server import MockDecisionsServer


class ErrorShapeTests(JevTestCase):
    def test_zod_issue_array_shape(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "TRIGGER_ZOD_ERROR"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("API 错误 (HTTP 400)", proc.stderr)
            self.assertIn("questions.answer.criteria: Required", proc.stderr)

    def test_http_400_detail_string_shape(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "TRIGGER_HTTP400_STR"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("Invalid request payload", proc.stderr)

    def test_http_400_detail_object_shape(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "TRIGGER_HTTP400_OBJ"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("Bad criteria shape", proc.stderr)

    def test_plain_string_shape(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "TRIGGER_PLAIN_ERROR"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("Something went wrong", proc.stderr)


class UnauthorizedTests(JevTestCase):
    def test_401_appends_key_hint(self):
        with MockDecisionsServer(expected_key="right-key") as mock:
            env = self.base_env(api_key="wrong-key", JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("API 错误 (HTTP 401)", proc.stderr)
            self.assertIn("No auth credentials found", proc.stderr)
            self.assertIn("请检查 OPENROUTER_API_KEY", proc.stderr)


class RetryTests(JevTestCase):
    def test_429_with_retry_after_0_then_succeeds(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(
                ["yes", "q", "-s", "RETRY429:unique-a", "--json"], env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertIn("noul", out["answer"])
            retry_requests = [
                r for r in mock.requests if r["body"] and r["body"].get("state") == "RETRY429:unique-a"
            ]
            self.assertEqual(len(retry_requests), 2)


class MissingKeyTests(JevTestCase):
    def test_missing_key_never_hits_the_network(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, JEV_BASE_URL=mock.base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("OPENROUTER_API_KEY", proc.stderr)
            self.assertEqual(mock.request_count, 0)

    def test_env_file_in_config_dir_is_read(self):
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / ".env").write_text("OPENROUTER_API_KEY=from-config-file\n", encoding="utf-8")
        with MockDecisionsServer(expected_key="from-config-file") as mock:
            env = self.base_env(api_key=None, JEV_BASE_URL=mock.base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["yes", "q", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_cwd_env_file_is_not_consulted(self):
        # The removed lookup: a repo-scoped ./.env must not supply the key.
        cwd_env = self.tmp_path / ".env"
        cwd_env.write_text("OPENROUTER_API_KEY=should-not-be-used\n", encoding="utf-8")
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, JEV_BASE_URL=mock.base_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(
                ["yes", "q", "-s", "YES case"], env=env, cwd=str(self.tmp_path)
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("OPENROUTER_API_KEY", proc.stderr)
            self.assertEqual(mock.request_count, 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
