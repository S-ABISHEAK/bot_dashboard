// Run History tab: list past runs, click through to detail + jump into
// the Watch tab for post-hoc replay. Also lets the user select one or
// more completed runs and export an eta/conflict/congestion dataset
// from them (the same builders the CLI's export-dataset command uses,
// just triggered from the dashboard instead of a terminal) -- results
// land in model_dataset_registry and show up on the Datasets tab with
// no further action needed.
const EXPORT_POLL_INTERVAL_MS = 700;

const RunHistory = {
  selectedRunIds: new Set(),
  _pollTimer: null,

  async init() {
    await this.refresh();
    document.getElementById("runsSelectAll").addEventListener("change", (e) => this._selectAll(e.target.checked));
    document.getElementById("exportDatasetBtn").addEventListener("click", () => this.exportSelected());
  },

  async refresh() {
    const runs = await Api.listRuns(50);
    this.selectedRunIds.clear();
    const tbody = document.querySelector("#runsTable tbody");
    tbody.innerHTML = "";
    for (const r of runs) {
      const isCompleted = r.status === "completed";
      const tr = document.createElement("tr");
      tr.innerHTML = `<td><input type="checkbox" class="run-select" data-run="${r.run_id}" ${isCompleted ? "" : "disabled"}></td>
        <td>${r.run_id}</td><td>${r.layout_id ?? ""}</td><td>${r.status}</td>
        <td>${r.seed}</td><td>${r.started_at ? new Date(r.started_at).toLocaleString() : ""}</td>
        <td>${r.final_tick ?? ""}</td>
        <td><button data-action="watch" data-run="${r.run_id}">Watch/Replay</button>
            <button data-action="report" data-run="${r.run_id}">Report</button></td>`;
      tr.querySelector(".run-select").addEventListener("change", (e) => {
        e.stopPropagation();
        this._toggleSelected(r.run_id, e.target.checked);
      });
      tr.querySelector("td:nth-child(2)").addEventListener("click", () => this.showDetail(r.run_id));
      tr.querySelector('button[data-action="watch"]').addEventListener("click", (e) => {
        e.stopPropagation();
        Main.goToTab("watch");
        document.getElementById("watchRunId").value = r.run_id;
        SimView.watch(r.run_id);
      });
      tr.querySelector('button[data-action="report"]').addEventListener("click", (e) => {
        e.stopPropagation();
        Main.goToTab("report");
        document.getElementById("reportRunId").value = r.run_id;
        ReportView.load(r.run_id);
      });
      tbody.appendChild(tr);
    }
    this._updateExportButton();
  },

  async showDetail(runId) {
    const detail = await Api.getRun(runId);
    document.getElementById("runDetail").textContent = JSON.stringify(detail, null, 2);
  },

  _toggleSelected(runId, checked) {
    if (checked) this.selectedRunIds.add(runId);
    else this.selectedRunIds.delete(runId);
    this._updateExportButton();
  },

  _selectAll(checked) {
    for (const cb of document.querySelectorAll("#runsTable .run-select:not(:disabled)")) {
      cb.checked = checked;
      this._toggleSelected(cb.dataset.run, checked);
    }
  },

  _updateExportButton() {
    document.getElementById("exportDatasetBtn").disabled = this.selectedRunIds.size === 0;
  },

  async exportSelected() {
    const runIds = Array.from(this.selectedRunIds);
    const statusEl = document.getElementById("exportDatasetStatus");
    document.getElementById("exportDatasetBtn").disabled = true;
    statusEl.textContent = `exporting from ${runIds.length} run(s)…`;
    try {
      const resp = await Api.exportDataset(runIds);
      this._poll(resp.job_id);
    } catch (err) {
      statusEl.textContent = `error: ${err.message}`;
      this._updateExportButton();
    }
  },

  _poll(jobId) {
    if (this._pollTimer) clearTimeout(this._pollTimer);
    const statusEl = document.getElementById("exportDatasetStatus");
    const tick = async () => {
      try {
        const status = await Api.exportDatasetStatus(jobId);
        if (status.status === "completed" || status.status === "failed") {
          statusEl.textContent = this._summarize(status);
          this._updateExportButton();
        } else {
          statusEl.textContent = `${status.status}…`;
          this._pollTimer = setTimeout(tick, EXPORT_POLL_INTERVAL_MS);
        }
      } catch (err) {
        statusEl.textContent = `error: ${err.message}`;
        this._updateExportButton();
      }
    };
    tick();
  },

  _summarize(status) {
    const parts = [];
    for (const [model, r] of Object.entries(status.results || {})) {
      parts.push(`${model}: ${r.n_rows} rows`);
    }
    for (const [model, err] of Object.entries(status.errors || {})) {
      parts.push(`${model}: failed (${err})`);
    }
    return parts.length ? parts.join(", ") : "export finished with no results";
  },
};
