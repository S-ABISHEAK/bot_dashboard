// Thin fetch wrappers for the dashboard's REST API.
const Api = {
  async listLayouts() {
    const r = await fetch("/api/layouts");
    if (!r.ok) throw new Error(`listLayouts failed: ${r.status}`);
    return (await r.json()).layouts;
  },
  async getLayout(layoutId) {
    const r = await fetch(`/api/layouts/${encodeURIComponent(layoutId)}`);
    if (!r.ok) throw new Error(`getLayout(${layoutId}) failed: ${r.status}`);
    return r.json();
  },
  async listRuns(limit = 50) {
    const r = await fetch(`/api/runs?limit=${limit}`);
    if (!r.ok) throw new Error(`listRuns failed: ${r.status}`);
    return (await r.json()).runs;
  },
  async getRun(runId) {
    const r = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!r.ok) throw new Error(`getRun(${runId}) failed: ${r.status}`);
    return r.json();
  },
  async getFrames(runId, sinceTick = 0, limit = 200) {
    const r = await fetch(`/api/runs/${encodeURIComponent(runId)}/frames?since_tick=${sinceTick}&limit=${limit}`);
    if (!r.ok) throw new Error(`getFrames(${runId}) failed: ${r.status}`);
    return r.json();
  },
  async getReport(runId) {
    const r = await fetch(`/api/runs/${encodeURIComponent(runId)}/report`);
    if (!r.ok) throw new Error(`getReport(${runId}) failed: ${r.status}`);
    return r.json();
  },
  async launchSimulation(body) {
    const r = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `launch failed: ${r.status}`);
    return data;
  },
  async simulateStatus(runId) {
    const r = await fetch(`/api/simulate/${encodeURIComponent(runId)}/status`);
    if (!r.ok) throw new Error(`simulateStatus(${runId}) failed: ${r.status}`);
    return r.json();
  },
  async generateLayout(body) {
    const r = await fetch("/api/layouts/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `generate failed: ${r.status}`);
    return data;
  },
  async generateStatus(jobId) {
    const r = await fetch(`/api/layouts/generate/${encodeURIComponent(jobId)}/status`);
    if (!r.ok) throw new Error(`generateStatus(${jobId}) failed: ${r.status}`);
    return r.json();
  },
  async listDatasets() {
    const r = await fetch("/api/datasets");
    if (!r.ok) throw new Error(`listDatasets failed: ${r.status}`);
    return (await r.json()).datasets;
  },
  async getDataset(datasetId) {
    const r = await fetch(`/api/datasets/${encodeURIComponent(datasetId)}`);
    if (!r.ok) throw new Error(`getDataset(${datasetId}) failed: ${r.status}`);
    return r.json();
  },
  async getDatasetRows(datasetId, offset = 0, limit = 200, split = "") {
    const params = new URLSearchParams({ offset, limit });
    if (split) params.set("split", split);
    const r = await fetch(`/api/datasets/${encodeURIComponent(datasetId)}/rows?${params}`);
    if (!r.ok) throw new Error(`getDatasetRows(${datasetId}) failed: ${r.status}`);
    return r.json();
  },
  async exportDataset(runIds) {
    const r = await fetch("/api/datasets/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_ids: runIds }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `exportDataset failed: ${r.status}`);
    return data;
  },
  async exportDatasetStatus(jobId) {
    const r = await fetch(`/api/datasets/export/${encodeURIComponent(jobId)}/status`);
    if (!r.ok) throw new Error(`exportDatasetStatus(${jobId}) failed: ${r.status}`);
    return r.json();
  },
};
