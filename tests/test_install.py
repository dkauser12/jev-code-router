# End-to-end packaging and installation: .github/package.sh's output installs
# cleanly via installers/install.sh, a corrupted archive aborts without
# touching an existing install, and no build artifacts are left in dist/.
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_SH = REPO_ROOT / ".github" / "package.sh"
INSTALL_SH = REPO_ROOT / "installers" / "install.sh"
VERSION = "v0.1.0"
ARCHIVE_NAME = f"jev-{VERSION}.tar.gz"


def _sh_env():
    env = dict(os.environ)
    env["COPYFILE_DISABLE"] = "1"
    return env


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


@unittest.skipUnless(shutil.which("sh"), "sh not available")
class PackageAndInstallTests(unittest.TestCase):
    dist_dir = REPO_ROOT / "dist"

    @classmethod
    def setUpClass(cls):
        # Hermetic: build fresh, ignoring anything a previous manual run left.
        if cls.dist_dir.exists():
            shutil.rmtree(cls.dist_dir)
        proc = subprocess.run(
            ["sh", str(PACKAGE_SH), VERSION],
            cwd=REPO_ROOT,
            env=_sh_env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, f"package.sh failed: {proc.stderr}"
        cls.archive = cls.dist_dir / ARCHIVE_NAME
        cls.sha256 = cls.dist_dir / f"{ARCHIVE_NAME}.sha256"
        assert cls.archive.is_file(), "package.sh did not produce the archive"
        assert cls.sha256.is_file(), "package.sh did not produce the checksum file"

    @classmethod
    def tearDownClass(cls):
        if cls.dist_dir.exists():
            shutil.rmtree(cls.dist_dir)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="jev-install-test-")
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _install_env(self, archive_dir):
        # Deliberately minimal and without XDG_DATA_HOME / XDG_CONFIG_HOME /
        # OPENROUTER_API_KEY: install.sh must fall back to $HOME-relative
        # defaults, regardless of what this dev machine happens to export.
        return {
            "HOME": str(self.home),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "JEV_ARCHIVE_DIR": str(archive_dir),
            "JEV_VERSION": VERSION,
        }

    def test_tarball_contains_only_the_skill_folder(self):
        out = subprocess.run(
            ["tar", "-tzf", str(self.archive)], capture_output=True, text=True, check=True
        ).stdout.split()
        self.assertTrue(out, "empty archive listing")
        for member in out:
            self.assertTrue(member.startswith("jev/"), member)
        self.assertIn("jev/scripts/jev", out)
        for name in ("mail", "feedback", "signal", "commit", "route"):
            self.assertIn(f"jev/specs/{name}.json", out)

    def test_checksum_file_matches_archive(self):
        expected = self.sha256.read_text().split()[0]
        actual = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.assertEqual(expected, actual)

    def test_fresh_install_runs_and_lists_specs(self):
        proc = subprocess.run(
            ["sh", str(INSTALL_SH)],
            env=self._install_env(self.dist_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("jev 0.1.0", proc.stdout)

        installed_bin = self.home / ".local" / "bin" / "jev"
        self.assertTrue(installed_bin.is_symlink())

        run_env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        version_proc = subprocess.run(
            [str(installed_bin), "--version"],
            env=run_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(version_proc.returncode, 0)
        self.assertEqual(version_proc.stdout.strip(), "jev 0.1.0")

        run_proc = subprocess.run(
            [str(installed_bin), "run"],
            env=run_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(run_proc.returncode, 0)
        names = {line.split("\t")[0] for line in run_proc.stdout.strip().splitlines()}
        self.assertEqual(names, {"mail", "feedback", "signal", "commit", "route"})

    def test_install_is_idempotent(self):
        env = self._install_env(self.dist_dir)
        first = subprocess.run(["sh", str(INSTALL_SH)], env=env, capture_output=True, text=True)
        second = subprocess.run(["sh", str(INSTALL_SH)], env=env, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        leftovers = list((self.home / ".local" / "share").glob(".jev-*"))
        self.assertEqual(leftovers, [])

    def test_corrupted_archive_aborts_without_touching_existing_install(self):
        env = self._install_env(self.dist_dir)
        good = subprocess.run(["sh", str(INSTALL_SH)], env=env, capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        installed_dir = self.home / ".local" / "share" / "jev"
        before = _tree_digest(installed_dir)

        corrupt_dir = Path(self._tmp.name) / "corrupt"
        corrupt_dir.mkdir()
        shutil.copy(self.sha256, corrupt_dir / self.sha256.name)
        data = self.archive.read_bytes() + b"TAMPERED"
        (corrupt_dir / ARCHIVE_NAME).write_bytes(data)

        bad = subprocess.run(
            ["sh", str(INSTALL_SH)],
            env=self._install_env(corrupt_dir),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("checksum mismatch", bad.stderr)

        after = _tree_digest(installed_dir)
        self.assertEqual(before, after, "installed tree changed after a rejected corrupt archive")
        leftovers = list((self.home / ".local" / "share").glob(".jev-*"))
        self.assertEqual(leftovers, [])

    def test_symlinked_jev_home_is_refused(self):
        target = Path(self._tmp.name) / "elsewhere"
        target.mkdir()
        data_home = self.home / ".local" / "share"
        data_home.mkdir(parents=True)
        (data_home / "jev").symlink_to(target)

        proc = subprocess.run(
            ["sh", str(INSTALL_SH)],
            env=self._install_env(self.dist_dir),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("symlink", proc.stderr)
        self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
