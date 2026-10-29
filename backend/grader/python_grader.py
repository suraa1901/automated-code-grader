"""
python_grader.py
Executes a student's Python submission against a single test case.

Sandboxing note (intentionally simple, explained in README):
We run the submission as a separate OS process with `subprocess`, a hard
wall-clock timeout, and no shell=True. That stops infinite loops and lets
us capture stdout/stderr/exit code cleanly. It is NOT a full security
sandbox (no seccomp/container isolation) - fine for a grading demo on
trusted college submissions, called out as future work otherwise.
"""

import subprocess
import time
import sys


def run_python(code_path: str, input_data: str, timeout: float = 5.0):
    """
    Runs `python3 code_path`, feeding input_data on stdin.

    Returns a dict: {output, error, execution_time_ms, timed_out}
    """
    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, code_path],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed_ms = (time.time() - start) * 1000
        return {
            "output": result.stdout,
            "error": result.stderr.strip(),
            "execution_time_ms": round(elapsed_ms, 2),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.time() - start) * 1000
        return {
            "output": "",
            "error": f"Time Limit Exceeded (> {timeout}s)",
            "execution_time_ms": round(elapsed_ms, 2),
            "timed_out": True,
        }
    except Exception as exc:  # noqa: BLE001 - surface any launch failure to the UI
        return {
            "output": "",
            "error": f"Execution failed: {exc}",
            "execution_time_ms": 0,
            "timed_out": False,
        }
