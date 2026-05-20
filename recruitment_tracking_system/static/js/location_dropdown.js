document.addEventListener("DOMContentLoaded", () => {
  const countrySelect = document.getElementById("countrySelect");
  const stateSelect = document.getElementById("stateSelect");
  const selectedCountry = (countrySelect && countrySelect.dataset.selectedCountry) || "";
  const selectedState = (stateSelect && stateSelect.dataset.selectedState) || "";

  if (!countrySelect || !stateSelect) {
    return;
  }

  const fallbackData = [
    { name: "India", states: ["Maharashtra", "Karnataka", "Delhi", "Tamil Nadu", "Gujarat"] },
    { name: "United States", states: ["California", "Texas", "Florida", "New York", "Washington"] },
    { name: "United Kingdom", states: ["England", "Scotland", "Wales", "Northern Ireland"] },
  ];

  const setOptions = (selectEl, values, placeholder) => {
    selectEl.innerHTML = "";
    const defaultOption = document.createElement("option");
    defaultOption.value = "";
    defaultOption.textContent = placeholder;
    selectEl.appendChild(defaultOption);

    values.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      selectEl.appendChild(option);
    });
  };

  const normalizeCountry = (value) => String(value || "").trim().toLowerCase();
  const setSelectValue = (selectEl, value) => {
    if (!selectEl || !value) {
      return;
    }
    const target = String(value).trim().toLowerCase();
    const option = Array.from(selectEl.options).find(
      (item) => String(item.value || "").trim().toLowerCase() === target
    );
    if (option) {
      selectEl.value = option.value;
    }
  };

  const extractStates = (country) => {
    const rawStates = country && Array.isArray(country.states) ? country.states : [];
    return rawStates
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item === "object") {
          return item.name || item.state_name || item.state || "";
        }
        return "";
      })
      .filter(Boolean);
  };

  const applyCountries = (countriesData) => {
    const countryNames = countriesData.map((c) => c.name).sort((a, b) => a.localeCompare(b));
    setOptions(countrySelect, countryNames, "Select Country");

    const updateStateOptions = (selected) => {
      const selectedNorm = normalizeCountry(selected);
      const match =
        countriesData.find((c) => normalizeCountry(c.name) === selectedNorm) ||
        countriesData.find((c) => normalizeCountry(c.name).includes(selectedNorm)) ||
        countriesData.find((c) => selectedNorm.includes(normalizeCountry(c.name)));
      const states = extractStates(match);

      setOptions(stateSelect, states, "Select State");
      stateSelect.disabled = states.length === 0;
      setSelectValue(stateSelect, selectedState);
    };

    if (selectedCountry) {
      setSelectValue(countrySelect, selectedCountry);
    } else if (countryNames.length > 0) {
      countrySelect.value = countryNames[0];
    }
    updateStateOptions(countrySelect.value);

    countrySelect.addEventListener("change", () => {
      updateStateOptions(countrySelect.value);
    });
  };

  const fetchCountryStateData = async () => {
    try {
      const response = await fetch("https://countriesnow.space/api/v0.1/countries/states", {
        method: "GET",
      });
      if (!response.ok) {
        throw new Error("Failed to fetch country/state data");
      }
      const payload = await response.json();
      const list = payload && payload.data ? payload.data : [];
      if (!Array.isArray(list) || list.length === 0) {
        throw new Error("Empty country/state data");
      }
      applyCountries(list);
    } catch (_err) {
      applyCountries(fallbackData);
    }
  };

  fetchCountryStateData();
});
