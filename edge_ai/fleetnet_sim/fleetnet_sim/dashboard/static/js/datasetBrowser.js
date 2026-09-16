// Datasets tab: browse the ML datasets (ETA/Conflict/Congestion) built
// by datasets/*_builder.py -- lists everything in model_dataset_registry
// (enriched with each export's own .schema.json sidecar), then pages
// through a selected dataset's actual rows. Page size is fixed (not
// user-configurable) to keep this simple; datasets can reach 150k-300k
// rows once real batch runs land, so rows are always paginated server-side,
// never dumped into the DOM in one shot.
const DATASET_PAGE_SIZE = 200;

const DatasetBrowser = {
  datasets: [],
  currentDatasetId: null,
  currentSchema: null,
  currentOffset: 0,
  currentTotal: 0,
  currentSplit: "",

  init() {
    document.getElementById("datasetSplitFilter").addEventListener("change", (e) => {
      this.currentSplit = e.target.value;
      this.loadPage(0);
    });
    document.getElementById("datasetPrevBtn").addEventListener("click", () => {
      this.loadPage(Math.max(0, this.currentOffset - DATASET_PAGE_SIZE));
    });
    document.getElementById("datasetNextBtn").addEventListener("click", () => {
      this.loadPage(this.currentOffset + DATASET_PAGE_SIZE);
    });
  },

  async refresh() {
    this.datasets = await Api.listDatasets();
    const tbody = document.querySelector("#datasetsTable tbody");
    tbody.innerHTML = "";
    for (const d of this.datasets) {
      const tr = document.createElement("tr");
      const posRate = d.positive_rate != null ? d.positive_rate.toFixed(3) : "—";
      const rows = d.row_count != null ? d.row_count.toLocaleString() : "—";
      tr.innerHTML = `<td>${d.model_name}${d.sidecar_missing ? " ⚠" : ""}</td><td>${rows}</td><td>${posRate}</td>
        <td>${d.source_run_count}</td><td>${d.created_at ? new Date(d.created_at).toLocaleString() : ""}</td>`;
      tr.addEventListener("click", () => this.select(d.dataset_id));
      tbody.appendChild(tr);
    }
  },

  async select(datasetId) {
    this.currentDatasetId = datasetId;
    this.currentSplit = "";
    document.getElementById("datasetSplitFilter").value = "";
    this.currentSchema = await Api.getDataset(datasetId);
    this._renderMeta();
    await this.loadPage(0);
  },

  _renderMeta() {
    const s = this.currentSchema;
    const lines = [
      `dataset_id: ${s.dataset_id}`,
      `model: ${s.model}   feature_version: ${s.feature_version}`,
      `rows: ${s.row_count}   split_counts: ${JSON.stringify(s.split_counts)}`,
      s.positive_rate != null ? `positive_rate: ${s.positive_rate.toFixed(4)}` : null,
      s.dropped_from_v1 && s.dropped_from_v1.length ? `dropped_from_v1: ${s.dropped_from_v1.join(", ")} (${s.dropped_from_v1_reason})` : null,
      s.proxy_features ? `proxy features: ${Object.keys(s.proxy_features).join(", ")}` : null,
      `source_run_ids: ${(s.source_run_ids || []).join(", ")}`,
    ].filter(Boolean);
    document.getElementById("datasetMeta").textContent = lines.join("\n");
  },

  async loadPage(offset) {
    if (!this.currentDatasetId) return;
    const resp = await Api.getDatasetRows(this.currentDatasetId, offset, DATASET_PAGE_SIZE, this.currentSplit);
    this.currentOffset = resp.offset;
    this.currentTotal = resp.total;
    this._renderRows(resp.rows);

    const lastRow = Math.min(resp.offset + resp.rows.length, resp.total);
    document.getElementById("datasetPageInfo").textContent =
      resp.total === 0 ? "no rows" : `rows ${resp.offset + 1}-${lastRow} of ${resp.total}`;
    document.getElementById("datasetPrevBtn").disabled = resp.offset <= 0;
    document.getElementById("datasetNextBtn").disabled = lastRow >= resp.total;
  },

  _renderRows(rows) {
    const table = document.getElementById("datasetRowsTable");
    const thead = table.querySelector("thead tr");
    const tbody = table.querySelector("tbody");
    thead.innerHTML = "";
    tbody.innerHTML = "";
    if (!rows.length) return;

    const columns = Object.keys(rows[0]);
    for (const col of columns) {
      const th = document.createElement("th");
      th.textContent = col;
      thead.appendChild(th);
    }
    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = columns.map((c) => `<td>${this._fmt(row[c])}</td>`).join("");
      tbody.appendChild(tr);
    }
  },

  _fmt(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "number" && !Number.isInteger(v)) return v.toFixed(4);
    if (typeof v === "boolean") return v ? "true" : "false";
    return String(v);
  },
};
