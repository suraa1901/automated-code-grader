"""
app.py
Flask application tying the grading engine, plagiarism engine, and
SQLite storage together behind a small set of routes.

Access control summary (see auth.py for the decorators):
- Anyone logged in (teacher or student) can view assignments and submit
  code under their own account.
- Only teachers can create classrooms/assignments, edit test cases,
  trigger grading, run the plagiarism check, view the plagiarism
  report, or open the diff compare view.
- Students only ever see their OWN submissions and scores; the results
  route filters by the logged-in user's id before it even reaches the
  template.
- Assignments live inside a classroom. A teacher can only manage
  classrooms they created; a student can only see classrooms they've
  joined with a join code. Assignments created before classrooms
  existed (classroom_id IS NULL) stay visible to everyone, for
  backward compatibility with data from before this feature.

Run with:  python run.py   (from the project root)
"""

import difflib
import os
import random
import string
import sys

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g

sys.path.append(os.path.dirname(__file__))

from database import get_connection, init_db, now
from grader.grader_engine import grade_submission
from plagiarism.plagiarism_engine import compute_plagiarism
from auth import (
    hash_password, verify_password, get_current_user,
    login_required, teacher_required,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "frontend", "templates"),
    static_folder=os.path.join(BASE_DIR, "frontend", "static"),
)
app.secret_key = os.environ.get("SECRET_KEY", "college-project-dev-secret")  # fine for local demo use


@app.context_processor
def inject_current_user():
    # Makes `current_user` available in every template without passing
    # it explicitly from every view function.
    return {"current_user": get_current_user()}


# ------------------------------------------------------------- access helpers

def generate_join_code(conn, length=6):
    """A short code students type in to join a classroom. Retries on the
    astronomically unlikely chance of a collision."""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choices(alphabet, k=length))
        exists = conn.execute("SELECT 1 FROM classrooms WHERE join_code = ?", (code,)).fetchone()
        if not exists:
            return code


def user_can_access_classroom(conn, user, classroom_id):
    """Teacher must own the classroom; student must have joined it."""
    if user["role"] == "teacher":
        return conn.execute(
            "SELECT 1 FROM classrooms WHERE id = ? AND teacher_id = ?", (classroom_id, user["id"])
        ).fetchone() is not None
    return conn.execute(
        "SELECT 1 FROM classroom_members WHERE classroom_id = ? AND user_id = ?", (classroom_id, user["id"])
    ).fetchone() is not None


def user_can_access_assignment(conn, user, assignment):
    """Assignments predating classrooms (classroom_id IS NULL) stay open to
    anyone logged in, so old data isn't suddenly locked out."""
    if assignment["classroom_id"] is None:
        return True
    return user_can_access_classroom(conn, user, assignment["classroom_id"])


def teacher_owns_assignment(conn, user, assignment):
    """Stricter than user_can_access_assignment: for teacher-only actions
    (grading, plagiarism, editing test cases) a teacher must own the
    classroom, not just any teacher account. Legacy classroom-less
    assignments stay open to any teacher, matching pre-classroom behavior."""
    if assignment["classroom_id"] is None:
        return True
    classroom = conn.execute(
        "SELECT teacher_id FROM classrooms WHERE id = ?", (assignment["classroom_id"],)
    ).fetchone()
    return classroom is not None and classroom["teacher_id"] == user["id"]


# --------------------------------------------------------------------- auth

