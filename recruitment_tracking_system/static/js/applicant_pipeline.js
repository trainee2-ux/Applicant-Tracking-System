(() => {
  const board = document.querySelector(".pipeline-board");
  if (!board) return;

  const searchInput = document.getElementById("pipelineSearch");
  const createStageBtn = document.getElementById("createStageBtn");
  const stageModal = document.getElementById("stageModal");
  const stageModalBackdrop = document.getElementById("stageModalBackdrop");
  const stageNameInput = document.getElementById("stageNameInput");
  const saveStageBtn = document.getElementById("saveStageBtn");
  const cancelStageBtn = document.getElementById("cancelStageBtn");
  const getColumns = () => [...board.querySelectorAll(".pipeline-column, .pipeline-col")];
  const cardsSelector = ".pipeline-card, .kanban-card";
  let columns = getColumns();

  const nowString = () => {
    const now = new Date();
    return now.toLocaleDateString("en-GB");
  };

  const getCookie = (name) => {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  };

  const updateStageServer = async (card, stage) => {
    const candidateId = card.dataset.candidateId || "";
    const jobApplied = card.dataset.job || card.dataset.jobApplied || "";
    if (!candidateId || !stage) return;
    try {
      const tokenInput = document.getElementById("pipelineCsrfToken");
      const csrfToken = (tokenInput && tokenInput.value) || getCookie("csrftoken");
      await fetch("/applicant-tracking/application-pipeline/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        credentials: "same-origin",
        body: JSON.stringify({
          action: "update_stage",
          candidate_id: candidateId,
          job_applied: jobApplied,
          stage: stage,
        }),
      }).then(async (res) => {
        let data = null;
        try { data = await res.json(); } catch (e) { data = null; }
        if (data && data.ok && data.email_ok === false) {
          const msg = data.email_error || "Unknown error";
          console.warn("Stage update email failed:", msg);
          try {
            alert(`Stage updated, but email failed:\n${msg}`);
          } catch (e) {}
        }
      });
    } catch (e) {
      console.error("Stage update failed", e);
    }
  };

  const ensureEmptyState = (column) => {
    const cardsWrap = column.querySelector(".pipeline-cards, .pipeline-body");
    if (!cardsWrap) return;

    const hasCards = cardsWrap.querySelector(cardsSelector);
    let empty = cardsWrap.querySelector(".pipeline-empty");

    if (!hasCards && !empty) {
      empty = document.createElement("div");
      empty.className = "pipeline-empty";
      empty.textContent = "No candidates";
      cardsWrap.appendChild(empty);
    }

    if (hasCards && empty) {
      empty.remove();
    }
  };

  const updateCounts = () => {
    columns.forEach((column) => {
      const count = column.querySelectorAll(cardsSelector).length;
      const countEl = column.querySelector(".pipeline-count");
      if (countEl) countEl.textContent = String(count);
      ensureEmptyState(column);
    });
  };

  const setCardBindings = (card) => {
    if (!card.getAttribute("draggable")) card.setAttribute("draggable", "true");
    if (!card.getAttribute("tabindex")) card.setAttribute("tabindex", "0");

    const openCandidate = () => {
      const candidateId = card.dataset.candidateId || "";
      if (!candidateId) return;
      window.location.href = `/candidate-management/profile/?candidate_id=${encodeURIComponent(candidateId)}`;
    };

    card.addEventListener("dragstart", () => {
      card.classList.add("dragging");
    });

    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      columns.forEach((c) => c.classList.remove("drop-target"));
    });

    card.addEventListener("click", (event) => {
      const target = event.target;
      if (target instanceof Element && target.closest("button, a, input, select, textarea, .btn-delete-stage")) return;
      if (card.classList.contains("dragging")) return;
      openCandidate();
    });

    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openCandidate();
      }
    });
  };

  const bindColumnDrop = (column) => {
    const cardsWrap = column.querySelector(".pipeline-cards, .pipeline-body");
    if (!cardsWrap) return;

    cardsWrap.addEventListener("dragover", (event) => {
      event.preventDefault();
      column.classList.add("drop-target");
    });

    cardsWrap.addEventListener("dragleave", (event) => {
      if (!column.contains(event.relatedTarget)) {
        column.classList.remove("drop-target");
      }
    });

    cardsWrap.addEventListener("drop", (event) => {
      event.preventDefault();
      const dragging = board.querySelector(".pipeline-card.dragging, .kanban-card.dragging");
      if (!dragging) return;

      cardsWrap.appendChild(dragging);

      const stage = column.dataset.stage || "";
      const stageEl = dragging.querySelector(".card-stage");
      const updatedEl = dragging.querySelector(".card-updated");
      if (stageEl) stageEl.textContent = stage;
      if (updatedEl) updatedEl.textContent = nowString();

      column.classList.remove("drop-target");
      updateCounts();
      applySearch();
      updateStageServer(dragging, stage);
    });
  };

  const createStageColumn = (stageName) => {
    const safeStage = stageName.trim();
    if (!safeStage) return;

    const column = document.createElement("section");
    column.className = "pipeline-column";
    column.dataset.stage = safeStage;
    column.innerHTML = `
      <header class="pipeline-column-head">
        <div style="display: flex; align-items: center; gap: 0.5rem;">
          <span>${safeStage}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 0.5rem;">
          <button type="button" class="btn-delete-stage" aria-label="Delete stage" title="Delete Stage">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" class="bi bi-trash3" viewBox="0 0 16 16">
              <path d="M6.5 1h3a.5.5 0 0 1 .5.5v1H6v-1a.5.5 0 0 1 .5-.5ZM11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3A1.5 1.5 0 0 0 5 1.5v1H2.506a.58.58 0 0 0-.01 0H1.5a.5.5 0 0 0 0 1h.538l.853 10.66A2 2 0 0 0 4.885 16h6.23a2 2 0 0 0 1.994-1.84l.853-10.66h.538a.5.5 0 0 0 0-1h-.995a.59.59 0 0 0-.01 0H11Zm1.813 1H3.187l-.834 10.428A1 1 0 0 0 3.348 15h9.304a1 1 0 0 0 .995-1.072L12.813 3.5Zm-8.487 1.838a.5.5 0 0 1 .498.507l.5 8.5a.5.5 0 0 1-.998.058l-.5-8.5a.5.5 0 0 1 .5-.492ZM8 5a.5.5 0 0 1 .5.5v8.5a.5.5 0 0 1-1 0v-8.5A.5.5 0 0 1 8 5Zm3.178.342a.5.5 0 0 1 .492.508l-.5 8.5a.5.5 0 0 1-.998-.058l.5-8.5a.5.5 0 0 1 .5-.492Z"/>
            </svg>
          </button>
          <span class="pipeline-count">0</span>
        </div>
      </header>
      <div class="pipeline-cards">
        <div class="pipeline-empty">No candidates</div>
      </div>
    `;
    board.appendChild(column);
    columns = getColumns();
    bindColumnDrop(column);
    updateCounts();
    applySearch();
  };

  const closeStageModal = () => {
    if (!stageModal) return;
    stageModal.hidden = true;
    if (stageModalBackdrop) stageModalBackdrop.hidden = true;
    if (stageNameInput) stageNameInput.value = "";
  };

  const openStageModal = () => {
    if (!stageModal) return;
    stageModal.hidden = false;
    if (stageModalBackdrop) stageModalBackdrop.hidden = false;
    if (stageNameInput) stageNameInput.focus();
  };

  const applySearch = () => {
    const term = (searchInput?.value || "").trim().toLowerCase();

    columns.forEach((column) => {
      const cards = [...column.querySelectorAll(cardsSelector)];
      cards.forEach((card) => {
        if (!term) {
          card.hidden = false;
          return;
        }

        const haystack = [
          card.dataset.name || "",
          card.dataset.job || "",
          card.textContent || "",
        ]
          .join(" ")
          .toLowerCase();
        card.hidden = !haystack.includes(term);
      });

      ensureEmptyState(column);
      const countEl = column.querySelector(".pipeline-count");
      if (countEl) {
        const visibleCount = cards.filter((c) => !c.hidden).length;
        countEl.textContent = String(visibleCount);
      }
    });
  };

  columns.forEach(bindColumnDrop);
  board.querySelectorAll(cardsSelector).forEach(setCardBindings);

  board.addEventListener("click", (event) => {
    const btn = event.target.closest(".btn-delete-stage");
    if (!btn) return;
    const column = btn.closest(".pipeline-column");
    if (!column) return;
    const stageName = column.dataset.stage || "this stage";
    if (confirm(`Are you sure you want to delete the "${stageName}" stage?`)) {
      column.remove();
      columns = getColumns();
      updateCounts();
    }
  });

  if (searchInput) searchInput.addEventListener("input", applySearch);
  if (createStageBtn) {
    createStageBtn.addEventListener("click", openStageModal);
  }
  if (cancelStageBtn) {
    cancelStageBtn.addEventListener("click", closeStageModal);
  }
  if (stageModal) {
    stageModal.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest("[data-close-stage-modal]")) closeStageModal();
    });
  }
  if (stageModalBackdrop) {
    stageModalBackdrop.addEventListener("click", closeStageModal);
  }
  if (saveStageBtn) {
    saveStageBtn.addEventListener("click", () => {
      const stageName = stageNameInput?.value || "";
      if (!stageName.trim()) return;
      createStageColumn(stageName);
      closeStageModal();
    });
  }
  if (stageNameInput) {
    stageNameInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        saveStageBtn?.click();
      }
      if (event.key === "Escape") {
        closeStageModal();
      }
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && stageModal && !stageModal.hidden) {
      closeStageModal();
    }
  });
  updateCounts();
})();
