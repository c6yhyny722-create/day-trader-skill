"""Issue #5 upstream: a character outside the Windows console code page must
not kill a command. Each tool reconfigures stdout to UTF-8 when it isn't."""
import glob
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = sorted(glob.glob(os.path.join(ROOT, "trader-*", "*.py"))
               + glob.glob(os.path.join(ROOT, "tv-estrategia", "*.py")))


class WindowsConsole(unittest.TestCase):
    def test_every_tool_guards_stdout(self):
        self.assertTrue(TOOLS)
        for path in TOOLS:
            with open(path, encoding="utf-8") as fh:
                self.assertIn('reconfigure(encoding="utf-8", errors="replace")', fh.read(), path)

    def test_emoji_survives_a_cp1252_pipe(self):
        path = os.path.join(ROOT, "trader-cripto", "cripto.py")
        code = ("import runpy,sys; sys.argv=['x']; "
                "g=runpy.run_path(%r, run_name='guard'); print('\\U0001F7E2 COMPRA')" % path)
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode("utf-8", "replace"))
        self.assertIn("COMPRA", out.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
