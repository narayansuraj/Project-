"""LearnGap - Learning Gap Identification & Intervention Platform (Flask REST API).

Run:  python seed.py && python app.py      ->  http://127.0.0.1:5000
Security controls are marked with  [SEC]  comments.
"""
import csv
import io
import logging
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, g, jsonify, redirect, request, send_from_directory,
                   session)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import storage

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("LEARNGAP_DB", os.path.join(BASE, "learngap.db"))
GAP_THRESHOLD = 60.0

app = Flask(__name__, static_folder="static", static_url_path="/static")
# [SEC] Secrets come from environment variables / Azure Key Vault, never from source code.
_secret = os.environ.get("LEARNGAP_SECRET_KEY")
if not _secret:
    _secret = secrets.token_hex(32)
    logging.warning("LEARNGAP_SECRET_KEY not set - using a temporary key (sessions reset on restart).")
HTTPS = os.environ.get("LEARNGAP_HTTPS", "0") == "1"
app.config.update(
    SECRET_KEY=_secret,
    SESSION_COOKIE_HTTPONLY=True,          # [SEC] JavaScript cannot read the session cookie
    SESSION_COOKIE_SAMESITE="Strict",      # [SEC] cookie not sent on cross-site requests
    SESSION_COOKIE_SECURE=HTTPS,           # [SEC] cookie only over HTTPS when deployed
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,   # [SEC] 10 MB upload limit
)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# --------------------------------------------------------------------------- database
def init_db_if_missing():
    if not os.path.exists(DB_PATH):
        con = sqlite3.connect(DB_PATH)
        with open(os.path.join(BASE, "schema.sql"), encoding="utf-8") as fh:
            con.executescript(fh.read())
        con.close()
        logging.info("Created empty database. Run `python seed.py --reset` for demo data.")


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, isolation_level=None)   # explicit transactions below
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def q(sql, params=(), one=False):
    """[SEC] All SQL uses ? placeholders - user input is never concatenated (stops SQL injection)."""
    cur = db().execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows


def log_action(action, entity=None, entity_id=None, detail=None, user_id=None):
    """[SEC] Activity log / audit trail."""
    uid = user_id if user_id is not None else session.get("user_id")
    db().execute(
        "INSERT INTO activity_log (user_id, action, entity, entity_id, ip_address, detail) VALUES (?,?,?,?,?,?)",
        (uid, action, entity, entity_id, request.remote_addr, (detail or "")[:500]))


# --------------------------------------------------------------------------- validation
class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error=e.message), e.status


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error="File too large (max 10 MB)."), 413


@app.errorhandler(404)
def not_found(_e):
    return (jsonify(error="Not found"), 404) if request.path.startswith("/api") else redirect("/")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if hasattr(e, "code") and isinstance(e.code, int):      # HTTP errors from werkzeug
        return jsonify(error=getattr(e, "description", "Error")), e.code
    logging.exception("Unhandled error")                    # [SEC] details only in server log
    return jsonify(error="Internal server error"), 500


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Expected a JSON object body.")
    return data


def v_str(data, key, lo=1, hi=200, pattern=None, required=True):
    val = data.get(key)
    if val is None or val == "":
        if required:
            raise ApiError(f"'{key}' is required.")
        return None
    if not isinstance(val, str):
        raise ApiError(f"'{key}' must be text.")
    val = val.strip()
    if not (lo <= len(val) <= hi):
        raise ApiError(f"'{key}' must be {lo}-{hi} characters.")
    if pattern and not re.fullmatch(pattern, val):
        raise ApiError(f"'{key}' has an invalid format.")
    return val


def v_int(data, key, required=True):
    val = data.get(key)
    if val is None and not required:
        return None
    if isinstance(val, bool) or not isinstance(val, (int, str)) or not str(val).lstrip("-").isdigit():
        raise ApiError(f"'{key}' must be an integer.")
    return int(val)


def v_num(data, key, lo, hi):
    val = data.get(key)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError(f"'{key}' must be a number.")
    if not (lo <= val <= hi):
        raise ApiError(f"'{key}' must be between {lo} and {hi}.")
    return float(val)


def v_date(data, key):
    val = v_str(data, key, 10, 10, r"\d{4}-\d{2}-\d{2}")
    try:
        datetime.strptime(val, "%Y-%m-%d")
    except ValueError:
        raise ApiError(f"'{key}' is not a valid date (YYYY-MM-DD).")
    return val


def v_choice(data, key, choices):
    val = data.get(key)
    if val not in choices:
        raise ApiError(f"'{key}' must be one of: {', '.join(choices)}.")
    return val


def arg_int(name, required=True):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            raise ApiError(f"Query parameter '{name}' is required.")
        return None
    if not raw.isdigit():
        raise ApiError(f"Query parameter '{name}' must be an integer.")
    return int(raw)


# --------------------------------------------------------------------------- auth & roles
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    u = q("SELECT user_id, username, role, full_name, email, is_active FROM users WHERE user_id = ?", (uid,), one=True)
    if not u or not u["is_active"]:
        session.clear()
        return None
    if u["role"] == "student":
        u["student_id"] = q("SELECT student_id FROM students WHERE user_id=?", (uid,), one=True)["student_id"]
    if u["role"] == "teacher":
        u["teacher_id"] = q("SELECT teacher_id FROM teachers WHERE user_id=?", (uid,), one=True)["teacher_id"]
    return u


