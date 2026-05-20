document.addEventListener("DOMContentLoaded", () => {
  if (typeof Chart === "undefined") {
    return;
  }

  const deptCtx = document.getElementById("deptChart");
  const statusCtx = document.getElementById("statusChart");

  if (!deptCtx || !statusCtx) {
    return;
  }

  const getCSSVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#64748b';
  Chart.defaults.color = getCSSVar('--text2');
  Chart.defaults.font.family = "'Inter', 'Plus Jakarta Sans', sans-serif";

  // Parse actual data from the backend
  let deptLabels = ["Engineering", "Sales", "Support", "HR"];
  let deptData = [0, 0, 0, 0];
  let statusData = [0, 0, 0];

  try {
    deptLabels = JSON.parse(document.getElementById('dept-labels').textContent);
    deptData = JSON.parse(document.getElementById('dept-data').textContent);
    statusData = JSON.parse(document.getElementById('status-data').textContent);
  } catch (e) {
    console.error("Could not load chart data from backend:", e);
  }

  new Chart(deptCtx, {
    type: "bar",
    data: {
      labels: ["Engineering", "Sales", "Support", "HR"],
      datasets: [
        {
          label: "Active Requisitions",
          data: deptData,
          backgroundColor: ["#6366f1", "#818cf8", "#a5b4fc", "#c7d2fe"],
          borderRadius: 8,
          borderSkipped: false,
          barPercentage: 0.6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { 
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1e293b',
          titleColor: '#f8fafc',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1,
          padding: 12,
          displayColors: false,
          cornerRadius: 8
        }
      },
      scales: {
        x: {
          grid: { display: false, drawBorder: false },
          ticks: { font: { weight: '600' } }
        },
        y: { 
          beginAtZero: true, 
          grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
          ticks: { precision: 0, padding: 10 }
        },
      },
    },
  });

  new Chart(statusCtx, {
    type: "doughnut",
    data: {
      labels: ["Pending Review", "Authorized", "Rejected"],
      datasets: [
        {
          data: statusData,
          backgroundColor: ["#f59e0b", "#10b981", "#ef4444"],
          hoverBackgroundColor: ["#fbbf24", "#34d399", "#f87171"],
          borderWidth: 0,
          hoverOffset: 4
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { 
          position: "bottom",
          labels: { padding: 20, usePointStyle: true, pointStyle: 'circle', font: { weight: '600' } }
        },
        tooltip: {
          backgroundColor: '#1e293b',
          titleColor: '#f8fafc',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1,
          padding: 12,
          cornerRadius: 8
        }
      },
      cutout: "75%",
    },
  });
});
