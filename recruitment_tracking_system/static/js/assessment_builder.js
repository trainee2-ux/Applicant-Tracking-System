document.addEventListener("DOMContentLoaded", () => {
  const openCreateBtn = document.getElementById("openCreateAssessmentBtn");
  const createFormWrap = document.getElementById("createAssessmentFormWrap");
  const openFieldBtn = document.getElementById("openAddFieldBtn");
  const addFieldFormWrap = document.getElementById("addFieldFormWrap");
  const fieldTypeSelect = document.getElementById("assessmentFieldType");
  const fieldOptionsWrap = document.getElementById("fieldOptionsWrap");

  if (openCreateBtn && createFormWrap) {
    openCreateBtn.addEventListener("click", () => {
      const isHidden = createFormWrap.classList.contains("d-none");
      createFormWrap.classList.toggle("d-none");
      
      // Update icon and text without destroying inner structure if possible
      // or just toggle the visibility
      const firstInput = createFormWrap.querySelector("input[name='name']");
      if (isHidden && firstInput) firstInput.focus();
    });
  }

  if (openFieldBtn && addFieldFormWrap) {
    openFieldBtn.addEventListener("click", () => {
      const isHidden = addFieldFormWrap.classList.contains("d-none");
      addFieldFormWrap.classList.toggle("d-none");
      
      const firstInput = addFieldFormWrap.querySelector("input[name='label']");
      if (isHidden && firstInput) firstInput.focus();
    });
  }

  if (fieldTypeSelect && fieldOptionsWrap) {
    const toggleOptions = () => {
      const needsOptions = ["select", "radio", "checkbox"].includes(fieldTypeSelect.value);
      fieldOptionsWrap.classList.toggle("d-none", !needsOptions);
    };
    fieldTypeSelect.addEventListener("change", toggleOptions);
    toggleOptions();
  }
});
