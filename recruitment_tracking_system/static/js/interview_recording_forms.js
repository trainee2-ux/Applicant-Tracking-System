document.addEventListener("DOMContentLoaded", () => {
  const panelBtn = document.getElementById("openPanelFormBtn");
  const panelWrap = document.getElementById("panelFormWrap");
  const panelCancel = document.getElementById("cancelPanelFormBtn");

  if (panelBtn && panelWrap) {
    panelBtn.addEventListener("click", (event) => {
      event.preventDefault();
      panelWrap.classList.remove("d-none");
      const firstInput = panelWrap.querySelector("input[name='candidate']");
      if (firstInput) firstInput.focus();
      window.history.replaceState({}, "", "/interview-recording/panel/?create=1");
    });
  }

  if (panelCancel && panelWrap) {
    panelCancel.addEventListener("click", (event) => {
      event.preventDefault();
      panelWrap.classList.add("d-none");
      window.history.replaceState({}, "", "/interview-recording/panel/");
    });
  }

  const recordingBtn = document.getElementById("openRecordingFormBtn");
  const recordingWrap = document.getElementById("recordingFormWrap");
  const recordingCancel = document.getElementById("cancelRecordingFormBtn");

  if (recordingBtn && recordingWrap) {
    recordingBtn.addEventListener("click", (event) => {
      event.preventDefault();
      recordingWrap.classList.remove("d-none");
      const firstInput = recordingWrap.querySelector("input[name='candidate']");
      if (firstInput) firstInput.focus();
      window.history.replaceState({}, "", "/interview-recording/recording/?create=1");
    });
  }

  if (recordingCancel && recordingWrap) {
    recordingCancel.addEventListener("click", (event) => {
      event.preventDefault();
      recordingWrap.classList.add("d-none");
      window.history.replaceState({}, "", "/interview-recording/recording/");
    });
  }

  const modeSelects = document.querySelectorAll("select[data-open-on-change='true']");
  modeSelects.forEach((select) => {
    select.addEventListener("change", () => {
      const form = select.closest("form");
      const recordIdInput = form ? form.querySelector("input[name='record_id']") : null;
      if (recordIdInput && String(recordIdInput.value || "").trim()) {
        return;
      }
      let value = String(select.value || "").trim();
      if (!value && select.options && select.selectedIndex >= 0) {
        value = String(select.options[select.selectedIndex].text || "").trim();
      }
      value = value.toLowerCase();
      const inPersonUrl = select.dataset.inpersonUrl || "";
      const videoUrl = select.dataset.videoUrl || "";
      if (value === "in person" && inPersonUrl) {
        window.location.href = inPersonUrl;
      } else if (value === "video" && videoUrl) {
        window.location.href = videoUrl;
      }
    });
  });
});
