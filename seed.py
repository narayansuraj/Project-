"""Create the database and fill it with realistic demo data.

Usage:  python seed.py            (creates learngap.db if empty)
        python seed.py --reset    (deletes and rebuilds the database)
"""
import os
import random
import sqlite3
import sys

from werkzeug.security import generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("LEARNGAP_DB", os.path.join(BASE, "learngap.db"))

STUDENT_NAMES = [
    "Aarav Mehta", "Diya Nair", "Kabir Singh", "Ananya Iyer", "Vihaan Gupta", "Ishita Rao",
    "Arjun Patel", "Saanvi Reddy", "Reyansh Joshi", "Myra Kapoor", "Aditya Verma", "Navya Menon",
    "Rohan Das", "Tara Bose", "Yash Malhotra", "Kiara Shah", "Dev Kulkarni", "Meera Pillai",
    "Karan Chopra", "Riya Sinha",
]

SUBJECTS = {
    "MATH": ("Mathematics", ["Number Systems", "Algebra", "Geometry", "Mensuration", "Statistics"]),
    "SCI": ("Science", ["Motion", "Force and Laws", "Gravitation", "Work and Energy", "Sound"]),
}

# (title, type, difficulty) templates created for every topic
RESOURCE_TEMPLATES = [
    ("{t}: Foundations Revision Notes", "pdf", "basic"),
    ("{t}: Step-by-step Video Lesson", "video", "basic"),
    ("{t}: Guided Practice Worksheet", "practice", "intermediate"),
    ("{t}: Concept Explainer Article", "article", "intermediate"),
    ("{t}: Challenge Problems", "document", "advanced"),
]

ASSESSMENT_DATES = ["2026-08-18", "2026-09-15", "2026-10-13", "2026-11-05"]
MAX_MARKS = 10


