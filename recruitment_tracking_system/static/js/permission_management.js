document.addEventListener("DOMContentLoaded", () => {
  const openBtn = document.getElementById("openPermissionCreateBtn");
  const cancelBtn = document.getElementById("cancelPermissionCreateBtn");
  const form = document.getElementById("permissionCreateForm");
  const fullAccess = document.getElementById("fullAccessPermission");
  const toggles = document.querySelectorAll(".perm-toggle");
  const moduleSelect = document.getElementById("permissionModuleSelect");
  const subModuleSelect = document.getElementById("permissionSubModuleSelect");
  const subModuleMapNode = document.getElementById("permissionSubModuleMapData");

  if (openBtn && form) {
    openBtn.addEventListener("click", () => {
      form.classList.remove("d-none");
      const firstInput = form.querySelector("select[name='role']");
      if (firstInput) firstInput.focus();
    });
  }

  if (cancelBtn && form) {
    cancelBtn.addEventListener("click", () => {
      form.classList.add("d-none");
    });
  }

  if (fullAccess) {
    fullAccess.addEventListener("change", () => {
      toggles.forEach((checkbox) => {
        checkbox.checked = fullAccess.checked;
      });
    });
  }

  let subModuleMap = {};
  try {
    subModuleMap = JSON.parse((subModuleMapNode && subModuleMapNode.textContent) || "{}");
  } catch (e) {
    subModuleMap = {};
  }

  const rebuildSubModules = () => {
    if (!moduleSelect || !subModuleSelect) return;
    const selectedModule = moduleSelect.value || "";
    const options = subModuleMap[selectedModule] || ["General"];
    const previous = subModuleSelect.value || "";
    subModuleSelect.innerHTML = "";

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Select";
    subModuleSelect.appendChild(placeholder);

    options.forEach((item) => {
      const option = document.createElement("option");
      option.value = item;
      option.textContent = item;
      if (previous && previous === item) option.selected = true;
      subModuleSelect.appendChild(option);
    });

    if (!Array.from(subModuleSelect.options).some((opt) => opt.value === previous)) {
      subModuleSelect.value = "";
    }
  };

  if (moduleSelect && subModuleSelect) {
    moduleSelect.addEventListener("change", rebuildSubModules);
    rebuildSubModules();
  }
});
