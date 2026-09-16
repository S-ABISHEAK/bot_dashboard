// Layout list + viewer tab logic.
const LayoutBrowser = {
  layouts: [],
  currentLayout: null,

  async init() {
    await this.refresh();

    document.getElementById("toggleGraph").addEventListener("change", () => this.redraw());
    document.getElementById("toggleExclusions").addEventListener("change", () => this.redraw());
    document.getElementById("toggleBottlenecks").addEventListener("change", () => this.redraw());
    document.getElementById("launchFromLayoutBtn").addEventListener("click", () => {
      if (!this.currentLayout) return;
      Main.goToTab("launch");
      LaunchForm.presetLayout(this.currentLayout.layout_id);
    });
  },

  // Re-fetch + re-render the list/select without re-wiring listeners --
  // safe to call repeatedly (e.g. after a new layout is generated).
  async refresh() {
    this.layouts = await Api.listLayouts();
    this.renderTable();
    this.populateLaunchSelect();
  },

  renderTable() {
    const tbody = document.querySelector("#layoutTable tbody");
    tbody.innerHTML = "";
    for (const l of this.layouts) {
      if (l.layout_id.startsWith("__error__")) continue;
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${l.layout_id}</td><td>${l.archetype ?? ""}</td><td>${l.scale_class ?? ""}</td>
        <td>${l.industry_type ?? ""}</td><td>${l.area_m2 ? l.area_m2.toFixed(0) : ""}</td>
        <td>${l.valid ? "✓" : "✗"}</td>`;
      tr.addEventListener("click", () => this.select(l.layout_id));
      tbody.appendChild(tr);
    }
  },

  populateLaunchSelect() {
    const sel = document.getElementById("launchLayoutSelect");
    sel.innerHTML = "";
    for (const l of this.layouts) {
      if (l.layout_id.startsWith("__error__")) continue;
      const opt = document.createElement("option");
      opt.value = l.layout_id;
      opt.textContent = `${l.layout_id} (${l.archetype}, ${l.scale_class})`;
      sel.appendChild(opt);
    }
  },

  async select(layoutId) {
    this.currentLayout = await Api.getLayout(layoutId);
    document.getElementById("launchFromLayoutBtn").disabled = false;
    this.redraw();
    const w = this.currentLayout.warehouse;
    document.getElementById("layoutMeta").textContent =
      `layout_id: ${this.currentLayout.layout_id}\n` +
      `archetype: ${w.archetype}  scale: ${w.scale_class}  industry: ${w.industry_type}\n` +
      `size: ${w.length_m?.toFixed(1)}m x ${w.width_m?.toFixed(1)}m  area: ${w.area_m2?.toFixed(0)}m²\n` +
      `valid: ${this.currentLayout.validation?.valid}` +
      (this.currentLayout.validation?.warnings?.length ? `  warnings: ${this.currentLayout.validation.warnings.length}` : "");
  },

  redraw() {
    if (!this.currentLayout) return;
    const canvas = document.getElementById("layoutCanvas");
    const ctx = canvas.getContext("2d");
    const transform = computeViewTransform(this.currentLayout.geometry.footprint, canvas.width, canvas.height);
    drawLayout(ctx, this.currentLayout, transform, {
      showGraph: document.getElementById("toggleGraph").checked,
      showExclusions: document.getElementById("toggleExclusions").checked,
      showBottlenecks: document.getElementById("toggleBottlenecks").checked,
    });
  },
};
