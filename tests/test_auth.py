# jev auth set/status/check, across both providers (TypeSafe is the default
# provider for `auth set`; OpenRouter is selected with --provider openrouter).
#
# `auth set` refuses without a real TTY (an agent has none, by design), so it
# is exercised two ways: piped stdin (must refuse, exit 2, touch nothing) and
# a real pseudo-terminal via the stdlib `pty` module (POSIX only -- skipped
# elsewhere), which also lets us assert the key is never echoed back.
from __future__ import annotations

import json
import os
import select
import sys
import time
import unittest

from base import JevTestCase, JEV_CLI
from mock_server import DEFAULT_KEY_INFO, DEFAULT_NATIVE_MODELS, MockDecisionsServer

try:
    import pty

    HAVE_PTY = True
except ImportError:  # Windows
    HAVE_PTY = False


def run_cli_in_pty(args, env, interactions, timeout=15):
    """Runs the CLI attached to a real pty. `interactions` is a list of
    (wait_for_substr, text_to_send) pairs, sent in order once the growing
    output buffer contains wait_for_substr (None sends immediately). Returns
    (exit_code, captured_output_str) -- captured_output_str is everything the
    child wrote to the terminal, prompts included, exactly as a person
    watching the terminal would have seen it."""
    pid, master_fd = pty.fork()
    if pid == 0:  # child
        try:
            os.execvpe(sys.executable, [sys.executable, str(JEV_CLI)] + list(args), env)
        except Exception:
            os._exit(126)

    buf = b""
    send_idx = 0
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            if send_idx < len(interactions):
                wait_substr, text = interactions[send_idx]
                if wait_substr is None or wait_substr.encode() in buf:
                    os.write(master_fd, text.encode())
                    send_idx += 1
                    continue
            ready, _, _ = select.select([master_fd], [], [], 0.2)
            if master_fd in ready:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
            elif send_idx >= len(interactions):
                # Nothing left to send; give the process a little longer to
                # exit/flush, then stop waiting.
                drain_deadline = time.time() + 1.5
                while time.time() < drain_deadline:
                    ready, _, _ = select.select([master_fd], [], [], 0.2)
                    if master_fd not in ready:
                        break
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                break
    finally:
        _, status = os.waitpid(pid, 0)
        try:
            os.close(master_fd)
        except OSError:
            pass
    exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
    return exit_code, buf.decode("utf-8", "replace")


