# Static checks that need no network and no subprocess: version numbers agree
# everywhere they're duplicated, SKILL.md frontmatter is well-formed, and the
# license/notice files travel identically with the skill folder.
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "jev" / "scripts" / "jev"
SKILL_MD = REPO_ROOT / "jev" / "SKILL.md"
INSTALL_SH = REPO_ROOT / "installers" / "install.sh"


def _frontmatter(text):
    assert text.startswith("---\n"), "SKILL.md must start with a --- frontmatter block"
    return text.split("---\n", 2)[1]


class VersionConsistencyTests(unittest.TestCase):
    def test_derivative_version_tracks_upstream_cli_and_installer(self):
        cli_text = CLI.read_text(encoding="utf-8")
        m = re.search(r'^VERSION = "([^"]+)"', cli_text, re.MULTILINE)
        self.assertIsNotNone(m, "scripts/jev must define VERSION = \"X.Y.Z\"")
        cli_version = m.group(1)

        front = _frontmatter(SKILL_MD.read_text(encoding="utf-8"))
        m = re.search(r'^\s*version:\s*"([^"]+)"', front, re.MULTILINE)
        self.assertIsNotNone(m, "SKILL.md metadata.version must be quoted")
        skill_version = m.group(1)

        install_text = INSTALL_SH.read_text(encoding="utf-8")
        m = re.search(r'JEV_VERSION:-v([0-9][^}]*)\}', install_text)
        self.assertIsNotNone(m, "install.sh must default JEV_VERSION to vX.Y.Z")
        installer_version = m.group(1)

        self.assertTrue(skill_version.startswith(cli_version + "-router."))
        self.assertEqual(cli_version, installer_version)


class SkillFrontmatterTests(unittest.TestCase):
    def test_derivative_skill_name(self):
        front = _frontmatter(SKILL_MD.read_text(encoding="utf-8"))
        names = [l for l in front.splitlines() if l.startswith("name:")]
        self.assertEqual(names, ["name: jev-code-router"])

    def test_description_is_present_and_bounded(self):
        front = _frontmatter(SKILL_MD.read_text(encoding="utf-8"))
        m = re.search(r"^description:\s*(.+)$", front, re.MULTILINE)
        self.assertIsNotNone(m)
        self.assertLessEqual(len(m.group(1)), 1024)
        self.assertGreater(len(m.group(1)), 0)

    def test_license_field_and_runtime_requirements_present(self):
        front = _frontmatter(SKILL_MD.read_text(encoding="utf-8"))
        self.assertIn("license: Apache-2.0; see LICENSE.txt", front)
        body = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("Python 3.9+", body)
        self.assertIn("OPENROUTER_API_KEY", body)

    def test_skill_md_is_under_150_lines(self):
        lines = SKILL_MD.read_text(encoding="utf-8").splitlines()
        self.assertLess(len(lines), 150)

    def test_local_links_resolve(self):
        docs = [SKILL_MD] + sorted((REPO_ROOT / "jev" / "references").glob("*.md"))
        for doc in docs:
            text = doc.read_text(encoding="utf-8")
            for tail in text.split("](")[1:]:
                target = tail.split(")")[0]
                if "://" in target or target.startswith("#"):
                    continue
                target = target.split("#")[0]
                self.assertTrue(
                    (doc.parent / target).is_file(),
                    f"broken link in {doc}: {target}",
                )


class LicenseTravelsWithSkillTests(unittest.TestCase):
    def test_license_identical(self):
        self.assertEqual(
            (REPO_ROOT / "LICENSE").read_bytes(),
            (REPO_ROOT / "jev" / "LICENSE.txt").read_bytes(),
        )

    def test_notice_identical(self):
        self.assertEqual(
            (REPO_ROOT / "NOTICE").read_bytes(),
            (REPO_ROOT / "jev" / "NOTICE").read_bytes(),
        )


class SkillFrontmatterYamlSafetyTests(unittest.TestCase):
    """The frontmatter must parse with a strict YAML parser: `npx skills add`
    rejects the whole skill otherwise. No YAML library in the stdlib, so lint
    the plain scalars for the constructs that break them."""

    def _frontmatter_lines(self):
        text = (Path(__file__).resolve().parent.parent / "jev" / "SKILL.md").read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(m, "SKILL.md has no frontmatter block")
        return m.group(1).splitlines()

    def test_plain_scalars_contain_no_yaml_breaking_sequences(self):
        for line in self._frontmatter_lines():
            m = re.match(r"^(\s*)([A-Za-z_-]+):\s?(.*)$", line)
            self.assertIsNotNone(m, f"unexpected frontmatter line: {line!r}")
            value = m.group(3)
            if not value or value[0] in "\"'>|":
                continue  # empty (mapping), quoted or block scalar
            self.assertNotIn(": ", value, f"': ' inside a plain YAML scalar breaks parsing: {line[:70]!r}")
            self.assertNotIn(" #", value, f"' #' starts a YAML comment: {line[:70]!r}")
            self.assertFalse(value.endswith(":"), line[:70])
            self.assertNotIn(value[0], "[]{}&*!%@`,?-", f"plain scalar starts with a YAML indicator: {line[:70]!r}")

    def test_parses_with_pyyaml_when_available(self):
        try:
            import yaml  # noqa: WPS433 - optional, not a project dependency
        except ImportError:
            self.skipTest("PyYAML not installed")
        data = yaml.safe_load("\n".join(self._frontmatter_lines()))
        self.assertEqual(data["name"], "jev-code-router")
        self.assertLessEqual(len(data["description"]), 1024)


if __name__ == "__main__":
    unittest.main()
