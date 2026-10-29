import sqlite3
import os
from datetime import datetime

# Resolve the absolute path to ensure data directory creation works on Linux/Render
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "data")
DB_PATH = os.path.abspath(os.path.join(DATA_DIR, "grader.db"))

def get_connection():
    # Make sure the target 'data' directory exists before attempting to connect
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_connection()
    c = conn.cursor()

    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',  -- teacher / student
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS classrooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            join_code TEXT NOT NULL UNIQUE,
            teacher_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (teacher_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS classroom_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            classroom_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,
            UNIQUE(classroom_id, user_id),
            FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            classroom_id INTEGER,
            name TEXT NOT NULL,
            description TEXT,
            allowed_language TEXT NOT NULL DEFAULT 'both',  -- python / java / both
            plagiarism_threshold REAL NOT NULL DEFAULT 70.0,
            due_date TEXT,                    -- ISO datetime, NULL = no deadline
            max_attempts INTEGER,             -- NULL/0 = unlimited
            created_at TEXT NOT NULL,
            FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS test_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            input_data TEXT NOT NULL DEFAULT '',
            expected_output TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            is_hidden INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            user_id INTEGER,
            student_name TEXT NOT NULL,
            language TEXT NOT NULL,          -- python / java
            filename TEXT NOT NULL,
            code TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            attempt_number INTEGER NOT NULL DEFAULT 1,
            is_late INTEGER NOT NULL DEFAULT 0,
            score REAL,
            graded_at TEXT,
            FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS grading_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            test_case_id INTEGER NOT NULL,
            passed INTEGER NOT NULL,
            actual_output TEXT,
            error_message TEXT,
            execution_time_ms REAL,
            FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE,
            FOREIGN KEY (test_case_id) REFERENCES test_cases(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS plagiarism_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            submission_id_1 INTEGER NOT NULL,
            submission_id_2 INTEGER NOT NULL,
            token_similarity REAL NOT NULL,
            text_similarity REAL NOT NULL,
            combined_score REAL NOT NULL,
            flagged INTEGER NOT NULL DEFAULT 0,
            computed_at TEXT NOT NULL,
            FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
            FOREIGN KEY (submission_id_1) REFERENCES submissions(id) ON DELETE CASCADE,
            FOREIGN KEY (submission_id_2) REFERENCES submissions(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()

    # ---- Migrations for databases created before this feature set existed.
    # SQLite has no "ADD COLUMN IF NOT EXISTS", so each one is guarded by a
    # schema check first. Safe to run every time the app starts.
    def add_column_if_missing(table, column, coldef):
        cols = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
            conn.commit()

    add_column_if_missing("submissions", "user_id", "user_id INTEGER REFERENCES users(id)")
    add_column_if_missing("submissions", "attempt_number", "attempt_number INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing("submissions", "is_late", "is_late INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing("assignments", "classroom_id", "classroom_id INTEGER REFERENCES classrooms(id)")
    add_column_if_missing("assignments", "due_date", "due_date TEXT")
    add_column_if_missing("assignments", "max_attempts", "max_attempts INTEGER")

    conn.close()

# Initialize tables when database module loads
init_db()

def now():
    return datetime.utcnow().isoformat(timespec="seconds")