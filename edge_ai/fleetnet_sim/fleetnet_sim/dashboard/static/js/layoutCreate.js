// Create Layout tab: submits a generation request, polls its job status
// (generation takes 1-5+ seconds, never instant, so this mirrors
// launchForm.js's poll-until-terminal pattern), then previews the
// result with the same layoutRenderer.js drawing code the Layouts tab
// uses -- no separate rendering path.
const GENERATE_POLL_INTERVAL_MS = 700;

const LayoutCreate = {
  currentLayout: null,
  _pollTimer: null,

  init() {
    document.getElementById("createLayoutForm").addEventListener("submit", (e) => {
      e.preventDefault();
      this.submit();
    });
    document.getElementById("createLaunchBtn").addEventListener("click", () => {
      if (!this.currentLayout) return;
      Main.goToTab("launch");
      LaunchForm.presetLayout(this.currentLayout.layout_id);
    });
  },

  async submit() {
    const val = (id) => {
      const v = document.getElementById(id).value;
      return v === "" ? null : v;
    };
    const num = (id) => {
      const v = document.getElementById(id).value;
      return v === "" ? null : Number(v);
    };

    const body = {
      archetype: val("createArchetype"),
      scale_class: val("createScale"),
      industry_type: val("createIndustry"),
      dock_wall: val("createDockWall"),
      irregularity_level: num("createIrregularity"),
      seed: num("createSeed"),
    };

    const resultBox = document.getElementById("createResult");
    document.getElementById("createLaunchBtn").disabled = true;
    resultBox.textContent = "generating… (this can take a few seconds, especially for larger scale classes)";
    try {
      const resp = await Api.generateLayout(body);
      this._poll(resp.job_id);
    } catch (err) {
      resultBox.textContent = `error: ${err.message}`;
    }
  },

  _poll(jobId) {
    if (this._pollTimer) clearTimeout(this._pollTimer);
    const tick = async () => {
      const resultBox = document.getElementById("createResult");
      try {
        const status = await Api.generateStatus(jobId);
        if (status.status === "completed") {
          resultBox.textContent = `done — layout_id=${status.layout_id}`;
          await this._showResult(status);
        } else if (status.status === "failed") {
          const e = status.error || {};
          resultBox.textContent = `generation failed: ${e.reason || "unknown error"} (stage=${e.stage}, seed=${e.seed})`;
        } else {
          resultBox.textContent = `${status.status}…`;
          this._pollTimer = setTimeout(tick, GENERATE_POLL_INTERVAL_MS);
        }
      } catch (err) {
        resultBox.textContent = `error: ${err.message}`;
      }
    };
    tick();
  },

  async _showResult(status) {
    this.currentLayout = await Api.getLayout(status.layout_id);
    const canvas = document.getElementById("createCanvas");
    const transform = computeViewTransform(this.currentLayout.geometry.footprint, canvas.width, canvas.height);
    drawLayout(canvas.getContext("2d"), this.currentLayout, transform, {});

    const r = status.resolved || {};
    document.getElementById("createMeta").textContent =
      `layout_id: ${status.layout_id}\n` +
      `archetype: ${r.archetype}  scale: ${r.scale_class}  industry: ${r.industry_type}  dock_wall: ${r.dock_wall}\n` +
      `seed: ${r.seed}  area: ${r.area_m2} m²  valid: ${r.valid}`;
    document.getElementById("createLaunchBtn").disabled = false;

    // The new layout is on disk now -- refresh the Layouts tab's list
    // and the Launch tab's dropdown so it's usable everywhere else
    // without a page reload.
    await LayoutBrowser.refresh();
  },
};
