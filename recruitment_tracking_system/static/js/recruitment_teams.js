document.addEventListener("DOMContentLoaded", () => {
  const openBtn = document.getElementById("openTeamCreateBtn");
  const cancelBtn = document.getElementById("cancelTeamCreateBtn");
  const form = document.getElementById("teamCreateForm");
  if (!openBtn || !form) return;

  openBtn.addEventListener("click", () => {
    form.classList.remove("d-none");
    const firstInput = form.querySelector("input[name='team_name']");
    if (firstInput) firstInput.focus();
  });

  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      form.classList.add("d-none");
    });
  }

  function initCheckboxDropdown(dropdownEl, toggleEl) {
    if (!dropdownEl || !toggleEl) return;

    const defaultLabel = (toggleEl.textContent || "").trim() || "Select";
    toggleEl.dataset.defaultLabel = defaultLabel;

    function updateLabel() {
      const checked = dropdownEl.querySelectorAll("input[type='checkbox']:checked");
      if (!checked.length) {
        toggleEl.textContent = toggleEl.dataset.defaultLabel || defaultLabel;
        return;
      }
      const labels = Array.from(checked)
        .map((input) => {
          const wrapper = input.closest("label");
          return (wrapper ? wrapper.textContent : input.value).trim();
        })
        .filter(Boolean);

      if (labels.length <= 2) {
        toggleEl.textContent = labels.join(", ");
      } else {
        toggleEl.textContent = `${labels.length} selected`;
      }
    }

    updateLabel();

    toggleEl.addEventListener("click", (event) => {
      event.stopPropagation();
      // Close other open dropdowns first.
      document.querySelectorAll(".member-dropdown.open").forEach((el) => {
        if (el !== dropdownEl) el.classList.remove("open");
      });
      dropdownEl.classList.toggle("open");
    });

    dropdownEl.addEventListener("change", (event) => {
      const target = event.target;
      if (target && target.matches("input[type='checkbox']")) updateLabel();
    });
  }

  document.querySelectorAll(".member-dropdown").forEach((dropdownEl) => {
    const toggleEl = dropdownEl.querySelector(".member-dropdown-toggle");
    initCheckboxDropdown(dropdownEl, toggleEl);
  });

  document.addEventListener("click", (event) => {
    document.querySelectorAll(".member-dropdown.open").forEach((dropdown) => {
      if (!dropdown.contains(event.target)) dropdown.classList.remove("open");
    });
  });
});
