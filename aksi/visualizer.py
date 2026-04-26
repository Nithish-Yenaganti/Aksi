from __future__ import annotations

import argparse
import json
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

GRAPH_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Aksi Map</title>
  <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
  <style>
    :root {
      color-scheme: light;
      --ink: #202124;
      --muted: #5f6368;
      --line: #d7dbe3;
      --paper: #fafafa;
      --panel: #ffffff;
      --folder: #f0b849;
      --file: #4f8f7a;
      --symbol: #6b6ecf;
      --edge: #d95040;
      --stale: #9b2f2f;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      overflow: hidden;
      background: var(--paper);
      color: var(--ink);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    .shell {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      height: 100vh;
    }

    aside {
      border-right: 1px solid var(--line);
      background: var(--panel);
      padding: 18px;
      overflow: auto;
    }

    main {
      position: relative;
      min-width: 0;
      min-height: 0;
    }

    h1 {
      margin: 0 0 4px;
      font-size: 22px;
      font-weight: 760;
      letter-spacing: 0;
    }

    .subtle {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }

    .metrics {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin: 18px 0;
    }

    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fbfbfc;
    }

    .metric strong {
      display: block;
      font-size: 18px;
    }

    .metric span {
      display: block;
      margin-top: 2px;
      color: var(--muted);
      font-size: 12px;
    }

    .legend {
      display: grid;
      gap: 8px;
      margin-top: 16px;
      font-size: 13px;
    }

    .legend-item {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
    }

    .swatch {
      width: 12px;
      height: 12px;
      border-radius: 3px;
      flex: 0 0 auto;
    }

    .detail {
      margin-top: 18px;
      border-top: 1px solid var(--line);
      padding-top: 14px;
      font-size: 13px;
      line-height: 1.45;
      word-break: break-word;
    }

    .detail h2 {
      margin: 0 0 8px;
      font-size: 15px;
    }

    .detail code {
      color: #3f5850;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }

    .toolbar {
      position: absolute;
      top: 14px;
      right: 14px;
      z-index: 4;
      display: flex;
      gap: 8px;
    }

    button {
      width: 38px;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.92);
      color: var(--ink);
      font-size: 18px;
      cursor: pointer;
    }

    button:hover {
      border-color: #b8bec9;
      background: #fff;
    }

    svg {
      display: block;
      width: 100%;
      height: 100%;
      background: #f7f8fa;
    }

    .node rect {
      vector-effect: non-scaling-stroke;
      stroke: rgba(32, 33, 36, 0.22);
      stroke-width: 1;
      rx: 6;
      cursor: pointer;
    }

    .node text {
      pointer-events: none;
      fill: #202124;
      font-size: 12px;
      font-weight: 650;
      letter-spacing: 0;
    }

    .node .meta {
      fill: #5f6368;
      font-size: 10px;
      font-weight: 520;
    }

    .edge {
      fill: none;
      stroke: var(--edge);
      stroke-opacity: 0.58;
      stroke-width: 1.8;
      vector-effect: non-scaling-stroke;
    }

    .edge.dim {
      stroke-opacity: 0.08;
    }

    .node.dim {
      opacity: 0.26;
    }

    .node.active rect {
      stroke: #202124;
      stroke-width: 2;
    }

    .load-error {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      padding: 24px;
      color: var(--stale);
      font-weight: 700;
    }

    @media (max-width: 760px) {
      .shell {
        grid-template-columns: 1fr;
        grid-template-rows: auto minmax(0, 1fr);
      }

      aside {
        max-height: 230px;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }

      .metrics {
        grid-template-columns: repeat(4, 1fr);
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <h1>Aksi Map</h1>
      <div class="subtle" id="rootLabel">Loading graph</div>
      <div class="metrics">
        <div class="metric"><strong id="folderCount">0</strong><span>Folders</span></div>
        <div class="metric"><strong id="fileCount">0</strong><span>Files</span></div>
        <div class="metric"><strong id="symbolCount">0</strong><span>Symbols</span></div>
        <div class="metric"><strong id="edgeCount">0</strong><span>Edges</span></div>
      </div>
      <div class="legend">
        <div class="legend-item"><span class="swatch" style="background: var(--folder)"></span>Folder</div>
        <div class="legend-item"><span class="swatch" style="background: var(--file)"></span>File</div>
        <div class="legend-item"><span class="swatch" style="background: var(--symbol)"></span>Symbol</div>
        <div class="legend-item"><span class="swatch" style="background: var(--edge)"></span>Import edge</div>
      </div>
      <section class="detail" id="detail">
        <h2>Selection</h2>
        <div class="subtle">No node selected</div>
      </section>
    </aside>
    <main>
      <div class="toolbar" aria-label="Map controls">
        <button id="zoomOut" title="Zoom out">-</button>
        <button id="zoomReset" title="Reset zoom">0</button>
        <button id="zoomIn" title="Zoom in">+</button>
      </div>
      <svg id="map" role="img" aria-label="Aksi zoomable code map"></svg>
    </main>
  </div>
  <script>
    const svg = d3.select("#map");
    const viewport = svg.append("g");
    const edgeLayer = viewport.append("g").attr("class", "edges");
    const nodeLayer = viewport.append("g").attr("class", "nodes");
    const nodeById = new Map();
    const colors = {
      project: "#e9edf4",
      folder: "#f0b849",
      file: "#4f8f7a",
      symbol: "#a9a7e8"
    };

    const zoom = d3.zoom()
      .scaleExtent([0.35, 12])
      .on("zoom", event => viewport.attr("transform", event.transform));

    svg.call(zoom);
    d3.select("#zoomIn").on("click", () => svg.transition().duration(180).call(zoom.scaleBy, 1.25));
    d3.select("#zoomOut").on("click", () => svg.transition().duration(180).call(zoom.scaleBy, 0.8));
    d3.select("#zoomReset").on("click", () => svg.transition().duration(180).call(zoom.transform, d3.zoomIdentity));

    const graphSource = window.__AKSI_GRAPH__
      ? Promise.resolve(window.__AKSI_GRAPH__)
      : fetch("../index.json").then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      });

    graphSource.then(renderGraph)
      .catch(error => {
        d3.select("main").append("div")
          .attr("class", "load-error")
          .text(`Unable to load Files/index.json: ${error.message}`);
      });

    function renderGraph(graph) {
      const width = Math.max(960, document.querySelector("main").clientWidth);
      const height = Math.max(720, document.querySelector("main").clientHeight);
      svg.attr("viewBox", [0, 0, width, height]);

      const root = d3.hierarchy(graph.tree)
        .sum(d => d.children && d.children.length ? 0 : 1)
        .sort((a, b) => kindRank(a.data.kind) - kindRank(b.data.kind) || d3.ascending(a.data.name, b.data.name));

      d3.treemap()
        .tile(d3.treemapSquarify)
        .size([width - 56, height - 56])
        .paddingOuter(18)
        .paddingTop(d => d.depth === 0 ? 32 : 24)
        .paddingInner(6)
        .round(true)(root);

      root.each(d => {
        d.x0 += 28;
        d.x1 += 28;
        d.y0 += 28;
        d.y1 += 28;
        nodeById.set(d.data.id, d);
      });

      const nodes = nodeLayer.selectAll("g.node")
        .data(root.descendants(), d => d.data.id)
        .join("g")
        .attr("class", "node")
        .attr("transform", d => `translate(${d.x0},${d.y0})`)
        .on("click", (event, d) => {
          event.stopPropagation();
          selectNode(d, graph.edges);
        });

      nodes.append("rect")
        .attr("width", d => Math.max(1, d.x1 - d.x0))
        .attr("height", d => Math.max(1, d.y1 - d.y0))
        .attr("fill", d => colorFor(d.data))
        .attr("fill-opacity", d => d.data.kind === "symbol" ? 0.72 : 0.86);

      nodes.append("text")
        .attr("x", 10)
        .attr("y", 17)
        .text(d => trimLabel(d.data.name, d.x1 - d.x0));

      nodes.append("text")
        .attr("class", "meta")
        .attr("x", 10)
        .attr("y", 32)
        .text(d => metaLabel(d.data, d.x1 - d.x0));

      drawEdges(graph.edges);
      setMetrics(graph, root);
      selectNode(root, graph.edges);

      svg.on("click", () => selectNode(root, graph.edges));
    }

    function drawEdges(edges) {
      edgeLayer.selectAll("path.edge")
        .data(edges)
        .join("path")
        .attr("class", "edge")
        .attr("data-source", d => d.source)
        .attr("data-target", d => d.target)
        .attr("d", d => {
          const source = nodeById.get(d.source);
          const target = nodeById.get(d.target);
          if (!source || !target) return "";
          const a = center(source);
          const b = center(target);
          const midX = (a.x + b.x) / 2;
          return `M${a.x},${a.y} C${midX},${a.y} ${midX},${b.y} ${b.x},${b.y}`;
        });
    }

    function selectNode(node, edges) {
      const id = node.data.id;
      const related = new Set([id]);
      edges.forEach(edge => {
        if (edge.source === id || edge.target === id) {
          related.add(edge.source);
          related.add(edge.target);
        }
      });

      nodeLayer.selectAll("g.node")
        .classed("active", d => d.data.id === id)
        .classed("dim", d => !related.has(d.data.id) && node.data.kind !== "project");

      edgeLayer.selectAll("path.edge")
        .classed("dim", d => d.source !== id && d.target !== id && node.data.kind !== "project");

      d3.select("#detail").html(detailHtml(node.data, edges));
    }

    function setMetrics(graph, root) {
      const descendants = root.descendants();
      d3.select("#rootLabel").text(graph.root);
      d3.select("#folderCount").text(descendants.filter(d => d.data.kind === "folder").length);
      d3.select("#fileCount").text(descendants.filter(d => d.data.kind === "file").length);
      d3.select("#symbolCount").text(descendants.filter(d => d.data.kind === "symbol").length);
      d3.select("#edgeCount").text(graph.edges.length);
    }

    function detailHtml(data, edges) {
      const linked = edges.filter(edge => edge.source === data.id || edge.target === data.id);
      const rows = [
        ["Kind", data.symbol_kind || data.kind],
        ["Path", data.path || "(project)"],
        ["Language", data.language],
        ["Signature", data.signature],
        ["SHA-256", data.sha256],
        ["Stale", data.stale ? "true" : "false"],
        ["Edges", linked.length]
      ].filter(([, value]) => value !== null && value !== undefined && value !== "");

      return `<h2>${escapeHtml(data.name)}</h2>` + rows.map(([label, value]) => {
        return `<p><strong>${label}</strong><br><code>${escapeHtml(String(value))}</code></p>`;
      }).join("");
    }

    function colorFor(data) {
      if (data.stale) return "#e5b2ac";
      return colors[data.kind] || "#d8dce5";
    }

    function metaLabel(data, width) {
      const value = data.signature || data.language || data.path || data.kind;
      return trimLabel(value || "", width);
    }

    function trimLabel(value, width) {
      const max = Math.max(4, Math.floor((width - 20) / 7));
      return value.length > max ? `${value.slice(0, max - 1)}...` : value;
    }

    function center(node) {
      return {
        x: (node.x0 + node.x1) / 2,
        y: (node.y0 + node.y1) / 2
      };
    }

    function kindRank(kind) {
      return { project: 0, folder: 1, file: 2, symbol: 3 }[kind] || 9;
    }

    function escapeHtml(value) {
      return value.replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;"
      }[char]));
    }
  </script>
