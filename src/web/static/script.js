const svg = d3.select("#map");
const viewport = svg.append("g");
const edgeLayer = viewport.append("g");
const nodeLayer = viewport.append("g");
const nodeById = new Map();

const colors = {
  project: "#edf1f7",
  folder: "#e9b44c",
  file: "#4f8f7a",
  function: "#8792d6",
  class: "#c58e67"
};

const zoom = d3.zoom()
  .scaleExtent([0.35, 12])
  .on("zoom", event => viewport.attr("transform", event.transform));

svg.call(zoom);
d3.select("#zoomIn").on("click", () => svg.transition().duration(160).call(zoom.scaleBy, 1.25));
d3.select("#zoomOut").on("click", () => svg.transition().duration(160).call(zoom.scaleBy, 0.8));
d3.select("#zoomReset").on("click", () => svg.transition().duration(160).call(zoom.transform, d3.zoomIdentity));

fetch("/graph.json")
  .then(response => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(render)
  .catch(error => {
    d3.select("#detail").text(`Unable to load graph.json: ${error.message}`);
  });

function render(graph) {
  const main = document.querySelector("main");
  const width = Math.max(900, main.clientWidth);
  const height = Math.max(680, main.clientHeight);
  svg.attr("viewBox", [0, 0, width, height]);
  d3.select("#root").text(graph.root);

  const root = d3.hierarchy(graph.tree)
    .sum(d => d.children && d.children.length ? 0 : 1)
    .sort((a, b) => kindRank(a.data.kind) - kindRank(b.data.kind) || d3.ascending(a.data.name, b.data.name));

  d3.treemap()
    .size([width - 48, height - 48])
    .paddingOuter(18)
    .paddingTop(d => d.depth === 0 ? 32 : 24)
    .paddingInner(6)
    .round(true)(root);

  root.each(node => {
    node.x0 += 24;
    node.x1 += 24;
    node.y0 += 24;
    node.y1 += 24;
    nodeById.set(node.data.id, node);
  });

  const nodes = nodeLayer.selectAll("g.node")
    .data(root.descendants(), d => d.data.id)
    .join("g")
    .attr("class", "node")
    .attr("transform", d => `translate(${d.x0},${d.y0})`)
    .on("click", (event, node) => {
      event.stopPropagation();
      selectNode(node, graph.edges);
    });

  nodes.append("rect")
    .attr("width", d => Math.max(1, d.x1 - d.x0))
    .attr("height", d => Math.max(1, d.y1 - d.y0))
    .attr("rx", 6)
    .attr("fill", d => d.data.stale ? "var(--stale)" : colors[d.data.kind] || "#d6dae3")
    .attr("fill-opacity", d => d.data.kind === "function" || d.data.kind === "class" ? 0.72 : 0.88);

  nodes.append("text")
    .attr("x", 10)
    .attr("y", 17)
    .text(d => trim(d.data.name, d.x1 - d.x0));

  nodes.append("text")
    .attr("x", 10)
    .attr("y", 32)
    .attr("fill", "#68707d")
    .attr("font-size", 10)
    .text(d => trim(d.data.language || d.data.kind, d.x1 - d.x0));

  drawEdges(graph.edges);
  selectNode(root, graph.edges);
  svg.on("click", () => selectNode(root, graph.edges));
}

function drawEdges(edges) {
  edgeLayer.selectAll("path.edge")
    .data(edges)
    .join("path")
    .attr("class", "edge")
    .attr("d", edge => {
      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      if (!source || !target) return "";
      const a = center(source);
      const b = center(target);
      const mid = (a.x + b.x) / 2;
      return `M${a.x},${a.y} C${mid},${a.y} ${mid},${b.y} ${b.x},${b.y}`;
    });
}

function selectNode(node, edges) {
  const related = new Set([node.data.id]);
  edges.forEach(edge => {
    if (edge.source === node.data.id || edge.target === node.data.id) {
      related.add(edge.source);
      related.add(edge.target);
    }
  });
  nodeLayer.selectAll("g.node")
    .classed("active", d => d.data.id === node.data.id)
    .classed("dim", d => node.data.kind !== "project" && !related.has(d.data.id));
  edgeLayer.selectAll("path.edge")
    .classed("dim", edge => node.data.kind !== "project" && edge.source !== node.data.id && edge.target !== node.data.id);
  d3.select("#detail").html(detailHtml(node.data, edges));
}

function detailHtml(data, edges) {
  const count = edges.filter(edge => edge.source === data.id || edge.target === data.id).length;
  return [
    `<strong>${escapeHtml(data.name)}</strong>`,
    `<p>Kind<br><code>${escapeHtml(data.kind)}</code></p>`,
    `<p>Path<br><code>${escapeHtml(data.path || "(project)")}</code></p>`,
    data.sha256 ? `<p>SHA-256<br><code>${escapeHtml(data.sha256)}</code></p>` : "",
    `<p>Edges<br><code>${count}</code></p>`,
    data.stale ? `<p><strong>Stale hash</strong></p>` : ""
  ].join("");
}

function center(node) {
  return { x: (node.x0 + node.x1) / 2, y: (node.y0 + node.y1) / 2 };
}

function trim(value, width) {
  const limit = Math.max(4, Math.floor((width - 18) / 7));
  return value.length > limit ? `${value.slice(0, limit - 1)}...` : value;
}

function kindRank(kind) {
  return { project: 0, folder: 1, file: 2, class: 3, function: 4 }[kind] || 9;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[char]));
}
