from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from base import JevTestCase
from mock_server import MockDecisionsServer


ROUTER = Path(__file__).resolve().parent.parent / "jev" / "scripts" / "jev-code"


class CodeRouterTests(JevTestCase):
    def run_router(self, command, state, env=None, timeout=10):
        state_path = self.tmp_path / f"{command}.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        full_env = self.base_env() if env is None else env
        proc = subprocess.run(
            [sys.executable, str(ROUTER), command, "--state-file", str(state_path)],
            env=full_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        return proc, json.loads(proc.stdout) if proc.stdout.strip() else None

    def route_state(self, marker="CHOICE=standard"):
        return {"task": marker, "changes_code": True}

    def escalate_state(self, profile="economy", marker="CHOICE=stay"):
        return {
            "current_profile": profile,
            "task": marker,
            "failure_evidence": {"unsuccessful_edit_count": 2},
        }

    def context_state(self):
        candidates = []
        for index in range(6):
            candidates.append({
                "id": f"c{index}",
                "path": f"src/{index}.py",
                "excerpt": "YES relevant" if index in (0, 2) else "NO unrelated",
            })
        return {"objective": "find the handler", "candidates": candidates}

    def test_valid_route_responses(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            for label in ("economy", "standard", "deep"):
                proc, out = self.run_router("route", self.route_state(f"CHOICE={label}"), env)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(out["decision"], label)
                self.assertFalse(out["fallback"])
                self.assertEqual(set(out["distribution"]), {"economy", "standard", "deep"})

    def test_unknown_label_falls_back(self):
        fake = self._fake_jev({
            "model": "~typesafe/jev-latest", "provider": "openrouter",
            "answers": {"decision": {"choice": "turbo", "probabilities": {
                "economy": 0.1, "standard": 0.1, "deep": 0.8}}},
        })
        proc, out = self.run_router("route", self.route_state(),
                                    self.base_env(JEV_CODE_JEV_PATH=str(fake)))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(out["decision"], "standard")
        self.assertEqual(out["reason"], "unknown_label")

    def test_missing_answer_falls_back(self):
        fake = self._fake_jev({"model": "x", "answers": {}})
        _, out = self.run_router("route", self.route_state(),
                                 self.base_env(JEV_CODE_JEV_PATH=str(fake)))
        self.assertEqual(out["reason"], "missing_answer")

    def test_malformed_json_falls_back(self):
        fake = self._fake_jev(None, raw="not-json")
        _, out = self.run_router("route", self.route_state(),
                                 self.base_env(JEV_CODE_JEV_PATH=str(fake)))
        self.assertEqual(out["reason"], "malformed_response")

    def test_timeout_has_no_retry(self):
        count_path = self.tmp_path / "invocations.txt"
        fake = self.tmp_path / "slow-jev"
        fake.write_text(
            "import pathlib, sys, time\n"
            f"p = pathlib.Path({str(count_path)!r})\n"
            "p.write_text(p.read_text() + 'x' if p.exists() else 'x')\n"
            "time.sleep(2)\n",
            encoding="utf-8",
        )
        env = self.base_env(JEV_CODE_JEV_PATH=str(fake), JEV_CODE_TIMEOUT="0.1")
        proc, out = self.run_router("route", self.route_state(), env)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(out["fallback"])
        self.assertEqual(out["reason"], "timeout")
        self.assertEqual(count_path.read_text(), "x")

    def test_network_failure_falls_back(self):
        env = self.base_env(JEV_BASE_URL="http://127.0.0.1:1/api/alpha/decisions")
        proc, out = self.run_router("route", self.route_state(), env)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(out["decision"], "standard")
        self.assertTrue(out["fallback"])

    def test_probability_out_of_bounds_falls_back(self):
        fake = self._fake_jev({
            "answers": {"decision": {"choice": "economy", "probabilities": {
                "economy": 1.2, "standard": 0.0, "deep": 0.0}}},
        })
        _, out = self.run_router("route", self.route_state(),
                                 self.base_env(JEV_CODE_JEV_PATH=str(fake)))
        self.assertEqual(out["reason"], "invalid_probability")

    def test_context_selects_only_allowlisted_ids(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc, out = self.run_router("context", self.context_state(), env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(out["decision"], ["c0", "c2"])
            self.assertLessEqual(set(out["decision"]), {f"c{i}" for i in range(6)})

    def test_context_ignores_returned_ids_outside_allowlist(self):
        malicious_row = json.dumps({
            "input": {"candidate": {"id": "outside-allowlist"}},
            "answers": {"selected": {"type": "noul", "noul": 0.9}},
        })
        fake = self._fake_jev(None, raw="\n".join([malicious_row] * 6))
        proc, out = self.run_router(
            "context", self.context_state(), self.base_env(JEV_CODE_JEV_PATH=str(fake)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(out["decision"], [f"c{i}" for i in range(6)])
        self.assertNotIn("outside-allowlist", out["decision"])

    def test_duplicate_context_id_is_rejected(self):
        state = self.context_state()
        state["candidates"].append({"id": "c0", "path": "duplicate"})
        proc, out = self.run_router("context", state)
        self.assertEqual(proc.returncode, 2)
        self.assertIsNone(out)

    def test_empty_context_selection_is_valid(self):
        state = self.context_state()
        for candidate in state["candidates"]:
            candidate["excerpt"] = "NO unrelated"
        with MockDecisionsServer() as mock:
            proc, out = self.run_router("context", state,
                                        self.base_env(JEV_BASE_URL=mock.base_url))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(out["decision"], [])
            self.assertFalse(out["fallback"])

    def test_context_failure_keeps_all_candidates(self):
        state = self.context_state()
        proc, out = self.run_router(
            "context", state,
            self.base_env(JEV_BASE_URL="http://127.0.0.1:1/api/alpha/decisions"),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(out["decision"], [f"c{i}" for i in range(6)])
        self.assertTrue(out["fallback"])

    def test_escalation_moves_at_most_one_level(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            for current, expected in (("economy", "standard"), ("standard", "deep")):
                proc, out = self.run_router(
                    "escalate", self.escalate_state(current, "CHOICE=escalate"), env)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(out["recommended_profile"], expected)

    def test_deep_never_escalates_or_calls_api(self):
        proc, out = self.run_router("escalate", self.escalate_state("deep", "CHOICE=escalate"))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(out["decision"], "stay")
        self.assertEqual(out["recommended_profile"], "deep")

    def test_secret_is_never_emitted(self):
        secret = "credential-sentinel-value"
        fake = self._fake_jev(None, raw=secret, exit_code=2, stderr=secret)
        env = self.base_env(api_key=secret, JEV_CODE_JEV_PATH=str(fake))
        proc, out = self.run_router("route", self.route_state(), env)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(out["fallback"])
        self.assertNotIn(secret, proc.stdout)
        self.assertNotIn(secret, proc.stderr)

    def test_evaluation_fixtures_have_required_coverage(self):
        fixture_dir = Path(__file__).parent / "fixtures" / "evaluation"
        route = json.loads((fixture_dir / "route-cases.json").read_text(encoding="utf-8"))
        route_expected = json.loads((fixture_dir / "route-expected.json").read_text(encoding="utf-8"))
        escalation = json.loads((fixture_dir / "escalation-cases.json").read_text(encoding="utf-8"))
        escalation_expected = json.loads((fixture_dir / "escalation-expected.json").read_text(encoding="utf-8"))
        self.assertEqual({item["id"] for item in route}, set(route_expected))
        self.assertEqual({item["id"] for item in escalation}, set(escalation_expected))
        for label in ("economy", "standard", "deep"):
            self.assertGreaterEqual(list(route_expected.values()).count(label), 5)
        self.assertGreaterEqual(len(escalation), 5)

    def _fake_jev(self, payload, *, raw=None, exit_code=0, stderr=""):
        path = self.tmp_path / f"fake-jev-{len(list(self.tmp_path.glob('fake-jev-*')))}"
        stdout = raw if raw is not None else json.dumps(payload)
        source = (
            "import sys\n"
            f"sys.stdout.write({stdout!r})\n"
            f"sys.stderr.write({stderr!r})\n"
            f"raise SystemExit({exit_code})\n"
        )
        path.write_text(source, encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
