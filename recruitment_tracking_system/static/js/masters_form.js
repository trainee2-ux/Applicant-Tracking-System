document.addEventListener("DOMContentLoaded", () => {
  const openBtn = document.getElementById("openMasterAddFormBtn");
  const formWrap = document.getElementById("masterAddFormWrap");
  const form = document.getElementById("masterAddForm");
  
  if (!openBtn || !formWrap) return;

  openBtn.addEventListener("click", () => {
    formWrap.classList.toggle("d-none");
    if (!formWrap.classList.contains("d-none")) {
        const firstInput = form.querySelector("#masterNameInput") || form.querySelector("input");
        if (firstInput) firstInput.focus();
    }
  });
});
