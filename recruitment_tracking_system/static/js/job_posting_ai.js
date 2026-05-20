document.addEventListener("DOMContentLoaded", function () {
  const titleInput = document.getElementById("postingTitleInput");
  const suggestButtons = Array.from(document.querySelectorAll(".gemini-field-btn"));
  const msg = document.getElementById("geminiSuggestMsg");
  const descriptionInput = document.getElementById("descriptionInput");
  const requirementsInput = document.getElementById("requirementsInput");
  const benefitsInput = document.getElementById("benefitsInput");
  const industryInput = document.querySelector('[name="industry"]');
  const experienceInput = document.querySelector('[name="work_experience"]');
  const requiredSkillsInput = document.querySelector('[name="required_skills"]');
  const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');

  if (!titleInput || !descriptionInput || !requirementsInput || !benefitsInput || !csrfInput || !suggestButtons.length) {
    return;
  }

  const setMsg = function (text, colorClass) {
    if (!msg) return;
    msg.classList.remove("text-muted", "text-danger", "text-success");
    msg.classList.add(colorClass || "text-muted");
    msg.textContent = text || "";
  };

  const selectedSkills = function () {
    if (!requiredSkillsInput || !requiredSkillsInput.options) return "";
    const chosen = Array.from(requiredSkillsInput.options)
      .filter(function (opt) {
        return opt.selected;
      })
      .map(function (opt) {
        return (opt.textContent || "").trim();
      })
      .filter(Boolean);
    return chosen.join(", ");
  };

  const fieldInputByName = function (fieldName) {
    if (fieldName === "description") return descriptionInput;
    if (fieldName === "requirements") return requirementsInput;
    if (fieldName === "benefits") return benefitsInput;
    return null;
  };

  const suggestContent = function (targetField, triggerBtn) {
    const postingTitle = (titleInput.value || "").trim();
    if (!postingTitle) {
      setMsg("Enter posting title first.", "text-danger");
      titleInput.focus();
      return;
    }

    const targetInput = fieldInputByName(targetField);
    if (!targetInput) {
      setMsg("Invalid target field.", "text-danger");
      return;
    }
    if ((targetInput.value || "").trim() && !window.confirm("Existing text will be replaced. Continue?")) return;

    triggerBtn.disabled = true;
    setMsg("Generating " + targetField + "...", "text-muted");

    const formData = new FormData();
    formData.append("csrfmiddlewaretoken", csrfInput.value);
    formData.append("posting_title", postingTitle);
    formData.append("target_field", targetField);
    formData.append("industry", industryInput ? industryInput.value : "");
    formData.append("work_experience", experienceInput ? experienceInput.value : "");
    formData.append("required_skills", selectedSkills());

    fetch("/job-requisition/posting-form/suggest-content/", {
      method: "POST",
      body: formData,
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          throw new Error((result.data && result.data.message) || "Suggestion failed.");
        }
        const fields = result.data.fields || {};
        targetInput.value = fields[targetField] || targetInput.value || "";
        setMsg("Suggestion applied for " + targetField + ".", "text-success");
      })
      .catch(function (err) {
        setMsg(err.message || "Unable to generate suggestions.", "text-danger");
      })
      .finally(function () {
        triggerBtn.disabled = false;
      });
  };

  suggestButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      const targetField = (btn.getAttribute("data-target-field") || "").trim();
      suggestContent(targetField, btn);
    });
  });
});
