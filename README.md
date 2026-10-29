# Ledger — Automated Code Grader with Plagiarism Detection

A web app that runs student **Java or Python** submissions against instructor-defined
test cases, scores them automatically, and flags likely plagiarism between
submissions using a combination of structural and textual similarity analysis.

Built as a college project. This document doubles as the project report outline —
use the section headers below as your report's table of contents.

---

## 1. Tech stack

| Layer | Technology | Why |
|---|---|---|
| Backend / web server | Python 3, Flask | Small, easy to explain line-by-line in a viva |
| Grading targets | Python & Java | The two languages the tool can grade — run via `subprocess` + `python3` / `javac`+`java` |
| Plagiarism detection | Python (`scikit-learn`, stdlib `tokenize`) | TF-IDF cosine + custom k-gram winnowing |
| Storage | SQLite | Zero-config, file-based, plenty for a course-sized dataset |
| Frontend | Server-rendered Jinja2 templates, vanilla CSS/JS | No build step, easy to demo on any machine |

Java is graded, not used to build the tool itself — the grader launches `javac`/`java`
as subprocesses. This is the natural design once you're building a **multi-language**
grader: the tool's own implementation language (Python) is decoupled from the
languages it evaluates (Python and Java).

---

## 2. Setup

**Requirements:** Python 3.10+, and a JDK (`javac`/`java` on PATH) if you want to grade
Java submissions — Python-only grading works without a JDK.

```bash
cd codegrader
pip install -r backend/requirements.txt
python run.py
```

Open `http://127.0.0.1:5000` — you'll land on the login page. Register at least two
accounts to try it properly: one **teacher** account (creates the assignment, grades,
checks plagiarism) and one or more **student** accounts (submit code, see only their
own results). Use the sample files below once you're logged in as a student.

Sample submissions to try the plagiarism detector with are in `sample_submissions/`:
`Alice_Sum.py` and `Charlie_Sum.py` are the same logic with renamed variables (should
flag near 100%); `Bob_Sum.py` has a genuine bug (subtracts instead of adds). Submit
each one from a *different* student account, then log in as the teacher to grade and
run the plagiarism check.

---

## 3. Architecture

```
codegrader/
├── run.py                        # entry point
├── backend/
│   ├── app.py                    # Flask routes (auth, dashboard, assignment, grading, plagiarism)
│   ├── auth.py                    # session login, password hashing, role decorators
│   ├── database.py                # SQLite schema + connection helper
│   ├── grader/
│   │   ├── python_grader.py       # subprocess execution of .py submissions
│   │   ├── java_grader.py         # javac compile + java execution
│   │   └── grader_engine.py       # language-agnostic orchestration + scoring
│   └── plagiarism/
│       ├── tokenizer.py           # Python/Java source -> normalized token stream
│       ├── fingerprint.py         # k-gram winnowing (structural similarity)
│       ├── text_similarity.py     # TF-IDF cosine (textual similarity)
│       └── plagiarism_engine.py   # combines both signals per submission pair
└── frontend/
    ├── templates/                 # Jinja2 pages
    └── static/                    # CSS + JS
```

### Data flow

1. Instructor creates an **Assignment** with **Test Cases** (stdin → expected stdout).
2. Students (or the instructor, for a demo) **submit** `.py`/`.java` files or pasted code.
3. **Grading**: each submission is run once per test case in a subprocess with a
   timeout; output is normalized (trailing-whitespace-tolerant) and compared to the
   expected output; the score is the weighted percentage of test cases passed.
4. **Plagiarism check**: every pair of submissions *in the same language* is compared
   and stored with three scores (structural, textual, combined).

---

## 4. Grading engine

- **Python**: `subprocess.run([sys.executable, path], input=stdin_data, timeout=5)`.
- **Java**: the source is written to a temp file named after its `public class`
  (extracted with a regex, since `javac` requires the filename to match), compiled
  with `javac`, then run with `java -cp <dir> <ClassName>`.
- Both paths capture stdout/stderr and wall-clock time, and enforce a timeout so an
  infinite loop in a submission can't hang the grader.
- **Sandboxing caveat** (worth stating explicitly in your report): this uses
  process-level isolation only (separate OS process + timeout, no `shell=True`).
  It is **not** a full security sandbox — for a real deployment with untrusted code
  you'd add OS-level isolation (containers, `seccomp`, restricted users). For a
  classroom tool grading your own students' work, this tradeoff is reasonable and
  is worth naming as a "future work" item.

---

## 5. Plagiarism detection — the two-signal design

This is the part most worth explaining carefully, because a single similarity
metric is easy to fool or easy to false-positive on.

**Step 1 — Tokenization (`tokenizer.py`).**
Source code is converted into a normalized token stream: identifiers become `ID`,
numbers become `NUM`, strings become `STR`, comments are dropped, and
keywords/operators are kept as-is. This means renaming a variable from `total` to
`t` does not change the token stream at all — it defeats the most common shallow
disguise technique.

**Step 2 — Structural similarity (`fingerprint.py`).**
A **k-gram winnowing** algorithm (the same family MOSS/JPlag use) slides a window
over the token stream, hashes each window, and keeps only local-minimum hashes to
build a compact *fingerprint set* per submission. Two submissions' similarity is the
Jaccard index of their fingerprint sets. This catches copied *structure* even when
statements are reordered or formatting changes completely.

