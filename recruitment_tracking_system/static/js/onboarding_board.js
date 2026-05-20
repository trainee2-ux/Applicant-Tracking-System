(() => {
  const modal = document.getElementById("offerAssignModal");
  if (!modal) return;

  const closeBtn = document.getElementById("offerAssignCloseBtn");
  const cancelBtn = document.getElementById("offerAssignCancelBtn");
  const sendBtn = document.getElementById("offerAssignSendBtn");
  const metaEl = document.getElementById("offerAssignMeta");
  const errorEl = document.getElementById("offerAssignError");
  const templateSel = document.getElementById("offerAssignTemplate");
  const subjectInput = document.getElementById("offerAssignSubject");
  const bodyInput = document.getElementById("offerAssignBody");
  const toEl = document.getElementById("offerAssignTo");
  const fromEl = document.getElementById("offerAssignFrom");
  const jobEl = document.getElementById("offerAssignJob");
  const previewBtn = document.getElementById("offerAssignPreviewBtn");
  const previewFrame = document.getElementById("offerAssignPreviewFrame");

  let offerUrl = "";
  let busy = false;

  const getCookie = (name) => {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  };

  const setBusy = (value) => {
    busy = value;
    if (sendBtn) sendBtn.disabled = value;
    if (previewBtn) previewBtn.disabled = value;
    if (templateSel) templateSel.disabled = value;
    if (subjectInput) subjectInput.disabled = value;
    if (bodyInput) bodyInput.disabled = value;
  };

  const setPreviewHtml = (html) => {
    if (!previewFrame) return;
    previewFrame.srcdoc = html || "<div style='padding:16px;font-family:Arial,sans-serif;color:#64748b'>No preview available.</div>";
  };

  const showError = (message) => {
    if (!errorEl) return;
    if (!message) {
      errorEl.style.display = "none";
      errorEl.textContent = "";
      return;
    }
    errorEl.style.display = "block";
    errorEl.textContent = message;
  };

  const open = () => {
    modal.style.display = "flex";
    showError("");
  };

  const close = () => {
    if (busy) return;
    modal.style.display = "none";
    offerUrl = "";
  };

  const renderTemplates = (templates, selectedId) => {
    if (!templateSel) return;
    templateSel.innerHTML = "";

    const optManual = document.createElement("option");
    optManual.value = "";
    optManual.textContent = "Manual Composition";
    templateSel.appendChild(optManual);

    (templates || []).forEach((t) => {
      const opt = document.createElement("option");
      opt.value = String(t.id);
      opt.textContent = t.module ? `${t.name} (${t.module})` : t.name;
      if (selectedId && String(selectedId) === String(t.id)) opt.selected = true;
      templateSel.appendChild(opt);
    });
  };

  const loadOfferData = async (templateId = "") => {
    if (!offerUrl) return;
    setBusy(true);
    showError("");
    if (metaEl) metaEl.textContent = "Loading…";
    try {
      const url = new URL(offerUrl, window.location.origin);
      url.searchParams.set("ajax", "1");
      if (templateId) url.searchParams.set("email_template_id", templateId);

      const res = await fetch(url.toString(), { credentials: "same-origin" });
      const data = await res.json();
      if (!data || !data.ok) throw new Error((data && data.message) || "Unable to load offer template.");

      const candidate = data.candidate || {};
      if (metaEl) metaEl.textContent = `${candidate.full_name || "Candidate"} · ${candidate.candidate_id || ""}`;
      if (toEl) toEl.textContent = data.to_email || candidate.email || "-";
      if (fromEl) fromEl.textContent = data.smtp_from_email || "-";
      if (jobEl) jobEl.textContent = data.job_title || "-";

      renderTemplates(data.email_templates || [], data.selected_email_template_id || "");
      if (subjectInput) subjectInput.value = data.default_subject || "";
      if (bodyInput) bodyInput.value = data.default_body || "";

      // Auto-refresh preview after loading template content.
      await previewOffer();
    } catch (e) {
      showError(e && e.message ? e.message : "Unable to load offer template.");
      if (metaEl) metaEl.textContent = "Offer Email";
    } finally {
      setBusy(false);
    }
  };

  const previewOffer = async () => {
    if (!offerUrl) return;
    try {
      const csrfToken = getCookie("csrftoken");
      const payload = new URLSearchParams();
      payload.set("action", "preview_offer");
      payload.set("email_template_id", templateSel ? templateSel.value : "");
      payload.set("subject", subjectInput ? subjectInput.value : "");
      payload.set("body_html", bodyInput ? bodyInput.value : "");

      const url = new URL(offerUrl, window.location.origin);
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
    }
  };

  const sendOffer = async () => {
    if (!offerUrl || busy) return;
    setBusy(true);
    showError("");
    try {
      const csrfToken = getCookie("csrftoken");
      const payload = new URLSearchParams();
      payload.set("action", "send_offer");
      payload.set("email_template_id", templateSel ? templateSel.value : "");
      payload.set("subject", subjectInput ? subjectInput.value : "");
      payload.set("body_html", bodyInput ? bodyInput.value : "");

      const url = new URL(offerUrl, window.location.origin);
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
      if (!data || !data.ok) throw new Error((data && data.message) || "Offer could not be sent.");
      window.location.href = data.redirect_url || "/onboarding/board/";
    } catch (e) {
      showError(e && e.message ? e.message : "Offer could not be sent.");
      setBusy(false);
    }
  };

  document.addEventListener("click", (event) => {
    const btn = event.target.closest(".js-offer-assign-btn");
    if (!btn) return;
    event.preventDefault();
    const url = btn.getAttribute("data-offer-url") || "";
    if (!url) return;
    offerUrl = url;
    open();
    loadOfferData("");
  });

  if (closeBtn) closeBtn.addEventListener("click", close);
  if (cancelBtn) cancelBtn.addEventListener("click", close);
  if (sendBtn) sendBtn.addEventListener("click", sendOffer);
  if (previewBtn) previewBtn.addEventListener("click", previewOffer);

  if (templateSel) {
    templateSel.addEventListener("change", () => {
      loadOfferData(templateSel.value || "");
    });
  }

  if (subjectInput) subjectInput.addEventListener("input", () => previewOffer());
  if (bodyInput) bodyInput.addEventListener("input", () => previewOffer());

  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });
})();

