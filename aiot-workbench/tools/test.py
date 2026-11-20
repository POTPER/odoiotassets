"""Run each backend in a fresh interpreter and retain readable regression logs."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", nargs="?", choices=("all", "launcher", "engineer", "integration"), default="all")
    args = parser.parse_args()
    output = ROOT / ".tmp"
    output.mkdir(exist_ok=True)
    temp = Path(tempfile.gettempdir()) / "aiot-workbench-regression"
    temp.mkdir(exist_ok=True)
    environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8",
                       PUBLISH_SWITCHER_TEST_TMP=str(temp))
    paths = {"launcher": ROOT / "launcher/tests", "engineer": ROOT / "engineer/tests", "integration": ROOT / "tests"}
    code = 0
    for name, path in paths.items():
        if args.suite not in ("all", name):
            continue
        logfile = output / ("tests-" + name + "-" + sys.platform + ".log")
        with logfile.open("w", encoding="utf-8") as log:
            result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(path), "-q"],
                                    cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
        print(name + ": " + ("PASS" if result.returncode == 0 else "FAIL") + " → " + str(logfile), flush=True)
        print("\n".join(logfile.read_text(encoding="utf-8").splitlines()[-5:]), flush=True)
        code = code or result.returncode
    return code


if __name__ == "__main__":
    raise SystemExit(main())
