# LearnGap - Learning Gap Identification & Intervention Platform

Finds topic-wise learning gaps from assessment results, recommends resources, and lets teachers plan and track interventions.

## Run it (2 minutes)
```
pip install -r requirements.txt
python seed.py --reset        # creates learngap.db with demo data
python app.py                 # open http://127.0.0.1:5000
```
Demo logins: `stu01 / Student@123` (student), `priya / Teacher@123` (Maths teacher), `rahul / Teacher@123` (Science teacher), `admin / Admin@123`.

Run the tests: `python -m unittest discover -s tests -v` (19 tests).

## The 6 core features
| # | Feature | Where |
|---|---|---|
| 1 | Student academic performance tracking | Student "My Performance"; teacher "Assessments" (records scores in one transaction) |
| 2 | Topic-wise learning gap identification | DB trigger `trg_scores_gap_*` (mastery < 60% over last 2 results); "Learning Gaps" |
| 3 | Personalized resource recommendations | View `v_recommendations` -> "Recommended Resources" |
| 4 | Teacher intervention & follow-up management | Teacher "Interventions" (plan, follow-ups, close, overdue flag) |
| 5 | Student progress & improvement tracking | Student "My Progress"; trigger auto-closes interventions as *improved* |
| 6 | Teacher dashboard for class-level analytics | Teacher "Class Dashboard" |

## Files
`app.py` REST API + security · `schema.sql` SQLite schema, triggers, views · `azure/schema_azure.sql` T-SQL (Azure SQL) incl. stored procedures · `storage.py` local/Azure Blob storage · `static/` frontend · `tests/` automated tests · `azure/DEPLOY_AZURE.md` cloud deployment + Power BI.
