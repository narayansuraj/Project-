-- ============================================================================
-- LearnGap - Learning Gap Identification & Intervention Platform
-- Relational schema (SQLite dialect, runs locally).  The Azure SQL (T-SQL)
-- equivalent is in azure/schema_azure.sql.
-- Normalised to 3NF. Constraints: PK, FK, UNIQUE, CHECK, NOT NULL, DEFAULT.
-- ============================================================================
PRAGMA foreign_keys = ON;

-- ---------- Identity & organisation ----------------------------------------
CREATE TABLE users (
    user_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(username) BETWEEN 3 AND 40),
    password_hash  TEXT NOT NULL,                      -- PBKDF2-SHA256, never plain text
    role           TEXT NOT NULL CHECK (role IN ('student','teacher','admin')),
    full_name      TEXT NOT NULL CHECK (length(full_name) BETWEEN 2 AND 100),
    email          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    failed_logins  INTEGER NOT NULL DEFAULT 0,
    locked_until   TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE classes (
    class_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL UNIQUE,
    academic_year  TEXT NOT NULL
);

CREATE TABLE teachers (
    teacher_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    department     TEXT NOT NULL
);

CREATE TABLE students (
    student_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    roll_no        TEXT NOT NULL UNIQUE,
    class_id       INTEGER NOT NULL REFERENCES classes(class_id)
);

-- ---------- Curriculum -----------------------------------------------------
CREATE TABLE subjects (
    subject_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    code           TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL UNIQUE
);

