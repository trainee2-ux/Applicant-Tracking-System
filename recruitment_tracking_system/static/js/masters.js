document.addEventListener("DOMContentLoaded", () => {
  const cards = Array.from(document.querySelectorAll(".master-option-card"));
  if (!cards.length) return;

  cards.forEach((card) => {
    card.addEventListener("click", () => {
      const url = card.dataset.url || "";
      if (!url) return;
      window.location.href = url;
    });
  });
});
