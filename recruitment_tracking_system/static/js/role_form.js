document.addEventListener("DOMContentLoaded", () => {
  const openBtn = document.getElementById("openRoleCreateBtn");
  const formWrap = document.getElementById("roleCreateFormWrap");
  const form = document.getElementById("roleCreateForm");
  
  if (!openBtn || !formWrap) return;

  openBtn.addEventListener("click", () => {
    formWrap.classList.toggle("d-none");
    if (!formWrap.classList.contains("d-none")) {
        const firstInput = form.querySelector("input[name='role_name']");
        if (firstInput) firstInput.focus();
    }
  });
});