CREATE TABLE topics (
    topic_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id     INTEGER NOT NULL REFERENCES subjects(subject_id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    UNIQUE (subject_id, name)
);

-- Many-to-many: which teacher teaches which subject to which class
CREATE TABLE teaching_assignments (
    teacher_id     INTEGER NOT NULL REFERENCES teachers(teacher_id) ON DELETE CASCADE,
    class_id       INTEGER NOT NULL REFERENCES classes(class_id)   ON DELETE CASCADE,
    subject_id     INTEGER NOT NULL REFERENCES subjects(subject_id) ON DELETE CASCADE,
    PRIMARY KEY (teacher_id, class_id, subject_id)
);

-- ---------- Assessments & performance --------------------------------------
CREATE TABLE assessments (
    assessment_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id        INTEGER NOT NULL REFERENCES classes(class_id),
    subject_id      INTEGER NOT NULL REFERENCES subjects(subject_id),
    title           TEXT NOT NULL CHECK (length(title) BETWEEN 2 AND 120),
    assessment_date TEXT NOT NULL CHECK (assessment_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    created_by      INTEGER NOT NULL REFERENCES teachers(teacher_id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row = one student's marks on one topic within one assessment
CREATE TABLE assessment_scores (
    score_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id  INTEGER NOT NULL REFERENCES assessments(assessment_id) ON DELETE CASCADE,
    student_id     INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    topic_id       INTEGER NOT NULL REFERENCES topics(topic_id),
    marks          REAL NOT NULL,
    max_marks      REAL NOT NULL CHECK (max_marks > 0),
    CHECK (marks >= 0 AND marks <= max_marks),
    UNIQUE (assessment_id, student_id, topic_id)
);
CREATE INDEX ix_scores_student_topic ON assessment_scores(student_id, topic_id);

-- ---------- Learning gaps ---------------------------------------------------
-- Maintained automatically by triggers below. mastery_pct = average of the
-- student's latest 2 results on that topic. Gap threshold = 60 %.
CREATE TABLE learning_gaps (
    gap_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    topic_id       INTEGER NOT NULL REFERENCES topics(topic_id),
    mastery_pct    REAL NOT NULL CHECK (mastery_pct BETWEEN 0 AND 100),
    severity       TEXT NOT NULL CHECK (severity IN ('critical','moderate','none')),
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
    detected_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at    TEXT,
    UNIQUE (student_id, topic_id)
);

-- ---------- Learning resources ---------------------------------------------
-- blob_url is one of:  local:<file> | blob:<container>/<file> | https://...
CREATE TABLE resources (
    resource_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id       INTEGER NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    title          TEXT NOT NULL CHECK (length(title) BETWEEN 2 AND 150),
    resource_type  TEXT NOT NULL CHECK (resource_type IN ('pdf','video','article','practice','document')),
    difficulty     TEXT NOT NULL CHECK (difficulty IN ('basic','intermediate','advanced')),
    blob_url       TEXT NOT NULL,
    uploaded_by    INTEGER NOT NULL REFERENCES teachers(teacher_id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE resource_progress (
    student_id     INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    resource_id    INTEGER NOT NULL REFERENCES resources(resource_id) ON DELETE CASCADE,
    status         TEXT NOT NULL CHECK (status IN ('in_progress','completed')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (student_id, resource_id)
);

-- ---------- Interventions ---------------------------------------------------
CREATE TABLE interventions (
    intervention_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    gap_id           INTEGER NOT NULL REFERENCES learning_gaps(gap_id) ON DELETE CASCADE,
    teacher_id       INTEGER NOT NULL REFERENCES teachers(teacher_id),
    intervention_type TEXT NOT NULL CHECK (intervention_type IN
                     ('extra_class','practice_set','peer_tutoring','one_on_one','parent_meeting','resource_assignment')),
    plan             TEXT NOT NULL CHECK (length(plan) BETWEEN 3 AND 1000),
    start_date       TEXT NOT NULL,
    due_date         TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','in_progress','completed','cancelled')),
    outcome          TEXT NOT NULL DEFAULT 'pending' CHECK (outcome IN ('pending','improved','no_change','worsened')),
    mastery_at_start REAL NOT NULL,
    completed_at     TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (due_date >= start_date)
);

CREATE TABLE intervention_followups (
    followup_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    intervention_id  INTEGER NOT NULL REFERENCES interventions(intervention_id) ON DELETE CASCADE,
    followup_date    TEXT NOT NULL,
    notes            TEXT NOT NULL CHECK (length(notes) BETWEEN 2 AND 1000),
    mastery_snapshot REAL,
    created_by       INTEGER NOT NULL REFERENCES teachers(teacher_id),
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------- Security audit trail --------------------------------------------
CREATE TABLE activity_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    entity      TEXT,
    entity_id   INTEGER,
    ip_address  TEXT,
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_log_created ON activity_log(created_at);

-- ============================================================================
-- TRIGGERS : keep learning_gaps in sync whenever scores are written
-- ============================================================================
-- (a) New score  -> recompute mastery for that student/topic.
CREATE TRIGGER trg_scores_gap_insert AFTER INSERT ON assessment_scores
BEGIN
    -- open or refresh a gap when mastery < 60 %
    INSERT INTO learning_gaps (student_id, topic_id, mastery_pct, severity, status)
    SELECT NEW.student_id, NEW.topic_id, m,
           CASE WHEN m < 40 THEN 'critical' ELSE 'moderate' END, 'open'
    FROM (SELECT ROUND(100.0 * SUM(marks) / SUM(max_marks), 1) AS m
          FROM (SELECT s.marks, s.max_marks FROM assessment_scores s
                JOIN assessments a ON a.assessment_id = s.assessment_id
                WHERE s.student_id = NEW.student_id AND s.topic_id = NEW.topic_id
                ORDER BY a.assessment_date DESC, s.score_id DESC LIMIT 2))
    WHERE m < 60
    ON CONFLICT (student_id, topic_id) DO UPDATE SET
        mastery_pct = excluded.mastery_pct,
        severity    = excluded.severity,
        status      = 'open',
        resolved_at = NULL,
        updated_at  = datetime('now');

    -- resolve an existing gap when mastery reaches >= 60 %
    UPDATE learning_gaps
       SET mastery_pct = (SELECT ROUND(100.0 * SUM(marks) / SUM(max_marks), 1)
                          FROM (SELECT s.marks, s.max_marks FROM assessment_scores s
                                JOIN assessments a ON a.assessment_id = s.assessment_id
                                WHERE s.student_id = NEW.student_id AND s.topic_id = NEW.topic_id
                                ORDER BY a.assessment_date DESC, s.score_id DESC LIMIT 2)),
           severity    = 'none',
           resolved_at = CASE WHEN status = 'open' THEN datetime('now') ELSE resolved_at END,
           status      = 'resolved',
           updated_at  = datetime('now')
     WHERE student_id = NEW.student_id AND topic_id = NEW.topic_id
       AND (SELECT ROUND(100.0 * SUM(marks) / SUM(max_marks), 1)
            FROM (SELECT s.marks, s.max_marks FROM assessment_scores s
                  JOIN assessments a ON a.assessment_id = s.assessment_id
                  WHERE s.student_id = NEW.student_id AND s.topic_id = NEW.topic_id
                  ORDER BY a.assessment_date DESC, s.score_id DESC LIMIT 2)) >= 60;
END;

-- (b) Corrected score -> same recomputation.
CREATE TRIGGER trg_scores_gap_update AFTER UPDATE OF marks, max_marks ON assessment_scores
BEGIN
    INSERT INTO learning_gaps (student_id, topic_id, mastery_pct, severity, status)
    SELECT NEW.student_id, NEW.topic_id, m,
           CASE WHEN m < 40 THEN 'critical' ELSE 'moderate' END, 'open'
    FROM (SELECT ROUND(100.0 * SUM(marks) / SUM(max_marks), 1) AS m
          FROM (SELECT s.marks, s.max_marks FROM assessment_scores s
                JOIN assessments a ON a.assessment_id = s.assessment_id
                WHERE s.student_id = NEW.student_id AND s.topic_id = NEW.topic_id
                ORDER BY a.assessment_date DESC, s.score_id DESC LIMIT 2))
    WHERE m < 60
    ON CONFLICT (student_id, topic_id) DO UPDATE SET
        mastery_pct = excluded.mastery_pct,
        severity    = excluded.severity,
        status      = 'open',
        resolved_at = NULL,
        updated_at  = datetime('now');

    UPDATE learning_gaps
       SET mastery_pct = (SELECT ROUND(100.0 * SUM(marks) / SUM(max_marks), 1)
                          FROM (SELECT s.marks, s.max_marks FROM assessment_scores s
                                JOIN assessments a ON a.assessment_id = s.assessment_id
                                WHERE s.student_id = NEW.student_id AND s.topic_id = NEW.topic_id
                                ORDER BY a.assessment_date DESC, s.score_id DESC LIMIT 2)),
           severity    = 'none',
           resolved_at = CASE WHEN status = 'open' THEN datetime('now') ELSE resolved_at END,
           status      = 'resolved',
           updated_at  = datetime('now')
     WHERE student_id = NEW.student_id AND topic_id = NEW.topic_id
       AND (SELECT ROUND(100.0 * SUM(marks) / SUM(max_marks), 1)
            FROM (SELECT s.marks, s.max_marks FROM assessment_scores s
                  JOIN assessments a ON a.assessment_id = s.assessment_id
                  WHERE s.student_id = NEW.student_id AND s.topic_id = NEW.topic_id
                  ORDER BY a.assessment_date DESC, s.score_id DESC LIMIT 2)) >= 60;
END;

-- (c) Gap resolved -> automatically close open interventions as "improved".
CREATE TRIGGER trg_gap_resolved_close_interventions
AFTER UPDATE OF status ON learning_gaps
WHEN NEW.status = 'resolved' AND OLD.status = 'open'
BEGIN
    UPDATE interventions
       SET status = 'completed', outcome = 'improved', completed_at = datetime('now')
     WHERE gap_id = NEW.gap_id AND status IN ('planned','in_progress');
END;

-- ============================================================================
-- VIEWS : reusable analytics (also the data source for Power BI)
-- ============================================================================
-- Each student's percentage per assessment (performance tracking)
CREATE VIEW v_student_assessment_summary AS
SELECT sc.student_id, a.assessment_id, a.title, a.assessment_date, a.subject_id,
       sub.name AS subject_name,
       SUM(sc.marks) AS marks, SUM(sc.max_marks) AS max_marks,
       ROUND(100.0 * SUM(sc.marks) / SUM(sc.max_marks), 1) AS pct
FROM assessment_scores sc
JOIN assessments a ON a.assessment_id = sc.assessment_id
JOIN subjects sub  ON sub.subject_id = a.subject_id
GROUP BY sc.student_id, a.assessment_id;

-- All-time topic percentage per student
CREATE VIEW v_student_topic_performance AS
SELECT sc.student_id, sc.topic_id, t.name AS topic_name, t.subject_id,
       COUNT(*) AS attempts,
       ROUND(100.0 * SUM(sc.marks) / SUM(sc.max_marks), 1) AS avg_pct
FROM assessment_scores sc JOIN topics t ON t.topic_id = sc.topic_id
GROUP BY sc.student_id, sc.topic_id;

-- Class-level topic analytics (teacher dashboard)
CREATE VIEW v_class_topic_analytics AS
SELECT st.class_id, t.subject_id, sub.name AS subject_name, t.topic_id, t.name AS topic_name,
       COUNT(DISTINCT sc.student_id) AS students_assessed,
       ROUND(100.0 * SUM(sc.marks) / SUM(sc.max_marks), 1) AS class_avg_pct,
       (SELECT COUNT(*) FROM learning_gaps g JOIN students s2 ON s2.student_id = g.student_id
         WHERE s2.class_id = st.class_id AND g.topic_id = t.topic_id AND g.status = 'open') AS students_with_gap
FROM assessment_scores sc
JOIN students st ON st.student_id = sc.student_id
JOIN topics t    ON t.topic_id = sc.topic_id
JOIN subjects sub ON sub.subject_id = t.subject_id
GROUP BY st.class_id, t.topic_id;

-- Recommendation engine: open gap  ->  matching resources
-- rank 1 = best fit (critical->basic, moderate->intermediate); advanced is never recommended for a gap
CREATE VIEW v_recommendations AS
SELECT g.student_id, g.gap_id, g.topic_id, t.name AS topic_name, g.severity, g.mastery_pct,
       r.resource_id, r.title, r.resource_type, r.difficulty,
       CASE WHEN (g.severity = 'critical' AND r.difficulty = 'basic')
              OR (g.severity = 'moderate' AND r.difficulty = 'intermediate') THEN 1 ELSE 2 END AS match_rank,
       COALESCE(rp.status, 'new') AS progress_status
FROM learning_gaps g
JOIN topics t    ON t.topic_id = g.topic_id
JOIN resources r ON r.topic_id = g.topic_id AND r.difficulty <> 'advanced'
LEFT JOIN resource_progress rp ON rp.resource_id = r.resource_id AND rp.student_id = g.student_id
WHERE g.status = 'open';

-- Intervention effectiveness (mastery before vs now)
CREATE VIEW v_intervention_outcomes AS
SELECT i.intervention_id, i.intervention_type, i.status, i.outcome,
       g.student_id, st.class_id, g.topic_id, t.name AS topic_name, t.subject_id,
       i.mastery_at_start, g.mastery_pct AS mastery_now,
       ROUND(g.mastery_pct - i.mastery_at_start, 1) AS improvement,
       i.start_date, i.due_date, i.completed_at, i.teacher_id
FROM interventions i
JOIN learning_gaps g ON g.gap_id = i.gap_id
JOIN students st     ON st.student_id = g.student_id
JOIN topics t        ON t.topic_id = g.topic_id;
