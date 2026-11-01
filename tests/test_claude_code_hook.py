# The Claude Code UserPromptSubmit hook in integrations/claude-code/.
from __future__ import annotations

import json
import subprocess
import sys

from base import JEV_CLI, REPO_ROOT, JevTestCase
from mock_server import MockDecisionsServer

HOOK = REPO_ROOT / "integrations" / "claude-code" / "jev-route-hook.py"


class HookTests(JevTestCase):
    def run_hook(self, prompt, mock=None, **env_extra):
        env = self.base_env(**{"JEV_BIN": str(JEV_CLI), **env_extra})
        if mock is not None:
            env["JEV_BASE_URL"] = mock.base_url
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}),
            env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def hint(self, proc):
        out = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "UserPromptSubmit")
        return out["additionalContext"]

    def test_emits_advisory_hint(self):
        with MockDecisionsServer() as mock:
            proc = self.run_hook("please refactor this module CHOICE=code YES", mock)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        hint = self.hint(proc)
        self.assertIn("handler=code", hint)
        self.assertIn("needs_web=yes", hint)
        self.assertIn("advisory", hint)

    def test_skips_slash_commands_and_short_prompts(self):
        with MockDecisionsServer() as mock:
            for prompt in ("/compact now please, thanks", "!ls -la /tmp/somewhere", "hi"):
                proc = self.run_hook(prompt, mock)
                self.assertEqual((proc.returncode, proc.stdout), (0, ""), prompt)
            self.assertEqual(mock.request_count, 0)

    def test_disable_switch(self):
        with MockDecisionsServer() as mock:
            proc = self.run_hook("a long enough prompt here", mock, JEV_ROUTE_DISABLE="1")
            self.assertEqual((proc.returncode, proc.stdout), (0, ""))
            self.assertEqual(mock.request_count, 0)

    def test_fails_open_without_jev_or_on_error(self):
        proc = self.run_hook("a long enough prompt here", JEV_BIN=str(self.tmp_path / "missing"))
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))
        with MockDecisionsServer() as mock:  # wrong key -> 401 -> jev exits 2
            proc = self.run_hook("a long enough prompt here", mock, OPENROUTER_API_KEY="bad")
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_fails_open_on_slow_server(self):
        with MockDecisionsServer() as mock:
            proc = self.run_hook("SLOW:3000:a long enough prompt", mock, JEV_ROUTE_TIMEOUT="1")
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_bad_stdin_is_ignored(self):
        proc = subprocess.run([sys.executable, str(HOOK)], input="not json",
                              capture_output=True, text=True, env=self.base_env())
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))
