document.addEventListener("DOMContentLoaded", () => {
  const tabButtons = Array.from(document.querySelectorAll(".job-tab-btn, .job-step"));
  const panes = Array.from(document.querySelectorAll(".job-tab-pane"));
  const nextButtons = Array.from(document.querySelectorAll(".job-next-btn"));

  if (!tabButtons.length || !panes.length) {
    return;
  }

  const activatePane = (paneId) => {
    panes.forEach((pane) => {
      pane.classList.toggle("active", pane.id === paneId);
    });

    tabButtons.forEach((btn) => {
      const isActive = btn.dataset.target === paneId;
      btn.classList.toggle("active", isActive);
      if (btn.getAttribute("role") === "tab") {
        btn.setAttribute("aria-selected", isActive ? "true" : "false");
      }
    });
  };

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => activatePane(btn.dataset.target));
  });

  nextButtons.forEach((btn) => {
    btn.addEventListener("click", () => activatePane(btn.dataset.next));
  });
});
