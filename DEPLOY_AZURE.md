# Deploying LearnGap on Azure (DP-900 + Cloud Security)

| Component | Azure service | Purpose |
|---|---|---|
| Web app + REST API | **App Service** (Linux, Python 3.12) | `gunicorn app:app`, HTTPS only |
| Structured data | **Azure SQL Database** | run `azure/schema_azure.sql` |
| Learning resources (PDF, DOCX, MP4) | **Blob Storage** (private container `learning-resources`) | app issues 10-minute read-only SAS links |
| Analytics | **Power BI** | connects to the SQL views |
| Secrets | **Key Vault** + App Service Managed Identity | no passwords in code |
| Monitoring | **Azure Monitor / App Insights** + `activity_log` table | audit trail |

## Steps
1. Create a resource group, then an **Azure SQL Database** (Basic/Serverless is enough). In *Networking*: disable public access or add only the App Service outbound IPs / use a Private Endpoint; set *Minimum TLS 1.2*.
2. Open *Query editor* and run `azure/schema_azure.sql` (tables, trigger, stored procedures, views).
3. Create a **Storage account** (TLS 1.2, "Allow Blob anonymous access" = Disabled) and a private container `learning-resources`.
4. Create the **App Service**, enable *HTTPS Only*, and set Application Settings:
   `LEARNGAP_SECRET_KEY` (Key Vault reference), `LEARNGAP_HTTPS=1`, `AZURE_STORAGE_CONNECTION_STRING` (Key Vault reference), `AZURE_STORAGE_CONTAINER=learning-resources`.
5. Startup command: `gunicorn --bind=0.0.0.0 app:app`. Deploy by ZIP deploy or GitHub Actions.
6. In SQL, create a least-privilege user for the app (see bottom of `schema_azure.sql`), never use the server admin login.

## Power BI dashboard (3 pages)
Get Data -> Azure SQL Database -> import the views `v_student_assessment_summary`, `v_class_topic_analytics`, `v_intervention_outcomes`.
* **Page 1 - Student performance:** line chart of `pct` by `assessment_date`, slicer on `subject_name`.
* **Page 2 - Learning gaps:** bar chart `class_avg_pct` by `topic_name`; card = sum of `students_with_gap`.
* **Page 3 - Intervention outcomes:** clustered column of count by `outcome`; average of `improvement` by `intervention_type`.
For the local demo, the admin account can download the same views as CSV (Power BI Export tab).

## Honest scope note
The runnable prototype uses SQLite so it works on any laptop; the Azure SQL scripts, Blob integration (`storage.py`) and deployment steps above are provided to show the cloud design. Port the data-access layer to `pyodbc` / SQLAlchemy when you actually deploy to Azure SQL.
