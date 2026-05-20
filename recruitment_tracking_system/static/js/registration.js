document.addEventListener("DOMContentLoaded", () => {
  const registrationForm = document.getElementById("candidateRegistrationForm");
  const personalSection = document.getElementById("personalSection");
  const educationSection = document.getElementById("educationSection");
  const toEducationBtn = document.getElementById("toEducationBtn");
  const backToPersonalBtn = document.getElementById("backToPersonalBtn");
  const toCandidateListBtn = document.getElementById("toCandidateListBtn");
  const resumeUploadInput = document.getElementById("resumeUploadInput");
  const resumeParseAlert = document.getElementById("resumeParseAlert");
  const fullNameInput = document.getElementById("candidateFullNameInput");
  const emailInput = document.getElementById("candidateEmailInput");
  const contactInput = document.getElementById("candidateContactInput");
  const socialMediaInput = document.getElementById("candidateSocialMediaInput");
  const educationLevelInput = document.getElementById("candidateEducationLevelInput");
  const degreeInput = document.getElementById("candidateDegreeInput");
  const instituteInput = document.getElementById("candidateInstituteInput");
  const yearInput = document.getElementById("candidateYearInput");
  const cgpaInput = document.getElementById("candidateCgpaInput");
  const certificationsInput = document.getElementById("candidateCertificationsInput");
  const skillsInput = document.getElementById("candidateSkillsInput");
  const experienceInput = document.getElementById("candidateExperienceInput");
  const employmentHistoryInput = document.getElementById("candidateEmploymentHistoryInput");
  const referencesInput = document.getElementById("candidateReferencesInput");
  const educationRecordsPreview = document.getElementById("educationRecordsPreview");
  const educationRecordsJsonInput = document.getElementById("educationRecordsJsonInput");

  if (!personalSection || !educationSection || !toEducationBtn || !backToPersonalBtn || !toCandidateListBtn) {
    return;
  }

  toEducationBtn.addEventListener("click", () => {
    personalSection.classList.add("d-none");
    educationSection.classList.remove("d-none");
  });

  backToPersonalBtn.addEventListener("click", () => {
    educationSection.classList.add("d-none");
    personalSection.classList.remove("d-none");
  });

  if (!registrationForm || !resumeUploadInput || !resumeParseAlert) {
    return;
  }

  const parseResumeUrl = registrationForm.dataset.parseResumeUrl;
  const csrfInput = registrationForm.querySelector("input[name='csrfmiddlewaretoken']");
  const csrfToken = csrfInput ? csrfInput.value : "";

  const showResumeParseMessage = (type, message) => {
    resumeParseAlert.className = `alert py-2 mt-2 mb-0 alert-${type}`;
    resumeParseAlert.textContent = message;
    resumeParseAlert.classList.remove("d-none");
  };

  const applyFieldValue = (input, value, force = false) => {
    if (!input || !value) return;
    if (force || !String(input.value || "").trim()) {
      input.value = value;
    }
  };

  const applyEducationIfMatch = (selectInput, value) => {
    if (!selectInput || !value || String(selectInput.value || "").trim()) return;
    const normalized = String(value).trim().toLowerCase();
    const aliases = {
      be: ["be", "b.e", "bachelor of engineering", "engineering"],
      btech: ["btech", "b.tech", "bachelor of technology"],
      me: ["me", "m.e", "master of engineering"],
      mtech: ["mtech", "m.tech", "master of technology"],
      bca: ["bca", "bachelor of computer applications"],
      mca: ["mca", "master of computer applications"],
      bsc: ["bsc", "b.sc", "bachelor of science"],
      msc: ["msc", "m.sc", "master of science"],
      mba: ["mba", "master of business administration"],
      phd: ["phd", "ph.d", "doctorate"],
      diploma: ["diploma"],
      graduate: ["graduate", "bachelors", "bachelor"],
      post_graduate: ["post graduate", "postgraduate", "masters", "master"],
    };
    const normalizedNoPunct = normalized.replace(/[^a-z0-9 ]/g, "").trim();
    let candidates = [normalized, normalizedNoPunct];
    Object.keys(aliases).forEach((key) => {
      if (aliases[key].includes(normalized) || aliases[key].includes(normalizedNoPunct)) {
        candidates = candidates.concat(aliases[key]);
      }
    });
    candidates = Array.from(new Set(candidates.filter(Boolean)));

    for (const option of selectInput.options) {
      const optionValue = String(option.value || "").trim().toLowerCase();
      const optionText = String(option.textContent || "").trim().toLowerCase();
      const optionValueNoPunct = optionValue.replace(/[^a-z0-9 ]/g, "").trim();
      const optionTextNoPunct = optionText.replace(/[^a-z0-9 ]/g, "").trim();
      for (const candidate of candidates) {
        if (
          optionValue === candidate ||
          optionText === candidate ||
          optionValueNoPunct === candidate ||
          optionTextNoPunct === candidate
        ) {
          selectInput.value = option.value;
          return;
        }
      }
    }

    if (selectInput.options.length <= 1) {
      const newOpt = document.createElement("option");
      newOpt.value = value;
      newOpt.textContent = value;
      selectInput.appendChild(newOpt);
      selectInput.value = value;
    }
  };

  const renderEducationRecords = (records) => {
    if (!educationRecordsPreview || !educationRecordsJsonInput) return;
    if (!Array.isArray(records) || records.length === 0) {
      educationRecordsJsonInput.value = "";
      educationRecordsPreview.innerHTML = "<span class='text-muted'>No education records parsed yet.</span>";
      return;
    }
    educationRecordsJsonInput.value = JSON.stringify(records);
    const escapeHtml = (value) =>
      String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#39;");
    const rows = records
      .map((item) => {
        const level = escapeHtml(item.level || "-");
        const course = escapeHtml(item.course || "");
        const institute = escapeHtml(item.institute || "");
        const board = escapeHtml(item.board_university || "");
        const year = escapeHtml(item.year_of_passing || "");
        const score = escapeHtml(item.score || "");
        return `<div style="padding:6px 0;border-bottom:1px solid #e9ecef;">
          <div><strong>${level}</strong>${course ? " - " + course : ""}</div>
          <div class="text-muted" style="font-size:12px;">${institute}${board ? " | " + board : ""}${year ? " | " + year : ""}${score ? " | " + score : ""}</div>
        </div>`;
      })
      .join("");
    educationRecordsPreview.innerHTML = rows;
  };

  const parseResumeAndAutofill = () => {
    const file = resumeUploadInput.files && resumeUploadInput.files[0];
    if (!file) return;
    if (!parseResumeUrl) {
      showResumeParseMessage("warning", "Resume parser URL not configured.");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      showResumeParseMessage("danger", "Resume must be uploaded in PDF format only.");
      return;
    }

    const formData = new FormData();
    formData.append("resume_upload", file);
    if (csrfToken) {
      formData.append("csrfmiddlewaretoken", csrfToken);
    }

    showResumeParseMessage("info", "Parsing resume and auto-filling fields...");
    fetch(parseResumeUrl, {
      method: "POST",
      body: formData,
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.ok) {
          showResumeParseMessage("danger", data.message || "Unable to parse resume.");
          return;
        }
        const fields = data.fields || {};
        applyFieldValue(fullNameInput, fields.full_name, true);
        applyFieldValue(emailInput, fields.email, true);
        applyFieldValue(contactInput, fields.contact_number, true);
        applyFieldValue(socialMediaInput, fields.social_media_link, false);
        applyEducationIfMatch(educationLevelInput, fields.highest_education_level);
        applyFieldValue(degreeInput, fields.education_details || fields.degree_name, true);
        applyFieldValue(instituteInput, fields.institute_name);
        applyFieldValue(yearInput, fields.year_of_passing);
        applyFieldValue(cgpaInput, fields.percentage_cgpa);
        applyFieldValue(certificationsInput, fields.certifications, true);
        applyFieldValue(skillsInput, fields.skills, true);
        applyFieldValue(experienceInput, fields.experience, true);
        applyFieldValue(employmentHistoryInput, fields.employment_history, true);
        applyFieldValue(referencesInput, fields.references, true);
        renderEducationRecords(fields.education_records || []);
        showResumeParseMessage("success", data.message || "Resume parsed and fields auto-filled.");
      })
      .catch(() => {
        showResumeParseMessage("danger", "Unable to parse resume right now.");
      });
  };

  resumeUploadInput.addEventListener("change", parseResumeAndAutofill);

  if (educationRecordsJsonInput && educationRecordsJsonInput.value) {
    try {
      renderEducationRecords(JSON.parse(educationRecordsJsonInput.value));
    } catch (error) {
      renderEducationRecords([]);
    }
  } else {
    renderEducationRecords([]);
  }
});
