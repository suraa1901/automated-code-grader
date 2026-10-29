"""
auth.py
Minimal session-based authentication with two roles: teacher and student.

Deliberately simple (no Flask-Login, no JWT, no external auth service) -
a signed Flask session cookie stores the logged-in user's id, and two
small decorators gate access by role. Passwords are hashed with
werkzeug's scrypt-based helpers, which ship with Flask itself so this
adds no new dependency.

Role model:
- teacher: full access - create assignments, grade, run plagiarism
  checks, view every submission and every report.
- student: can view assignments and their own results only. Cannot see
  other students' code or scores, cannot see plagiarism reports or the
  diff comparison view (both would leak other students' code), cannot
  create assignments, and cannot trigger grading or plagiarism runs.
"""

from functools import wraps

from flask import session, redirect, url_for, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

from database import get_connection


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password, password_hash):
    return check_password_hash(password_hash, password)


def get_current_user():
    """Returns the logged-in user's DB row, or None. Cached per-request on g."""
    if "user_id" not in session:
        return None
    if not hasattr(g, "_current_user"):
        conn = get_connection()
        g._current_user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        conn.close()
    return g._current_user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if get_current_user() is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def teacher_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        if user["role"] != "teacher":
            flash("That action is only available to teacher accounts.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped
