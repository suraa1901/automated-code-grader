"""
java_grader.py
Compiles and executes a student's Java submission against a single test case.

Java needs one extra step Python doesn't: the source filename must match
the `public class` name before `javac` will accept it. We detect that name
with a regex, write the file under the correct name in a scratch directory,
then compile and run there.
"""

import subprocess
import time
import re
import os


PUBLIC_CLASS_RE = re.compile(r"public\s+class\s+(\w+)")


def extract_public_class_name(code: str) -> str | None:
    match = PUBLIC_CLASS_RE.search(code)
    return match.group(1) if match else None


def prepare_source(code: str, work_dir: str) -> tuple[str, str]:
    """
    Writes `code` into work_dir under the name Java requires.
    Returns (class_name, java_file_path).
    """
    class_name = extract_public_class_name(code) or "Main"
    if not PUBLIC_CLASS_RE.search(code):
        # No public class found (e.g. student forgot `public`) - fall back
        # to a best-effort single `class Name` match so grading can still run.
        m = re.search(r"class\s+(\w+)", code)
        if m:
            class_name = m.group(1)

    java_path = os.path.join(work_dir, f"{class_name}.java")
    with open(java_path, "w") as f:
        f.write(code)
    return class_name, java_path


def compile_java(java_path: str, work_dir: str, timeout: float = 10.0):
    try:
        result = subprocess.run(
            ["javac", java_path],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "Compilation timed out"
    except FileNotFoundError:
        return False, "javac not found on this machine - install a JDK to grade Java submissions"


def run_java(class_name: str, work_dir: str, input_data: str, timeout: float = 5.0):
    start = time.time()
    try:
        result = subprocess.run(
            ["java", "-cp", work_dir, class_name],
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
