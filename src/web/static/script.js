const svg = d3.select("#map");
const viewport = svg.append("g");
const edgeLayer = viewport.append("g");
const linkLayer = viewport.append("g");
const nodeLayer = viewport.append("g");
const nodeById = new Map();
let graphData = null;

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
document.querySelector("#chatForm").addEventListener("submit", handleQuestion);

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
  graphData = graph;
  nodeById.clear();
  edgeLayer.selectAll("*").remove();
  nodeLayer.selectAll("*").remove();

  const main = document.querySelector("main");
  const width = Math.max(900, main.clientWidth);
  const height = Math.max(680, main.clientHeight);
  svg.attr("viewBox", [0, 0, width, height]);
  d3.select("#root").text(graph.root);

  const root = d3.hierarchy(graph.tree)
    .sort((a, b) => kindRank(a.data.kind) - kindRank(b.data.kind) || d3.ascending(a.data.name, b.data.name));

  d3.tree()
    .nodeSize([96, 150])
    .separation((a, b) => a.parent === b.parent ? 1.2 : 1.8)(root);

  const bounds = root.descendants().reduce(
    (box, node) => ({
      minX: Math.min(box.minX, node.x),
      maxX: Math.max(box.maxX, node.x),
      minY: Math.min(box.minY, node.y),
      maxY: Math.max(box.maxY, node.y)
    }),
    { minX: 0, maxX: 0, minY: 0, maxY: 0 }
  );
  const offsetX = Math.max(120, (width - (bounds.maxX - bounds.minX)) / 2 - bounds.minX);
  const offsetY = 72;

  root.each(node => {
    node.x += offsetX;
    node.y += offsetY;
    nodeById.set(node.data.id, node);
  });

  linkLayer.selectAll("path.tree-link")
    .data(root.links())
    .join("path")
    .attr("class", "tree-link")
    .attr("d", d3.linkVertical()
      .x(d => d.x)
      .y(d => d.y));

  const nodes = nodeLayer.selectAll("g.node")
    .data(root.descendants(), d => d.data.id)
    .join("g")
    .attr("class", "node")
    .attr("transform", d => `translate(${d.x},${d.y})`)
    .on("click", (event, node) => {
      event.stopPropagation();
      selectNode(node, graph.edges);
    });

  nodes.append("circle")
    .attr("r", d => nodeRadius(d.data.kind))
    .attr("fill", d => d.data.stale ? "var(--stale)" : colors[d.data.kind] || "#d6dae3")
    .attr("fill-opacity", 0.92);

  nodes.append("text")
    .attr("x", 0)
    .attr("y", d => nodeRadius(d.data.kind) + 15)
    .attr("text-anchor", "middle")
    .text(d => trim(d.data.name, 120));

  nodes.append("text")
    .attr("x", 0)
    .attr("y", d => nodeRadius(d.data.kind) + 28)
    .attr("text-anchor", "middle")
    .attr("fill", "#68707d")
    .attr("font-size", 10)
    .text(d => trim(d.data.language || d.data.kind, 120));

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
  linkLayer.selectAll("path.tree-link")
    .classed("dim", d => node.data.kind !== "project" && d.source.data.id !== node.data.id && d.target.data.id !== node.data.id);
  d3.select("#detail").html(detailHtml(node.data, edges));
  fetch(`/api/node?node_id=${encodeURIComponent(node.data.id)}`)
    .then(response => response.ok ? response.json() : null)
    .then(payload => {
      if (payload) d3.select("#detail").html(detailHtml(node.data, edges, payload));
    })
    .catch(() => {});
}

function detailHtml(data, edges, context = null) {
  const count = edges.filter(edge => edge.source === data.id || edge.target === data.id).length;
  return [
    `<strong>${escapeHtml(data.name)}</strong>`,
    `<p>Kind<br><code>${escapeHtml(data.kind)}</code></p>`,
    `<p>Path<br><code>${escapeHtml(data.path || "(project)")}</code></p>`,
    data.sha256 ? `<p>SHA-256<br><code>${escapeHtml(data.sha256)}</code></p>` : "",
    `<p>Edges<br><code>${count}</code></p>`,
    context ? `<p>Context<br>${escapeHtml(context.summary)}</p>` : "",
    data.stale ? `<p><strong>Stale hash</strong></p>` : ""
  ].join("");
}

function handleQuestion(event) {
  event.preventDefault();
  const input = document.querySelector("#chatInput");
  const question = input.value.trim();
  if (!question) return;

  document.querySelector("#answer").textContent = "Searching current map...";
  fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question })
  })
    .then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(payload => {
      document.querySelector("#answer").textContent = payload.answer;
      renderResults(payload.matches || []);
      highlightMatches(payload.matches || []);
    })
    .catch(error => {
      document.querySelector("#answer").textContent = `Unable to answer from the map: ${error.message}`;
    });
}

function renderResults(matches) {
  const results = document.querySelector("#results");
  if (!matches.length) {
    results.innerHTML = "";
    return;
  }

  results.innerHTML = matches.slice(0, 8).map(match => {
    const hitText = (match.hits || []).slice(0, 3).map(hit => {
      const record = hit.record || {};
      return `${hit.kind || hit.match_type}: ${record.name || record.module || ""}`;
    }).join("<br>");
    return `<button class="result-item" type="button" data-node="file:${escapeAttr(match.path)}">
      <strong>${escapeHtml(match.path)}</strong><br>${hitText || escapeHtml(match.language || "file")}
    </button>`;
  }).join("");

  results.querySelectorAll("[data-node]").forEach(button => {
    button.addEventListener("click", () => {
      const node = nodeById.get(button.dataset.node);
      if (node && graphData) selectNode(node, graphData.edges);
    });
  });
}

function highlightMatches(matches) {
  const ids = new Set(matches.map(match => `file:${match.path}`));
  nodeLayer.selectAll("g.node")
    .classed("active", d => ids.has(d.data.id))
    .classed("dim", d => ids.size > 0 && !ids.has(d.data.id));
  edgeLayer.selectAll("path.edge")
    .classed("dim", edge => ids.size > 0 && !ids.has(edge.source) && !ids.has(edge.target));
}

function center(node) {
  return { x: node.x, y: node.y };
}

function trim(value, width) {
  const limit = Math.max(4, Math.floor((width - 18) / 7));
  return value.length > limit ? `${value.slice(0, limit - 1)}...` : value;
}

function nodeRadius(kind) {
  return { project: 24, folder: 20, file: 17, class: 13, function: 12 }[kind] || 12;
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

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}
