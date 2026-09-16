// Launch tab: submits a simulation request, then polls its job status
// until completion/failure. On success, hands off to the Watch tab.
const LaunchForm = {
  init() {
    document.getElementById("launchForm").addEventListener("submit", (e) => {
      e.preventDefault();
      this.submit();
    });
  },

  presetLayout(layoutId) {
    document.getElementById("launchLayoutSelect").value = layoutId;
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
      layout_id: val("launchLayoutSelect"),
      preset: val("launchPreset"),
      robots: num("launchRobots"),
      arrival_rate: num("launchArrival"),
      duration_s: num("launchDuration"),
      dt: num("launchDt"),
      seed: num("launchSeed") ?? 0,
    };

    const resultBox = document.getElementById("launchResult");
    resultBox.textContent = "launching…";
    try {
      const resp = await Api.launchSimulation(body);
      resultBox.textContent = `launched run_id=${resp.run_id} (status: ${resp.status}) — switching to Watch…`;
      Main.goToTab("watch");
      document.getElementById("watchRunId").value = resp.run_id;
      SimView.watch(resp.run_id);
    } catch (err) {
      resultBox.textContent = `error: ${err.message}`;
    }
  },
};
