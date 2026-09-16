// App bootstrap + tab switching glue.
const Main = {
  goToTab(name) {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
    if (name === "runs") RunHistory.refresh();
    if (name === "datasets") DatasetBrowser.refresh();
  },
};

document.addEventListener("DOMContentLoaded", async () => {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => Main.goToTab(btn.dataset.tab));
  });

  document.getElementById("watchLoadBtn").addEventListener("click", () => {
    const runId = document.getElementById("watchRunId").value.trim();
    if (runId) SimView.watch(runId);
  });
  document.getElementById("watchReplayFromStartBtn").addEventListener("click", () => SimView.replayFromStart());

  document.getElementById("reportLoadBtn").addEventListener("click", () => {
    const runId = document.getElementById("reportRunId").value.trim();
    if (runId) ReportView.load(runId);
  });
  document.getElementById("reportPrintBtn").addEventListener("click", () => window.print());

  LaunchForm.init();
  LayoutCreate.init();
  DatasetBrowser.init();
  await LayoutBrowser.init();
  await RunHistory.init();
});
