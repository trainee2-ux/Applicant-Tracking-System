document.addEventListener("DOMContentLoaded", () => {
  const dataNode = document.getElementById("panelScheduleData");
  if (!dataNode) return;

  let schedules = [];
  try {
    schedules = JSON.parse(dataNode.textContent || "[]");
  } catch (e) {
    schedules = [];
  }

  const monthLabel = document.getElementById("calendarMonthLabel");
  const grid = document.getElementById("interviewCalendarGrid");
  const prevBtn = document.getElementById("calendarPrevBtn");
  const nextBtn = document.getElementById("calendarNextBtn");
  const selectedDateLabel = document.getElementById("calendarSelectedDateLabel");
  const eventsList = document.getElementById("calendarEventsList");

  if (!monthLabel || !grid || !prevBtn || !nextBtn || !selectedDateLabel || !eventsList) return;

  const eventsByDate = {};
  const toDateKey = (rawValue) => {
    const value = String(rawValue || "").trim();
    if (!value) return "";
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "";
    const y = parsed.getFullYear();
    const m = String(parsed.getMonth() + 1).padStart(2, "0");
    const d = String(parsed.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  };

  schedules.forEach((item) => {
    const key = toDateKey(item.date);
    if (!key) return;
    if (!eventsByDate[key]) eventsByDate[key] = [];
    eventsByDate[key].push(item);
  });

  const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  let current = new Date();
  let activeDate = null;

  const formatDateLabel = (dateObj) =>
    dateObj.toLocaleDateString("en-US", { day: "2-digit", month: "short", year: "numeric" });

  const renderEvents = (dateKey) => {
    if (!dateKey) {
      selectedDateLabel.textContent = "Select a date";
      eventsList.textContent = "No schedules.";
      eventsList.classList.add("text-muted");
      return;
    }
    const list = eventsByDate[dateKey] || [];
    const dateObj = new Date(dateKey + "T00:00:00");
    selectedDateLabel.textContent = formatDateLabel(dateObj);
    if (!list.length) {
      eventsList.textContent = "No interviews scheduled.";
      eventsList.classList.add("text-muted");
      return;
    }
    eventsList.classList.remove("text-muted");
    eventsList.innerHTML = list
      .map(
        (row) => `
          <div class="interview-event-row">
            <strong>${row.candidate || "-"}</strong>
            <span>Time: ${row.time || "-"}</span>
            <span>Interviewers: ${row.interviewers || "-"}</span>
            <span>Mode: ${row.mode || "-"}</span>
          </div>
        `
      )
      .join("");
  };

  const renderCalendar = () => {
    const year = current.getFullYear();
    const month = current.getMonth();
    const now = new Date();
    const todayKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
      now.getDate()
    ).padStart(2, "0")}`;
    monthLabel.textContent = current.toLocaleDateString("en-US", { month: "long", year: "numeric" });

    const firstDay = new Date(year, month, 1);
    const startWeekday = firstDay.getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const daysInPrevMonth = new Date(year, month, 0).getDate();

    let html = "";
    weekdays.forEach((day) => {
      html += `<div class="interview-calendar-dow">${day}</div>`;
    });

    for (let i = 0; i < startWeekday; i += 1) {
      const dayNum = daysInPrevMonth - startWeekday + i + 1;
      html += `<button type="button" class="interview-calendar-day muted" disabled>${dayNum}</button>`;
    }

    for (let day = 1; day <= daysInMonth; day += 1) {
      const monthNum = String(month + 1).padStart(2, "0");
      const dayNum = String(day).padStart(2, "0");
      const key = `${year}-${monthNum}-${dayNum}`;
      const hasEvent = !!eventsByDate[key];
      const isActive = key === activeDate;
      const isToday = key === todayKey;
      html += `
        <button type="button" class="interview-calendar-day ${hasEvent ? "has-event" : ""} ${
        isActive ? "active" : ""
      } ${isToday ? "today" : ""}" data-date="${key}">
          ${day}
        </button>
      `;
    }

    grid.innerHTML = html;
    grid.querySelectorAll(".interview-calendar-day[data-date]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeDate = btn.dataset.date;
        renderCalendar();
        renderEvents(activeDate);
      });
    });
  };

  prevBtn.addEventListener("click", () => {
    current = new Date(current.getFullYear(), current.getMonth() - 1, 1);
    renderCalendar();
  });

  nextBtn.addEventListener("click", () => {
    current = new Date(current.getFullYear(), current.getMonth() + 1, 1);
    renderCalendar();
  });

  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(
    today.getDate()
  ).padStart(2, "0")}`;
  const allEventDates = Object.keys(eventsByDate).sort();
  const earliestEventDate = allEventDates[0];
  if (earliestEventDate) {
    if (eventsByDate[todayKey]) {
      current = new Date(today.getFullYear(), today.getMonth(), 1);
      activeDate = todayKey;
    } else {
      const eventDate = new Date(earliestEventDate + "T00:00:00");
      current = new Date(eventDate.getFullYear(), eventDate.getMonth(), 1);
      activeDate = earliestEventDate;
    }
  }

  renderCalendar();
  renderEvents(activeDate);
});
