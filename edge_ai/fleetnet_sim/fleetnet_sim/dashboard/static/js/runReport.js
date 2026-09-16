// Report tab: a structured, presentation-ready view of one run --
// header, config summary, KPI cards, timeline charts, and a static
// full-trajectory map -- built from GET /api/runs/{id}/report. This is
// the "show it to a person" alternative to the raw JSON in Run History
// and the live-only Watch canvas.

const _ROBOT_COLORS = [
  "#e63946", "#2a9d8f", "#f4a261", "#264653", "#e9c46a",
  "#8ab17d", "#457b9d", "#e07a5f", "#3d405b", "#81b29a",
  "#f2cc8f", "#bdb2ff",
];

const ReportView = {
  async load(runId) {
    const body = document.getElementById("reportBody");
    body.innerHTML = "<p>loading…</p>";
    let report, layout;
    try {
      report = await Api.getReport(runId);
      layout = await Api.getLayout(report.layout_id);
    } catch (err) {
      body.innerHTML = `<p class="error">error: ${err.message}</p>`;
      return;
    }
    this._render(body, report, layout);
  },

  _render(body, r, layout) {
    const m = r.metrics || {};
    const cfg = r.config || {};
    const duration = r.finished_at
      ? ((new Date(r.finished_at) - new Date(r.started_at)) / 1000).toFixed(1) + "s (wall clock)"
      : "—";

    body.innerHTML = `
      <div class="report-header">
        <h3>${r.run_id} <span class="status-pill status-${r.status}">${r.status}</span></h3>
        <table class="kv-table">
          <tr><td>Experiment</td><td>${r.experiment_id}</td><td>Layout</td><td>${r.layout_id}</td></tr>
          <tr><td>Seed</td><td>${r.seed}</td><td>dt</td><td>${r.dt}</td></tr>
          <tr><td>Started</td><td>${r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
              <td>Final tick</td><td>${r.final_tick ?? "—"}</td></tr>
          <tr><td>Wall time</td><td colspan="3">${duration}</td></tr>
        </table>
      </div>

      <div class="kpi-grid">
        ${this._kpi("Tasks completed", `${m.task?.completed ?? "—"} / ${m.task?.created ?? "—"}`)}
        ${this._kpi("Throughput", m.task?.throughput_per_min != null ? `${m.task.throughput_per_min.toFixed(1)} /min` : "—")}
        ${this._kpi("Mean completion", m.task?.mean_completion_time_s != null ? `${m.task.mean_completion_time_s.toFixed(1)} s` : "—")}
        ${this._kpi("P95 completion", m.task?.p95_completion_time_s != null ? `${m.task.p95_completion_time_s.toFixed(1)} s` : "—")}
        ${this._kpi("Collisions", m.safety?.collision_count ?? "—")}
        ${this._kpi("Total replans", m.planning?.total_replans ?? "—")}
        ${this._kpi("Mean travel dist.", m.travel?.mean_distance_m != null ? `${m.travel.mean_distance_m.toFixed(1)} m` : "—")}
        ${this._kpi("Fleet size", m.fleet?.robot_count ?? "—")}
      </div>

      <div class="report-section">
        <h4>Configuration</h4>
        <table class="kv-table">
          <tr><td>Robots</td><td>${cfg.fleet?.robot_count ?? "—"}</td>
              <td>Arrival rate</td><td>${cfg.tasks?.arrival_rate_per_s ?? "—"} /s</td></tr>
          <tr><td>Duration</td><td>${cfg.simulation?.duration_s ?? "—"} s</td>
              <td>Max speed</td><td>${cfg.fleet?.max_speed_mps ?? "—"} m/s</td></tr>
          <tr><td colspan="4">Algorithms: ${Object.entries(cfg.algorithms || {}).map(([k, v]) => `${k.replace("enable_", "")}: ${v ? "on" : "off"}`).join(" · ")}</td></tr>
        </table>
      </div>

      <div class="report-section charts-row">
        <div class="chart-box">
          <h4>Task completions (cumulative)</h4>
          <canvas width="380" height="180" id="chartTasks"></canvas>
        </div>
        <div class="chart-box">
          <h4>Conflicts &amp; congestion detours / 10s</h4>
          <canvas width="380" height="180" id="chartConflicts"></canvas>
        </div>
        <div class="chart-box">
          <h4>Replans / 10s</h4>
          <canvas width="380" height="180" id="chartReplans"></canvas>
        </div>
      </div>

      <div class="report-section">
        <h4>Full trajectory map</h4>
        <canvas id="reportTrajCanvas" width="900" height="700"></canvas>
        <div id="reportLegend" class="trajectory-legend"></div>
      </div>
    `;

    drawLineChart(
      document.getElementById("chartTasks").getContext("2d"),
      (r.task_timeline || []).map((p) => ({ t: p.t, y: p.cumulative })),
      { xLabel: "sim time (s)", yLabel: "completed", color: "#2a9d8f" }
    );
    const conflictPoints = this._mergeTimelines(r.conflict_timeline, r.congestion_timeline);
    drawBarChart(
      document.getElementById("chartConflicts").getContext("2d"),
      conflictPoints,
      { xLabel: "sim time (s)", yLabel: "events", color: "#e76f51" }
    );
    drawBarChart(
      document.getElementById("chartReplans").getContext("2d"),
      (r.replan_timeline || []).map((p) => ({ t: p.t, y: p.count })),
      { xLabel: "sim time (s)", yLabel: "replans", color: "#e9c46a" }
    );

    this._drawTrajectories(layout, r.trajectories || {});
  },

  _kpi(label, value) {
    return `<div class="kpi-card"><div class="kpi-value">${value}</div><div class="kpi-label">${label}</div></div>`;
  },

  _mergeTimelines(a = [], b = []) {
    const byT = {};
    for (const p of a) byT[p.t] = (byT[p.t] || 0) + p.count;
    for (const p of b) byT[p.t] = (byT[p.t] || 0) + p.count;
    return Object.keys(byT).map(Number).sort((x, y) => x - y).map((t) => ({ t, y: byT[t] }));
  },

  _drawTrajectories(layout, trajectories) {
    const canvas = document.getElementById("reportTrajCanvas");
    const ctx = canvas.getContext("2d");
    const transform = computeViewTransform(layout.geometry.footprint, canvas.width, canvas.height);
    drawLayout(ctx, layout, transform, { showGraph: false, showExclusions: true, showBottlenecks: false });

    const robotIds = Object.keys(trajectories);
    const legend = document.getElementById("reportLegend");
    legend.innerHTML = "";
    robotIds.forEach((rid, i) => {
      const path = trajectories[rid];
      const color = _ROBOT_COLORS[i % _ROBOT_COLORS.length];
      if (path.length < 2) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.globalAlpha = 0.85;
      ctx.beginPath();
      path.forEach(([x, y], j) => {
        const [cx, cy] = transform.toCanvas(x, y);
        if (j === 0) ctx.moveTo(cx, cy); else ctx.lineTo(cx, cy);
      });
      ctx.stroke();
      ctx.globalAlpha = 1.0;

      const swatch = document.createElement("span");
      swatch.className = "legend-item";
      swatch.innerHTML = `<i style="background:${color}"></i>${rid}`;
      legend.appendChild(swatch);
    });
  },
};
