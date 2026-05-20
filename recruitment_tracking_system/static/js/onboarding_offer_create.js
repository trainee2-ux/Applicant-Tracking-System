(() => {
  const subjectInput = document.getElementById("offerCreateSubject");
  const bodyInput = document.getElementById("offerCreateBody");
  const previewBtn = document.getElementById("offerCreatePreviewBtn");
  const previewFrame = document.getElementById("offerCreatePreviewFrame");

  if (!subjectInput || !bodyInput || !previewFrame) return;

  const getCookie = (name) => {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  };

  const setPreviewHtml = (html) => {
    previewFrame.srcdoc =
      html ||
      "<div style='padding:16px;font-family:Arial,sans-serif;color:#64748b'>No preview available.</div>";
  };

  let busy = false;
  const setBusy = (v) => {
    busy = v;
    if (previewBtn) previewBtn.disabled = v;
    subjectInput.disabled = v;
    bodyInput.disabled = v;
  };

  const previewOffer = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const csrfToken = getCookie("csrftoken");
      const payload = new URLSearchParams();
      payload.set("action", "preview_offer");
      payload.set("subject", subjectInput.value || "");
      payload.set("body_html", bodyInput.value || "");

      const url = new URL(window.location.href, window.location.origin);
      url.searchParams.set("ajax", "1");

      const res = await fetch(url.toString(), {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": csrfToken,
        },
        credentials: "same-origin",
        body: payload.toString(),
      });

      const data = await res.json();
      if (!data || !data.ok) throw new Error((data && data.message) || "Unable to generate preview.");
      setPreviewHtml(data.preview_html || "");
    } catch (e) {
      setPreviewHtml("");
    } finally {
      setBusy(false);
    }
  };

  const debounce = (fn, delay) => {
    let t = null;
    return (...args) => {
      if (t) clearTimeout(t);
      t = setTimeout(() => fn(...args), delay);
    };
  };

  const debouncedPreview = debounce(previewOffer, 400);
  subjectInput.addEventListener("input", debouncedPreview);
  bodyInput.addEventListener("input", debouncedPreview);
  if (previewBtn) previewBtn.addEventListener("click", previewOffer);

  // Initial preview
  previewOffer();
})();