</body>
</html>
"""


def write_visualization(output_dir: Path = Path("Files")) -> Path:
    graph_dir = output_dir / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    html_path = graph_dir / "index.html"
    html_path.write_text(GRAPH_HTML, encoding="utf-8")
    return html_path


def write_standalone_bundle(
    graph_path: Path = Path("Files/index.json"),
    output_path: Path = Path("Files/aksi_bundle.html"),
) -> Path:
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    embedded = f"<script>window.__AKSI_GRAPH__ = {json.dumps(graph, sort_keys=True)};</script>"
    html = GRAPH_HTML.replace("</head>", f"  {embedded}\n</head>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def serve(output_dir: Path = Path("Files"), host: str = "127.0.0.1", port: int = 8765) -> None:
    write_visualization(output_dir)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(output_dir))
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Aksi map: http://{host}:{port}/graph/index.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAksi map server stopped.")
    finally:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the Aksi zoomable code map.")
    parser.add_argument("--dir", type=Path, default=Path("Files"), help="Artifact directory to serve.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port.")
    parser.add_argument("--write-only", action="store_true", help="Only write graph/index.html.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.write_only:
        html_path = write_visualization(args.dir)
        print(f"Wrote {html_path}")
        return
    serve(args.dir, args.host, args.port)


if __name__ == "__main__":
    main()