(() => {
  const modal = document.getElementById("docRequestModal");
  if (!modal) return;

  const closeBtn = document.getElementById("docRequestCloseBtn");
  const cancelBtn = document.getElementById("docRequestCancelBtn");
  const sendBtn = document.getElementById("docRequestSendBtn");
  const metaEl = document.getElementById("docRequestMeta");
  const errorEl = document.getElementById("docRequestError");
  const templateSel = document.getElementById("docRequestTemplate");
  const subjectInput = document.getElementById("docRequestSubject");
  const bodyInput = document.getElementById("docRequestBody");
  const toEl = document.getElementById("docRequestTo");
  const fromEl = document.getElementById("docRequestFrom");
  const previewBtn = document.getElementById("docRequestPreviewBtn");
  const previewFrame = document.getElementById("docRequestPreviewFrame");
  const modeDefault = document.getElementById("docModeDefault");
  const modeManual = document.getElementById("docModeManual");
  const manualBox = document.getElementById("docManualBox");
  const manualList = document.getElementById("docManualList");

  let requestUrl = "";
  let busy = false;
  let availableDocs = [];

  const getCookie = (name) => {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  };

  const setBusy = (value) => {
    busy = value;
    if (sendBtn) sendBtn.disabled = value;
    if (previewBtn) previewBtn.disabled = value;
    if (templateSel) templateSel.disabled = value;
    if (subjectInput) subjectInput.disabled = value;
    if (bodyInput) bodyInput.disabled = value;
  };

  const setPreviewHtml = (html) => {
    if (!previewFrame) return;
    previewFrame.srcdoc = html || "<div style='padding:16px;font-family:Arial,sans-serif;color:#64748b'>No preview available.</div>";
  };

  const showError = (message) => {
    if (!errorEl) return;
    if (!message) {
      errorEl.style.display = "none";
      errorEl.textContent = "";
      return;
    }
    errorEl.style.display = "block";
    errorEl.textContent = message;
  };

  const open = () => {
    modal.style.display = "flex";
    showError("");
  };

  const close = () => {
    if (busy) return;
    modal.style.display = "none";
    requestUrl = "";
  };

  const renderTemplates = (templates, selectedId) => {
    if (!templateSel) return;
    templateSel.innerHTML = "";

    const optManual = document.createElement("option");
    optManual.value = "";
    optManual.textContent = "Manual Composition";
    templateSel.appendChild(optManual);

    (templates || []).forEach((t) => {
      const opt = document.createElement("option");
      opt.value = String(t.id);
      opt.textContent = t.module ? `${t.name} (${t.module})` : t.name;
      if (selectedId && String(selectedId) === String(t.id)) opt.selected = true;
      templateSel.appendChild(opt);
    });
  };

  const getMode = () => {
    if (modeManual && modeManual.checked) return "manual";
    return "default";
  };

  const setMode = (mode) => {
    const isManual = String(mode || "").toLowerCase() === "manual";
    if (modeManual) modeManual.checked = isManual;
    if (modeDefault) modeDefault.checked = !isManual;
    if (manualBox) manualBox.style.display = isManual ? "block" : "none";
  };

  const getSelectedDocs = () => {
    if (getMode() !== "manual") return [];
    const selected = [];
    if (!manualList) return selected;
    manualList.querySelectorAll("input[type=checkbox][data-doc-key]").forEach((el) => {
      if (el.checked) selected.push(el.getAttribute("data-doc-key"));
    });
    return selected;
  };

  const renderDocChecklist = (docs, selectedKeys) => {
    if (!manualList) return;
    manualList.innerHTML = "";
    const set = new Set((selectedKeys || []).map(String));
    (docs || []).forEach((d) => {
      const key = String(d.key || "").trim();
      if (!key) return;
      const label = d.label || key;
      const row = document.createElement("label");
      row.style.display = "flex";
      row.style.gap = "10px";
      row.style.alignItems = "center";
      row.style.fontSize = "13px";
      row.style.fontWeight = "700";
      row.style.color = "var(--text)";

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.setAttribute("data-doc-key", key);
      cb.checked = set.has(key);
      cb.addEventListener("change", () => previewRequest());

      const text = document.createElement("div");
      text.textContent = label;

      row.appendChild(cb);
      row.appendChild(text);
      manualList.appendChild(row);
    });
  };

  const loadRequestData = async (templateId = "") => {
    if (!requestUrl) return;
    setBusy(true);
    showError("");
    if (metaEl) metaEl.textContent = "Loading…";
    try {
      const url = new URL(requestUrl, window.location.origin);
      url.searchParams.set("ajax", "1");
      if (templateId) url.searchParams.set("email_template_id", templateId);

      const res = await fetch(url.toString(), { credentials: "same-origin" });
      const data = await res.json();
      if (!data || !data.ok) throw new Error((data && data.message) || "Unable to load document request template.");

      const candidate = data.candidate || {};
      if (metaEl) metaEl.textContent = `${candidate.full_name || "Candidate"} · ${candidate.candidate_id || ""}`;
      if (toEl) toEl.textContent = data.to_email || candidate.email || "-";
      if (fromEl) fromEl.textContent = data.smtp_from_email || "-";

      renderTemplates(data.email_templates || [], data.selected_email_template_id || "");
      if (subjectInput) subjectInput.value = data.default_subject || "";
      if (bodyInput) bodyInput.value = data.default_body || "";

      availableDocs = data.available_documents || [];
      renderDocChecklist(availableDocs, data.document_requirements || []);
      setMode(data.document_mode || (data.document_requirements && data.document_requirements.length ? "manual" : "default"));

      await previewRequest();
    } catch (e) {
      showError(e && e.message ? e.message : "Unable to load document request template.");
      if (metaEl) metaEl.textContent = "Document Request";
    } finally {
      setBusy(false);
    }
  };

  const previewRequest = async () => {
    if (!requestUrl) return;
    try {
      const csrfToken = getCookie("csrftoken");
      const payload = new URLSearchParams();
      payload.set("action", "preview_request");
      payload.set("email_template_id", templateSel ? templateSel.value : "");
      payload.set("subject", subjectInput ? subjectInput.value : "");
      payload.set("body_html", bodyInput ? bodyInput.value : "");
      payload.set("document_mode", getMode());
      payload.set("document_requirements", JSON.stringify(getSelectedDocs()));

      const url = new URL(requestUrl, window.location.origin);
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
    }
  };

  const sendRequest = async () => {
    if (!requestUrl || busy) return;
    setBusy(true);
    showError("");
    try {
      const csrfToken = getCookie("csrftoken");
      const payload = new URLSearchParams();
      payload.set("action", "send_request");
      payload.set("email_template_id", templateSel ? templateSel.value : "");
      payload.set("subject", subjectInput ? subjectInput.value : "");
      payload.set("body_html", bodyInput ? bodyInput.value : "");
      payload.set("document_mode", getMode());
      payload.set("document_requirements", JSON.stringify(getSelectedDocs()));

      const url = new URL(requestUrl, window.location.origin);
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
      if (!data || !data.ok) throw new Error((data && data.message) || "Document request could not be sent.");
      window.location.href = data.redirect_url || "/onboarding/board/";
    } catch (e) {
      showError(e && e.message ? e.message : "Document request could not be sent.");
      setBusy(false);
    }
  };

  document.addEventListener("click", (event) => {
    const btn = event.target.closest(".js-doc-request-btn");
    if (!btn) return;
    event.preventDefault();
    const url = btn.getAttribute("data-doc-url") || "";
    if (!url) return;
    requestUrl = url;
    open();
    loadRequestData("");
  });

  if (closeBtn) closeBtn.addEventListener("click", close);
  if (cancelBtn) cancelBtn.addEventListener("click", close);
  if (sendBtn) sendBtn.addEventListener("click", sendRequest);
  if (previewBtn) previewBtn.addEventListener("click", previewRequest);

  if (templateSel) {
    templateSel.addEventListener("change", () => {
      loadRequestData(templateSel.value || "");
    });
  }

  if (modeDefault) modeDefault.addEventListener("change", () => { setMode("default"); previewRequest(); });
  if (modeManual) modeManual.addEventListener("change", () => { setMode("manual"); previewRequest(); });

  if (subjectInput) subjectInput.addEventListener("input", () => previewRequest());
  if (bodyInput) bodyInput.addEventListener("input", () => previewRequest());

  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });
})();
