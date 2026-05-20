document.addEventListener("DOMContentLoaded", () => {
  const statusSelect = document.getElementById("evaluationStatus");
  const customWrap = document.getElementById("customStatusWrap");
  const customInput = document.getElementById("customStatusInput");
  const prefillSelect = document.getElementById("candidatePrefillSelect");
  const candidateIdInput = document.getElementById("candidateIdInput");
  const candidateNameInput = document.getElementById("candidateNameInput");
  const candidatePhoneInput = document.getElementById("candidatePhoneInput");
  const candidateEmailInput = document.getElementById("candidateEmailInput");
  const postingTitleInput = document.getElementById("postingTitleInput");
  const prefillDataNode = document.getElementById("candidatePrefillData");
  const roundMapNode = document.getElementById("candidateRoundMapData");
  const roundSelect = document.getElementById("candidateInterviewRound");
  const formMapNode = document.getElementById("evaluationFormMapData");
  const initialAssessmentValuesNode = document.getElementById("initialAssessmentFormValuesData");
  const initialFeedbackValuesNode = document.getElementById("initialFeedbackFormValuesData");
  const assessmentFormSelect = document.getElementById("assessmentFormSelect");
  const feedbackFormSelect = document.getElementById("feedbackFormSelect");
  const assessmentDynamicFields = document.getElementById("assessmentDynamicFields");
  const feedbackDynamicFields = document.getElementById("feedbackDynamicFields");

  if (statusSelect && customWrap && customInput) {
    const toggleCustomStatus = () => {
      const isCustom = statusSelect.value === "__custom__";
      customWrap.classList.toggle("d-none", !isCustom);
      customInput.required = isCustom;
      if (isCustom) {
        customInput.focus();
      } else {
        customInput.value = "";
      }
    };

    statusSelect.addEventListener("change", toggleCustomStatus);
    toggleCustomStatus();
  }

  if (
    !prefillSelect ||
    !candidateIdInput ||
    !candidateNameInput ||
    !candidatePhoneInput ||
    !candidateEmailInput ||
    !postingTitleInput ||
    !prefillDataNode
  ) {
    // continue so form-rendering logic can still work on edit/create pages
  } else {
    let candidates = [];
    try {
      candidates = JSON.parse(prefillDataNode.textContent || "[]");
    } catch (e) {
      candidates = [];
    }

    const byId = {};
    candidates.forEach((item) => {
      const key = String(item.id || "").trim().toUpperCase();
      if (key) byId[key] = item;
    });

    prefillSelect.addEventListener("change", () => {
      const rawValue = String(prefillSelect.value || "").trim();
      if (rawValue) {
        window.location.href = `/candidate-management/evaluation/?create=1&candidate_id=${encodeURIComponent(rawValue)}`;
        return;
      }

      const selectedKey = String(prefillSelect.value || "").trim().toUpperCase();
      const selected = byId[selectedKey] || null;
      if (!selected) return;
      candidateIdInput.value = selected.id || "";
      candidateNameInput.value = selected.name || "";
      candidatePhoneInput.value = selected.phone || "";
      candidateEmailInput.value = selected.email || "";
      postingTitleInput.value = selected.posting_title || "";
    });
  }

  let formMap = {};
  let initialAssessmentValues = {};
  let initialFeedbackValues = {};
  let candidateRoundMap = {};

  try {
    candidateRoundMap = JSON.parse((roundMapNode && roundMapNode.textContent) || "{}");
  } catch (e) {
    candidateRoundMap = {};
  }

  try {
    formMap = JSON.parse((formMapNode && formMapNode.textContent) || "{}");
  } catch (e) {
    formMap = {};
  }

  try {
    initialAssessmentValues = JSON.parse((initialAssessmentValuesNode && initialAssessmentValuesNode.textContent) || "{}");
  } catch (e) {
    initialAssessmentValues = {};
  }

  try {
    initialFeedbackValues = JSON.parse((initialFeedbackValuesNode && initialFeedbackValuesNode.textContent) || "{}");
  } catch (e) {
    initialFeedbackValues = {};
  }

  const buildFieldControl = (field, prefix, valueMap) => {
    const wrapper = document.createElement("div");
    wrapper.className = "mb-2";

    const label = document.createElement("label");
    label.className = "form-label";
    label.textContent = field.label;
    wrapper.appendChild(label);

    const fieldName = `${prefix}${field.field_name}`;
    const fieldValue = valueMap[field.field_name] || "";
    let control;

    if (field.field_type === "textarea") {
      control = document.createElement("textarea");
      control.rows = 2;
      control.className = "form-control";
      control.value = fieldValue;
    } else if (field.field_type === "select") {
      control = document.createElement("select");
      control.className = "form-select reg-input";
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = "Select";
      control.appendChild(blank);
      (field.options || []).forEach((opt) => {
        const option = document.createElement("option");
        option.value = opt;
        option.textContent = opt;
        if (String(fieldValue) === String(opt)) option.selected = true;
        control.appendChild(option);
      });
    } else if (field.field_type === "radio" || field.field_type === "checkbox") {
      control = document.createElement("div");
      control.className = "d-flex flex-wrap gap-3 mt-1";
      (field.options || []).forEach((opt) => {
        const label = document.createElement("label");
        label.className = "form-check-label d-flex align-items-center gap-1";
        const input = document.createElement("input");
        input.className = "form-check-input mt-0";
        input.type = field.field_type;
        input.name = fieldName;
        input.value = opt;
        if (field.field_type === "checkbox") {
          const selectedValues = String(fieldValue || "").split(",").map((v) => v.trim());
          if (selectedValues.includes(String(opt))) input.checked = true;
        } else if (String(fieldValue) === String(opt)) {
          input.checked = true;
        }
        label.appendChild(input);
        const text = document.createElement("span");
        text.textContent = opt;
        label.appendChild(text);
        control.appendChild(label);
      });
    } else {
      control = document.createElement("input");
      control.className = "form-control reg-input";
      const htmlTypeMap = {
        number: "number",
        date: "date",
        email: "email",
        tel: "tel",
        url: "url",
        time: "time",
        datetime: "datetime-local",
        text: "text",
      };
      control.type = htmlTypeMap[field.field_type] || "text";
      control.value = fieldValue;
    }

    if (field.field_type !== "radio" && field.field_type !== "checkbox") {
      control.name = fieldName;
      control.required = Boolean(field.required);
    } else if (field.field_type === "radio" && field.required && control.firstChild) {
      const firstRadio = control.querySelector(`input[type="radio"][name="${fieldName}"]`);
      if (firstRadio) firstRadio.required = true;
    }
    wrapper.appendChild(control);
    return wrapper;
  };

  const renderDynamicFields = (selectEl, containerEl, prefix, valueMap) => {
    if (!selectEl || !containerEl) return;
    containerEl.innerHTML = "";
    const formId = String(selectEl.value || "").trim();
    const formCfg = formMap[formId];
    if (!formCfg || !Array.isArray(formCfg.fields) || !formCfg.fields.length) return;

    const title = document.createElement("div");
    title.className = "settings-subtitle mb-1";
    title.textContent = `${formCfg.name} Fields`;
    containerEl.appendChild(title);

    formCfg.fields.forEach((field) => {
      containerEl.appendChild(buildFieldControl(field, prefix, valueMap));
    });
  };

  if (assessmentFormSelect && assessmentDynamicFields) {
    const repaintAssessment = () => {
      renderDynamicFields(assessmentFormSelect, assessmentDynamicFields, "assessment_field_", initialAssessmentValues);
      initialAssessmentValues = {};
    };
    assessmentFormSelect.addEventListener("change", repaintAssessment);
    repaintAssessment();
  }

  if (feedbackFormSelect && feedbackDynamicFields) {
    const repaintFeedback = () => {
      renderDynamicFields(feedbackFormSelect, feedbackDynamicFields, "feedback_field_", initialFeedbackValues);
      initialFeedbackValues = {};
    };
    feedbackFormSelect.addEventListener("change", repaintFeedback);
    repaintFeedback();
  }

  const applyRoundFromCandidate = () => {
    if (!roundSelect || !candidateIdInput) return;
    if (roundSelect.value) return;
    const candidateId = String(candidateIdInput.value || "").trim();
    if (!candidateId) return;
    const round = candidateRoundMap[candidateId];
    if (round) {
      roundSelect.value = round;
    }
  };

  if (candidateIdInput) {
    candidateIdInput.addEventListener("change", applyRoundFromCandidate);
    candidateIdInput.addEventListener("blur", applyRoundFromCandidate);
  }
  applyRoundFromCandidate();
});
