/* LearnGap single-page frontend. No inline scripts/styles (strict CSP).
   [SEC] All dynamic text goes through esc() before reaching innerHTML -> XSS protection. */
(function () {
  "use strict";
  const $app = document.getElementById("app");
  const S = { user: null, csrf: "", tab: null, classes: [], classId: null, subjectId: null, data: {} };

  // ---------- helpers
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v) => (v == null ? "-" : Number(v).toFixed(1) + "%");
  const label = (s) => esc(String(s || "").replace(/_/g, " "));
  const pill = (s) => `<span class="pill ${esc(s)}">${label(s)}</span>`;
  const barCls = (v) => (v < 40 ? "critical" : v < 60 ? "moderate" : "good");
  const bar = (v) => `<div class="bar"><i class="${barCls(v)}" data-w="${Math.max(0, Math.min(100, v))}"></i></div>`;
  const today = () => new Date().toISOString().slice(0, 10);
  const addDays = (n) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);

  function toast(msg) {
    const t = document.getElementById("toast");
    t.textContent = msg; t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 2600);
  }

  async function api(path, opts = {}) {
    const o = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
    if (opts.body instanceof FormData) o.body = opts.body;
    else if (opts.body) { o.body = JSON.stringify(opts.body); o.headers["Content-Type"] = "application/json"; }
    if (o.method !== "GET") o.headers["X-CSRF-Token"] = S.csrf;
    const r = await fetch(path, o);
    let data = null;
    try { data = await r.json(); } catch (e) { /* non-JSON */ }
    if (!r.ok) {
      if (r.status === 401 && S.user) { S.user = null; render(); }
      throw new Error((data && data.error) || "Request failed (" + r.status + ")");
    }
    return data;
  }
  const act = async (fn) => { try { await fn(); } catch (e) { toast(e.message); } };

  // ---------- charts (inline SVG, presentation attributes only)
  function lineChart(points, opts = {}) {
    // points: [{x:label, y:number}]
    if (!points.length) return '<div class="empty">No data yet.</div>';
    const W = 520, H = 220, L = 38, R = 14, T = 12, B = 34;
    const px = (i) => L + (points.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (points.length - 1));
    const py = (v) => T + (H - T - B) * (1 - v / 100);
    let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.title || "Trend chart")}">`;
    [0, 25, 50, 75, 100].forEach((g) => {
      s += `<line class="ax" x1="${L}" x2="${W - R}" y1="${py(g)}" y2="${py(g)}"/><text x="${L - 6}" y="${py(g) + 4}" text-anchor="end">${g}</text>`;
    });
    s += `<line class="thr" x1="${L}" x2="${W - R}" y1="${py(60)}" y2="${py(60)}"/>`;
    s += `<polyline class="ln" points="${points.map((p, i) => px(i) + "," + py(p.y)).join(" ")}"/>`;
    points.forEach((p, i) => {
      s += `<circle class="dot" cx="${px(i)}" cy="${py(p.y)}" r="4"><title>${esc(p.x)}: ${p.y}%</title></circle>`;
      s += `<text x="${px(i)}" y="${H - 14}" text-anchor="middle">${esc(p.x)}</text>`;
    });
    return s + "</svg>";
  }

  function barChart(items) {
    // items: [{name, value}] horizontal bars sorted by caller; red line = 60% threshold
    if (!items.length) return '<div class="empty">No data yet.</div>';
    const rowH = 30, L = 130, W = 520, R = 40, H = items.length * rowH + 24;
    const x = (v) => L + ((W - L - R) * v) / 100;
    let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Average score by topic">`;
    items.forEach((it, i) => {
      const y = 6 + i * rowH, cls = it.value < 40 ? "b-crit" : it.value < 60 ? "b-mod" : "b-ok";
      const name = it.name.length > 20 ? it.name.slice(0, 19) + "…" : it.name;
      s += `<text x="${L - 8}" y="${y + 15}" text-anchor="end">${esc(name)}</text>`;
      s += `<rect class="${cls}" x="${L}" y="${y + 3}" width="${Math.max(2, x(it.value) - L)}" height="16" rx="3"><title>${esc(it.name)}: ${it.value}%</title></rect>`;
      s += `<text x="${x(it.value) + 5}" y="${y + 15}">${it.value}%</text>`;
    });
    s += `<line class="thr" x1="${x(60)}" x2="${x(60)}" y1="0" y2="${H - 18}"/><text x="${x(60)}" y="${H - 4}" text-anchor="middle">60% target</text>`;
    return s + "</svg>";
  }

  // ---------- shell
  const TABS = {
    student: [["overview", "My Performance"], ["gaps", "Learning Gaps"], ["resources", "Recommended Resources"],
              ["interventions", "Teacher Support"], ["progress", "My Progress"]],
    teacher: [["dashboard", "Class Dashboard"], ["students", "Students"], ["assessments", "Assessments"],
              ["interventions", "Interventions"], ["resources", "Resources"]],
    admin: [["dashboard", "Overview"], ["classview", "Class Analytics"], ["users", "Users"], ["logs", "Activity Log"], ["export", "Power BI Export"]],
  };

  function frame(inner) {
    const tabs = TABS[S.user.role].map(([k, n]) => `<button data-act="tab" data-v="${k}" class="${S.tab === k ? "on" : ""}">${esc(n)}</button>`).join("");
    return `<header class="top"><span class="logo">LearnGap</span><nav>${tabs}</nav><span class="sp"></span>
      <span class="who">${esc(S.user.full_name)} · ${esc(S.user.role)}</span>
      <button class="btn sec sm" data-act="pw">Change password</button><button class="btn sec sm" data-act="logout">Log out</button></header>
      <main>${inner}</main>`;
  }

  function loginView(err) {
    return `<div class="card login"><h1>LearnGap</h1><p class="hint">Learning gap identification &amp; intervention platform</p>
      <form id="loginForm"><label for="u">Username</label><input id="u" autocomplete="username" required maxlength="40">
      <label for="p">Password</label><input id="p" type="password" autocomplete="current-password" required maxlength="128">
      <div class="err" id="loginErr">${esc(err || "")}</div><button class="btn block">Log in</button></form>
      <div class="demo"><b>Demo accounts</b><br>Student <code>stu01</code> / <code>Student@123</code><br>
      Teacher <code>priya</code> (Maths) or <code>rahul</code> (Science) / <code>Teacher@123</code><br>Admin <code>admin</code> / <code>Admin@123</code></div></div>`;
  }

  // ---------- STUDENT views
  async function studentView() {
    const t = S.tab;
    if (t === "overview") {
      const d = await api("/api/student/overview");
      const byAssess = d.assessments.map((a) => ({ x: a.subject_name.slice(0, 4) + " " + a.assessment_date.slice(5), y: a.pct }));
      return `<h1>My academic performance</h1><div class="grid g2">
        <div class="card"><h2>Assessment scores over time</h2>${lineChart(byAssess, { title: "Assessment percentage over time" })}<p class="hint">Dashed line = 60% target.</p></div>
        <div class="card"><h2>Topic-wise average</h2>${barChart(d.topics.map((x) => ({ name: x.topic_name, value: x.avg_pct })))}</div></div>
        <div class="card"><h2>All assessments</h2><div class="tw"><table><tr><th>Date</th><th>Assessment</th><th>Marks</th><th>Score</th></tr>
        ${d.assessments.slice().reverse().map((a) => `<tr><td>${esc(a.assessment_date)}</td><td>${esc(a.title)}</td><td>${a.marks}/${a.max_marks}</td><td>${pct(a.pct)}</td></tr>`).join("")}</table></div></div>`;
    }
    if (t === "gaps") {
      const d = await api("/api/student/gaps");
      const rows = (l) => l.map((g) => `<tr><td>${esc(g.subject_name)}</td><td>${esc(g.topic_name)}</td><td>${bar(g.mastery_pct)}<small>${pct(g.mastery_pct)}</small></td><td>${pill(g.severity === "none" ? "resolved" : g.severity)}</td><td>${g.active_interventions ? pill("in_progress") + " teacher support" : '<span class="hint">-</span>'}</td></tr>`).join("");
      return `<h1>Topic-wise learning gaps</h1><p class="hint">A gap is a topic where your last two results average below 60%.</p>
        <div class="card"><h2>Open gaps (${d.open.length})</h2>${d.open.length ? `<div class="tw"><table><tr><th>Subject</th><th>Topic</th><th>Mastery</th><th>Severity</th><th>Support</th></tr>${rows(d.open)}</table></div>` : '<div class="empty">No open gaps. Great work!</div>'}</div>
        <div class="card"><h2>Gaps you closed (${d.resolved.length})</h2>${d.resolved.length ? `<div class="tw"><table><tr><th>Subject</th><th>Topic</th><th>Mastery</th><th>Status</th><th></th></tr>${rows(d.resolved)}</table></div>` : '<div class="empty">None yet.</div>'}</div>`;
    }
    if (t === "resources") {
      const d = await api("/api/student/recommendations");
      if (!d.length) return `<h1>Recommended resources</h1><div class="card empty">No open gaps, so no recommendations right now.</div>`;
      const groups = {};
      d.forEach((r) => { (groups[r.topic_name] = groups[r.topic_name] || { g: r, items: [] }).items.push(r); });
      return `<h1>Recommended resources</h1><p class="hint">Matched to your weakest topics. Basic material is recommended first for critical gaps.</p>` +
        Object.values(groups).map(({ g, items }) => `<div class="card"><h2>${esc(g.topic_name)} ${pill(g.severity)} <small class="hint">${pct(g.mastery_pct)}</small></h2><div class="tw"><table>
        <tr><th>Resource</th><th>Type</th><th>Level</th><th>Status</th><th></th></tr>
        ${items.sort((a, b) => a.match_rank - b.match_rank).map((r) => `<tr><td>${esc(r.title)} ${r.match_rank === 1 ? '<span class="pill moderate">best fit</span>' : ""}</td><td>${label(r.resource_type)}</td><td>${label(r.difficulty)}</td>
        <td>${pill(r.progress_status === "new" ? "pending" : r.progress_status)}</td><td>
        <a class="btn sm" data-act="openres" data-id="${r.resource_id}" href="/api/resources/${r.resource_id}/open" target="_blank" rel="noopener">Open</a>
        ${r.progress_status !== "completed" ? `<button class="btn sec sm" data-act="resdone" data-id="${r.resource_id}">Mark done</button>` : ""}</td></tr>`).join("")}</table></div></div>`).join("");
    }
    if (t === "interventions") {
      const d = await api("/api/student/interventions");
      return `<h1>Support from my teachers</h1>` + (d.length ? d.map((i) => `<div class="card"><h2>${esc(i.topic_name)} · ${label(i.intervention_type)} ${pill(i.status)} ${pill(i.outcome)}</h2>
        <p>${esc(i.plan)}</p><p class="hint">By ${esc(i.teacher_name)} · ${esc(i.start_date)} to ${esc(i.due_date)} · mastery ${pct(i.mastery_at_start)} → ${pct(i.mastery_now)}</p>
        ${i.followups.map((f) => `<div class="followup"><b>${esc(f.followup_date)}</b> ${esc(f.notes)}</div>`).join("")}</div>`).join("") : '<div class="card empty">No interventions yet.</div>');
    }
    if (t === "progress") {
      const [p, ov] = await Promise.all([api("/api/student/progress"), api("/api/student/overview")]);
      const diff = p.first_pct != null ? (p.latest_pct - p.first_pct).toFixed(1) : null;
      const trendTopics = {};
      ov.trend.forEach((r) => { (trendTopics[r.topic_name] = trendTopics[r.topic_name] || []).push({ x: r.assessment_date.slice(5), y: r.pct }); });
      return `<h1>My progress &amp; improvement</h1><div class="kpis">
        <div class="kpi ok"><b>${p.resolved_gaps}</b><span>Gaps closed</span></div><div class="kpi bad"><b>${p.open_gaps}</b><span>Open gaps</span></div>
        <div class="kpi"><b>${pct(p.latest_pct)}</b><span>Latest assessment</span></div>
        <div class="kpi ${diff >= 0 ? "ok" : "bad"}"><b>${diff == null ? "-" : (diff > 0 ? "+" : "") + diff}</b><span>Change since first test</span></div>
        <div class="kpi"><b>${p.resources_completed}</b><span>Resources completed</span></div></div>
        <div class="card"><h2>Most improved topics</h2>${p.top_improvements.length ? `<table>${p.top_improvements.map((x) => `<tr><td>${esc(x.topic_name)}</td><td>${x.change > 0 ? "+" : ""}${x.change} points</td></tr>`).join("")}</table>` : '<div class="empty">Not enough data.</div>'}</div>
        <div class="grid g2">${Object.entries(trendTopics).map(([n, pts]) => `<div class="card"><h3>${esc(n)}</h3>${lineChart(pts, { title: n + " trend" })}</div>`).join("")}</div>`;
    }
  }

  // ---------- TEACHER / ADMIN shared selectors
  function classPicker() {
    const classes = [...new Map(S.classes.map((c) => [c.class_id, c.name])).entries()];
    const subjects = [...new Map(S.classes.filter((c) => c.class_id === S.classId).map((c) => [c.subject_id, c.subject_name])).entries()];
    return `<div class="card row"><div><label for="selClass">Class</label><select id="selClass">${classes.map(([id, n]) => `<option value="${id}" ${id === S.classId ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>
      <div><label for="selSub">Subject</label><select id="selSub"><option value="">All my subjects</option>${subjects.map(([id, n]) => `<option value="${id}" ${id === S.subjectId ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div></div>`;
  }

  function dashboardHtml(d) {
    const k = d.kpis;
    return `<div class="kpis"><div class="kpi"><b>${k.students}</b><span>Students</span></div><div class="kpi"><b>${pct(k.class_avg)}</b><span>Class average</span></div>
      <div class="kpi bad"><b>${k.open_gaps || 0}</b><span>Open learning gaps</span></div><div class="kpi bad"><b>${k.critical || 0}</b><span>Critical gaps (&lt;40%)</span></div>
      <div class="kpi warn"><b>${k.students_at_risk || 0}</b><span>Students at risk</span></div><div class="kpi warn"><b>${k.gaps_without_intervention}</b><span>Gaps with no intervention</span></div></div>
      <div class="grid g2"><div class="card"><h2>Average by topic (weakest first)</h2>${barChart(d.topics.map((t) => ({ name: t.topic_name, value: t.class_avg_pct })))}</div>
      <div class="card"><h2>Class average over time</h2>${lineChart(d.trend.map((t) => ({ x: t.assessment_date.slice(5), y: t.avg_pct })), { title: "Class average trend" })}</div></div>
      <div class="grid g2"><div class="card"><h2>Topics where most students struggle</h2><div class="tw"><table><tr><th>Topic</th><th>Class avg</th><th>Students with gap</th></tr>
      ${d.topics.slice(0, 6).map((t) => `<tr><td>${esc(t.topic_name)}</td><td>${pct(t.class_avg_pct)}</td><td>${t.students_with_gap} / ${t.students_assessed}</td></tr>`).join("")}</table></div></div>
      <div class="card"><h2>Students needing attention</h2>${d.at_risk.length ? `<div class="tw"><table><tr><th>Student</th><th>Gaps</th><th>Lowest</th><th>Topics</th></tr>${d.at_risk.map((s) => `<tr><td>${esc(s.full_name)}</td><td>${s.open_gaps}</td><td>${pct(s.lowest_mastery)}</td><td>${esc(s.topics)}</td></tr>`).join("")}</table></div>` : '<div class="empty">No students at risk.</div>'}</div></div>
      <div class="card"><h2>Intervention outcomes</h2>${d.outcomes.length ? `<table><tr><th>Status</th><th>Outcome</th><th>Count</th><th>Avg mastery change</th></tr>${d.outcomes.map((o) => `<tr><td>${pill(o.status)}</td><td>${pill(o.outcome)}</td><td>${o.n}</td><td>${o.avg_improvement > 0 ? "+" : ""}${o.avg_improvement}</td></tr>`).join("")}</table>` : '<div class="empty">No interventions yet.</div>'}</div>`;
  }

  async function teacherView() {
    const t = S.tab, cid = S.classId;
    const sub = S.subjectId ? "&subject_id=" + S.subjectId : "";
    if (t === "dashboard") return `<h1>Class learning analytics</h1>${classPicker()}${dashboardHtml(await api(`/api/teacher/dashboard?class_id=${cid}${sub}`))}`;
    if (t === "students") {
      const d = await api(`/api/teacher/students?class_id=${cid}`);
      return `<h1>Students</h1>${classPicker()}<div class="card tw"><table><tr><th>Roll</th><th>Name</th><th>Average</th><th>Open gaps</th><th>Closed</th><th></th></tr>
        ${d.map((s) => `<tr><td>${esc(s.roll_no)}</td><td>${esc(s.full_name)}</td><td>${pct(s.avg_pct)}</td><td>${s.open_gaps ? `<span class="pill moderate">${s.open_gaps}</span>` : "0"}</td><td>${s.resolved_gaps}</td>
        <td><button class="btn sec sm" data-act="student" data-id="${s.student_id}">View profile</button></td></tr>`).join("")}</table></div>`;
    }
    if (t === "assessments") {
      const d = await api(`/api/teacher/assessments?class_id=${cid}`);
      return `<h1>Assessments</h1>${classPicker()}${S.user.role === "teacher" ? '<p><button class="btn" data-act="newassess">+ Record new assessment</button></p>' : ""}
        <div class="card tw"><table><tr><th>Date</th><th>Title</th><th>Subject</th><th>Students</th><th>Class avg</th></tr>
        ${d.map((a) => `<tr><td>${esc(a.assessment_date)}</td><td>${esc(a.title)}</td><td>${esc(a.subject_name)}</td><td>${a.students}</td><td>${pct(a.avg_pct)}</td></tr>`).join("")}</table></div>`;
    }
    if (t === "interventions") {
      const [list, gaps] = await Promise.all([api(`/api/teacher/interventions?class_id=${cid}`), api(`/api/teacher/gaps?class_id=${cid}`)]);
      const open = gaps.filter((g) => !g.active_interventions);
      return `<h1>Intervention &amp; follow-up management</h1>${classPicker()}
        <div class="card"><h2>Gaps waiting for an intervention (${open.length})</h2>${open.length ? `<div class="tw"><table><tr><th>Student</th><th>Topic</th><th>Mastery</th><th>Severity</th><th></th></tr>
        ${open.map((g) => `<tr><td>${esc(g.full_name)}</td><td>${esc(g.topic_name)}</td><td>${pct(g.mastery_pct)}</td><td>${pill(g.severity)}</td>
        <td>${S.user.role === "teacher" ? `<button class="btn sm" data-act="newint" data-id="${g.gap_id}" data-name="${esc(g.full_name)}" data-topic="${esc(g.topic_name)}">Plan intervention</button>` : ""}</td></tr>`).join("")}</table></div>` : '<div class="empty">Every open gap has an active intervention.</div>'}</div>
        <h2>Interventions</h2>${list.map((i) => `<div class="card"><h3>${esc(i.full_name)} · ${esc(i.topic_name)} ${pill(i.status)} ${pill(i.outcome)} ${i.overdue ? pill("overdue") : ""}</h3>
        <p>${label(i.intervention_type)}: ${esc(i.plan)}</p><p class="hint">${esc(i.start_date)} → ${esc(i.due_date)} · mastery ${pct(i.mastery_at_start)} → ${pct(i.mastery_now)}</p>
        ${i.followups.map((f) => `<div class="followup"><b>${esc(f.followup_date)}</b> ${esc(f.notes)} <span class="hint">(mastery ${pct(f.mastery_snapshot)})</span></div>`).join("")}
        ${S.user.role === "teacher" && (i.status === "in_progress" || i.status === "planned") ? `<p><button class="btn sec sm" data-act="followup" data-id="${i.intervention_id}">Add follow-up</button>
        <button class="btn sec sm" data-act="closeint" data-id="${i.intervention_id}">Mark completed</button></p>` : ""}</div>`).join("") || '<div class="card empty">No interventions yet.</div>'}`;
    }
    if (t === "resources") {
      const subs = [...new Map(S.classes.map((c) => [c.subject_id, c.subject_name])).entries()];
      const sid = S.subjectId || subs[0][0];
      const d = await api(`/api/teacher/resources?subject_id=${sid}`);
      return `<h1>Learning resources</h1><div class="card row"><div><label for="selSub2">Subject</label><select id="selSub2">${subs.map(([id, n]) => `<option value="${id}" ${id === sid ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>
        ${S.user.role === "teacher" ? `<div class="auto"><button class="btn" data-act="newres" data-sub="${sid}">+ Add resource</button></div>` : ""}</div>
        <div class="card tw"><table><tr><th>Topic</th><th>Title</th><th>Type</th><th>Level</th><th>Stored in</th><th></th></tr>
        ${d.map((r) => `<tr><td>${esc(r.topic_name)}</td><td>${esc(r.title)}</td><td>${label(r.resource_type)}</td><td>${label(r.difficulty)}</td><td>${esc(r.storage)}</td><td><a class="btn sec sm" href="/api/resources/${r.resource_id}/open" target="_blank" rel="noopener">Open</a></td></tr>`).join("")}</table></div>`;
    }
  }

  async function studentDetail(id) {
    const d = await api("/api/teacher/students/" + id);
    const p = d.progress;
    return `<p><button class="btn sec sm" data-act="back">← Back</button></p><h1>${esc(d.info.full_name)} <small class="hint">${esc(d.info.roll_no)} · ${esc(d.info.class_name)}</small></h1>
      <div class="kpis"><div class="kpi bad"><b>${p.open_gaps}</b><span>Open gaps</span></div><div class="kpi ok"><b>${p.resolved_gaps}</b><span>Closed gaps</span></div>
      <div class="kpi"><b>${pct(p.latest_pct)}</b><span>Latest assessment</span></div><div class="kpi"><b>${p.resources_completed}</b><span>Resources completed</span></div></div>
      <div class="grid g2"><div class="card"><h2>Performance over time</h2>${lineChart(d.overview.assessments.map((a) => ({ x: a.subject_name.slice(0, 4) + " " + a.assessment_date.slice(5), y: a.pct })))}</div>
      <div class="card"><h2>Topic averages</h2>${barChart(d.overview.topics.map((x) => ({ name: x.topic_name, value: x.avg_pct })))}</div></div>
      <div class="card"><h2>Open gaps</h2>${d.open.length ? `<table><tr><th>Topic</th><th>Mastery</th><th>Severity</th></tr>${d.open.map((g) => `<tr><td>${esc(g.topic_name)}</td><td>${pct(g.mastery_pct)}</td><td>${pill(g.severity)}</td></tr>`).join("")}</table>` : '<div class="empty">None.</div>'}</div>
      <div class="card"><h2>Interventions</h2>${d.interventions.map((i) => `<p><b>${esc(i.topic_name)}</b> · ${label(i.intervention_type)} ${pill(i.status)} ${pill(i.outcome)}<br><span class="hint">${pct(i.mastery_at_start)} → ${pct(i.mastery_now)}</span></p>`).join("") || '<div class="empty">None.</div>'}</div>`;
  }

  // ---------- ADMIN views
  async function adminView() {
    const t = S.tab;
    if (t === "dashboard") {
      const d = await api("/api/admin/stats");
      return `<h1>Institution overview</h1><div class="kpis">
        <div class="kpi"><b>${d.students}</b><span>Students</span></div><div class="kpi"><b>${d.teachers}</b><span>Teachers</span></div><div class="kpi"><b>${d.assessments}</b><span>Assessments</span></div>
        <div class="kpi bad"><b>${d.open_gaps}</b><span>Open gaps</span></div><div class="kpi ok"><b>${d.resolved_gaps}</b><span>Resolved gaps</span></div>
        <div class="kpi warn"><b>${d.active_interventions}</b><span>Active interventions</span></div><div class="kpi ok"><b>${d.improved}</b><span>Improved after intervention</span></div>
        <div class="kpi ${d.failed_logins_24h ? "bad" : ""}"><b>${d.failed_logins_24h}</b><span>Failed logins (24h)</span></div></div>
        <div class="card"><h2>By class</h2><table><tr><th>Class</th><th>Students</th><th>Average</th><th>Open gaps</th></tr>${d.by_class.map((c) => `<tr><td>${esc(c.name)}</td><td>${c.students}</td><td>${pct(c.avg_pct)}</td><td>${c.open_gaps}</td></tr>`).join("")}</table></div>`;
    }
    if (t === "classview") return `<h1>Class analytics</h1>${classPicker()}${dashboardHtml(await api(`/api/teacher/dashboard?class_id=${S.classId}${S.subjectId ? "&subject_id=" + S.subjectId : ""}`))}`;
    if (t === "users") {
      const d = await api("/api/admin/users");
      return `<h1>User management</h1><p><button class="btn" data-act="newuser">+ Add user</button></p><div class="card tw"><table><tr><th>Username</th><th>Name</th><th>Role</th><th>Class</th><th>Status</th><th></th></tr>
        ${d.map((u) => `<tr><td>${esc(u.username)}</td><td>${esc(u.full_name)}</td><td>${esc(u.role)}</td><td>${esc(u.class_name || "-")}</td><td>${u.is_active ? pill("completed").replace("completed", "active") : pill("critical").replace("critical", "disabled")}</td>
        <td>${u.user_id !== S.user.user_id ? `<button class="btn sec sm" data-act="toggleuser" data-id="${u.user_id}" data-on="${u.is_active ? 0 : 1}">${u.is_active ? "Disable" : "Enable"}</button>` : ""}</td></tr>`).join("")}</table></div>`;
    }
    if (t === "logs") {
      const d = await api("/api/admin/logs");
      return `<h1>Security activity log</h1><p class="hint">Latest 200 events: logins, failures, access denials, data changes.</p><div class="card tw"><table><tr><th>Time (UTC)</th><th>User</th><th>Action</th><th>Detail</th><th>IP</th></tr>
        ${d.map((l) => `<tr><td>${esc(l.created_at)}</td><td>${esc(l.username)}</td><td>${label(l.action)}</td><td>${esc(l.detail || "")}</td><td>${esc(l.ip_address || "")}</td></tr>`).join("")}</table></div>`;
    }
    if (t === "export") return `<h1>Power BI export</h1><div class="card"><p>In production, Power BI connects directly to the Azure SQL views. For the local demo, download the same views as CSV and use <b>Get data → Text/CSV</b>.</p>
      <p><a class="btn" href="/api/export/v_student_assessment_summary.csv">Student assessment summary</a> <a class="btn" href="/api/export/v_class_topic_analytics.csv">Class topic analytics</a> <a class="btn" href="/api/export/v_intervention_outcomes.csv">Intervention outcomes</a></p></div>`;
  }

  // ---------- modals
  function modal(html) {
    const bg = document.createElement("div");
    bg.className = "modal-bg"; bg.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
    bg.addEventListener("click", (e) => { if (e.target === bg || e.target.dataset.act === "close") bg.remove(); });
    document.body.appendChild(bg);
    const f = bg.querySelector("input,select,textarea"); if (f) f.focus();
    return bg;
  }

  async function newAssessment() {
    const subs = S.classes.filter((c) => c.class_id === S.classId);
    const sid = S.subjectId && subs.some((s) => s.subject_id === S.subjectId) ? S.subjectId : subs[0].subject_id;
    const [topics, roster] = await Promise.all([api("/api/topics?subject_id=" + sid), api("/api/teacher/roster?class_id=" + S.classId)]);
    const m = modal(`<h2>Record assessment</h2><div class="row"><div><label>Subject</label><select id="as_sub">${subs.map((s) => `<option value="${s.subject_id}" ${s.subject_id === sid ? "selected" : ""}>${esc(s.subject_name)}</option>`).join("")}</select></div>
      <div><label>Title</label><input id="as_title" maxlength="120" value="Unit Test"></div><div><label>Date</label><input id="as_date" type="date" value="${today()}"></div>
      <div><label>Max marks per topic</label><input id="as_max" type="number" min="1" value="10"></div></div>
      <p class="hint">Enter marks for each student and topic. Learning gaps update automatically when you save.</p>
      <div class="tw"><table class="scoregrid"><tr><th>Student</th>${topics.map((t) => `<th>${esc(t.name)}</th>`).join("")}</tr>
      ${roster.map((s) => `<tr><td>${esc(s.full_name)}</td>${topics.map((t) => `<td><input type="number" min="0" step="0.5" data-s="${s.student_id}" data-t="${t.topic_id}"></td>`).join("")}</tr>`).join("")}</table></div>
      <div class="err" id="as_err"></div><p><button class="btn" id="as_save">Save assessment</button> <button class="btn sec" data-act="close">Cancel</button></p>`);
    m.querySelector("#as_sub").addEventListener("change", (e) => { S.subjectId = +e.target.value; m.remove(); act(newAssessment); });
    m.querySelector("#as_save").addEventListener("click", () => act(async () => {
      const max = +m.querySelector("#as_max").value;
      const scores = [...m.querySelectorAll("input[data-s]")].filter((i) => i.value !== "")
        .map((i) => ({ student_id: +i.dataset.s, topic_id: +i.dataset.t, marks: +i.value, max_marks: max }));
      try {
        const r = await api("/api/teacher/assessments", { method: "POST", body: { class_id: S.classId, subject_id: +m.querySelector("#as_sub").value, title: m.querySelector("#as_title").value, date: m.querySelector("#as_date").value, scores } });
        m.remove(); toast(`Saved ${r.scores} scores. Gaps updated.`); render();
      } catch (e) { m.querySelector("#as_err").textContent = e.message; }
    }));
  }

  function newIntervention(gapId, name, topic) {
    const m = modal(`<h2>Plan intervention</h2><p class="hint">${esc(name)} · ${esc(topic)}</p>
      <label>Type</label><select id="iv_type"><option value="extra_class">Extra class</option><option value="practice_set">Practice set</option><option value="peer_tutoring">Peer tutoring</option><option value="one_on_one">One-on-one session</option><option value="parent_meeting">Parent meeting</option><option value="resource_assignment">Resource assignment</option></select>
      <label>Plan</label><textarea id="iv_plan" rows="3" maxlength="1000"></textarea>
      <div class="row"><div><label>Start</label><input type="date" id="iv_s" value="${today()}"></div><div><label>Due</label><input type="date" id="iv_d" value="${addDays(21)}"></div></div>
      <div class="err" id="iv_err"></div><p><button class="btn" id="iv_save">Create</button> <button class="btn sec" data-act="close">Cancel</button></p>`);
    m.querySelector("#iv_save").addEventListener("click", () => act(async () => {
      try {
        await api("/api/teacher/interventions", { method: "POST", body: { gap_id: gapId, intervention_type: m.querySelector("#iv_type").value, plan: m.querySelector("#iv_plan").value, start_date: m.querySelector("#iv_s").value, due_date: m.querySelector("#iv_d").value } });
        m.remove(); toast("Intervention created."); render();
      } catch (e) { m.querySelector("#iv_err").textContent = e.message; }
    }));
  }

  function newFollowup(id) {
    const m = modal(`<h2>Add follow-up</h2><label>Date</label><input type="date" id="fu_d" value="${today()}"><label>Notes</label><textarea id="fu_n" rows="3" maxlength="1000"></textarea>
      <div class="err" id="fu_err"></div><p><button class="btn" id="fu_save">Save</button> <button class="btn sec" data-act="close">Cancel</button></p>`);
    m.querySelector("#fu_save").addEventListener("click", () => act(async () => {
      try { await api(`/api/teacher/interventions/${id}/followups`, { method: "POST", body: { followup_date: m.querySelector("#fu_d").value, notes: m.querySelector("#fu_n").value } }); m.remove(); toast("Follow-up saved."); render(); }
      catch (e) { m.querySelector("#fu_err").textContent = e.message; }
    }));
  }

  async function newResource(subjectId) {
    const topics = await api("/api/topics?subject_id=" + subjectId);
    const m = modal(`<h2>Add learning resource</h2><label>Topic</label><select id="rs_t">${topics.map((t) => `<option value="${t.topic_id}">${esc(t.name)}</option>`).join("")}</select>
      <label>Title</label><input id="rs_title" maxlength="150"><div class="row"><div><label>Type</label><select id="rs_type"><option>pdf</option><option>video</option><option>article</option><option>practice</option><option>document</option></select></div>
      <div><label>Level</label><select id="rs_diff"><option>basic</option><option>intermediate</option><option>advanced</option></select></div></div>
      <label>Upload file (pdf, docx, pptx, mp4, png, jpg, txt - max 10 MB)</label><input type="file" id="rs_file"><label>...or https link</label><input id="rs_url" placeholder="https://">
      <div class="err" id="rs_err"></div><p><button class="btn" id="rs_save">Save</button> <button class="btn sec" data-act="close">Cancel</button></p>`);
    m.querySelector("#rs_save").addEventListener("click", () => act(async () => {
      const fd = new FormData();
      fd.append("topic_id", m.querySelector("#rs_t").value); fd.append("title", m.querySelector("#rs_title").value);
      fd.append("resource_type", m.querySelector("#rs_type").value); fd.append("difficulty", m.querySelector("#rs_diff").value);
      const f = m.querySelector("#rs_file").files[0];
      if (f) fd.append("file", f); else fd.append("url", m.querySelector("#rs_url").value);
      try { await api("/api/teacher/resources", { method: "POST", body: fd }); m.remove(); toast("Resource added."); render(); }
      catch (e) { m.querySelector("#rs_err").textContent = e.message; }
    }));
  }

  async function newUser() {
    const classes = await api("/api/admin/classes");
    const m = modal(`<h2>Add user</h2><div class="row"><div><label>Role</label><select id="nu_role"><option value="student">Student</option><option value="teacher">Teacher</option></select></div>
      <div><label>Username</label><input id="nu_user" maxlength="40"></div></div><label>Full name</label><input id="nu_name" maxlength="100"><label>Email</label><input id="nu_mail" type="email">
      <label>Temporary password (8+ chars, letters and digits)</label><input id="nu_pw" type="password" autocomplete="new-password">
      <div id="nu_stu" class="row"><div><label>Class</label><select id="nu_class">${classes.map((c) => `<option value="${c.class_id}">${esc(c.name)}</option>`).join("")}</select></div><div><label>Roll no.</label><input id="nu_roll" maxlength="20"></div></div>
      <div id="nu_tea" class="row" hidden><div><label>Department</label><input id="nu_dep" maxlength="80"></div></div>
      <div class="err" id="nu_err"></div><p><button class="btn" id="nu_save">Create</button> <button class="btn sec" data-act="close">Cancel</button></p>`);
    const role = m.querySelector("#nu_role");
    role.addEventListener("change", () => { m.querySelector("#nu_stu").hidden = role.value !== "student"; m.querySelector("#nu_tea").hidden = role.value !== "teacher"; });
    m.querySelector("#nu_save").addEventListener("click", () => act(async () => {
      const b = { role: role.value, username: m.querySelector("#nu_user").value, full_name: m.querySelector("#nu_name").value, email: m.querySelector("#nu_mail").value, password: m.querySelector("#nu_pw").value };
      if (b.role === "student") { b.class_id = +m.querySelector("#nu_class").value; b.roll_no = m.querySelector("#nu_roll").value; } else b.department = m.querySelector("#nu_dep").value;
      try { await api("/api/admin/users", { method: "POST", body: b }); m.remove(); toast("User created."); render(); }
      catch (e) { m.querySelector("#nu_err").textContent = e.message; }
    }));
  }

  function changePassword() {
    const m = modal(`<h2>Change password</h2><label>Current password</label><input type="password" id="cp_o" autocomplete="current-password"><label>New password</label><input type="password" id="cp_n" autocomplete="new-password">
      <div class="err" id="cp_err"></div><p><button class="btn" id="cp_save">Update</button> <button class="btn sec" data-act="close">Cancel</button></p>`);
    m.querySelector("#cp_save").addEventListener("click", () => act(async () => {
      try { await api("/api/auth/change-password", { method: "POST", body: { current_password: m.querySelector("#cp_o").value, new_password: m.querySelector("#cp_n").value } }); m.remove(); toast("Password updated."); }
      catch (e) { m.querySelector("#cp_err").textContent = e.message; }
    }));
  }

  // ---------- render + events
  async function render() {
    if (!S.user) { $app.innerHTML = loginView(); return; }
    const role = S.user.role;
    if (!S.tab || !TABS[role].some(([k]) => k === S.tab)) S.tab = TABS[role][0][0];
    if (role !== "student" && !S.classes.length) {
      S.classes = await api("/api/teacher/classes");
      S.classId = S.classes.length ? S.classes[0].class_id : null;
    }
    let inner;
    try {
      if (S.detail) inner = await studentDetail(S.detail);
      else inner = await (role === "student" ? studentView() : role === "teacher" ? teacherView() : adminView());
    } catch (e) { inner = `<div class="card err">${esc(e.message)}</div>`; }
    $app.innerHTML = frame(inner || "");
    document.querySelectorAll("[data-w]").forEach((el) => { el.style.width = el.dataset.w + "%"; });   // CSSOM (CSP-safe)
  }

  document.addEventListener("submit", (e) => {
    if (e.target.id !== "loginForm") return;
    e.preventDefault();
    act(async () => {
      try {
        const r = await api("/api/auth/login", { method: "POST", body: { username: document.getElementById("u").value, password: document.getElementById("p").value } });
        S.user = r.user; S.csrf = r.csrf; S.tab = null; S.classes = []; S.detail = null; render();
      } catch (err) { document.getElementById("loginErr").textContent = err.message; }
    });
  });

  document.addEventListener("change", (e) => {
    if (e.target.id === "selClass") { S.classId = +e.target.value; S.subjectId = null; render(); }
    if (e.target.id === "selSub") { S.subjectId = e.target.value ? +e.target.value : null; render(); }
    if (e.target.id === "selSub2") { S.subjectId = +e.target.value; render(); }
  });

  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-act]");
    if (!el || el.dataset.act === "close") return;
    const a = el.dataset.act, id = el.dataset.id && +el.dataset.id;
    if (a === "openres") { if (S.user.role === "student") act(() => api(`/api/student/resources/${id}/progress`, { method: "POST", body: { status: "in_progress" } })); return; }
    if (el.tagName === "A") return;
    act(async () => {
      if (a === "tab") { S.tab = el.dataset.v; S.detail = null; render(); }
      else if (a === "logout") { await api("/api/auth/logout", { method: "POST" }); S.user = null; S.classes = []; render(); }
      else if (a === "pw") changePassword();
      else if (a === "resdone") { await api(`/api/student/resources/${id}/progress`, { method: "POST", body: { status: "completed" } }); toast("Marked as completed."); render(); }
      else if (a === "student") { S.detail = id; render(); }
      else if (a === "back") { S.detail = null; render(); }
      else if (a === "newassess") await newAssessment();
      else if (a === "newint") newIntervention(id, el.dataset.name, el.dataset.topic);
      else if (a === "followup") newFollowup(id);
      else if (a === "closeint") { if (confirm("Mark this intervention as completed?")) { const r = await api("/api/teacher/interventions/" + id, { method: "PATCH", body: { status: "completed" } }); toast("Closed: " + r.outcome.replace("_", " ")); render(); } }
      else if (a === "newres") await newResource(+el.dataset.sub);
      else if (a === "newuser") await newUser();
      else if (a === "toggleuser") { await api("/api/admin/users/" + id, { method: "PATCH", body: { is_active: el.dataset.on === "1" } }); render(); }
    });
  });

  api("/api/auth/me").then((r) => { S.user = r.user; S.csrf = r.csrf || ""; render(); }).catch(() => render());
})();
