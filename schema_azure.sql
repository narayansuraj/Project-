-- ============================================================================
-- LearnGap - Azure SQL Database (T-SQL) deployment script
-- Same logical model as schema.sql (SQLite) written for Azure SQL Database.
-- Run in the Azure portal Query editor, Azure Data Studio or sqlcmd.
-- NOTE: written for Azure SQL; the running prototype uses SQLite locally.
-- ============================================================================
SET NOCOUNT ON;
GO

CREATE TABLE dbo.users (
    user_id        INT IDENTITY(1,1) PRIMARY KEY,
    username       NVARCHAR(40)  NOT NULL UNIQUE,
    password_hash  NVARCHAR(256) NOT NULL,
    role           VARCHAR(10)   NOT NULL CHECK (role IN ('student','teacher','admin')),
    full_name      NVARCHAR(100) NOT NULL,
    email          NVARCHAR(150) NOT NULL UNIQUE,
    is_active      BIT NOT NULL DEFAULT 1,
    failed_logins  INT NOT NULL DEFAULT 0,
    locked_until   DATETIME2 NULL,
    created_at     DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE TABLE dbo.classes (
    class_id INT IDENTITY(1,1) PRIMARY KEY,
    name NVARCHAR(50) NOT NULL UNIQUE,
    academic_year VARCHAR(9) NOT NULL
);
CREATE TABLE dbo.teachers (
    teacher_id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL UNIQUE REFERENCES dbo.users(user_id) ON DELETE CASCADE,
    department NVARCHAR(80) NOT NULL
);
CREATE TABLE dbo.students (
    student_id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL UNIQUE REFERENCES dbo.users(user_id) ON DELETE CASCADE,
    roll_no VARCHAR(20) NOT NULL UNIQUE,
    class_id INT NOT NULL REFERENCES dbo.classes(class_id)
);
CREATE TABLE dbo.subjects (
    subject_id INT IDENTITY(1,1) PRIMARY KEY,
    code VARCHAR(10) NOT NULL UNIQUE,
    name NVARCHAR(80) NOT NULL UNIQUE
);
CREATE TABLE dbo.topics (
    topic_id INT IDENTITY(1,1) PRIMARY KEY,
    subject_id INT NOT NULL REFERENCES dbo.subjects(subject_id) ON DELETE CASCADE,
    name NVARCHAR(100) NOT NULL,
    CONSTRAINT uq_topic UNIQUE (subject_id, name)
);
CREATE TABLE dbo.teaching_assignments (
    teacher_id INT NOT NULL REFERENCES dbo.teachers(teacher_id) ON DELETE CASCADE,
    class_id   INT NOT NULL REFERENCES dbo.classes(class_id),
    subject_id INT NOT NULL REFERENCES dbo.subjects(subject_id),
    PRIMARY KEY (teacher_id, class_id, subject_id)
);
CREATE TABLE dbo.assessments (
    assessment_id INT IDENTITY(1,1) PRIMARY KEY,
    class_id INT NOT NULL REFERENCES dbo.classes(class_id),
    subject_id INT NOT NULL REFERENCES dbo.subjects(subject_id),
    title NVARCHAR(120) NOT NULL,
    assessment_date DATE NOT NULL,
    created_by INT NOT NULL REFERENCES dbo.teachers(teacher_id),
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE TABLE dbo.assessment_scores (
    score_id INT IDENTITY(1,1) PRIMARY KEY,
    assessment_id INT NOT NULL REFERENCES dbo.assessments(assessment_id) ON DELETE CASCADE,
    student_id INT NOT NULL REFERENCES dbo.students(student_id),
    topic_id INT NOT NULL REFERENCES dbo.topics(topic_id),
    marks DECIMAL(6,2) NOT NULL,
    max_marks DECIMAL(6,2) NOT NULL CHECK (max_marks > 0),
    CONSTRAINT ck_marks CHECK (marks >= 0 AND marks <= max_marks),
    CONSTRAINT uq_score UNIQUE (assessment_id, student_id, topic_id)
);
CREATE INDEX ix_scores_student_topic ON dbo.assessment_scores(student_id, topic_id);
CREATE TABLE dbo.learning_gaps (
    gap_id INT IDENTITY(1,1) PRIMARY KEY,
    student_id INT NOT NULL REFERENCES dbo.students(student_id),
    topic_id INT NOT NULL REFERENCES dbo.topics(topic_id),
    mastery_pct DECIMAL(5,1) NOT NULL CHECK (mastery_pct BETWEEN 0 AND 100),
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('critical','moderate','none')),
    status VARCHAR(10) NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
    detected_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    resolved_at DATETIME2 NULL,
    CONSTRAINT uq_gap UNIQUE (student_id, topic_id)
);
CREATE TABLE dbo.resources (
    resource_id INT IDENTITY(1,1) PRIMARY KEY,
    topic_id INT NOT NULL REFERENCES dbo.topics(topic_id) ON DELETE CASCADE,
    title NVARCHAR(150) NOT NULL,
    resource_type VARCHAR(10) NOT NULL CHECK (resource_type IN ('pdf','video','article','practice','document')),
    difficulty VARCHAR(12) NOT NULL CHECK (difficulty IN ('basic','intermediate','advanced')),
    blob_url NVARCHAR(500) NOT NULL,          -- Azure Blob Storage URL / blob:container/name
    uploaded_by INT NOT NULL REFERENCES dbo.teachers(teacher_id),
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE TABLE dbo.resource_progress (
    student_id INT NOT NULL REFERENCES dbo.students(student_id),
    resource_id INT NOT NULL REFERENCES dbo.resources(resource_id) ON DELETE CASCADE,
    status VARCHAR(12) NOT NULL CHECK (status IN ('in_progress','completed')),
    updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    PRIMARY KEY (student_id, resource_id)
);
CREATE TABLE dbo.interventions (
    intervention_id INT IDENTITY(1,1) PRIMARY KEY,
    gap_id INT NOT NULL REFERENCES dbo.learning_gaps(gap_id),
    teacher_id INT NOT NULL REFERENCES dbo.teachers(teacher_id),
    intervention_type VARCHAR(25) NOT NULL CHECK (intervention_type IN
        ('extra_class','practice_set','peer_tutoring','one_on_one','parent_meeting','resource_assignment')),
    plan NVARCHAR(1000) NOT NULL,
    start_date DATE NOT NULL,
    due_date DATE NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','in_progress','completed','cancelled')),
    outcome VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (outcome IN ('pending','improved','no_change','worsened')),
    mastery_at_start DECIMAL(5,1) NOT NULL,
    completed_at DATETIME2 NULL,
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT ck_dates CHECK (due_date >= start_date)
);
CREATE TABLE dbo.intervention_followups (
    followup_id INT IDENTITY(1,1) PRIMARY KEY,
    intervention_id INT NOT NULL REFERENCES dbo.interventions(intervention_id) ON DELETE CASCADE,
    followup_date DATE NOT NULL,
    notes NVARCHAR(1000) NOT NULL,
    mastery_snapshot DECIMAL(5,1) NULL,
    created_by INT NOT NULL REFERENCES dbo.teachers(teacher_id),
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE TABLE dbo.activity_log (
    log_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NULL REFERENCES dbo.users(user_id) ON DELETE SET NULL,
    action NVARCHAR(60) NOT NULL,
    entity NVARCHAR(40) NULL,
    entity_id INT NULL,
    ip_address VARCHAR(45) NULL,
    detail NVARCHAR(500) NULL,
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

-- ============================================================================
-- STORED PROCEDURE : recalculate gap status for one student/topic
-- mastery = percentage over the student's latest 2 results on the topic
-- ============================================================================
CREATE OR ALTER PROCEDURE dbo.usp_RecalculateGap @student_id INT, @topic_id INT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @m DECIMAL(5,1);
    SELECT @m = ROUND(100.0 * SUM(x.marks) / SUM(x.max_marks), 1)
    FROM (SELECT TOP (2) s.marks, s.max_marks
          FROM dbo.assessment_scores s JOIN dbo.assessments a ON a.assessment_id = s.assessment_id
          WHERE s.student_id = @student_id AND s.topic_id = @topic_id
          ORDER BY a.assessment_date DESC, s.score_id DESC) x;
    IF @m IS NULL RETURN;

    IF @m < 60
    BEGIN
        DECLARE @sev VARCHAR(10) = CASE WHEN @m < 40 THEN 'critical' ELSE 'moderate' END;
        MERGE dbo.learning_gaps AS tgt
        USING (SELECT @student_id AS student_id, @topic_id AS topic_id) AS src
           ON tgt.student_id = src.student_id AND tgt.topic_id = src.topic_id
        WHEN MATCHED THEN UPDATE SET mastery_pct = @m, severity = @sev, status = 'open',
                                     resolved_at = NULL, updated_at = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN INSERT (student_id, topic_id, mastery_pct, severity, status)
                              VALUES (@student_id, @topic_id, @m, @sev, 'open');
    END
    ELSE
    BEGIN
        UPDATE dbo.learning_gaps
           SET mastery_pct = @m, severity = 'none',
               resolved_at = CASE WHEN status = 'open' THEN SYSUTCDATETIME() ELSE resolved_at END,
               status = 'resolved', updated_at = SYSUTCDATETIME()
         WHERE student_id = @student_id AND topic_id = @topic_id;

        -- close interventions of a resolved gap
        UPDATE i SET status = 'completed', outcome = 'improved', completed_at = SYSUTCDATETIME()
          FROM dbo.interventions i JOIN dbo.learning_gaps g ON g.gap_id = i.gap_id
         WHERE g.student_id = @student_id AND g.topic_id = @topic_id
           AND g.status = 'resolved' AND i.status IN ('planned','in_progress');
    END
END
GO

-- ============================================================================
-- TRIGGER : any new/changed score refreshes the learning gap automatically
-- ============================================================================
CREATE OR ALTER TRIGGER dbo.trg_scores_gap ON dbo.assessment_scores
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @s INT, @t INT;
    DECLARE c CURSOR LOCAL FAST_FORWARD FOR SELECT DISTINCT student_id, topic_id FROM inserted;
    OPEN c; FETCH NEXT FROM c INTO @s, @t;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        EXEC dbo.usp_RecalculateGap @s, @t;
        FETCH NEXT FROM c INTO @s, @t;
    END
    CLOSE c; DEALLOCATE c;
END
GO

-- ============================================================================
-- TRANSACTIONAL PROCEDURE : save a whole assessment atomically (JSON input)
-- Example: EXEC dbo.usp_RecordAssessment 1,1,'Unit Test 4','2026-11-20',1,
--          '[{"student_id":1,"topic_id":2,"marks":7,"max_marks":10}]';
-- ============================================================================
CREATE OR ALTER PROCEDURE dbo.usp_RecordAssessment
    @class_id INT, @subject_id INT, @title NVARCHAR(120), @date DATE, @teacher_id INT, @scores_json NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    BEGIN TRY
        BEGIN TRAN;
        INSERT INTO dbo.assessments (class_id, subject_id, title, assessment_date, created_by)
        VALUES (@class_id, @subject_id, @title, @date, @teacher_id);
        DECLARE @aid INT = SCOPE_IDENTITY();
        INSERT INTO dbo.assessment_scores (assessment_id, student_id, topic_id, marks, max_marks)
        SELECT @aid, student_id, topic_id, marks, max_marks
        FROM OPENJSON(@scores_json)
             WITH (student_id INT '$.student_id', topic_id INT '$.topic_id',
                   marks DECIMAL(6,2) '$.marks', max_marks DECIMAL(6,2) '$.max_marks');
        COMMIT;
        SELECT @aid AS assessment_id;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        THROW;
    END CATCH
END
GO

-- ============================================================================
-- VIEWS (Power BI connects to these)
-- ============================================================================
CREATE OR ALTER VIEW dbo.v_student_assessment_summary AS
SELECT sc.student_id, a.assessment_id, a.title, a.assessment_date, a.subject_id, sub.name AS subject_name,
       SUM(sc.marks) AS marks, SUM(sc.max_marks) AS max_marks,
       ROUND(100.0 * SUM(sc.marks) / SUM(sc.max_marks), 1) AS pct
FROM dbo.assessment_scores sc
JOIN dbo.assessments a ON a.assessment_id = sc.assessment_id
JOIN dbo.subjects sub ON sub.subject_id = a.subject_id
GROUP BY sc.student_id, a.assessment_id, a.title, a.assessment_date, a.subject_id, sub.name;
GO
CREATE OR ALTER VIEW dbo.v_class_topic_analytics AS
SELECT st.class_id, t.subject_id, sub.name AS subject_name, t.topic_id, t.name AS topic_name,
       COUNT(DISTINCT sc.student_id) AS students_assessed,
       ROUND(100.0 * SUM(sc.marks) / SUM(sc.max_marks), 1) AS class_avg_pct,
       (SELECT COUNT(*) FROM dbo.learning_gaps g JOIN dbo.students s2 ON s2.student_id = g.student_id
         WHERE s2.class_id = st.class_id AND g.topic_id = t.topic_id AND g.status = 'open') AS students_with_gap
FROM dbo.assessment_scores sc
JOIN dbo.students st ON st.student_id = sc.student_id
JOIN dbo.topics t ON t.topic_id = sc.topic_id
JOIN dbo.subjects sub ON sub.subject_id = t.subject_id
GROUP BY st.class_id, t.subject_id, sub.name, t.topic_id, t.name;
GO
CREATE OR ALTER VIEW dbo.v_intervention_outcomes AS
SELECT i.intervention_id, i.intervention_type, i.status, i.outcome, g.student_id, st.class_id, g.topic_id,
       t.name AS topic_name, i.mastery_at_start, g.mastery_pct AS mastery_now,
       g.mastery_pct - i.mastery_at_start AS improvement, i.start_date, i.due_date, i.teacher_id
FROM dbo.interventions i
JOIN dbo.learning_gaps g ON g.gap_id = i.gap_id
JOIN dbo.students st ON st.student_id = g.student_id
JOIN dbo.topics t ON t.topic_id = g.topic_id;
GO

-- ============================================================================
-- LEAST-PRIVILEGE DATABASE USERS (Cloud Security)
-- The web app connects with a limited user, never with the server admin login.
-- ============================================================================
-- CREATE USER learngap_app FROM EXTERNAL PROVIDER;      -- Managed Identity (preferred)
-- ALTER ROLE db_datareader ADD MEMBER learngap_app;
-- ALTER ROLE db_datawriter ADD MEMBER learngap_app;
-- GRANT EXECUTE ON SCHEMA::dbo TO learngap_app;
-- CREATE USER powerbi_reader FROM EXTERNAL PROVIDER;    -- read-only on views
-- GRANT SELECT ON dbo.v_class_topic_analytics TO powerbi_reader;
-- GRANT SELECT ON dbo.v_intervention_outcomes TO powerbi_reader;
-- GRANT SELECT ON dbo.v_student_assessment_summary TO powerbi_reader;
