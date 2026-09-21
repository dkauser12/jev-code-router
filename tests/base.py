# Shared test scaffolding: run the jev CLI as a subprocess against a real
# loopback mock server, with HOME/XDG_CONFIG_HOME pointed at a throwaway dir.
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JEV_CLI = REPO_ROOT / "jev" / "scripts" / "jev"


class JevTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="jev-test-")
        self.tmp_path = Path(self._tmp.name)
        self.home = self.tmp_path / "home"
        self.xdg_config = self.tmp_path / "xdgconfig"
        self.home.mkdir()
        self.xdg_config.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def base_env(self, api_key="test", **overrides):
        env = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.xdg_config),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        # Native Windows subprocesses need these OS runtime variables for
        # Winsock/TLS initialization. Preserve no user credential variables.
        if os.name == "nt":
            for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP"):
                if os.environ.get(name):
                    env[name] = os.environ[name]
        if api_key is not None:
            env["OPENROUTER_API_KEY"] = api_key
        env.update(overrides)
        return env

    def user_specs_dir(self):
        d = self.xdg_config / "jev" / "specs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def run_jev(self, args, input=None, env=None, python=None, timeout=30, **popen_kwargs):
        python = python or sys.executable
        full_env = self.base_env() if env is None else env
        return subprocess.run(
            [python, str(JEV_CLI)] + list(args),
            input=input,
            env=full_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            **popen_kwargs,
        )

    def popen_jev(self, args, env=None, python=None, **kwargs):
        python = python or sys.executable
        full_env = self.base_env() if env is None else env
        return subprocess.Popen(
            [python, str(JEV_CLI)] + list(args),
            env=full_env,
            encoding="utf-8",
            **kwargs,
        )
