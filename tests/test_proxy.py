# jev otherwise inherits urllib's implicit proxy behavior unchanged (see
# resolve_proxy() in jev/scripts/jev); the one thing worth a dedicated test is
# that a loopback target always connects directly, regardless of proxy
# settings -- this is what keeps every other offline test in this suite
# hermetic against the developer machine's own proxy/environment.
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import unittest

from base import JEV_CLI


def _load_cli_module():
    loader = importlib.machinery.SourceFileLoader("jev_cli_under_test_proxy", str(JEV_CLI))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


jev_cli = _load_cli_module()


class LoopbackAlwaysDirectTests(unittest.TestCase):
    def test_loopback_target_bypasses_any_configured_proxy(self):
        old = os.environ.get("HTTPS_PROXY")
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:1"
        try:
            self.assertIsNone(jev_cli.resolve_proxy("https", "127.0.0.1"))
            self.assertIsNone(jev_cli.resolve_proxy("https", "localhost"))
        finally:
            if old is None:
                os.environ.pop("HTTPS_PROXY", None)
            else:
                os.environ["HTTPS_PROXY"] = old


if __name__ == "__main__":
    unittest.main()