def require(*roles):
    """[SEC] Role-based access control decorator; also enforces the CSRF token on writes."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            user = current_user()
            if not user:
                raise ApiError("Please log in.", 401)
            if roles and user["role"] not in roles:
                log_action("access_denied", detail=f"{request.method} {request.path}", user_id=user["user_id"])
                raise ApiError("You do not have permission for this action.", 403)
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                token = request.headers.get("X-CSRF-Token", "")
                if not secrets.compare_digest(token, session.get("csrf", "")):
                    raise ApiError("Invalid CSRF token.", 403)
            g.user = user
            return fn(*a, **kw)
        return wrapper
    return deco


def teacher_class_ids(user):
    if user["role"] == "admin":
        return [r["class_id"] for r in q("SELECT class_id FROM classes")]
    return [r["class_id"] for r in q(
        "SELECT DISTINCT class_id FROM teaching_assignments WHERE teacher_id=?", (user["teacher_id"],))]


def teacher_subject_ids(user, class_id=None):
    if user["role"] == "admin":
        return [r["subject_id"] for r in q("SELECT subject_id FROM subjects")]
    sql = "SELECT DISTINCT subject_id FROM teaching_assignments WHERE teacher_id=?"
    params = [user["teacher_id"]]
    if class_id:
        sql += " AND class_id=?"
        params.append(class_id)
    return [r["subject_id"] for r in q(sql, params)]


def check_class(user, class_id):
    if class_id not in teacher_class_ids(user):
        raise ApiError("You are not assigned to this class.", 403)


def check_student(user, student_id):
    """Teachers may only see students of their own classes."""
    row = q("SELECT class_id FROM students WHERE student_id=?", (student_id,), one=True)
    if not row:
        raise ApiError("Student not found.", 404)
    check_class(user, row["class_id"])
    return row["class_id"]


PASSWORD_RE = re.compile(r"(?=.*[A-Za-z])(?=.*\d).{8,64}")


@app.post("/api/auth/login")
def login():
    data = body()
    username = v_str(data, "username", 3, 40)
    password = v_str(data, "password", 1, 128)
    u = q("SELECT * FROM users WHERE username = ?", (username,), one=True)
    now = datetime.utcnow()
    if u and u["locked_until"] and datetime.fromisoformat(u["locked_until"]) > now:
        raise ApiError("Account temporarily locked after repeated failures. Try again in a few minutes.", 429)
    if not u or not u["is_active"] or not check_password_hash(u["password_hash"], password):
        if u:   # [SEC] brute-force protection: lock after 5 consecutive failures
            fails = u["failed_logins"] + 1
            locked = (now + timedelta(minutes=5)).isoformat() if fails >= 5 else None
            db().execute("UPDATE users SET failed_logins=?, locked_until=? WHERE user_id=?",
                         (0 if locked else fails, locked, u["user_id"]))
        log_action("login_failed", "user", u["user_id"] if u else None, f"username={username}",
                   user_id=u["user_id"] if u else None)
        raise ApiError("Invalid username or password.", 401)   # same message for every failure
    db().execute("UPDATE users SET failed_logins=0, locked_until=NULL WHERE user_id=?", (u["user_id"],))
    session.clear()                                            # [SEC] prevents session fixation
    session.permanent = True
    session["user_id"] = u["user_id"]
    session["csrf"] = secrets.token_hex(16)
    log_action("login_success", "user", u["user_id"], user_id=u["user_id"])
    return jsonify(user=current_user(), csrf=session["csrf"])


@app.post("/api/auth/logout")
@require()
def logout():
    log_action("logout", "user", g.user["user_id"])
    session.clear()
    return jsonify(ok=True)


@app.get("/api/auth/me")
def me():
    user = current_user()
    if not user:
        return jsonify(user=None)
    return jsonify(user=user, csrf=session.get("csrf"))


@app.post("/api/auth/change-password")
@require()
def change_password():
    data = body()
    row = q("SELECT password_hash FROM users WHERE user_id=?", (g.user["user_id"],), one=True)
    if not check_password_hash(row["password_hash"], v_str(data, "current_password", 1, 128)):
        raise ApiError("Current password is incorrect.", 401)
    new = v_str(data, "new_password", 8, 64)
    if not PASSWORD_RE.fullmatch(new):
        raise ApiError("New password needs 8+ characters with letters and digits.")
    db().execute("UPDATE users SET password_hash=? WHERE user_id=?", (generate_password_hash(new), g.user["user_id"]))
    log_action("password_changed", "user", g.user["user_id"])
    return jsonify(ok=True)


# [SEC] security headers on every response
@app.after_request
def security_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Cache-Control"] = "no-store" if request.path.startswith("/api") else "no-cache"
    if HTTPS:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


@app.before_request
def enforce_https():
    # [SEC] When deployed behind Azure App Service, redirect HTTP to HTTPS.
    if HTTPS and request.headers.get("X-Forwarded-Proto", "https") == "http":
        return redirect(request.url.replace("http://", "https://", 1), code=301)


# --------------------------------------------------------------------------- shared helpers
def student_gaps(student_id, status="open"):
    return q(
        "SELECT g.gap_id, g.topic_id, t.name AS topic_name, s.name AS subject_name, g.mastery_pct, "
        "g.severity, g.status, g.detected_at, g.resolved_at, "
        "(SELECT COUNT(*) FROM interventions i WHERE i.gap_id = g.gap_id AND i.status IN ('planned','in_progress')) AS active_interventions "
        "FROM learning_gaps g JOIN topics t ON t.topic_id=g.topic_id JOIN subjects s ON s.subject_id=t.subject_id "
        "WHERE g.student_id=? AND g.status=? ORDER BY g.mastery_pct", (student_id, status))


def student_overview(student_id):
    summary = q("SELECT * FROM v_student_assessment_summary WHERE student_id=? ORDER BY assessment_date, assessment_id",
                (student_id,))
    topics = q("SELECT topic_id, topic_name, subject_id, attempts, avg_pct FROM v_student_topic_performance "
               "WHERE student_id=? ORDER BY avg_pct", (student_id,))
    # per-topic trend over time (Feature 5: improvement tracking)
    trend = q("SELECT sc.topic_id, t.name AS topic_name, a.assessment_date, a.title, "
              "ROUND(100.0*sc.marks/sc.max_marks,1) AS pct FROM assessment_scores sc "
              "JOIN assessments a ON a.assessment_id=sc.assessment_id JOIN topics t ON t.topic_id=sc.topic_id "
              "WHERE sc.student_id=? ORDER BY a.assessment_date", (student_id,))
    return {"assessments": summary, "topics": topics, "trend": trend}


def student_interventions(student_id):
    interventions = q(
        "SELECT i.intervention_id, i.intervention_type, i.plan, i.start_date, i.due_date, i.status, i.outcome, "
        "i.mastery_at_start, g.mastery_pct AS mastery_now, t.name AS topic_name, u.full_name AS teacher_name "
        "FROM interventions i JOIN learning_gaps g ON g.gap_id=i.gap_id JOIN topics t ON t.topic_id=g.topic_id "
        "JOIN teachers te ON te.teacher_id=i.teacher_id JOIN users u ON u.user_id=te.user_id "
        "WHERE g.student_id=? ORDER BY i.created_at DESC, i.intervention_id DESC", (student_id,))
    for i in interventions:
        i["followups"] = q("SELECT followup_date, notes, mastery_snapshot FROM intervention_followups "
                           "WHERE intervention_id=? ORDER BY followup_date", (i["intervention_id"],))
    return interventions


def progress_summary(student_id):
    gaps_all = q("SELECT status, COUNT(*) AS n FROM learning_gaps WHERE student_id=? GROUP BY status", (student_id,))
    counts = {r["status"]: r["n"] for r in gaps_all}
    res = q("SELECT status, COUNT(*) AS n FROM resource_progress WHERE student_id=? GROUP BY status", (student_id,))
    rcount = {r["status"]: r["n"] for r in res}
    asm = q("SELECT pct FROM v_student_assessment_summary WHERE student_id=? ORDER BY assessment_date", (student_id,))
    first = asm[0]["pct"] if asm else None
    last = asm[-1]["pct"] if asm else None
    # most-improved topic: last result minus first result
    improved = q(
        "SELECT t.name AS topic_name, "
        "ROUND((SELECT 100.0*marks/max_marks FROM assessment_scores x JOIN assessments ax ON ax.assessment_id=x.assessment_id "
        "WHERE x.student_id=sc.student_id AND x.topic_id=sc.topic_id ORDER BY ax.assessment_date DESC LIMIT 1) - "
        "(SELECT 100.0*marks/max_marks FROM assessment_scores y JOIN assessments ay ON ay.assessment_id=y.assessment_id "
        "WHERE y.student_id=sc.student_id AND y.topic_id=sc.topic_id ORDER BY ay.assessment_date ASC LIMIT 1),1) AS change "
        "FROM assessment_scores sc JOIN topics t ON t.topic_id=sc.topic_id WHERE sc.student_id=? GROUP BY sc.topic_id "
        "ORDER BY change DESC LIMIT 3", (student_id,))
    return {"open_gaps": counts.get("open", 0), "resolved_gaps": counts.get("resolved", 0),
            "resources_completed": rcount.get("completed", 0), "resources_in_progress": rcount.get("in_progress", 0),
            "first_pct": first, "latest_pct": last, "top_improvements": improved}


# --------------------------------------------------------------------------- STUDENT API
@app.get("/api/student/overview")
@require("student")
def api_student_overview():
    sid = g.user["student_id"]
    return jsonify(student_overview(sid))


@app.get("/api/student/gaps")
@require("student")
def api_student_gaps():
    sid = g.user["student_id"]
    return jsonify(open=student_gaps(sid, "open"), resolved=student_gaps(sid, "resolved"))


@app.get("/api/student/recommendations")
@require("student")
def api_student_recs():
    return jsonify(q(
        "SELECT * FROM v_recommendations WHERE student_id=? ORDER BY mastery_pct, match_rank, resource_type",
        (g.user["student_id"],)))


@app.post("/api/student/resources/<int:rid>/progress")
@require("student")
def api_resource_progress(rid):
    status = v_choice(body(), "status", ("in_progress", "completed"))
    if not q("SELECT 1 FROM resources WHERE resource_id=?", (rid,), one=True):
        raise ApiError("Resource not found.", 404)
    db().execute(
        "INSERT INTO resource_progress (student_id, resource_id, status) VALUES (?,?,?) "
        "ON CONFLICT(student_id, resource_id) DO UPDATE SET status=excluded.status, updated_at=datetime('now')",
        (g.user["student_id"], rid, status))
    log_action("resource_progress", "resource", rid, status)
    return jsonify(ok=True)


@app.get("/api/student/interventions")
@require("student")
def api_student_interventions():
    return jsonify(student_interventions(g.user["student_id"]))


@app.get("/api/student/progress")
@require("student")
def api_student_progress():
    return jsonify(progress_summary(g.user["student_id"]))


# --------------------------------------------------------------------------- RESOURCES (all roles)
@app.get("/api/resources/<int:rid>/open")
@require()
def open_resource(rid):
    r = q("SELECT blob_url FROM resources WHERE resource_id=?", (rid,), one=True)
    if not r:
        abort(404)
    ref = r["blob_url"]
    log_action("resource_opened", "resource", rid)
    if ref.startswith("local:"):
        name = secure_filename(ref[len("local:"):])                 # [SEC] no path traversal
        return send_from_directory(storage.UPLOAD_DIR, name, as_attachment=False)
    if ref.startswith("blob:"):
        return redirect(storage.blob_read_url(ref))                 # short-lived SAS link
    if ref.startswith("https://"):
        return redirect(ref)
    abort(404)


# --------------------------------------------------------------------------- TEACHER API
@app.get("/api/teacher/classes")
@require("teacher", "admin")
def api_teacher_classes():
    if g.user["role"] == "admin":
        rows = q("SELECT c.class_id, c.name, s.subject_id, s.name AS subject_name FROM classes c, subjects s ORDER BY c.name, s.name")
    else:
        rows = q("SELECT c.class_id, c.name, s.subject_id, s.name AS subject_name FROM teaching_assignments ta "
                 "JOIN classes c ON c.class_id=ta.class_id JOIN subjects s ON s.subject_id=ta.subject_id "
                 "WHERE ta.teacher_id=? ORDER BY c.name, s.name", (g.user["teacher_id"],))
    return jsonify(rows)


@app.get("/api/topics")
@require("teacher", "admin")
def api_topics():
    sid = arg_int("subject_id")
    return jsonify(q("SELECT topic_id, name FROM topics WHERE subject_id=? ORDER BY topic_id", (sid,)))


@app.get("/api/teacher/dashboard")
@require("teacher", "admin")
def api_teacher_dashboard():
    """Feature 6: class-level learning analytics."""
    class_id = arg_int("class_id")
    subject_id = arg_int("subject_id", required=False)
    check_class(g.user, class_id)
    allowed_subjects = teacher_subject_ids(g.user, class_id)
    if subject_id and subject_id not in allowed_subjects:
        raise ApiError("You do not teach this subject in this class.", 403)
    subs = [subject_id] if subject_id else allowed_subjects
    marks = ",".join("?" * len(subs))        # placeholders only - values stay parameterised

    topics = q(f"SELECT * FROM v_class_topic_analytics WHERE class_id=? AND subject_id IN ({marks}) "
               "ORDER BY class_avg_pct", [class_id, *subs])
    trend = q(f"SELECT a.assessment_id, a.title, a.assessment_date, ROUND(100.0*SUM(sc.marks)/SUM(sc.max_marks),1) AS avg_pct "
              "FROM assessments a JOIN assessment_scores sc ON sc.assessment_id=a.assessment_id "
              f"WHERE a.class_id=? AND a.subject_id IN ({marks}) GROUP BY a.assessment_id ORDER BY a.assessment_date",
              [class_id, *subs])
    n_students = q("SELECT COUNT(*) AS n FROM students WHERE class_id=?", (class_id,), one=True)["n"]
    gap_row = q(f"SELECT COUNT(*) AS open_gaps, SUM(g.severity='critical') AS critical, "
                "COUNT(DISTINCT g.student_id) AS students_at_risk "
                "FROM learning_gaps g JOIN students s ON s.student_id=g.student_id JOIN topics t ON t.topic_id=g.topic_id "
                f"WHERE s.class_id=? AND g.status='open' AND t.subject_id IN ({marks})", [class_id, *subs], one=True)
    no_action = q(f"SELECT COUNT(*) AS n FROM learning_gaps g JOIN students s ON s.student_id=g.student_id "
                  f"JOIN topics t ON t.topic_id=g.topic_id WHERE s.class_id=? AND g.status='open' AND t.subject_id IN ({marks}) "
                  "AND NOT EXISTS (SELECT 1 FROM interventions i WHERE i.gap_id=g.gap_id AND i.status IN ('planned','in_progress'))",
                  [class_id, *subs], one=True)["n"]
    outcomes = q(f"SELECT outcome, status, COUNT(*) AS n, ROUND(AVG(improvement),1) AS avg_improvement "
                 f"FROM v_intervention_outcomes WHERE class_id=? AND subject_id IN ({marks}) GROUP BY outcome, status",
                 [class_id, *subs])
    at_risk = q(f"SELECT s.student_id, u.full_name, s.roll_no, COUNT(*) AS open_gaps, ROUND(MIN(g.mastery_pct),1) AS lowest_mastery, "
                "GROUP_CONCAT(t.name, ', ') AS topics FROM learning_gaps g JOIN students s ON s.student_id=g.student_id "
                "JOIN users u ON u.user_id=s.user_id JOIN topics t ON t.topic_id=g.topic_id "
                f"WHERE s.class_id=? AND g.status='open' AND t.subject_id IN ({marks}) "
                "GROUP BY s.student_id ORDER BY open_gaps DESC, lowest_mastery LIMIT 8", [class_id, *subs])
    overall = q(f"SELECT ROUND(100.0*SUM(sc.marks)/SUM(sc.max_marks),1) AS avg FROM assessment_scores sc "
                "JOIN assessments a ON a.assessment_id=sc.assessment_id "
                f"WHERE a.class_id=? AND a.subject_id IN ({marks})", [class_id, *subs], one=True)["avg"]
    return jsonify(kpis={"students": n_students, "class_avg": overall, **gap_row, "gaps_without_intervention": no_action},
                   topics=topics, trend=trend, outcomes=outcomes, at_risk=at_risk)


@app.get("/api/teacher/students")
@require("teacher", "admin")
def api_teacher_students():
    class_id = arg_int("class_id")
    check_class(g.user, class_id)
    return jsonify(q(
        "SELECT s.student_id, s.roll_no, u.full_name, "
        "(SELECT ROUND(100.0*SUM(marks)/SUM(max_marks),1) FROM assessment_scores WHERE student_id=s.student_id) AS avg_pct, "
        "(SELECT COUNT(*) FROM learning_gaps WHERE student_id=s.student_id AND status='open') AS open_gaps, "
        "(SELECT COUNT(*) FROM learning_gaps WHERE student_id=s.student_id AND status='resolved') AS resolved_gaps "
        "FROM students s JOIN users u ON u.user_id=s.user_id WHERE s.class_id=? ORDER BY open_gaps DESC, u.full_name",
        (class_id,)))


@app.get("/api/teacher/students/<int:sid>")
@require("teacher", "admin")
def api_teacher_student_detail(sid):
    check_student(g.user, sid)
    info = q("SELECT s.student_id, s.roll_no, u.full_name, c.name AS class_name FROM students s "
             "JOIN users u ON u.user_id=s.user_id JOIN classes c ON c.class_id=s.class_id WHERE s.student_id=?", (sid,), one=True)
    return jsonify(info=info, overview=student_overview(sid), open=student_gaps(sid, "open"),
                   resolved=student_gaps(sid, "resolved"), interventions=student_interventions(sid),
                   progress=progress_summary(sid))


@app.get("/api/teacher/assessments")
@require("teacher", "admin")
def api_assessments_list():
    class_id = arg_int("class_id")
    check_class(g.user, class_id)
    return jsonify(q("SELECT a.assessment_id, a.title, a.assessment_date, s.name AS subject_name, "
                     "ROUND(100.0*SUM(sc.marks)/SUM(sc.max_marks),1) AS avg_pct, COUNT(DISTINCT sc.student_id) AS students "
                     "FROM assessments a JOIN subjects s ON s.subject_id=a.subject_id "
                     "LEFT JOIN assessment_scores sc ON sc.assessment_id=a.assessment_id "
                     "WHERE a.class_id=? AND a.subject_id IN (%s) GROUP BY a.assessment_id ORDER BY a.assessment_date DESC"
                     % ",".join("?" * len(teacher_subject_ids(g.user, class_id) or [0])),
                     [class_id, *(teacher_subject_ids(g.user, class_id) or [0])]))


@app.post("/api/teacher/assessments")
@require("teacher")
def api_assessment_create():
    """Feature 1: record performance. The whole assessment is saved in ONE transaction."""
    data = body()
    class_id, subject_id = v_int(data, "class_id"), v_int(data, "subject_id")
    check_class(g.user, class_id)
    if subject_id not in teacher_subject_ids(g.user, class_id):
        raise ApiError("You do not teach this subject in this class.", 403)
    title = v_str(data, "title", 2, 120)
    adate = v_date(data, "date")
    scores = data.get("scores")
    if not isinstance(scores, list) or not scores or len(scores) > 2000:
        raise ApiError("'scores' must be a non-empty list.")
    valid_students = {r["student_id"] for r in q("SELECT student_id FROM students WHERE class_id=?", (class_id,))}
    valid_topics = {r["topic_id"] for r in q("SELECT topic_id FROM topics WHERE subject_id=?", (subject_id,))}
    clean, seen = [], set()
    for row in scores:
        if not isinstance(row, dict):
            raise ApiError("Each score must be an object.")
        sid, tid = v_int(row, "student_id"), v_int(row, "topic_id")
        if sid not in valid_students or tid not in valid_topics:
            raise ApiError("Score refers to a student/topic outside this class and subject.")
        if (sid, tid) in seen:
            raise ApiError("Duplicate student/topic score in request.")
        seen.add((sid, tid))
        mx = v_num(row, "max_marks", 0.5, 1000)
        clean.append((sid, tid, v_num(row, "marks", 0, mx), mx))
    con = db()
    try:
        con.execute("BEGIN")                                          # transaction start
        aid = con.execute("INSERT INTO assessments (class_id, subject_id, title, assessment_date, created_by) VALUES (?,?,?,?,?)",
                          (class_id, subject_id, title, adate, g.user["teacher_id"])).lastrowid
        con.executemany("INSERT INTO assessment_scores (assessment_id, student_id, topic_id, marks, max_marks) VALUES (?,?,?,?,?)",
                        [(aid, *c) for c in clean])                    # triggers update learning_gaps
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")                                       # all-or-nothing
        raise
    log_action("assessment_created", "assessment", aid, f"{title}: {len(clean)} scores")
    return jsonify(assessment_id=aid, scores=len(clean)), 201


@app.get("/api/teacher/roster")
@require("teacher")
def api_roster():
    class_id = arg_int("class_id")
    check_class(g.user, class_id)
    return jsonify(q("SELECT s.student_id, s.roll_no, u.full_name FROM students s JOIN users u ON u.user_id=s.user_id "
                     "WHERE s.class_id=? ORDER BY s.roll_no", (class_id,)))


@app.get("/api/teacher/gaps")
@require("teacher", "admin")
def api_teacher_gaps():
    class_id = arg_int("class_id")
    check_class(g.user, class_id)
    subs = teacher_subject_ids(g.user, class_id) or [0]
    return jsonify(q(
        "SELECT g.gap_id, g.student_id, u.full_name, s.roll_no, t.name AS topic_name, sub.name AS subject_name, "
        "g.mastery_pct, g.severity, "
        "(SELECT COUNT(*) FROM interventions i WHERE i.gap_id=g.gap_id AND i.status IN ('planned','in_progress')) AS active_interventions "
        "FROM learning_gaps g JOIN students s ON s.student_id=g.student_id JOIN users u ON u.user_id=s.user_id "
        "JOIN topics t ON t.topic_id=g.topic_id JOIN subjects sub ON sub.subject_id=t.subject_id "
        "WHERE s.class_id=? AND g.status='open' AND t.subject_id IN (%s) ORDER BY g.mastery_pct" % ",".join("?" * len(subs)),
        [class_id, *subs]))


INTERVENTION_TYPES = ("extra_class", "practice_set", "peer_tutoring", "one_on_one", "parent_meeting", "resource_assignment")


@app.post("/api/teacher/interventions")
@require("teacher")
def api_intervention_create():
    """Feature 4: teacher creates an intervention for an open learning gap."""
    data = body()
    gap_id = v_int(data, "gap_id")
    gap = q("SELECT g.gap_id, g.student_id, g.status, g.mastery_pct, t.subject_id FROM learning_gaps g "
            "JOIN topics t ON t.topic_id=g.topic_id WHERE g.gap_id=?", (gap_id,), one=True)
    if not gap:
        raise ApiError("Gap not found.", 404)
    cid = check_student(g.user, gap["student_id"])
    if gap["subject_id"] not in teacher_subject_ids(g.user, cid):
        raise ApiError("You do not teach this subject to this class.", 403)
    if gap["status"] != "open":
        raise ApiError("This gap is already resolved.")
    itype = v_choice(data, "intervention_type", INTERVENTION_TYPES)
    plan = v_str(data, "plan", 3, 1000)
    start, due = v_date(data, "start_date"), v_date(data, "due_date")
    if due < start:
        raise ApiError("Due date cannot be before the start date.")
    iid = db().execute(
        "INSERT INTO interventions (gap_id, teacher_id, intervention_type, plan, start_date, due_date, status, mastery_at_start) "
        "VALUES (?,?,?,?,?,?, 'in_progress', ?)",
        (gap_id, g.user["teacher_id"], itype, plan, start, due, gap["mastery_pct"])).lastrowid
    log_action("intervention_created", "intervention", iid, itype)
    return jsonify(intervention_id=iid), 201


def own_intervention(iid):
    row = q("SELECT i.*, g.student_id, g.mastery_pct AS mastery_now, t.subject_id FROM interventions i "
            "JOIN learning_gaps g ON g.gap_id=i.gap_id JOIN topics t ON t.topic_id=g.topic_id "
            "WHERE i.intervention_id=?", (iid,), one=True)
    if not row:
        raise ApiError("Intervention not found.", 404)
    cid = check_student(g.user, row["student_id"])
    if g.user["role"] == "teacher" and row["subject_id"] not in teacher_subject_ids(g.user, cid):
        raise ApiError("You do not teach this subject to this class.", 403)
    return row


@app.get("/api/teacher/interventions")
@require("teacher", "admin")
def api_interventions_list():
    class_id = arg_int("class_id")
    check_class(g.user, class_id)
    subs = teacher_subject_ids(g.user, class_id) or [0]
    rows = q("SELECT i.intervention_id, i.intervention_type, i.plan, i.start_date, i.due_date, i.status, i.outcome, "
             "i.mastery_at_start, g.mastery_pct AS mastery_now, g.student_id, u.full_name, t.name AS topic_name, "
             "CASE WHEN i.status IN ('planned','in_progress') AND i.due_date < date('now') THEN 1 ELSE 0 END AS overdue "
             "FROM interventions i JOIN learning_gaps g ON g.gap_id=i.gap_id JOIN students s ON s.student_id=g.student_id "
             "JOIN users u ON u.user_id=s.user_id JOIN topics t ON t.topic_id=g.topic_id "
             "WHERE s.class_id=? AND t.subject_id IN (%s) ORDER BY (i.status IN ('planned','in_progress')) DESC, i.due_date"
             % ",".join("?" * len(subs)), [class_id, *subs])
    for r in rows:
        r["followups"] = q("SELECT followup_date, notes, mastery_snapshot FROM intervention_followups "
                           "WHERE intervention_id=? ORDER BY followup_date", (r["intervention_id"],))
    return jsonify(rows)


@app.post("/api/teacher/interventions/<int:iid>/followups")
@require("teacher")
def api_followup_create(iid):
    row = own_intervention(iid)
    data = body()
    notes = v_str(data, "notes", 2, 1000)
    fdate = v_date(data, "followup_date")
    db().execute("INSERT INTO intervention_followups (intervention_id, followup_date, notes, mastery_snapshot, created_by) "
                 "VALUES (?,?,?,?,?)", (iid, fdate, notes, row["mastery_now"], g.user["teacher_id"]))
    log_action("followup_added", "intervention", iid)
    return jsonify(ok=True), 201


@app.patch("/api/teacher/interventions/<int:iid>")
@require("teacher")
def api_intervention_update(iid):
    row = own_intervention(iid)
    status = v_choice(body(), "status", ("in_progress", "completed", "cancelled"))
    if row["status"] in ("completed", "cancelled"):
        raise ApiError("This intervention is already closed.")
    outcome, completed = "pending", None
    if status == "completed":
        diff = row["mastery_now"] - row["mastery_at_start"]
        outcome = "improved" if diff >= 5 else "worsened" if diff <= -5 else "no_change"
        completed = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db().execute("UPDATE interventions SET status=?, outcome=?, completed_at=? WHERE intervention_id=?",
                 (status, outcome, completed, iid))
    log_action("intervention_status", "intervention", iid, f"{status}/{outcome}")
    return jsonify(status=status, outcome=outcome)


@app.get("/api/teacher/resources")
@require("teacher", "admin")
def api_resources_list():
    sid = arg_int("subject_id")
    if sid not in teacher_subject_ids(g.user):
        raise ApiError("You do not teach this subject.", 403)
    return jsonify(q("SELECT r.resource_id, r.title, r.resource_type, r.difficulty, t.name AS topic_name, "
                     "CASE WHEN r.blob_url LIKE 'https://%' THEN 'link' WHEN r.blob_url LIKE 'blob:%' THEN 'azure blob' ELSE 'uploaded file' END AS storage "
                     "FROM resources r JOIN topics t ON t.topic_id=r.topic_id WHERE t.subject_id=? ORDER BY t.topic_id, r.difficulty", (sid,)))


@app.post("/api/teacher/resources")
@require("teacher")
def api_resource_create():
    """Upload a file (multipart) or register an external https link (JSON/form)."""
    form = request.form if request.files or request.form else (request.get_json(silent=True) or {})
    topic_id = v_int(form, "topic_id")
    topic = q("SELECT subject_id FROM topics WHERE topic_id=?", (topic_id,), one=True)
    if not topic or topic["subject_id"] not in teacher_subject_ids(g.user):
        raise ApiError("You do not teach the subject of this topic.", 403)
    title = v_str(form, "title", 2, 150)
    rtype = v_choice(form, "resource_type", ("pdf", "video", "article", "practice", "document"))
    diff = v_choice(form, "difficulty", ("basic", "intermediate", "advanced"))
    f = request.files.get("file")
    if f and f.filename:
        if not storage.allowed(f.filename):                           # [SEC] extension allow-list
            raise ApiError("File type not allowed. Use: " + ", ".join(sorted(storage.ALLOWED_EXT)))
        ref = storage.save_upload(f)
    else:
        url = v_str(form, "url", 10, 500)
        if not url.startswith("https://"):                            # [SEC] blocks javascript:/data: URLs
            raise ApiError("Link must start with https://")
        ref = url
    rid = db().execute("INSERT INTO resources (topic_id, title, resource_type, difficulty, blob_url, uploaded_by) VALUES (?,?,?,?,?,?)",
                       (topic_id, title, rtype, diff, ref, g.user["teacher_id"])).lastrowid
    log_action("resource_created", "resource", rid, title)
    return jsonify(resource_id=rid), 201


EXPORTS = {"v_student_assessment_summary", "v_class_topic_analytics", "v_intervention_outcomes"}


@app.get("/api/export/<name>.csv")
@require("admin")
def export_csv(name):
    """CSV export of analytics views (for Power BI 'Get data > Text/CSV' in the local demo)."""
    if name not in EXPORTS:                                            # [SEC] allow-list, no dynamic SQL from input
        abort(404)
    rows = q(f"SELECT * FROM {name}")
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    log_action("export", "view", None, name)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}.csv"})


# --------------------------------------------------------------------------- ADMIN API
@app.get("/api/admin/stats")
@require("admin")
def api_admin_stats():
    one = lambda sql: q(sql, one=True)["n"]
    return jsonify(
        students=one("SELECT COUNT(*) n FROM students"), teachers=one("SELECT COUNT(*) n FROM teachers"),
        classes=one("SELECT COUNT(*) n FROM classes"), assessments=one("SELECT COUNT(*) n FROM assessments"),
        open_gaps=one("SELECT COUNT(*) n FROM learning_gaps WHERE status='open'"),
        resolved_gaps=one("SELECT COUNT(*) n FROM learning_gaps WHERE status='resolved'"),
        active_interventions=one("SELECT COUNT(*) n FROM interventions WHERE status IN ('planned','in_progress')"),
        improved=one("SELECT COUNT(*) n FROM interventions WHERE outcome='improved'"),
        failed_logins_24h=one("SELECT COUNT(*) n FROM activity_log WHERE action='login_failed' AND created_at >= datetime('now','-1 day')"),
        by_class=q("SELECT c.name, COUNT(DISTINCT s.student_id) AS students, "
                   "ROUND((SELECT 100.0*SUM(sc.marks)/SUM(sc.max_marks) FROM assessment_scores sc JOIN students s2 ON s2.student_id=sc.student_id WHERE s2.class_id=c.class_id),1) AS avg_pct, "
                   "(SELECT COUNT(*) FROM learning_gaps g JOIN students s3 ON s3.student_id=g.student_id WHERE s3.class_id=c.class_id AND g.status='open') AS open_gaps "
                   "FROM classes c LEFT JOIN students s ON s.class_id=c.class_id GROUP BY c.class_id"))


@app.get("/api/admin/users")
@require("admin")
def api_admin_users():
    return jsonify(q("SELECT u.user_id, u.username, u.full_name, u.email, u.role, u.is_active, c.name AS class_name "
                     "FROM users u LEFT JOIN students s ON s.user_id=u.user_id LEFT JOIN classes c ON c.class_id=s.class_id "
                     "ORDER BY u.role, u.full_name"))


@app.post("/api/admin/users")
@require("admin")
def api_admin_user_create():
    data = body()
    username = v_str(data, "username", 3, 40, r"[A-Za-z0-9_.]+")
    full_name = v_str(data, "full_name", 2, 100)
    email = v_str(data, "email", 5, 150, r"[^@\s]+@[^@\s]+\.[^@\s]+")
    role = v_choice(data, "role", ("student", "teacher"))
    password = v_str(data, "password", 8, 64)
    if not PASSWORD_RE.fullmatch(password):
        raise ApiError("Password needs 8+ characters with letters and digits.")
    con = db()
    try:
        con.execute("BEGIN")
        uid = con.execute("INSERT INTO users (username, password_hash, role, full_name, email) VALUES (?,?,?,?,?)",
                          (username, generate_password_hash(password), role, full_name, email)).lastrowid
        if role == "student":
            class_id = v_int(data, "class_id")
            roll = v_str(data, "roll_no", 2, 20, r"[A-Za-z0-9-]+")
            con.execute("INSERT INTO students (user_id, roll_no, class_id) VALUES (?,?,?)", (uid, roll, class_id))
        else:
            con.execute("INSERT INTO teachers (user_id, department) VALUES (?,?)", (uid, v_str(data, "department", 2, 80)))
        con.execute("COMMIT")
    except sqlite3.IntegrityError:
        con.execute("ROLLBACK")
        raise ApiError("Username, email or roll number already exists, or class is invalid.", 409)
    except Exception:
        con.execute("ROLLBACK")
        raise
    log_action("user_created", "user", uid, role)
    return jsonify(user_id=uid), 201


@app.patch("/api/admin/users/<int:uid>")
@require("admin")
def api_admin_user_toggle(uid):
    active = 1 if body().get("is_active") else 0
    if uid == g.user["user_id"]:
        raise ApiError("You cannot deactivate your own account.")
    if not q("SELECT 1 FROM users WHERE user_id=?", (uid,), one=True):
        raise ApiError("User not found.", 404)
    db().execute("UPDATE users SET is_active=? WHERE user_id=?", (active, uid))
    log_action("user_active_changed", "user", uid, str(active))
    return jsonify(ok=True)


@app.get("/api/admin/classes")
@require("admin")
def api_admin_classes():
    return jsonify(q("SELECT class_id, name FROM classes ORDER BY name"))


@app.get("/api/admin/logs")
@require("admin")
def api_admin_logs():
    return jsonify(q("SELECT l.log_id, l.created_at, COALESCE(u.username,'-') AS username, l.action, l.entity, l.entity_id, "
                     "l.ip_address, l.detail FROM activity_log l LEFT JOIN users u ON u.user_id=l.user_id "
                     "ORDER BY l.log_id DESC LIMIT 200"))


# --------------------------------------------------------------------------- frontend
@app.get("/")
def index():
    return send_from_directory(os.path.join(BASE, "static"), "index.html")


init_db_if_missing()

if __name__ == "__main__":
    # Local development server. In Azure use:  gunicorn app:app
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