def main():
    reset = "--reset" in sys.argv
    if os.path.exists(DB_PATH):
        if reset:
            os.remove(DB_PATH)
        else:
            con = sqlite3.connect(DB_PATH)
            has_users = con.execute(
                "SELECT name FROM sqlite_master WHERE name='users'").fetchone() and \
                con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            con.close()
            if has_users:
                print("Database already has data. Use --reset to rebuild it.")
                return
            os.remove(DB_PATH)

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    with open(os.path.join(BASE, "schema.sql"), encoding="utf-8") as fh:
        con.executescript(fh.read())
    rng = random.Random(2026)
    pw = {r: generate_password_hash(p) for r, p in
          {"admin": "Admin@123", "teacher": "Teacher@123", "student": "Student@123"}.items()}

    def add_user(username, role, name, email):
        cur = con.execute(
            "INSERT INTO users (username, password_hash, role, full_name, email) VALUES (?,?,?,?,?)",
            (username, pw[role], role, name, email))
        return cur.lastrowid

    # --- admin, teachers
    add_user("admin", "admin", "Dr. Sunita Rao (Administrator)", "admin@learngap.edu")
    t_users = {"priya": ("Ms. Priya Sharma", "Mathematics"), "rahul": ("Mr. Rahul Verma", "Science")}
    teacher_ids = {}
    for uname, (name, dept) in t_users.items():
        uid = add_user(uname, "teacher", name, f"{uname}@learngap.edu")
        teacher_ids[uname] = con.execute(
            "INSERT INTO teachers (user_id, department) VALUES (?,?)", (uid, dept)).lastrowid

    # --- classes and students
    class_ids = {}
    for name in ("Class 9-A", "Class 9-B"):
        class_ids[name] = con.execute(
            "INSERT INTO classes (name, academic_year) VALUES (?,?)", (name, "2026-27")).lastrowid
    students = []  # (student_id, class_id)
    for i, name in enumerate(STUDENT_NAMES, start=1):
        cname = "Class 9-A" if i <= 12 else "Class 9-B"
        uid = add_user(f"stu{i:02d}", "student", name, f"stu{i:02d}@learngap.edu")
        sid = con.execute("INSERT INTO students (user_id, roll_no, class_id) VALUES (?,?,?)",
                          (uid, f"2026{i:03d}", class_ids[cname])).lastrowid
        students.append((sid, class_ids[cname]))

    # --- subjects, topics, assignments
    subj = {}
    topics = {}  # code -> [topic_id,...]
    for code, (sname, tlist) in SUBJECTS.items():
        subj[code] = con.execute("INSERT INTO subjects (code, name) VALUES (?,?)", (code, sname)).lastrowid
        topics[code] = [con.execute("INSERT INTO topics (subject_id, name) VALUES (?,?)",
                                    (subj[code], t)).lastrowid for t in tlist]
    owner = {"MATH": teacher_ids["priya"], "SCI": teacher_ids["rahul"]}
    for code in SUBJECTS:
        for cid in class_ids.values():
            con.execute("INSERT INTO teaching_assignments VALUES (?,?,?)", (owner[code], cid, subj[code]))

    # --- resources: each gets a small placeholder study file saved in ./uploads (local: reference).
    # In Azure mode, teachers upload real files to Blob Storage and the reference becomes blob:<container>/<name>.
    upload_dir = os.environ.get("LEARNGAP_UPLOADS", os.path.join(BASE, "uploads"))
    os.makedirs(upload_dir, exist_ok=True)
    for code, (sname, tlist) in SUBJECTS.items():
        for tid, tname in zip(topics[code], tlist):
            for tmpl, rtype, diff in RESOURCE_TEMPLATES:
                title = tmpl.format(t=tname)
                rid = con.execute(
                    "INSERT INTO resources (topic_id, title, resource_type, difficulty, blob_url, uploaded_by) "
                    "VALUES (?,?,?,?,?,?)", (tid, title, rtype, diff, "pending", owner[code])).lastrowid
                fname = f"demo-{rid}.txt"
                with open(os.path.join(upload_dir, fname), "w", encoding="utf-8") as fh:
                    fh.write(f"{title}\nSubject: {sname}   Level: {diff}   Format: {rtype}\n\n"
                             "[Demo placeholder] In a real deployment this is the teacher's uploaded "
                             f"{rtype} on '{tname}', stored in Azure Blob Storage.\n")
                con.execute("UPDATE resources SET blob_url=? WHERE resource_id=?", (f"local:{fname}", rid))

    # --- student ability profile: base skill + one or two weak topics each
    profile = {}
    for sid, _ in students:
        base = rng.uniform(0.58, 0.92)
        weak = {}
        for code in SUBJECTS:
            for tid in rng.sample(topics[code], rng.choice([0, 1, 1, 2])):
                weak[tid] = rng.uniform(0.25, 0.50)   # their typical score on a weak topic
        profile[sid] = (base, weak)

    def score_for(sid, tid, boost=0.0):
        base, weak = profile[sid]
        level = weak.get(tid, base) + boost
        return max(0, min(MAX_MARKS, round(MAX_MARKS * (level + rng.uniform(-0.10, 0.10)))))

    def run_assessment(code, date, title, cid, boost_for=None):
        aid = con.execute(
            "INSERT INTO assessments (class_id, subject_id, title, assessment_date, created_by) VALUES (?,?,?,?,?)",
            (cid, subj[code], title, date, owner[code])).lastrowid
        for sid, scid in students:
            if scid != cid:
                continue
            for tid in topics[code]:
                boost = (boost_for or {}).get((sid, tid), 0.0)
                con.execute(
                    "INSERT INTO assessment_scores (assessment_id, student_id, topic_id, marks, max_marks) VALUES (?,?,?,?,?)",
                    (aid, sid, tid, score_for(sid, tid, boost), MAX_MARKS))

    unit = ["Unit Test 1", "Unit Test 2", "Mid-term Check"]
    for n, date in enumerate(ASSESSMENT_DATES[:3]):
        for code in SUBJECTS:
            for cid in class_ids.values():
                run_assessment(code, date, f"{SUBJECTS[code][0]} {unit[n]}", cid)

    # --- teachers create interventions for the open gaps found so far
    gaps = con.execute(
        "SELECT g.gap_id, g.student_id, g.topic_id, g.mastery_pct, t.subject_id, "
        "       (SELECT code FROM subjects WHERE subject_id = t.subject_id) AS code "
        "FROM learning_gaps g JOIN topics t ON t.topic_id = g.topic_id "
        "WHERE g.status = 'open' ORDER BY g.gap_id").fetchall()
    types = ["extra_class", "practice_set", "one_on_one", "peer_tutoring", "resource_assignment"]
    plans = {
        "extra_class": "Weekly 40-minute remedial class focused on this topic's core concepts.",
        "practice_set": "Daily 15-minute graded practice set with answer review every Friday.",
        "one_on_one": "Two one-to-one doubt sessions followed by a short recap quiz.",
        "peer_tutoring": "Paired with a high-scoring classmate for twice-weekly peer tutoring.",
        "resource_assignment": "Assigned the basic revision notes and video; check completion in a week.",
    }
    boost = {}
    for k, (gap_id, sid, tid, mastery, subject_id, code) in enumerate(gaps):
        if k % 3 == 2:          # leave every third gap without an intervention (still needs attention)
            continue
        itype = types[k % len(types)]
        status = "in_progress"
        iid = con.execute(
            "INSERT INTO interventions (gap_id, teacher_id, intervention_type, plan, start_date, due_date, status, mastery_at_start) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (gap_id, owner[code], itype, plans[itype], "2026-10-16", "2026-11-14", status, mastery)).lastrowid
        con.execute(
            "INSERT INTO intervention_followups (intervention_id, followup_date, notes, mastery_snapshot, created_by) VALUES (?,?,?,?,?)",
            (iid, "2026-10-30", "Student attended sessions regularly; reviewed worked examples.", mastery, owner[code]))
        if k % 4 != 1:           # most students respond to the intervention
            boost[(sid, tid)] = 0.55

    # --- latest assessment: intervened students improve, resolving many gaps
    for code in SUBJECTS:
        for cid in class_ids.values():
            run_assessment(code, ASSESSMENT_DATES[3], f"{SUBJECTS[code][0]} Unit Test 3", cid, boost)

    # one intervention that did not work, closed manually by the teacher
    row = con.execute(
        "SELECT intervention_id FROM interventions WHERE status = 'in_progress' ORDER BY intervention_id LIMIT 1").fetchone()
    if row:
        con.execute("UPDATE interventions SET status='completed', outcome='no_change', completed_at='2026-11-08 10:00:00' "
                    "WHERE intervention_id = ?", (row[0],))

    con.execute("INSERT INTO activity_log (user_id, action, detail) VALUES (NULL, 'database_seeded', 'Demo data loaded')")
    con.commit()

    stats = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
             ("users", "students", "assessments", "assessment_scores", "learning_gaps", "resources", "interventions")}
    con.close()
    print("Database ready:", DB_PATH)
    print(stats)
    print("Demo logins ->  admin / Admin@123   priya / Teacher@123   rahul / Teacher@123   stu01 / Student@123")


if __name__ == "__main__":
    main()
