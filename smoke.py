import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp()
os.environ["LEARNGAP_DB"] = os.path.join(tmp, "t.db")
import seed; seed.DB_PATH = os.environ["LEARNGAP_DB"]; sys.argv = ["seed"]; seed.main()
import app as A
c = A.app.test_client()
r = c.post("/api/auth/login", json={"username": "priya", "password": "Teacher@123"})
print(r.status_code, r.json["user"]["role"])
csrf = r.json["csrf"]
print(c.get("/api/teacher/classes").json[:2])
d = c.get("/api/teacher/dashboard?class_id=1").json
print(d["kpis"])
