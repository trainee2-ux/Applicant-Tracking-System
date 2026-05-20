document.addEventListener("DOMContentLoaded", () => {
  const cards = document.querySelectorAll(".interview-option-card");
  const candidateSelect = document.getElementById("scheduleCandidateSelect");

  cards.forEach((card) => {
    card.addEventListener("click", () => {
      const url = card.dataset.url;
      if (!url) return;

      const selectedCandidate = candidateSelect ? candidateSelect.value : "";
      const target = new URL(url, window.location.origin);
      if (selectedCandidate) {
        target.searchParams.set("candidate_id", selectedCandidate);
      }
      window.location.href = target.toString();
    });
  });
});