@app.route("/register", methods=["GET", "POST"])
def register():
    if get_current_user() is not None:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form["name"].strip()
        username = request.form["username"].strip().lower()
        password = request.form["password"]
        role = request.form.get("role", "student")
        if role not in ("teacher", "student"):
            role = "student"

        if not name or not username or not password:
            flash("Please fill in every field.", "error")
            return render_template("register.html")

        conn = get_connection()
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            conn.close()
            flash("That username is already taken.", "error")
            return render_template("register.html")

        conn.execute(
            "INSERT INTO users (name, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, username, hash_password(password), role, now()),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        session["user_id"] = user["id"]
        flash(f"Welcome, {user['name']}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if get_current_user() is not None:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form["username"].strip().lower()
        password = request.form["password"]

        conn = get_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user is None or not verify_password(password, user["password_hash"]):
            flash("Incorrect username or password.", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------- dashboard

@app.route("/")
@login_required
def dashboard():
    user = get_current_user()
    conn = get_connection()

    if user["role"] == "teacher":
        classrooms = conn.execute(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM classroom_members m WHERE m.classroom_id = c.id) AS student_count,
                   (SELECT COUNT(*) FROM assignments a WHERE a.classroom_id = c.id) AS assignment_count
            FROM classrooms c WHERE c.teacher_id = ? ORDER BY c.created_at DESC
            """,
            (user["id"],),
        ).fetchall()
    else:
        classrooms = conn.execute(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM classroom_members m WHERE m.classroom_id = c.id) AS student_count,
                   (SELECT COUNT(*) FROM assignments a WHERE a.classroom_id = c.id) AS assignment_count
            FROM classrooms c
            JOIN classroom_members cm ON cm.classroom_id = c.id
            WHERE cm.user_id = ? ORDER BY c.created_at DESC
            """,
            (user["id"],),
        ).fetchall()

    # Assignments created before classrooms existed - kept visible so old
    # data isn't orphaned, shown separately from the new classroom flow.
    legacy_assignments = conn.execute(
        """
        SELECT a.*,
               (SELECT COUNT(*) FROM submissions s WHERE s.assignment_id = a.id) AS submission_count,
               (SELECT COUNT(*) FROM test_cases t WHERE t.assignment_id = a.id) AS test_case_count
        FROM assignments a WHERE a.classroom_id IS NULL ORDER BY a.created_at DESC
        """
    ).fetchall()
    conn.close()
    return render_template("index.html", classrooms=classrooms, legacy_assignments=legacy_assignments)


@app.route("/classroom/new", methods=["GET", "POST"])
@teacher_required
def new_classroom():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Give the classroom a name.", "error")
            return render_template("new_classroom.html")

        conn = get_connection()
        join_code = generate_join_code(conn)
        cur = conn.execute(
            "INSERT INTO classrooms (name, join_code, teacher_id, created_at) VALUES (?, ?, ?, ?)",
            (name, join_code, get_current_user()["id"], now()),
        )
        conn.commit()
        classroom_id = cur.lastrowid
        conn.close()
        flash(f"Classroom created. Join code: {join_code}", "success")
        return redirect(url_for("classroom_view", classroom_id=classroom_id))

    return render_template("new_classroom.html")


@app.route("/classroom/join", methods=["POST"])
@login_required
def join_classroom():
    user = get_current_user()
    if user["role"] != "student":
        flash("Only student accounts join classrooms with a code.", "error")
        return redirect(url_for("dashboard"))

    code = request.form.get("join_code", "").strip().upper()
    conn = get_connection()
    classroom = conn.execute("SELECT * FROM classrooms WHERE join_code = ?", (code,)).fetchone()
    if classroom is None:
        conn.close()
        flash("That join code doesn't match any classroom.", "error")
        return redirect(url_for("dashboard"))

    conn.execute(
        "INSERT OR IGNORE INTO classroom_members (classroom_id, user_id, joined_at) VALUES (?, ?, ?)",
        (classroom["id"], user["id"], now()),
    )
    conn.commit()
    conn.close()
    flash(f"Joined {classroom['name']}.", "success")
    return redirect(url_for("classroom_view", classroom_id=classroom["id"]))


@app.route("/classroom/<int:classroom_id>")
@login_required
def classroom_view(classroom_id):
    user = get_current_user()
    conn = get_connection()
    classroom = conn.execute("SELECT * FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()
    if classroom is None:
        conn.close()
        flash("Classroom not found.", "error")
        return redirect(url_for("dashboard"))

    if not user_can_access_classroom(conn, user, classroom_id):
        conn.close()
        flash("You don't have access to that classroom. Ask your teacher for the join code.", "error")
        return redirect(url_for("dashboard"))

    assignments = conn.execute(
        """
        SELECT a.*,
               (SELECT COUNT(*) FROM submissions s WHERE s.assignment_id = a.id) AS submission_count,
               (SELECT COUNT(*) FROM test_cases t WHERE t.assignment_id = a.id) AS test_case_count
        FROM assignments a WHERE a.classroom_id = ? ORDER BY a.created_at DESC
        """,
        (classroom_id,),
    ).fetchall()

    roster = None
    analytics = None
    if user["role"] == "teacher":
        roster = conn.execute(
            """
            SELECT u.name, u.username, cm.joined_at
            FROM classroom_members cm JOIN users u ON cm.user_id = u.id
            WHERE cm.classroom_id = ? ORDER BY u.name
            """,
            (classroom_id,),
        ).fetchall()

        avg_row = conn.execute(
            """
            SELECT AVG(s.score) AS avg_score, COUNT(s.id) AS graded_count
            FROM submissions s JOIN assignments a ON s.assignment_id = a.id
            WHERE a.classroom_id = ? AND s.score IS NOT NULL
            """,
            (classroom_id,),
        ).fetchone()
        flagged_row = conn.execute(
            """
            SELECT COUNT(*) AS flagged_count
            FROM plagiarism_results p JOIN assignments a ON p.assignment_id = a.id
            WHERE a.classroom_id = ? AND p.flagged = 1
            """,
            (classroom_id,),
        ).fetchone()
        analytics = {
            "avg_score": round(avg_row["avg_score"], 1) if avg_row["avg_score"] is not None else None,
            "graded_count": avg_row["graded_count"],
            "flagged_count": flagged_row["flagged_count"],
        }

    conn.close()
    return render_template(
        "classroom.html", classroom=classroom, assignments=assignments, roster=roster, analytics=analytics
    )


@app.route("/classroom/<int:classroom_id>/assignment/new", methods=["GET", "POST"])
@teacher_required
def new_assignment(classroom_id):
    conn = get_connection()
    classroom = conn.execute("SELECT * FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()
    if classroom is None or classroom["teacher_id"] != get_current_user()["id"]:
        conn.close()
        flash("You can only add assignments to your own classrooms.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        due_date = request.form.get("due_date", "").strip() or None
        max_attempts_raw = request.form.get("max_attempts", "").strip()
        max_attempts = int(max_attempts_raw) if max_attempts_raw else None

        cur = conn.execute(
            "INSERT INTO assignments "
            "(classroom_id, name, description, allowed_language, plagiarism_threshold, due_date, max_attempts, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                classroom_id,
                request.form["name"],
                request.form.get("description", ""),
                request.form["allowed_language"],
                float(request.form.get("plagiarism_threshold", 70.0)),
                due_date,
                max_attempts,
                now(),
            ),
        )
        assignment_id = cur.lastrowid

        inputs = request.form.getlist("test_input")
        outputs = request.form.getlist("test_output")
        weights = request.form.getlist("test_weight")
        hidden_flags = request.form.getlist("test_hidden")  # values are the indices marked hidden
        for i, (inp, out, weight) in enumerate(zip(inputs, outputs, weights)):
            if out.strip() == "":
                continue
            is_hidden = str(i) in hidden_flags
            conn.execute(
                "INSERT INTO test_cases (assignment_id, input_data, expected_output, weight, is_hidden) "
                "VALUES (?, ?, ?, ?, ?)",
                (assignment_id, inp, out, float(weight or 1.0), int(is_hidden)),
            )
        conn.commit()
        conn.close()
        flash("Assignment created.", "success")
        return redirect(url_for("view_assignment", assignment_id=assignment_id))

    conn.close()
    return render_template("new_assignment.html", classroom=classroom)


# ------------------------------------------------------------- assignment

@app.route("/assignment/<int:assignment_id>")
@login_required
def view_assignment(assignment_id):
    user = get_current_user()
    conn = get_connection()
    assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if assignment is None:
        conn.close()
        flash("Assignment not found.", "error")
        return redirect(url_for("dashboard"))

    if not user_can_access_assignment(conn, user, assignment):
        conn.close()
        flash("You don't have access to that assignment.", "error")
        return redirect(url_for("dashboard"))

    test_cases = conn.execute(
        "SELECT * FROM test_cases WHERE assignment_id = ?", (assignment_id,)
    ).fetchall()

    analytics = None
    attempts_used = None
    attempts_remaining = None

    if user["role"] == "teacher":
        submissions = conn.execute(
            "SELECT * FROM submissions WHERE assignment_id = ? ORDER BY submitted_at DESC", (assignment_id,)
        ).fetchall()
        avg_row = conn.execute(
            "SELECT AVG(score) AS avg_score, COUNT(*) AS graded_count FROM submissions "
            "WHERE assignment_id = ? AND score IS NOT NULL",
            (assignment_id,),
        ).fetchone()
        pass_row = conn.execute(
            "SELECT COUNT(*) AS pass_count FROM submissions WHERE assignment_id = ? AND score = 100",
            (assignment_id,),
        ).fetchone()
        flagged_row = conn.execute(
            "SELECT COUNT(*) AS flagged_count FROM plagiarism_results WHERE assignment_id = ? AND flagged = 1",
            (assignment_id,),
        ).fetchone()
        analytics = {
            "avg_score": round(avg_row["avg_score"], 1) if avg_row["avg_score"] is not None else None,
            "graded_count": avg_row["graded_count"],
            "pass_count": pass_row["pass_count"],
            "flagged_count": flagged_row["flagged_count"],
        }
    else:
        # Students only ever see their own submission history here.
        submissions = conn.execute(
            "SELECT * FROM submissions WHERE assignment_id = ? AND user_id = ? ORDER BY submitted_at DESC",
            (assignment_id, user["id"]),
        ).fetchall()
        attempts_used = len(submissions)
        if assignment["max_attempts"]:
            attempts_remaining = max(assignment["max_attempts"] - attempts_used, 0)

    conn.close()
    return render_template(
        "assignment.html", assignment=assignment, test_cases=test_cases, submissions=submissions,
        analytics=analytics, attempts_used=attempts_used, attempts_remaining=attempts_remaining,
    )


@app.route("/assignment/<int:assignment_id>/submit", methods=["POST"])
@login_required
def submit_code(assignment_id):
    user = get_current_user()
    conn = get_connection()
    assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if assignment is None or not user_can_access_assignment(conn, user, assignment):
        conn.close()
        flash("You don't have access to that assignment.", "error")
        return redirect(url_for("dashboard"))

    if user["role"] != "student":
        conn.close()
        flash("Only student accounts submit code.", "error")
        return redirect(url_for("view_assignment", assignment_id=assignment_id))

    prior_attempts = conn.execute(
        "SELECT COUNT(*) AS n FROM submissions WHERE assignment_id = ? AND user_id = ?",
        (assignment_id, user["id"]),
    ).fetchone()["n"]
    attempt_number = prior_attempts + 1

    if assignment["max_attempts"] and attempt_number > assignment["max_attempts"]:
        conn.close()
        flash(f"You've used all {assignment['max_attempts']} allowed attempt(s) for this assignment.", "error")
        return redirect(url_for("view_assignment", assignment_id=assignment_id))

    language = request.form["language"]

    uploaded = request.files.get("code_file")
    if uploaded and uploaded.filename:
        filename = uploaded.filename
        code = uploaded.read().decode("utf-8", errors="replace")
    else:
        filename = "pasted_code.py" if language == "python" else "Pasted.java"
        code = request.form.get("code_text", "")

    submitted_at = now()
    is_late = bool(assignment["due_date"]) and submitted_at > assignment["due_date"]

    conn.execute(
        "INSERT INTO submissions "
        "(assignment_id, user_id, student_name, language, filename, code, submitted_at, attempt_number, is_late) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (assignment_id, user["id"], user["name"], language, filename, code, submitted_at, attempt_number, int(is_late)),
    )
    conn.commit()
    conn.close()

    if is_late:
        flash(f"Submission received (attempt {attempt_number}) — after the due date, marked late.", "error")
    else:
        flash(f"Submission received (attempt {attempt_number}).", "success")
    return redirect(url_for("view_assignment", assignment_id=assignment_id))


# ----------------------------------------------------------- test cases

@app.route("/assignment/<int:assignment_id>/test_cases", methods=["GET", "POST"])
@teacher_required
def manage_test_cases(assignment_id):
    conn = get_connection()
    assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if assignment is None:
        conn.close()
        flash("Assignment not found.", "error")
        return redirect(url_for("dashboard"))
    if assignment["classroom_id"] is not None:
        classroom = conn.execute("SELECT * FROM classrooms WHERE id = ?", (assignment["classroom_id"],)).fetchone()
        if classroom is None or classroom["teacher_id"] != get_current_user()["id"]:
            conn.close()
            flash("You can only edit test cases for your own assignments.", "error")
            return redirect(url_for("dashboard"))

    if request.method == "POST":
        # Existing test cases: update in place, or delete if checked.
        existing_ids = request.form.getlist("existing_id")
        delete_ids = set(request.form.getlist("existing_delete"))
        for tc_id in existing_ids:
            if tc_id in delete_ids:
                conn.execute("DELETE FROM test_cases WHERE id = ? AND assignment_id = ?", (tc_id, assignment_id))
                continue
            conn.execute(
                "UPDATE test_cases SET input_data = ?, expected_output = ?, weight = ?, is_hidden = ? "
                "WHERE id = ? AND assignment_id = ?",
                (
                    request.form.get(f"input_{tc_id}", ""),
                    request.form.get(f"output_{tc_id}", ""),
                    float(request.form.get(f"weight_{tc_id}", 1.0) or 1.0),
                    int(f"hidden_{tc_id}" in request.form),
                    tc_id, assignment_id,
                ),
            )

        # Newly added rows, same shape as the assignment-creation form.
        inputs = request.form.getlist("test_input")
        outputs = request.form.getlist("test_output")
        weights = request.form.getlist("test_weight")
        hidden_flags = request.form.getlist("test_hidden")
        for i, (inp, out, weight) in enumerate(zip(inputs, outputs, weights)):
            if out.strip() == "":
                continue
            is_hidden = str(i) in hidden_flags
            conn.execute(
                "INSERT INTO test_cases (assignment_id, input_data, expected_output, weight, is_hidden) "
                "VALUES (?, ?, ?, ?, ?)",
                (assignment_id, inp, out, float(weight or 1.0), int(is_hidden)),
            )

        conn.commit()
        conn.close()
        flash(
            "Test cases updated. Existing scores were graded against the OLD test cases — "
            "click \"Grade all submissions\" again to refresh them.", "success"
        )
        return redirect(url_for("view_assignment", assignment_id=assignment_id))

    test_cases = conn.execute("SELECT * FROM test_cases WHERE assignment_id = ?", (assignment_id,)).fetchall()
    conn.close()
    return render_template("manage_test_cases.html", assignment=assignment, test_cases=test_cases)


# ----------------------------------------------------------------- grading

@app.route("/assignment/<int:assignment_id>/grade", methods=["POST"])
@teacher_required
def grade_assignment(assignment_id):
    conn = get_connection()
    assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if assignment is None or not teacher_owns_assignment(conn, get_current_user(), assignment):
        conn.close()
        flash("You can only grade your own assignments.", "error")
        return redirect(url_for("dashboard"))

    test_cases = conn.execute(
        "SELECT * FROM test_cases WHERE assignment_id = ?", (assignment_id,)
    ).fetchall()
    submissions = conn.execute(
        "SELECT * FROM submissions WHERE assignment_id = ?", (assignment_id,)
    ).fetchall()

    if not test_cases:
        flash("Add at least one test case before grading.", "error")
        conn.close()
        return redirect(url_for("view_assignment", assignment_id=assignment_id))

    for sub in submissions:
        score, per_test_results = grade_submission(sub, test_cases)

        conn.execute("DELETE FROM grading_results WHERE submission_id = ?", (sub["id"],))
        for r in per_test_results:
            conn.execute(
                "INSERT INTO grading_results "
                "(submission_id, test_case_id, passed, actual_output, error_message, execution_time_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    sub["id"], r["test_case_id"], int(r["passed"]),
                    r["actual_output"], r["error_message"], r["execution_time_ms"],
                ),
            )
        conn.execute(
            "UPDATE submissions SET score = ?, graded_at = ? WHERE id = ?",
            (score, now(), sub["id"]),
        )

    conn.commit()
    conn.close()
    flash(f"Graded {len(submissions)} submission(s).", "success")
    return redirect(url_for("results", assignment_id=assignment_id))


@app.route("/assignment/<int:assignment_id>/results")
@login_required
def results(assignment_id):
    user = get_current_user()
    conn = get_connection()
    assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()

    if user["role"] == "teacher":
        submissions = conn.execute(
            "SELECT * FROM submissions WHERE assignment_id = ? ORDER BY score DESC", (assignment_id,)
        ).fetchall()
    else:
        # Defense in depth: even if a student guessed another student's
        # results URL, this filter means they'd just see an empty page -
        # the query itself can only ever return their own row.
        submissions = conn.execute(
            "SELECT * FROM submissions WHERE assignment_id = ? AND user_id = ? ORDER BY score DESC",
            (assignment_id, user["id"]),
        ).fetchall()

    # The latest attempt per student is the one that counts (policy: most
    # recent attempt is the official score) - mark it so the template can
    # highlight it among a student's other attempts.
    latest_ids = set()
    by_user = {}
    for sub in submissions:
        uid = sub["user_id"]
        if uid is not None and (uid not in by_user or sub["submitted_at"] > by_user[uid]["submitted_at"]):
            by_user[uid] = sub
    latest_ids = {sub["id"] for sub in by_user.values()}

    details = {}
    for sub in submissions:
        rows = conn.execute(
            """
            SELECT gr.*, tc.input_data, tc.expected_output
            FROM grading_results gr JOIN test_cases tc ON gr.test_case_id = tc.id
            WHERE gr.submission_id = ?
            """,
            (sub["id"],),
        ).fetchall()
        details[sub["id"]] = rows
    conn.close()
    return render_template(
        "results.html", assignment=assignment, submissions=submissions, details=details, latest_ids=latest_ids
    )


@app.route("/my-results")
@login_required
def my_results():
    user = get_current_user()
    if user["role"] != "student":
        flash("This page is for student accounts.", "error")
        return redirect(url_for("dashboard"))

    conn = get_connection()
    # One row per assignment the student has ever submitted to, using their
    # LATEST attempt's score - matches the "most recent attempt counts" policy.
    rows = conn.execute(
        """
        SELECT a.id AS assignment_id, a.name AS assignment_name, a.due_date,
               c.name AS classroom_name,
               s.score, s.is_late, s.attempt_number, s.submitted_at
        FROM submissions s
        JOIN assignments a ON s.assignment_id = a.id
        LEFT JOIN classrooms c ON a.classroom_id = c.id
        WHERE s.user_id = ?
          AND s.submitted_at = (
              SELECT MAX(s2.submitted_at) FROM submissions s2
              WHERE s2.assignment_id = s.assignment_id AND s2.user_id = s.user_id
          )
        ORDER BY s.submitted_at DESC
        """,
        (user["id"],),
    ).fetchall()
    conn.close()
    return render_template("my_results.html", rows=rows)


# ------------------------------------------------------------- plagiarism
# Every route below is teacher-only: a plagiarism report or diff view is,
# by definition, another student's code - a student account must never
# be able to reach these, regardless of what URL they type.

@app.route("/assignment/<int:assignment_id>/check_plagiarism", methods=["POST"])
@teacher_required
def check_plagiarism(assignment_id):
    conn = get_connection()
    assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if assignment is None or not teacher_owns_assignment(conn, get_current_user(), assignment):
        conn.close()
        flash("You can only run this on your own assignments.", "error")
        return redirect(url_for("dashboard"))

    submissions = conn.execute(
        "SELECT * FROM submissions WHERE assignment_id = ?", (assignment_id,)
    ).fetchall()

    if len(submissions) < 2:
        flash("Need at least two submissions to compare.", "error")
        conn.close()
        return redirect(url_for("view_assignment", assignment_id=assignment_id))

    pair_results = compute_plagiarism(submissions, threshold=assignment["plagiarism_threshold"])

    conn.execute("DELETE FROM plagiarism_results WHERE assignment_id = ?", (assignment_id,))
    for r in pair_results:
        conn.execute(
            "INSERT INTO plagiarism_results "
            "(assignment_id, submission_id_1, submission_id_2, token_similarity, text_similarity, "
            "combined_score, flagged, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                assignment_id, r["submission_id_1"], r["submission_id_2"],
                r["token_similarity"], r["text_similarity"], r["combined_score"],
                int(r["flagged"]), now(),
            ),
        )
    conn.commit()
    conn.close()
    flash(f"Compared {len(submissions)} submissions ({len(pair_results)} pairs).", "success")
    return redirect(url_for("plagiarism_view", assignment_id=assignment_id))


@app.route("/assignment/<int:assignment_id>/plagiarism")
@teacher_required
def plagiarism_view(assignment_id):
    conn = get_connection()
    assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if assignment is None or not teacher_owns_assignment(conn, get_current_user(), assignment):
        conn.close()
        flash("You can only view reports for your own assignments.", "error")
        return redirect(url_for("dashboard"))

    pairs = conn.execute(
        """
        SELECT pr.*, s1.student_name AS student_1, s2.student_name AS student_2
        FROM plagiarism_results pr
        JOIN submissions s1 ON pr.submission_id_1 = s1.id
        JOIN submissions s2 ON pr.submission_id_2 = s2.id
        WHERE pr.assignment_id = ?
        ORDER BY pr.combined_score DESC
        """,
        (assignment_id,),
    ).fetchall()
    conn.close()
    return render_template("plagiarism.html", assignment=assignment, pairs=pairs)


@app.route("/compare/<int:sub_id_1>/<int:sub_id_2>")
@teacher_required
def compare(sub_id_1, sub_id_2):
    conn = get_connection()
    sub1 = conn.execute("SELECT * FROM submissions WHERE id = ?", (sub_id_1,)).fetchone()
    sub2 = conn.execute("SELECT * FROM submissions WHERE id = ?", (sub_id_2,)).fetchone()
    if sub1 is None or sub2 is None:
        conn.close()
        flash("Submission not found.", "error")
        return redirect(url_for("dashboard"))

    assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (sub1["assignment_id"],)).fetchone()
    if assignment is None or not teacher_owns_assignment(conn, get_current_user(), assignment):
        conn.close()
        flash("You can only compare submissions for your own assignments.", "error")
        return redirect(url_for("dashboard"))
    conn.close()

    differ = difflib.HtmlDiff(wrapcolumn=80)
    diff_html = differ.make_table(
        sub1["code"].splitlines(), sub2["code"].splitlines(),
        fromdesc=sub1["student_name"], todesc=sub2["student_name"],
        context=True, numlines=3,
    )
    return render_template("compare.html", sub1=sub1, sub2=sub2, diff_html=diff_html)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
