document.addEventListener("DOMContentLoaded", () => {
  const searchInput = document.getElementById("candidateSearchInput");
  const filters = document.getElementById("candidateFilters");

  const openFilters = () => {
    if (filters) {
      filters.classList.remove("d-none");
    }
  };

  if (searchInput) {
    searchInput.addEventListener("focus", openFilters);
    searchInput.addEventListener("click", openFilters);
  }
});
