# Provider administration: `jev provider list`, `jev provider default`,
# `jev auth remove`, and `jev auth set --stdin`. These are the settings/secret
# split (config.ini vs .env) and the non-interactive provisioning paths added
# on top of the base multi-provider support tested in test_providers.py and
# test_auth.py.
from __future__ import annotations

import json
import os
import unittest

from base import JevTestCase


class ProviderListTests(JevTestCase):
    def test_no_keys_configured(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["provider", "list"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("typesafe", proc.stdout)
        self.assertIn("openrouter", proc.stdout)
        self.assertIn("未配置", proc.stdout)
        self.assertIn("当前：未确定", proc.stdout)
        self.assertNotIn("*", proc.stdout.splitlines()[-1])  # last line is the summary, not a row

    def test_one_key_configured_marks_it_active(self):
        env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test")
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["provider", "list"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.strip().splitlines()
        active_rows = [l for l in lines if l.startswith("*")]
        self.assertEqual(len(active_rows), 1)
        self.assertIn("typesafe", active_rows[0])
        self.assertIn("当前：TypeSafe（自动）", proc.stdout)

    def test_both_keys_configured_never_prints_key_characters(self):
        env = self.base_env(api_key="or-secret-value", TYPESAFE_API_KEY="ts-secret-value")
        proc = self.run_jev(["provider", "list"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("or-secret-value", proc.stdout)
        self.assertNotIn("ts-secret-value", proc.stdout)
        self.assertIn("已配置", proc.stdout)

    def test_json_output_shape(self):
        env = self.base_env(api_key="or-test", TYPESAFE_API_KEY="ts-test")
        proc = self.run_jev(["provider", "list", "--json"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["provider"], "typesafe")
        self.assertEqual(out["reason"], "auto")
        ids = {p["id"] for p in out["providers"]}
        self.assertEqual(ids, {"typesafe", "openrouter"})
        for p in out["providers"]:
            self.assertTrue(p["configured"])
            self.assertNotIn("or-test", json.dumps(p))
            self.assertNotIn("ts-test", json.dumps(p))

    def test_explicit_provider_flag_changes_the_active_marker(self):
        env = self.base_env(api_key="or-test", TYPESAFE_API_KEY="ts-test")
        proc = self.run_jev(["provider", "list", "--provider", "openrouter", "--json"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["provider"], "openrouter")
        self.assertEqual(out["reason"], "--provider")


class ProviderDefaultTests(JevTestCase):
    def test_no_argument_prints_auto_when_nothing_pinned(self):
        env = self.base_env()
        proc = self.run_jev(["provider", "default"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "auto")

    def test_set_and_read_back(self):
        env = self.base_env(api_key="or-test", TYPESAFE_API_KEY="ts-test")
        set_proc = self.run_jev(["provider", "default", "openrouter"], env=env)
        self.assertEqual(set_proc.returncode, 0, set_proc.stderr)
        self.assertIn("当前 provider：OpenRouter（config.ini）", set_proc.stdout)

        get_proc = self.run_jev(["provider", "default"], env=env)
        self.assertEqual(get_proc.returncode, 0, get_proc.stderr)
        self.assertEqual(get_proc.stdout.strip(), "openrouter")

        ini_path = self.xdg_config / "jev" / "config.ini"
        self.assertTrue(ini_path.is_file())
        self.assertEqual(oct(ini_path.stat().st_mode & 0o777), "0o644")

    def test_auto_clears_the_pin(self):
        env = self.base_env(api_key="or-test", TYPESAFE_API_KEY="ts-test")
        self.run_jev(["provider", "default", "openrouter"], env=env)
        clear_proc = self.run_jev(["provider", "default", "auto"], env=env)
        self.assertEqual(clear_proc.returncode, 0, clear_proc.stderr)
        get_proc = self.run_jev(["provider", "default"], env=env)
        self.assertEqual(get_proc.stdout.strip(), "auto")
        # both keys exist, nothing pinned -> auto resolves to typesafe again
        self.assertIn("当前 provider：TypeSafe（自动）", clear_proc.stdout)

    def test_unknown_target_exits_2(self):
        env = self.base_env()
        proc = self.run_jev(["provider", "default", "bogus"], env=env)
        self.assertEqual(proc.returncode, 2)

    def test_warns_when_pinning_a_provider_without_a_key(self):
        env = self.base_env(api_key="or-test")  # no TYPESAFE_API_KEY
        proc = self.run_jev(["provider", "default", "typesafe"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("还没有配置密钥", proc.stderr)
        self.assertIn("jev auth set", proc.stderr)

    def test_pinning_preserves_other_config_ini_sections(self):
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config.ini").write_text("[other]\nkeep = me\n", encoding="utf-8")
        env = self.base_env(api_key="or-test")
        proc = self.run_jev(["provider", "default", "openrouter"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        content = (cfg / "config.ini").read_text(encoding="utf-8")
        self.assertIn("[other]", content)
        self.assertIn("keep = me", content)
        self.assertIn("provider = openrouter", content)


class AuthRemoveTests(JevTestCase):
    def test_removes_only_the_named_provider_key(self):
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / ".env").write_text(
            "TYPESAFE_API_KEY=ts-test\nOPENROUTER_API_KEY=sk-or-v1-test\n", encoding="utf-8"
        )
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "remove", "--provider", "typesafe"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        content = (cfg / ".env").read_text(encoding="utf-8")
        self.assertNotIn("TYPESAFE_API_KEY", content)
        self.assertIn("OPENROUTER_API_KEY=sk-or-v1-test", content)
        self.assertIn("当前 provider：OpenRouter", proc.stdout)

    def test_default_provider_is_typesafe(self):
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / ".env").write_text("TYPESAFE_API_KEY=ts-test\n", encoding="utf-8")
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "remove"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        content = (cfg / ".env").read_text(encoding="utf-8")
        self.assertNotIn("TYPESAFE_API_KEY", content)

    def test_absent_key_exits_1(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "remove", "--provider", "typesafe"], env=env)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("未配置", proc.stderr)

    def test_env_sourced_key_cannot_be_removed_and_says_so(self):
        env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test")
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "remove", "--provider", "typesafe"], env=env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("环境变量", proc.stderr)

    def test_env_file_sourced_key_cannot_be_removed_and_says_so(self):
        custom = self.tmp_path / "custom.env"
        custom.write_text("TYPESAFE_API_KEY=ts-test\n", encoding="utf-8")
        env = self.base_env(api_key=None, JEV_ENV_FILE=str(custom))
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "remove", "--provider", "typesafe"], env=env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("JEV_ENV_FILE", proc.stderr)
        self.assertEqual(custom.read_text(encoding="utf-8"), "TYPESAFE_API_KEY=ts-test\n")

    def test_symlinked_env_file_stays_a_symlink(self):
        real_dir = self.tmp_path / "real-secrets"
        real_dir.mkdir()
        real_path = real_dir / "actual.env"
        real_path.write_text("TYPESAFE_API_KEY=ts-test\nKEEP=also\n", encoding="utf-8")
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        link_path = cfg / ".env"
        link_path.symlink_to(real_path)

        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "remove", "--provider", "typesafe"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(link_path.is_symlink())
        self.assertEqual(os.readlink(link_path), str(real_path))
        content = real_path.read_text(encoding="utf-8")
        self.assertNotIn("TYPESAFE_API_KEY", content)
        self.assertIn("KEEP=also", content)

    def test_file_kept_even_when_left_empty(self):
        cfg = self.xdg_config / "jev"
        cfg.mkdir(parents=True, exist_ok=True)
        env_path = cfg / ".env"
        env_path.write_text("TYPESAFE_API_KEY=ts-test\n", encoding="utf-8")
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "remove", "--provider", "typesafe"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(env_path.is_file())
        self.assertEqual(env_path.read_text(encoding="utf-8"), "")


class AuthSetStdinTests(JevTestCase):
    def test_writes_typesafe_key_from_stdin_no_tty_needed(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "set", "--stdin"], input="ts-stdin-value\n", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        env_path = self.xdg_config / "jev" / ".env"
        self.assertEqual(env_path.read_text(encoding="utf-8"), "TYPESAFE_API_KEY=ts-stdin-value\n")

    def test_writes_openrouter_key_from_stdin(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(
            ["auth", "set", "--provider", "openrouter", "--stdin"],
            input="sk-or-v1-stdin-value\n", env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        env_path = self.xdg_config / "jev" / ".env"
        self.assertEqual(env_path.read_text(encoding="utf-8"), "OPENROUTER_API_KEY=sk-or-v1-stdin-value\n")

    def test_openrouter_prefix_mismatch_errors_and_writes_nothing(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(
            ["auth", "set", "--provider", "openrouter", "--stdin"],
            input="not-an-openrouter-key\n", env=env,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertFalse((self.xdg_config / "jev" / ".env").exists())

    def test_typesafe_sk_or_value_errors_and_writes_nothing(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(
            ["auth", "set", "--stdin"], input="sk-or-v1-oops\n", env=env
        )
        self.assertEqual(proc.returncode, 2)
        self.assertFalse((self.xdg_config / "jev" / ".env").exists())

    def test_empty_stdin_errors(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "set", "--stdin"], input="", env=env)
        self.assertEqual(proc.returncode, 2)
        self.assertFalse((self.xdg_config / "jev" / ".env").exists())

    def test_only_first_line_of_stdin_is_used(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(
            ["auth", "set", "--stdin"], input="ts-first-line\nignored-second-line\n", env=env
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        env_path = self.xdg_config / "jev" / ".env"
        self.assertEqual(env_path.read_text(encoding="utf-8"), "TYPESAFE_API_KEY=ts-first-line\n")


class AuthSetSuggestionTests(JevTestCase):
    def test_suggests_pinning_when_both_keys_end_up_configured(self):
        env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test")
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(
            ["auth", "set", "--provider", "openrouter", "--stdin"],
            input="sk-or-v1-value\n", env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("jev provider default", proc.stderr)

    def test_no_suggestion_when_only_one_key_configured(self):
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "set", "--stdin"], input="ts-test\n", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("jev provider default", proc.stderr)

    def test_no_suggestion_when_a_provider_is_already_pinned(self):
        env = self.base_env(api_key=None, TYPESAFE_API_KEY="ts-test")
        env.pop("OPENROUTER_API_KEY", None)
        self.run_jev(["provider", "default", "typesafe"], env=env)
        proc = self.run_jev(
            ["auth", "set", "--provider", "openrouter", "--stdin"],
            input="sk-or-v1-value\n", env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("jev provider default", proc.stderr)


class DataLossGuardTests(JevTestCase):
    """A file that exists but cannot be read or parsed must stop the command —
    treating it as empty would overwrite the other provider's key or the
    user's settings."""

    def _env_file(self):
        d = self.xdg_config / "jev"
        d.mkdir(parents=True, exist_ok=True)
        return d / ".env"

    @unittest.skipIf(os.geteuid() == 0, "root can read a mode-000 file")
    def test_unreadable_env_file_stops_auth_set_and_keeps_the_other_key(self):
        f = self._env_file()
        f.write_text("OPENROUTER_API_KEY=sk-or-keep-me\n", encoding="utf-8")
        os.chmod(f, 0o000)
        try:
            env = self.base_env(api_key=None)
            env.pop("OPENROUTER_API_KEY", None)
            proc = self.run_jev(["auth", "set", "--stdin"], input="ts-new-key\n", env=env)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("无法读取", proc.stderr)
        finally:
            os.chmod(f, 0o600)
        self.assertEqual(f.read_text(encoding="utf-8"), "OPENROUTER_API_KEY=sk-or-keep-me\n")

    def test_undecodable_env_file_stops_auth_remove(self):
        f = self._env_file()
        original = b"OPENROUTER_API_KEY=sk-or-keep-me\n\xff\xfe broken\nTYPESAFE_API_KEY=ts-x\n"
        f.write_bytes(original)
        env = self.base_env(api_key=None)
        env.pop("OPENROUTER_API_KEY", None)
        proc = self.run_jev(["auth", "set", "--stdin"], input="ts-new-key\n", env=env)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(f.read_bytes(), original)

    def test_malformed_config_ini_is_an_error_and_is_not_overwritten(self):
        d = self.xdg_config / "jev"
        d.mkdir(parents=True, exist_ok=True)
        ini = d / "config.ini"
        original = "this line has no section header\n[jev\nprovider = openrouter\n"
        ini.write_text(original, encoding="utf-8")
        env = self.base_env(api_key="or-test", TYPESAFE_API_KEY="ts-test")

        proc = self.run_jev(["provider", "default", "typesafe"], env=env)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("config.ini", proc.stderr)
        self.assertEqual(ini.read_text(encoding="utf-8"), original)

        # A judgment must not silently fall back to auto-detection either.
        proc = self.run_jev(["yes", "q", "-s", "YES case"], env=env)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("config.ini", proc.stderr)

    def test_percent_sign_in_config_ini_does_not_crash(self):
        d = self.xdg_config / "jev"
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.ini").write_text("[notes]\nhint = 100% mine\n", encoding="utf-8")
        env = self.base_env(api_key="or-test", TYPESAFE_API_KEY="ts-test")
        proc = self.run_jev(["provider", "default", "openrouter"], env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = (d / "config.ini").read_text(encoding="utf-8")
        self.assertIn("100% mine", text)
        self.assertIn("provider = openrouter", text)


if __name__ == "__main__":
    import unittest

    unittest.main()
