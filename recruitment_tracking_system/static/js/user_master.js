document.addEventListener("DOMContentLoaded", () => {
  const openBtn = document.getElementById("openUserCreateBtn");
  const cancelBtn = document.getElementById("cancelUserCreateBtn");
  const formWrap = document.getElementById("userCreateFormWrap");
  const form = document.getElementById("userCreateForm");
  const firstName = document.getElementById("userFirstName");
  const lastName = document.getElementById("userLastName");
  const fullName = document.getElementById("userFullName");

  if (openBtn && formWrap) {
    openBtn.addEventListener("click", () => {
      formWrap.classList.toggle("d-none");
      if (!formWrap.classList.contains("d-none")) {
        const firstInput = form ? form.querySelector("input[name='first_name']") : null;
        if (firstInput) firstInput.focus();
      }
    });
  }

  if (cancelBtn && formWrap) {
    cancelBtn.addEventListener("click", () => {
      formWrap.classList.add("d-none");
    });
  }

  const syncFullName = () => {
    if (!fullName || !firstName || !lastName) return;
    fullName.value = `${(firstName.value || "").trim()} ${(lastName.value || "").trim()}`.trim();
  };

  if (firstName) firstName.addEventListener("input", syncFullName);
  if (lastName) lastName.addEventListener("input", syncFullName);

  const bindManagerContact = (selectId, inputId) => {
    const managerSelect = document.getElementById(selectId);
    const contactInput = document.getElementById(inputId);
    if (!managerSelect || !contactInput) return;

    const updateContact = () => {
      const selected = managerSelect.options[managerSelect.selectedIndex];
      const mobile = selected ? selected.dataset.mobile || "" : "";
      contactInput.value = mobile;
    };

    managerSelect.addEventListener("change", updateContact);
    updateContact();
  };

  bindManagerContact("createReportingManager", "createReportingManagerContact");
  bindManagerContact("updateReportingManager", "updateReportingManagerContact");

  const dropdowns = Array.from(document.querySelectorAll("[data-module-dropdown]"));

  const updateSelectedText = (dropdown) => {
    const textNode = dropdown.querySelector("[data-module-selected]");
    if (!textNode) return;
    const checked = Array.from(dropdown.querySelectorAll('input[name="allowed_modules"]:checked'));
    if (!checked.length) {
      textNode.textContent = "No modules selected";
      return;
    }
    const labels = checked.map((item) => {
      const label = item.closest("label");
      const span = label ? label.querySelector("span") : null;
      return span ? span.textContent.trim() : item.value;
    });
    textNode.textContent = labels.join(", ");
  };

  dropdowns.forEach((dropdown) => {
    const toggle = dropdown.querySelector("[data-module-toggle]");
    const menu = dropdown.querySelector("[data-module-menu]");
    const checks = dropdown.querySelectorAll('input[name="allowed_modules"]');
    if (!toggle || !menu || !checks.length) return;

    toggle.addEventListener("click", (event) => {
      event.preventDefault();
      dropdown.classList.toggle("open");
    });

    checks.forEach((check) => {
      check.addEventListener("change", () => updateSelectedText(dropdown));
    });

    updateSelectedText(dropdown);
  });

  document.addEventListener("click", (event) => {
    dropdowns.forEach((dropdown) => {
      if (!dropdown.contains(event.target)) {
        dropdown.classList.remove("open");
      }
    });
  });

  const validateModules = (formElement) => {
    if (!formElement) return true;
    const checks = formElement.querySelectorAll('input[name="allowed_modules"]');
    if (!checks.length) return true;
    const hasSelection = Array.from(checks).some((item) => item.checked);
    if (!hasSelection) {
      alert("Please select at least one allowed module.");
      return false;
    }
    return true;
  };

  const createUserForm = document.getElementById("userCreateForm");
  const updateUserForm = document.getElementById("userUpdateForm");
  if (createUserForm) {
    createUserForm.addEventListener("submit", (event) => {
      if (!validateModules(createUserForm)) event.preventDefault();
    });
  }
  if (updateUserForm) {
    updateUserForm.addEventListener("submit", (event) => {
      if (!validateModules(updateUserForm)) event.preventDefault();
    });
  }
});