class AuthCheckOpenRouterTests(JevTestCase):
    """Only OPENROUTER_API_KEY is set by base_env(), so auto-resolution picks
    openrouter here without needing --provider."""

    def test_check_ok_reports_limit_and_usage_without_secrets(self):
        with MockDecisionsServer(key_info={
            **DEFAULT_KEY_INFO, "limit": 20, "limit_remaining": 17.5, "usage": 2.5,
        }) as mock:
            env = self.base_env(JEV_KEY_URL=mock.key_url)
            proc = self.run_jev(["auth", "check"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("密钥有效", proc.stdout)
            self.assertIn("20", proc.stdout)
            self.assertIn("17.5", proc.stdout)
            self.assertIn("2.5", proc.stdout)
            self.assertNotIn(DEFAULT_KEY_INFO["label"], proc.stdout + proc.stderr)
            self.assertNotIn(DEFAULT_KEY_INFO["creator_user_id"], proc.stdout + proc.stderr)

    def test_check_unlimited_when_limit_is_null(self):
        with MockDecisionsServer(key_info={**DEFAULT_KEY_INFO, "limit": None}) as mock:
            env = self.base_env(JEV_KEY_URL=mock.key_url)
            proc = self.run_jev(["auth", "check"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("无上限", proc.stdout)

    def test_check_401_hints_auth_set(self):
        with MockDecisionsServer(expected_key="right-key") as mock:
            env = self.base_env(api_key="wrong-key", JEV_KEY_URL=mock.key_url)
            proc = self.run_jev(["auth", "check"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("密钥无效", proc.stderr)
            self.assertIn("HTTP 401", proc.stderr)
            self.assertIn("jev auth set --provider openrouter", proc.stderr)

    def test_check_missing_key_never_hits_the_network(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, JEV_KEY_URL=mock.key_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["auth", "check"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("OPENROUTER_API_KEY", proc.stderr)
            self.assertEqual([r for r in mock.requests if r.get("method") == "GET"], [])

    def test_check_never_prints_the_key_itself(self):
        with MockDecisionsServer() as mock:
            secret = "test"  # the value base_env() sends as OPENROUTER_API_KEY
            env = self.base_env(api_key=secret, JEV_KEY_URL=mock.key_url)
            proc = self.run_jev(["auth", "check"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn(f"Bearer {secret}", proc.stdout + proc.stderr)


class AuthCheckNativeTests(JevTestCase):
    def test_check_ok_lists_model_names(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test", JEV_KEY_URL=mock.native_key_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["auth", "check"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("密钥有效（TypeSafe）", proc.stdout)
            for name in DEFAULT_NATIVE_MODELS:
                self.assertIn(name, proc.stdout)

    def test_check_401_bad_key_hints_auth_set(self):
        with MockDecisionsServer(expected_native_key="right-native-key") as mock:
            env = self.base_env(api_key=None, TYPESAFE_API_KEY="wrong-key", JEV_KEY_URL=mock.native_key_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["auth", "check"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("密钥无效", proc.stderr)
            self.assertIn("HTTP 401", proc.stderr)
            self.assertIn("jev auth set", proc.stderr)

    def test_check_explicit_provider_flag(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(TYPESAFE_API_KEY="ts-test", JEV_KEY_URL=mock.native_key_url)
            proc = self.run_jev(["auth", "check", "--provider", "typesafe"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("密钥有效（TypeSafe）", proc.stdout)

    def test_check_missing_key_never_hits_the_network(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(api_key=None, JEV_KEY_URL=mock.native_key_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["auth", "check", "--provider", "typesafe"], env=env)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("TYPESAFE_API_KEY", proc.stderr)
            self.assertEqual([r for r in mock.requests if r.get("method") == "GET"], [])

    def test_check_never_prints_the_key_itself(self):
        with MockDecisionsServer() as mock:
            secret = "ts-test"
            env = self.base_env(api_key=None, TYPESAFE_API_KEY=secret, JEV_KEY_URL=mock.native_key_url)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["auth", "check"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn(f"Bearer {secret}", proc.stdout + proc.stderr)


class AuthStatusTests(JevTestCase):
    def test_status_from_env_var(self):
        env = self.base_env(api_key="test-key-value")
        proc = self.run_jev(["auth", "status"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("环境变量", proc.stdout)
        self.assertNotIn("test-key-value", proc.stdout)

    def test_status_from_jev_env_file(self):
        custom = self.tmp_path / "custom.env"
        custom.write_text("OPENROUTER_API_KEY=from-custom-file\n", encoding="utf-8")
        os.chmod(custom, 0o600)
        env = self.base_env(api_key=None, JEV_ENV_FILE=str(custom))
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "status"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("JEV_ENV_FILE", proc.stdout)
        self.assertIn(str(custom), proc.stdout)
        self.assertIn("600", proc.stdout)
        self.assertNotIn("from-custom-file", proc.stdout)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not portable to Windows")
    def test_status_from_config_file_reports_path_and_mode(self):
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        env_path = cfg / ".env"
        env_path.write_text("OPENROUTER_API_KEY=from-config\n", encoding="utf-8")
        os.chmod(env_path, 0o600)
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "status"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(str(env_path), proc.stdout)
        self.assertIn("600", proc.stdout)
        self.assertNotIn("警告", proc.stdout)
        self.assertNotIn("from-config", proc.stdout)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not portable to Windows")
    def test_status_warns_when_group_or_other_can_read(self):
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        env_path = cfg / ".env"
        env_path.write_text("OPENROUTER_API_KEY=from-config\n", encoding="utf-8")
        os.chmod(env_path, 0o644)
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "status"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("644", proc.stdout)
        self.assertIn("chmod 600", proc.stdout)

    def test_status_none_configured_exits_1_with_hint(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "status"], env=env)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("jev auth set", proc.stdout)


class AuthStatusMultiProviderTests(JevTestCase):
    def test_active_provider_line_reflects_auto_choice_of_typesafe(self):
        env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test")
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "status"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("当前 provider：TypeSafe（自动）", proc.stdout)
        self.assertIn("[TypeSafe]", proc.stdout)
        self.assertIn("[OpenRouter]", proc.stdout)
        self.assertIn("未配置 OPENROUTER_API_KEY", proc.stdout)

    def test_both_keys_configured_shows_neither_as_unconfigured(self):
        env = self.base_env(api_key="or-test-key", TYPESAFE_API_KEY="ts-test")
        proc = self.run_jev(["auth", "status"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("当前 provider：TypeSafe", proc.stdout)
        self.assertNotIn("未配置 TYPESAFE_API_KEY", proc.stdout)
        self.assertNotIn("未配置 OPENROUTER_API_KEY", proc.stdout)

    def test_explicit_provider_flag_can_be_unconfigured_and_still_reported_as_active(self):
        env = self.base_env(api_key="or-test-key")  # no TYPESAFE_API_KEY
        proc = self.run_jev(["auth", "status", "--provider", "typesafe"], env=env)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("当前 provider：TypeSafe（--provider）", proc.stdout)

    def test_jev_provider_env_is_reflected_in_the_reason(self):
        env = self.base_env(api_key="or-test-key", TYPESAFE_API_KEY="ts-test", JEV_PROVIDER="openrouter")
        proc = self.run_jev(["auth", "status"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("当前 provider：OpenRouter（JEV_PROVIDER）", proc.stdout)


class AuthSetNonInteractiveTests(JevTestCase):
    def test_refuses_without_a_tty_and_touches_nothing(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "set"], input="sk-or-v1-should-not-be-used\n", env=env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("需要在你自己的终端", proc.stderr)
        self.assertIn("TYPESAFE_API_KEY", proc.stderr)
        self.assertFalse((self.xdg_config / "jev" / ".env").exists())

    def test_refuses_without_a_tty_for_openrouter_too(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(
            ["auth", "set", "--provider", "openrouter"], input="sk-or-v1-should-not-be-used\n", env=env
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("OPENROUTER_API_KEY", proc.stderr)
        self.assertFalse((self.xdg_config / "jev" / ".env").exists())


@unittest.skipUnless(HAVE_PTY, "requires a POSIX pty (pty module unavailable)")
class AuthSetPtyTests(JevTestCase):
    def _env(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        env.pop("JEV_ENV_FILE", None)
        return env

    def test_default_provider_is_typesafe(self):
        secret = "ts-test-fixture-key-abc123"  # hyphenated: never matches a real-key-shaped grep
        code, output = run_cli_in_pty(
            ["auth", "set"], self._env(),
            [("TypeSafe API key", secret + "\n")],
        )
        self.assertEqual(code, 0, output)
        self.assertNotIn(secret, output)
        env_path = self.xdg_config / "jev" / ".env"
        self.assertTrue(env_path.is_file())
        self.assertEqual(oct(env_path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(env_path.read_text(encoding="utf-8"), f"TYPESAFE_API_KEY={secret}\n")

    def test_default_preserves_existing_openrouter_key_and_leaves_config_ini_alone(self):
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / ".env").write_text("OPENROUTER_API_KEY=sk-or-v1-existing\n", encoding="utf-8")
        (cfg / "config.ini").write_text("[jev]\nprovider = openrouter\n", encoding="utf-8")
        secret = "ts-new-key-value"
        code, output = run_cli_in_pty(
            ["auth", "set"], self._env(),
            [("TypeSafe API key", secret + "\n")],
        )
        self.assertEqual(code, 0, output)
        content = (cfg / ".env").read_text(encoding="utf-8")
        self.assertIn("OPENROUTER_API_KEY=sk-or-v1-existing", content)
        self.assertIn(f"TYPESAFE_API_KEY={secret}", content)
        # config.ini is a separate (non-secret) file; auth set never touches it.
        self.assertEqual(
            (cfg / "config.ini").read_text(encoding="utf-8"), "[jev]\nprovider = openrouter\n"
        )

    def test_provider_openrouter_writes_openrouter_key(self):
        secret = "sk-or-v1-test-fixture-key-abc123"
        code, output = run_cli_in_pty(
            ["auth", "set", "--provider", "openrouter"], self._env(),
            [("OpenRouter API key", secret + "\n")],
        )
        self.assertEqual(code, 0, output)
        self.assertNotIn(secret, output)
        env_path = self.xdg_config / "jev" / ".env"
        self.assertEqual(env_path.read_text(encoding="utf-8"), f"OPENROUTER_API_KEY={secret}\n")

    def test_other_lines_preserved_and_symlink_target_updated(self):
        real_dir = self.tmp_path / "real-secrets"
        real_dir.mkdir()
        real_path = real_dir / "actual.env"
        real_path.write_text(
            "# a comment\nOTHER_VAR=keep-me\nexport TYPESAFE_API_KEY=old-value\nKEEP=also\n",
            encoding="utf-8",
        )
        os.chmod(real_path, 0o644)
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        link_path = cfg / ".env"
        link_path.symlink_to(real_path)

        secret = "ts-newvalue"
        code, output = run_cli_in_pty(
            ["auth", "set"], self._env(),
            [("TypeSafe API key", secret + "\n")],
        )
        self.assertEqual(code, 0, output)
        self.assertNotIn(secret, output)
        self.assertTrue(link_path.is_symlink())
        self.assertEqual(os.readlink(link_path), str(real_path))
        content = real_path.read_text(encoding="utf-8")
        self.assertIn("# a comment", content)
        self.assertIn("OTHER_VAR=keep-me", content)
        self.assertIn("KEEP=also", content)
        self.assertNotIn("old-value", content)
        self.assertIn(f"TYPESAFE_API_KEY={secret}", content)
        self.assertEqual(oct(real_path.stat().st_mode & 0o777), "0o600")

    def test_sk_or_value_for_typesafe_triggers_confirm_and_no_leaves_no_file(self):
        secret = "sk-or-v1-looks-like-openrouter"
        code, output = run_cli_in_pty(
            ["auth", "set"], self._env(),
            [("TypeSafe API key", secret + "\n"), ("y/N", "n\n")],
        )
        self.assertEqual(code, 2, output)
        self.assertIn("这看起来是 OpenRouter 的密钥", output)
        self.assertNotIn(secret, output)  # getpass never echoes, accepted or not
        self.assertFalse((self.xdg_config / "jev" / ".env").exists())

    def test_sk_or_value_for_typesafe_accepted_on_yes(self):
        secret = "sk-or-v1-user-insists-typesafe"
        code, output = run_cli_in_pty(
            ["auth", "set"], self._env(),
            [("TypeSafe API key", secret + "\n"), ("y/N", "y\n")],
        )
        self.assertEqual(code, 0, output)
        env_path = self.xdg_config / "jev" / ".env"
        self.assertEqual(env_path.read_text(encoding="utf-8"), f"TYPESAFE_API_KEY={secret}\n")

    def test_openrouter_non_sk_or_prefix_declined_leaves_no_file(self):
        secret = "not-a-real-key"
        code, output = run_cli_in_pty(
            ["auth", "set", "--provider", "openrouter"], self._env(),
            [("OpenRouter API key", secret + "\n"), ("y/N", "n\n")],
        )
        self.assertEqual(code, 2, output)
        self.assertIn("不像是 OpenRouter 密钥", output)
        self.assertNotIn(secret, output)
        self.assertFalse((self.xdg_config / "jev" / ".env").exists())

    def test_openrouter_non_sk_or_prefix_accepted_on_yes(self):
        secret = "not-a-real-key-but-user-insists"
        code, output = run_cli_in_pty(
            ["auth", "set", "--provider", "openrouter"], self._env(),
            [("OpenRouter API key", secret + "\n"), ("y/N", "y\n")],
        )
        self.assertEqual(code, 0, output)
        env_path = self.xdg_config / "jev" / ".env"
        self.assertEqual(env_path.read_text(encoding="utf-8"), f"OPENROUTER_API_KEY={secret}\n")


if __name__ == "__main__":
    unittest.main()
