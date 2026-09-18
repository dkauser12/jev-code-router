# Outgoing request shape: JSON-state auto-detection vs --text, --field
# coercion of number/bool/null, and OpenRouter attribution headers.
from __future__ import annotations

import json

from base import JevTestCase
from mock_server import MockDecisionsServer


class StateAutoDetectTests(JevTestCase):
    def test_json_object_is_sent_structured(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", '{"a": 1, "b": "x"}'], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            state = mock.requests[-1]["body"]["state"]
            self.assertIsInstance(state, dict)
            self.assertEqual(state, {"a": 1, "b": "x"})

    def test_json_array_is_sent_structured(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "[1, 2, 3]"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            state = mock.requests[-1]["body"]["state"]
            self.assertIsInstance(state, list)
            self.assertEqual(state, [1, 2, 3])

    def test_text_flag_forces_plain_string(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", '{"a": 1}', "--text"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            state = mock.requests[-1]["body"]["state"]
            self.assertIsInstance(state, str)
            self.assertEqual(state, '{"a": 1}')


class FieldCoercionTests(JevTestCase):
    def test_number_bool_null_are_coerced_to_scalars(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            lines = "\n".join(
                [
                    json.dumps({"text": "hello", "n": 42}),
                    json.dumps({"text": "hello", "n": True}),
                    json.dumps({"text": "hello", "n": None}),
                ]
            )
            proc = self.run_jev(
                ["yes", "q", "-l", "--field", "n", "--json"], input=lines, env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            outs = [json.loads(line) for line in proc.stdout.strip().splitlines()]
            self.assertEqual([o["input"] for o in outs], ["42", "true", "null"])

    def test_missing_field_errors_that_line_only(self):
        with MockDecisionsServer() as mock:
            env = self.base_env(JEV_BASE_URL=mock.base_url)
            lines = "\n".join([json.dumps({"other": 1}), json.dumps({"text": "YES ok"})])
            proc = self.run_jev(
                ["yes", "q", "-l", "--field", "text", "--json"], input=lines, env=env
            )
            self.assertEqual(proc.returncode, 2)
            outs = [json.loads(line) for line in proc.stdout.strip().splitlines()]
            self.assertIn("error", outs[0])
            self.assertEqual(outs[1].get("answer", {}).get("yes"), True)


class HeaderTests(JevTestCase):
    def test_attribution_and_auth_headers(self):
        with MockDecisionsServer(expected_key="my-secret") as mock:
            env = self.base_env(api_key="my-secret", JEV_BASE_URL=mock.base_url)
            proc = self.run_jev(["yes", "q", "-s", "YES case"], env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            headers = mock.requests[-1]["headers"]
            self.assertEqual(headers.get("authorization"), "Bearer my-secret")
            self.assertEqual(headers.get("x-title"), "jev-cli")
            self.assertEqual(headers.get("http-referer"), "https://github.com/okooo5km/jev")


if __name__ == "__main__":
    import unittest

    unittest.main()
