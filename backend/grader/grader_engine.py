"""
grader_engine.py
Language-agnostic orchestrator: given a submission and its assignment's
test cases, run each test case with the right language backend, compare
output, and compute a weighted score out of 100.
"""

import os
import shutil
import tempfile

from . import python_grader, java_grader


def normalize(text: str) -> str:
    """Whitespace-tolerant comparison: trims trailing spaces/newlines per line."""
    lines = [line.rstrip() for line in (text or "").strip().splitlines()]
    return "\n".join(lines)


def grade_submission(submission_row, test_cases):
    """
    submission_row: sqlite3.Row with columns language, code
    test_cases: list of sqlite3.Row with input_data, expected_output, weight, id

    Returns (overall_score: float, per_test_results: list[dict])
    """
    language = submission_row["language"]
    code = submission_row["code"]
    work_dir = tempfile.mkdtemp(prefix="grader_")

    per_test_results = []
    total_weight = sum(tc["weight"] for tc in test_cases) or 1.0
    earned_weight = 0.0

    try:
        if language == "java":
            class_name, java_path = java_grader.prepare_source(code, work_dir)
            compiled, compile_error = java_grader.compile_java(java_path, work_dir)
            if not compiled:
                for tc in test_cases:
                    per_test_results.append({
                        "test_case_id": tc["id"],
                        "passed": False,
                        "actual_output": "",
                        "error_message": f"Compilation error: {compile_error}",
                        "execution_time_ms": 0,
                    })
                return 0.0, per_test_results

        elif language == "python":
            code_path = os.path.join(work_dir, "submission.py")
            with open(code_path, "w") as f:
                f.write(code)
        else:
            raise ValueError(f"Unsupported language: {language}")

        for tc in test_cases:
            if language == "java":
                run_result = java_grader.run_java(class_name, work_dir, tc["input_data"])
            else:
                run_result = python_grader.run_python(code_path, tc["input_data"])

            passed = (
                not run_result["error"]
                and normalize(run_result["output"]) == normalize(tc["expected_output"])
            )
            if passed:
                earned_weight += tc["weight"]

            per_test_results.append({
                "test_case_id": tc["id"],
                "passed": passed,
                "actual_output": run_result["output"],
                "error_message": run_result["error"],
                "execution_time_ms": run_result["execution_time_ms"],
            })

        overall_score = round((earned_weight / total_weight) * 100, 2)
        return overall_score, per_test_results

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
