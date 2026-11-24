"""Automated tests: one group per core feature, plus security checks.
Run:  python -m unittest discover -s tests -v      (from the project folder)
Uses a temporary database; your real learngap.db is never touched.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.mkdtemp()
os.environ["LEARNGAP_DB"] = os.path.join(_tmp, "test.db")
os.environ["LEARNGAP_UPLOADS"] = os.path.join(_tmp, "uploads")

import seed  # noqa: E402
seed.DB_PATH = os.environ["LEARNGAP_DB"]
_argv, sys.argv = sys.argv, ["seed"]
seed.main()
sys.argv = _argv
import app as A  # noqa: E402


def login(username, password):
    c = A.app.test_client()
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.get_json()
    c.csrf = r.get_json()["csrf"]
    return c


def post(c, path, **json):
    return c.post(path, json=json, headers={"X-CSRF-Token": c.csrf})


class Features(unittest.TestCase):
    def test_1_performance_tracking_student(self):
        c = login("stu01", "Student@123")
        d = c.get("/api/student/overview").get_json()
        self.assertGreater(len(d["assessments"]), 3)
        self.assertGreater(len(d["topics"]), 3)

    def test_2_gap_identification(self):
        c = login("stu01", "Student@123")
        d = c.get("/api/student/gaps").get_json()
        for g in d["open"]:
            self.assertLess(g["mastery_pct"], 60)
        con = sqlite3.connect(os.environ["LEARNGAP_DB"])
        n = con.execute("SELECT COUNT(*) FROM learning_gaps WHERE status='open'").fetchone()[0]
        self.assertGreater(n, 5)

    def test_3_recommendations(self):
        for i in range(1, 13):
            c = login(f"stu{i:02d}", "Student@123")
            gaps = c.get("/api/student/gaps").get_json()["open"]
            if gaps:
                recs = c.get("/api/student/recommendations").get_json()
                self.assertTrue(recs)
                self.assertEqual({r["topic_name"] for r in recs}, {g["topic_name"] for g in gaps})
                self.assertNotIn("advanced", {r["difficulty"] for r in recs})
                r = post(c, f"/api/student/resources/{recs[0]['resource_id']}/progress", status="completed")
                self.assertEqual(r.status_code, 200)
                return
        self.fail("no student with gaps")

    def test_4_and_5_interventions_and_trigger_resolution(self):
        t = login("priya", "Teacher@123")
        # record a weak assessment for class 1 -> creates a gap through the trigger
        roster = t.get("/api/teacher/roster?class_id=1").get_json()
        topics = t.get("/api/topics?subject_id=1").get_json()
        sid, tid = roster[0]["student_id"], topics[0]["topic_id"]
        r = post(t, "/api/teacher/assessments", class_id=1, subject_id=1, title="T-bad", date="2026-11-20",
                 scores=[{"student_id": sid, "topic_id": tid, "marks": 1, "max_marks": 10}])
        self.assertEqual(r.status_code, 201, r.get_json())
        r = post(t, "/api/teacher/assessments", class_id=1, subject_id=1, title="T-bad2", date="2026-11-21",
                 scores=[{"student_id": sid, "topic_id": tid, "marks": 1, "max_marks": 10}])
        gaps = t.get("/api/teacher/gaps?class_id=1").get_json()
        gap = next(g for g in gaps if g["student_id"] == sid and g["topic_name"] == topics[0]["name"])
        self.assertEqual(gap["severity"], "critical")
        # create intervention + follow-up
        r = post(t, "/api/teacher/interventions", gap_id=gap["gap_id"], intervention_type="one_on_one",
                 plan="Two doubt sessions", start_date="2026-11-22", due_date="2026-12-05")
        self.assertEqual(r.status_code, 201, r.get_json())
        iid = r.get_json()["intervention_id"]
        r = post(t, f"/api/teacher/interventions/{iid}/followups", notes="Attended", followup_date="2026-11-25")
        self.assertEqual(r.status_code, 201)
        # two strong results -> trigger resolves gap and auto-closes intervention as improved
        for n, d in enumerate(("2026-12-01", "2026-12-02")):
            post(t, "/api/teacher/assessments", class_id=1, subject_id=1, title=f"T-good{n}", date=d,
                 scores=[{"student_id": sid, "topic_id": tid, "marks": 9, "max_marks": 10}])
        con = sqlite3.connect(os.environ["LEARNGAP_DB"])
        row = con.execute("SELECT status, outcome FROM interventions WHERE intervention_id=?", (iid,)).fetchone()
        self.assertEqual(row, ("completed", "improved"))
        gs = con.execute("SELECT status FROM learning_gaps WHERE gap_id=?", (gap["gap_id"],)).fetchone()[0]
        self.assertEqual(gs, "resolved")

    def test_6_teacher_dashboard(self):
        t = login("priya", "Teacher@123")
        d = t.get("/api/teacher/dashboard?class_id=1").get_json()
        for key in ("kpis", "topics", "trend", "outcomes", "at_risk"):
            self.assertIn(key, d)
        self.assertEqual(d["kpis"]["students"], 12)
        # subject scoping: Maths teacher must not see Science data
        self.assertEqual({x["subject_name"] for x in d["topics"]}, {"Mathematics"})

    def test_transaction_rollback(self):
        t = login("priya", "Teacher@123")
        roster = t.get("/api/teacher/roster?class_id=1").get_json()
        topics = t.get("/api/topics?subject_id=1").get_json()
        ok = {"student_id": roster[0]["student_id"], "topic_id": topics[0]["topic_id"], "marks": 5, "max_marks": 10}
        r = post(t, "/api/teacher/assessments", class_id=1, subject_id=1, title="Dup", date="2026-12-10", scores=[ok, dict(ok)])
        self.assertEqual(r.status_code, 400)
        con = sqlite3.connect(os.environ["LEARNGAP_DB"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM assessments WHERE title='Dup'").fetchone()[0], 0)


class Security(unittest.TestCase):
    def test_password_hashed(self):
        con = sqlite3.connect(os.environ["LEARNGAP_DB"])
        h = con.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
        self.assertNotIn("Admin@123", h)
        self.assertTrue(h.startswith(("scrypt:", "pbkdf2:")))

    def test_auth_required(self):
        self.assertEqual(A.app.test_client().get("/api/student/overview").status_code, 401)

    def test_role_based_access(self):
        s = login("stu02", "Student@123")
        self.assertEqual(s.get("/api/admin/users").status_code, 403)
        self.assertEqual(s.get("/api/teacher/dashboard?class_id=1").status_code, 403)
        t = login("priya", "Teacher@123")
        self.assertEqual(t.get("/api/admin/logs").status_code, 403)
        self.assertEqual(t.get("/api/student/gaps").status_code, 403)

    def test_teacher_cannot_access_other_subject(self):
        t = login("priya", "Teacher@123")
        self.assertEqual(t.get("/api/teacher/dashboard?class_id=1&subject_id=2").status_code, 403)

    def test_csrf_enforced(self):
        t = login("priya", "Teacher@123")
        r = t.post("/api/teacher/assessments", json={})
        self.assertEqual(r.status_code, 403)

    def test_sql_injection_login(self):
        c = A.app.test_client()
        r = c.post("/api/auth/login", json={"username": "admin' OR '1'='1", "password": "x' OR '1'='1"})
        self.assertEqual(r.status_code, 401)

    def test_sql_injection_param(self):
        t = login("priya", "Teacher@123")
        self.assertEqual(t.get("/api/teacher/students?class_id=1%20OR%201=1").status_code, 400)

    def test_xss_stored_text_is_data_only(self):
        t = login("priya", "Teacher@123")
        r = post(t, "/api/teacher/resources", topic_id=1, title="<script>alert(1)</script>", resource_type="pdf",
                 difficulty="basic", url="javascript:alert(1)")
        self.assertEqual(r.status_code, 400)           # non-https link rejected

    def test_security_headers(self):
        r = A.app.test_client().get("/")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")

    def test_lockout_after_failures(self):
        c = A.app.test_client()
        for _ in range(5):
            c.post("/api/auth/login", json={"username": "stu20", "password": "wrong"})
        r = c.post("/api/auth/login", json={"username": "stu20", "password": "Student@123"})
        self.assertEqual(r.status_code, 429)

    def test_activity_logged(self):
        login("stu03", "Student@123")
        A.app.test_client().post("/api/auth/login", json={"username": "stu03", "password": "bad"})
        con = sqlite3.connect(os.environ["LEARNGAP_DB"])
        acts = {r[0] for r in con.execute("SELECT DISTINCT action FROM activity_log")}
        self.assertTrue({"login_success", "login_failed"} <= acts)

    def test_upload_type_blocked(self):
        t = login("priya", "Teacher@123")
        import io
        r = t.post("/api/teacher/resources", data={"topic_id": "1", "title": "evil", "resource_type": "pdf", "difficulty": "basic",
                                                   "file": (io.BytesIO(b"x"), "shell.exe")},
                   headers={"X-CSRF-Token": t.csrf}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)

    def test_student_cannot_see_other_students_data(self):
        t = login("rahul", "Teacher@123")   # teaches both classes' science; any class OK
        s = login("stu01", "Student@123")
        self.assertEqual(s.get("/api/teacher/students/1").status_code, 403)


if __name__ == "__main__":
    unittest.main()
