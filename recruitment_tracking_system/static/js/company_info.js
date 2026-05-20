document.addEventListener("DOMContentLoaded", () => {
  const openBtn = document.getElementById("openCompanyCreateBtn");
  const form = document.getElementById("companyInfoForm");
  if (!openBtn || !form) return;

  openBtn.addEventListener("click", () => {
    form.classList.remove("d-none");
    const firstInput = form.querySelector("input[name='company_name']");
    if (firstInput) firstInput.focus();
  });
});
