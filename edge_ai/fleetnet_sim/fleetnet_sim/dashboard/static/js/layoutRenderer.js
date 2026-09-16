// Canvas reimplementation of fleetnet_layout/visualization/renderer.py's
// draw_layout_static -- same color tables, same z-order (footprint ->
// aisles/zones -> racks -> exclusions -> docks -> columns -> nav graph
// edges -> nav graph nodes -> bottleneck highlights). Canvas draw order
// *is* z-order, so this just calls the draw functions in that sequence.

const AISLE_COLORS = {
  main: "#f4a261", spine: "#e76f51", secondary: "#e9c46a", feeder: "#e9c46a",
  cross: "#f6d55c", zone_access: "#cccccc",
};
const AISLE_FALLBACK = "#eeeeee";

const ZONE_COLORS = {
  receiving: "#2a9d8f", shipping: "#264653", staging: "#8ab17d", picking: "#e07a5f",
  packing: "#f2cc8f", returns: "#81b29a", charging: "#3d405b", office: "#bdb2ff",
};
const ZONE_FALLBACK = "#dddddd";

function computeViewTransform(footprint, canvasW, canvasH, marginPx = 20) {
  const xs = footprint.map((p) => p[0]);
  const ys = footprint.map((p) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const w = Math.max(maxX - minX, 1e-6);
  const h = Math.max(maxY - minY, 1e-6);
  const scale = Math.min((canvasW - 2 * marginPx) / w, (canvasH - 2 * marginPx) / h);
  // Canvas y grows downward; simulation y grows upward -- flip.
  return {
    toCanvas: (x, y) => [
      marginPx + (x - minX) * scale,
      canvasH - marginPx - (y - minY) * scale,
    ],
    scale,
  };
}

function drawPoly(ctx, points, transform, fill, stroke, alpha = 1.0, lineWidth = 0.5) {
  if (!points || points.length === 0) return;
  ctx.beginPath();
  points.forEach(([x, y], i) => {
    const [cx, cy] = transform.toCanvas(x, y);
    if (i === 0) ctx.moveTo(cx, cy);
    else ctx.lineTo(cx, cy);
  });
  ctx.closePath();
  ctx.globalAlpha = alpha;
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = lineWidth; ctx.stroke(); }
  ctx.globalAlpha = 1.0;
}

function drawNavGraph(ctx, graph, transform) {
  if (!graph) return;
  const nodesById = {};
  for (const n of graph.nodes) nodesById[n.id] = n;
  ctx.strokeStyle = "black";
  ctx.lineWidth = 0.6;
  ctx.globalAlpha = 0.4;
  for (const link of graph.links || []) {
    const u = nodesById[link.source], v = nodesById[link.target];
    if (!u || !v) continue;
    const [x1, y1] = transform.toCanvas(u.x, u.y);
    const [x2, y2] = transform.toCanvas(v.x, v.y);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  }
  ctx.globalAlpha = 1.0;
  for (const n of graph.nodes) {
    const color = n.dead_end ? "red" : (n.node_type === "intersection" ? "blue" : "gray");
    const [cx, cy] = transform.toCanvas(n.x, n.y);
    ctx.beginPath(); ctx.arc(cx, cy, 2, 0, 2 * Math.PI); ctx.fillStyle = color; ctx.fill();
  }
}

function drawBottlenecks(ctx, bottlenecks, graph, transform) {
  if (!bottlenecks || !graph) return;
  const nodesById = {};
  for (const n of graph.nodes) nodesById[n.id] = n;
  ctx.strokeStyle = "magenta";
  ctx.lineWidth = 2.5;
  ctx.globalAlpha = 0.85;
  for (const cand of bottlenecks.slice(0, 5)) {
    const [u, v] = cand.edge;
    const nu = nodesById[u], nv = nodesById[v];
    if (!nu || !nv) continue;
    const [x1, y1] = transform.toCanvas(nu.x, nu.y);
    const [x2, y2] = transform.toCanvas(nv.x, nv.y);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  }
  ctx.globalAlpha = 1.0;
}

function drawLayout(ctx, layoutJson, transform, opts = {}) {
  const geo = layoutJson.geometry;
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);

  drawPoly(ctx, geo.footprint, transform, "white", "black", 1.0, 1.5);

  for (const aisle of geo.aisles || []) {
    const role = aisle.metadata?.archetype_role;
    const aisleColor = AISLE_COLORS[role] || AISLE_FALLBACK;
    drawPoly(ctx, aisle.points, transform, aisleColor, aisleColor, 0.7, 1);
  }
  for (const zone of geo.zones || []) {
    const zt = zone.metadata?.zone_type;
    drawPoly(ctx, zone.points, transform, ZONE_COLORS[zt] || ZONE_FALLBACK, "black", 0.6, 0.6);
    const cx = zone.points.reduce((s, p) => s + p[0], 0) / zone.points.length;
    const cy = zone.points.reduce((s, p) => s + p[1], 0) / zone.points.length;
    const [px, py] = transform.toCanvas(cx, cy);
    ctx.fillStyle = "black"; ctx.font = "10px sans-serif"; ctx.textAlign = "center";
    ctx.fillText(zt || "", px, py);
  }
  for (const rack of geo.racks || []) {
    drawPoly(ctx, rack.points, transform, "#457b9d", "#1d3557", 0.85);
  }
  if (opts.showExclusions !== false) {
    for (const excl of geo.exclusions || []) {
      drawPoly(ctx, excl.points, transform, "purple", "black", 0.5);
    }
  }
  for (const dock of geo.docks || []) {
    drawPoly(ctx, dock.points, transform, "black", null, 1.0);
  }
  if (opts.showExclusions !== false) {
    for (const col of geo.columns || []) {
      drawPoly(ctx, col.points, transform, "red", null, 1.0);
    }
  }
  if (opts.showGraph !== false) {
    drawNavGraph(ctx, layoutJson.navigation_graph, transform);
  }
  if (opts.showBottlenecks !== false) {
    drawBottlenecks(ctx, layoutJson.derived_metrics?.bottleneck_candidates, layoutJson.navigation_graph, transform);
  }
}
