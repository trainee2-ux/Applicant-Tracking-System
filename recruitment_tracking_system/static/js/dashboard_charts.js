document.addEventListener("DOMContentLoaded", function () {
  const palette = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#84cc16"];
  const parseJsonNode = (id) => {
    const node = document.getElementById(id);
    if (!node) return [];
    try {
      const parsed = JSON.parse(node.textContent || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  };

  const datasetRows = {
    requisition: parseJsonNode("dashboardJobRowsData").map((row) => [
      row.job_id,
      row.title,
      row.department,
      row.openings,
      row.applications_received,
      row.status,
    ]),
    bgv: parseJsonNode("dashboardBgvRowsData").map((row) => [
      row.candidate_id,
      row.document_type,
      row.verifier_assigned,
      row.status,
      row.comments,
    ]),
    candidate: parseJsonNode("dashboardCandidateRowsData").map((row) => [
      row.candidate_id,
      row.job_applied,
      row.status,
      row.interview_schedule,
      row.bgv_status,
      row.documents_uploaded,
    ]),
    team: parseJsonNode("dashboardTeamRowsData").map((row) => [
      row.team,
      row.tasks_pending,
      row.tasks_completed,
      row.total_hours,
      row.productivity_metrics,
    ]),
  };

  const toNumber = (value) => {
    const cleaned = String(value || "").replace(/[^0-9.-]/g, "");
    const num = Number(cleaned);
    return Number.isNaN(num) ? 0 : num;
  };

  const extractTableRows = (dashboardKey) => {
    if (datasetRows[dashboardKey] && datasetRows[dashboardKey].length) {
      return datasetRows[dashboardKey].map((cells) => cells.map((value) => String(value || "").trim()));
    }
    const section = document.querySelector(`.ats-data-card[data-dashboard-table="${dashboardKey}"]`);
    if (!section) return [];
    const rows = Array.from(section.querySelectorAll("tbody tr"));
    return rows
      .map((tr) => Array.from(tr.querySelectorAll("td")).map((td) => (td.textContent || "").trim()))
      .filter((cells) => cells.length > 1);
  };

  const buildStatusCount = (rows, statusIndex) => {
    const map = {};
    rows.forEach((cells) => {
      const key = (cells[statusIndex] || "Unknown").trim() || "Unknown";
      map[key] = (map[key] || 0) + 1;
    });
    return { labels: Object.keys(map), values: Object.values(map) };
  };

  const buildSumByGroup = (rows, groupIndex, valueIndex) => {
    const map = {};
    rows.forEach((cells) => {
      const key = (cells[groupIndex] || "Unknown").trim() || "Unknown";
      map[key] = (map[key] || 0) + toNumber(cells[valueIndex]);
    });
    return { labels: Object.keys(map), values: Object.values(map) };
  };

  const buildSeriesFromField = (rows, fieldIndex, labelIndex) => {
    if (!rows.length) return { labels: [], values: [] };
    const values = rows.map((cells) => (cells[fieldIndex] || "").trim());
    const numericValues = values.map((value) => toNumber(value));
    const allNumeric = values.every((value) => value !== "" && !Number.isNaN(Number(String(value).replace(/[^0-9.-]/g, ""))));

    if (allNumeric) {
      const labels = rows.map((cells, index) => {
        const label = (cells[labelIndex] || "").trim();
        return label || `Row ${index + 1}`;
      });
      return { labels: labels, values: numericValues };
    }
    return buildStatusCount(rows, fieldIndex);
  };

  const buildCountFromField = (rows, fieldIndex) => {
    const map = {};
    rows.forEach((cells) => {
      const key = (cells[fieldIndex] || "Unknown").trim() || "Unknown";
      map[key] = (map[key] || 0) + 1;
    });
    return { labels: Object.keys(map), values: Object.values(map) };
  };

  const setupCanvas = (canvas) => {
    if (!canvas) return null;
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 420;
    const height = canvas.clientHeight || parseInt(canvas.getAttribute("height") || "180", 10);
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.font = "10px Segoe UI";
    ctx.fillStyle = "#334155";
    return { ctx, width, height };
  };

  const drawPieLike = (canvas, labels, values, isDoughnut) => {
    const pack = setupCanvas(canvas);
    if (!pack) return;
    const { ctx, width, height } = pack;
    const total = values.reduce((a, b) => a + b, 0);
    if (!total) {
      ctx.fillText("No data", width / 2 - 18, height / 2);
      return;
    }

    const cx = width * 0.38;
    const cy = height * 0.52;
    const radius = Math.min(width, height) * 0.28;
    let angle = -Math.PI / 2;

    values.forEach((value, index) => {
      const slice = (value / total) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, radius, angle, angle + slice);
      ctx.closePath();
      ctx.fillStyle = palette[index % palette.length];
      ctx.fill();
      angle += slice;
    });

    if (isDoughnut) {
      ctx.beginPath();
      ctx.fillStyle = "#fff";
      ctx.arc(cx, cy, radius * 0.58, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.fillStyle = "#1f2937";
    ctx.font = "600 10px Segoe UI";
    ctx.fillText(`Total: ${total}`, cx - 24, cy + 4);
    ctx.font = "10px Segoe UI";

    labels.forEach((label, index) => {
      const y = 16 + index * 14;
      const x = width * 0.68;
      const percent = total ? Math.round((values[index] / total) * 100) : 0;
      ctx.fillStyle = palette[index % palette.length];
      ctx.fillRect(x, y - 7, 8, 8);
      ctx.fillStyle = "#334155";
      ctx.fillText(`${label}: ${values[index]} (${percent}%)`, x + 12, y);
    });
  };

  const drawBar = (canvas, labels, values) => {
    const pack = setupCanvas(canvas);
    if (!pack) return;
    const { ctx, width, height } = pack;
    const max = Math.max(...values, 1);
    const left = 30;
    const right = width - 10;
    const top = 15;
    const bottom = height - 26;
    const areaWidth = right - left;
    const barWidth = Math.max(14, areaWidth / Math.max(values.length * 1.6, 1));
    const gap = Math.max(6, (areaWidth - barWidth * values.length) / Math.max(values.length - 1, 1));

    ctx.strokeStyle = "#dbe4f1";
    ctx.beginPath();
    ctx.moveTo(left, top);
    ctx.lineTo(left, bottom);
    ctx.lineTo(right, bottom);
    ctx.stroke();

    values.forEach((value, i) => {
      const h = ((bottom - top) * value) / max;
      const x = left + i * (barWidth + gap);
      const y = bottom - h;
      ctx.fillStyle = palette[i % palette.length];
      ctx.fillRect(x, y, barWidth, h);
      ctx.fillStyle = "#334155";
      ctx.fillText(String(value), x + 2, y - 4);
      ctx.fillText(String(labels[i]).slice(0, 8), x, bottom + 12);
    });
  };

  const drawLine = (canvas, labels, values) => {
    const pack = setupCanvas(canvas);
    if (!pack) return;
    const { ctx, width, height } = pack;
    const max = Math.max(...values, 1);
    const left = 30;
    const right = width - 10;
    const top = 15;
    const bottom = height - 25;
    const step = values.length > 1 ? (right - left) / (values.length - 1) : 0;

    ctx.strokeStyle = "#dbe4f1";
    ctx.beginPath();
    ctx.moveTo(left, top);
    ctx.lineTo(left, bottom);
    ctx.lineTo(right, bottom);
    ctx.stroke();

    ctx.beginPath();
    values.forEach((value, i) => {
      const x = left + step * i;
      const y = bottom - ((bottom - top) * value) / max;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#3b82f6";
    ctx.lineWidth = 2;
    ctx.stroke();

    values.forEach((value, i) => {
      const x = left + step * i;
      const y = bottom - ((bottom - top) * value) / max;
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fillStyle = "#3b82f6";
      ctx.fill();
      ctx.fillStyle = "#334155";
      ctx.fillText(String(labels[i]).slice(0, 8), x - 8, bottom + 12);
    });
  };

  const drawRadar = (canvas, labels, values) => {
    const pack = setupCanvas(canvas);
    if (!pack) return;
    const { ctx, width, height } = pack;
    const max = Math.max(...values, 1);
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(width, height) * 0.32;
    const n = values.length || 1;

    for (let ring = 1; ring <= 4; ring += 1) {
      ctx.beginPath();
      for (let i = 0; i < n; i += 1) {
        const angle = -Math.PI / 2 + (i * Math.PI * 2) / n;
        const r = (radius * ring) / 4;
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.strokeStyle = "#e2e8f3";
      ctx.stroke();
    }

    ctx.beginPath();
    for (let i = 0; i < n; i += 1) {
      const angle = -Math.PI / 2 + (i * Math.PI * 2) / n;
      const r = (radius * values[i]) / max;
      const x = cx + r * Math.cos(angle);
      const y = cy + r * Math.sin(angle);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      const lx = cx + (radius + 12) * Math.cos(angle);
      const ly = cy + (radius + 12) * Math.sin(angle);
      ctx.fillStyle = "#334155";
      ctx.fillText(String(labels[i]).slice(0, 10), lx - 10, ly);
    }
    ctx.closePath();
    ctx.fillStyle = "rgba(59,130,246,0.25)";
    ctx.strokeStyle = "#3b82f6";
    ctx.fill();
    ctx.stroke();
  };

  const renderByType = (canvas, type, labels, values) => {
    if (!canvas) return;
    if (!labels.length || !values.length) {
      const pack = setupCanvas(canvas);
      if (pack) pack.ctx.fillText("No data", pack.width / 2 - 18, pack.height / 2);
      return;
    }
    if (type === "pie") drawPieLike(canvas, labels, values, false);
    else if (type === "doughnut") drawPieLike(canvas, labels, values, true);
    else if (type === "line") drawLine(canvas, labels, values);
    else if (type === "radar") drawRadar(canvas, labels, values);
    else drawBar(canvas, labels, values);
  };

  const getSelectedFieldIndex = (selectNode, fallbackIndex) => {
    if (!selectNode || !selectNode.selectedOptions || !selectNode.selectedOptions.length) return fallbackIndex;
    const raw = selectNode.selectedOptions[0].dataset.fieldIndex;
    const index = Number(raw);
    return Number.isNaN(index) ? fallbackIndex : index;
  };

  const requisitionSelect = document.getElementById("requisitionFieldSelect");
  const bgvSelect = document.getElementById("bgvFieldSelect");
  const candidateSelect = document.getElementById("candidateFieldSelect");
  const teamSelect = document.getElementById("teamFieldSelect");

  const renderRequisitionChart = () => {
    const rows = extractTableRows("requisition");
    const fieldIndex = getSelectedFieldIndex(requisitionSelect, 5);
    const data = buildCountFromField(rows, fieldIndex);
    renderByType(document.getElementById("requisitionChart"), "pie", data.labels, data.values);
  };

  const renderBgvChart = () => {
    const rows = extractTableRows("bgv");
    const fieldIndex = getSelectedFieldIndex(bgvSelect, 3);
    const data = buildSeriesFromField(rows, fieldIndex, 0);
    renderByType(document.getElementById("bgvChart"), "bar", data.labels, data.values);
  };

  const renderCandidateChart = () => {
    const rows = extractTableRows("candidate");
    const fieldIndex = getSelectedFieldIndex(candidateSelect, 2);
    const data = buildSeriesFromField(rows, fieldIndex, 0);
    renderByType(document.getElementById("candidateChart"), "line", data.labels, data.values);
  };

  const renderTeamChart = () => {
    const rows = extractTableRows("team");
    const fieldIndex = getSelectedFieldIndex(teamSelect, -1);
    let data = { labels: [], values: [] };
    if (fieldIndex === -1) {
      data = {
        labels: rows.map((cells) => cells[0] || "Unknown"),
        values: rows.map((cells) => toNumber(cells[1]) + toNumber(cells[2])),
      };
    } else {
      data = buildSeriesFromField(rows, fieldIndex, 0);
    }
    renderByType(document.getElementById("teamChart"), "doughnut", data.labels, data.values);
  };

  renderRequisitionChart();
  renderBgvChart();
  renderCandidateChart();
  renderTeamChart();

  if (requisitionSelect) requisitionSelect.addEventListener("change", renderRequisitionChart);
  if (bgvSelect) bgvSelect.addEventListener("change", renderBgvChart);
  if (candidateSelect) candidateSelect.addEventListener("change", renderCandidateChart);
  if (teamSelect) teamSelect.addEventListener("change", renderTeamChart);
});
