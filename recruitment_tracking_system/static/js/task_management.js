document.addEventListener("DOMContentLoaded", () => {
  const openTaskCreateBtn = document.getElementById("openTaskCreateBtn");
  const cancelTaskCreateBtn = document.getElementById("cancelTaskCreateBtn");
  const taskCreateForm = document.getElementById("taskCreateForm");
  const repeatToggle = document.getElementById("repeatToggle");
  const reminderToggle = document.getElementById("reminderToggle");
  const repeatFields = document.getElementById("repeatFields");
  const reminderFields = document.getElementById("reminderFields");
  const taskTargetType = document.getElementById("taskTargetType");
  const taskContactWrap = document.getElementById("taskContactWrap");
  const taskCandidateWrap = document.getElementById("taskCandidateWrap");

  if (openTaskCreateBtn && taskCreateForm) {
    openTaskCreateBtn.addEventListener("click", () => {
      taskCreateForm.classList.remove("d-none");
      const firstInput = taskCreateForm.querySelector("input, select, textarea");
      if (firstInput) firstInput.focus();
    });
  }

  if (cancelTaskCreateBtn && taskCreateForm) {
    cancelTaskCreateBtn.addEventListener("click", () => {
      taskCreateForm.classList.add("d-none");
    });
  }

  if (repeatToggle && repeatFields) {
    repeatToggle.addEventListener("change", () => {
      repeatFields.classList.toggle("d-none", !repeatToggle.checked);
    });
    repeatFields.classList.toggle("d-none", !repeatToggle.checked);
  }

  if (reminderToggle && reminderFields) {
    reminderToggle.addEventListener("change", () => {
      reminderFields.classList.toggle("d-none", !reminderToggle.checked);
    });
    reminderFields.classList.toggle("d-none", !reminderToggle.checked);
  }

  const toggleTaskTarget = () => {
    if (!taskTargetType || !taskContactWrap || !taskCandidateWrap) return;
    const selected = taskTargetType.value;
    taskContactWrap.classList.toggle("d-none", selected !== "contact");
    taskCandidateWrap.classList.toggle("d-none", selected !== "candidate");
  };

  // Global fallback for inline onchange handler in template.
  window.toggleTaskTargetType = (selectedValue) => {
    if (!taskTargetType || !taskContactWrap || !taskCandidateWrap) return;
    if (typeof selectedValue === "string") taskTargetType.value = selectedValue;
    const selected = taskTargetType.value;
    taskContactWrap.classList.toggle("d-none", selected !== "contact");
    taskCandidateWrap.classList.toggle("d-none", selected !== "candidate");
  };

  if (taskTargetType) {
    taskTargetType.addEventListener("change", toggleTaskTarget);
    toggleTaskTarget();
  }
});