**Step 3 — Textual similarity (`text_similarity.py`).**
A straightforward TF-IDF + cosine similarity over the same token stream, as a fast
corroborating signal.

**Step 4 — Combination (`plagiarism_engine.py`).**
```
combined_score = 0.6 × structural + 0.4 × textual
```
Weighted toward structural similarity because it survives cosmetic changes better.
During testing, a case came up that's worth including in your report as a
justification for using two signals rather than one: two genuinely different
solutions to the same trivial problem scored **90% on text similarity alone**
(they share a lot of common vocabulary — `input`, `split`, `int`, `print`) but only
**4% structurally** — the combined score correctly stayed low (39%), where a
text-only detector would have produced a false positive.

**Known limitation** (also worth a report line): very short/trivial programs have
little room for structural variation, so even honest, independently-written
solutions can score moderately high. The flag threshold is configurable per
assignment for this reason — bump it up for simple assignments.

---

## 6. Roles and access control

The app now has real accounts instead of one shared, unrestricted view. Anyone can
register as either a **teacher** or a **student** (`/register`); what they can do
afterward depends on that role, enforced on the *server* — not just hidden in the UI
— via helpers in `backend/auth.py` and `backend/app.py`.

| Action | Teacher | Student |
|---|---|---|
| Create classrooms / assignments / test cases | ✅, own classrooms only | ❌ |
| Edit or delete a test case after creation | ✅, own assignments only | — |
| Submit code | — | ✅, under their own logged-in identity |
| Trigger grading | ✅, own assignments only | ❌ |
| Run / view the plagiarism report, or the diff view | ✅, own assignments only | ❌ |
| View grading results | ✅ sees everyone in own assignments | ✅ sees **only their own** |

`@login_required` blocks any page from an anonymous visitor. `@teacher_required`
blocks the teacher-only actions above. On top of role, every teacher action also
checks **classroom ownership** — Teacher A can never grade, view the plagiarism
report, or open the roster for a classroom Teacher B created, even by guessing the
URL. This was verified directly (not just read from the code): a second teacher
account was created and confirmed blocked from every one of the first teacher's
classroom-scoped actions.

**Passwords** are hashed with `werkzeug.security` (ships with Flask, no extra
dependency) — never stored or compared in plaintext.

**Known simplification, worth naming in your report:** registration doesn't gate
who can sign up as "teacher" — anyone can pick either role. For a real deployment
you'd add an invite code, admin approval, or institutional SSO for teacher accounts.

---

## 7. Classrooms, deadlines, attempts, and analytics

- **Classrooms.** A teacher creates a classroom and gets a short join code; students
  enter that code once to join (`/classroom/join`). Assignments live inside a
  classroom, so a teacher's dashboard shows their classrooms, and a student's
  dashboard shows the classrooms they've joined — not a flat, unscoped list of
  every assignment on the server. Assignments created before this feature existed
  (`classroom_id IS NULL`) stay visible to everyone, so old data isn't orphaned.
- **Deadlines.** An assignment can have an optional due date. A submission made
  after it is stored with `is_late = 1` and shown with a **LATE** badge everywhere
  it appears (assignment page, results page, the student's own results page) —
  nothing is blocked, it's informational, matching how most classrooms actually
  handle "late but still accepted" work.
- **Attempt limits.** An assignment can optionally cap attempts per student
  (`max_attempts`); left blank, attempts are unlimited. The server counts a
  student's prior submissions before accepting a new one and rejects further
  attempts past the cap — checked in the route itself, not just hidden in the UI.
  **Policy: the most recent attempt is the one that counts** as the official score
  wherever a single number is shown (the student's own results page, and any
  cross-assignment summary) — every attempt is still kept and viewable individually
  on the per-assignment results page, just marked which one is "latest."
- **Analytics.** Both the classroom page and each assignment page show a teacher-only
  summary: average score, how many submissions are graded, how many scored 100%,
  and how many submission pairs got flagged for plagiarism — computed with plain
  SQL aggregates (`AVG`, `COUNT`), no separate analytics library.
- **Editable test cases** (`/assignment/<id>/test_cases`). If a teacher makes a
  mistake in a test case — wrong expected output, typo in the input — they can fix
  it, delete it, or add new ones after the assignment is already live, without
  recreating the whole assignment. This does **not** silently re-grade existing
  submissions (grading is only triggered explicitly, so it stays predictable) — the
  page reminds the teacher to click "Grade all submissions" again afterward.

---

## 8. Possible extensions (future work section)

- Restrict teacher sign-up (invite code, admin approval, or SSO), instead of open
  self-registration for both roles.
- AST-based comparison per language (e.g. `ast` module for Python, `javaparser` for
  Java) instead of regex/token-based normalization, for even more disguise-resistance.
- Container-based sandboxing (Docker) for untrusted submissions.
- CSV export of a classroom's or assignment's grades.
- Configurable per-test-case time and memory limits.
- Best-of-attempts as an alternative scoring policy, configurable per assignment
  (currently latest-attempt-counts is the only policy).
