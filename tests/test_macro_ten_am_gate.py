import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestMacroTenAmOrderGate(unittest.TestCase):
    def test_saved_and_manual_requests_cannot_submit_the_rejected_window(self) -> None:
        out = Path("/tmp/asymmetry-ten-am-gate")
        out.mkdir(parents=True, exist_ok=True)
        sources = [
            ROOT / "src/motivewave/MacroTenAmOrderGate.java",
            ROOT / "tests/java/MacroTenAmOrderGateTest.java",
        ]
        javac = ROOT / "tools/jdk25/Contents/Home/bin/javac"
        java = ROOT / "tools/jdk25/Contents/Home/bin/java"
        compiled = subprocess.run(
            [str(javac), "-d", str(out), *map(str, sources)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        ran = subprocess.run(
            [str(java), "-cp", str(out), "com.motivewave.platform.study.custom.MacroTenAmOrderGateTest"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn("passed", ran.stdout)
