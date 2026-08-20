import { useState } from "react";

// ─── Constants ───────────────────────────────────────────────────────────────
const OPEN_DAYS = [0, 1, 2, 3, 4]; // Sun=0, Mon=1, Tue=2, Wed=3, Thu=4
const BUSINESS_START = { h: 19, m: 30 }; // 7:30 PM
const BUSINESS_END = { h: 22, m: 0 };   // 10:00 PM
const TOTAL_MINUTES = 150; // 2.5 hours

const DURATIONS = [
  { label: "15 min", value: 15 },
  { label: "30 min", value: 30 },
  { label: "45 min", value: 45 },
  { label: "1 hr", value: 60 },
  { label: "1 hr 15 min", value: 75 },
  { label: "1 hr 30 min", value: 90 },
  { label: "1 hr 45 min", value: 105 },
  { label: "2 hr", value: 120 },
  { label: "2 hr 30 min", value: 150 },
];

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = [
  "January","February","March","April","May","June",
  "July","August","September","October","November","December"
];

// ─── Helpers ─────────────────────────────────────────────────────────────────
function toMinutes(h, m) { return h * 60 + m; }
const START_MIN = toMinutes(BUSINESS_START.h, BUSINESS_START.m);
const END_MIN   = toMinutes(BUSINESS_END.h, BUSINESS_END.m);

function getAvailableSlots(duration, bookedSlots = []) {
  const slots = [];
  let cursor = START_MIN;
  while (cursor + duration <= END_MIN) {
    const conflict = bookedSlots.some(
      (b) => cursor < b.end && cursor + duration > b.start
    );
    if (!conflict) {
      const hh = Math.floor(cursor / 60);
      const mm = cursor % 60;
      const period = hh >= 12 ? "PM" : "AM";
      const displayH = hh > 12 ? hh - 12 : hh;
      slots.push({
        minuteStart: cursor,
        label: `${displayH}:${mm.toString().padStart(2, "0")} ${period}`,
      });
    }
    cursor += 15;
  }
  return slots;
}

function getDaysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfMonth(year, month) {
  return new Date(year, month, 1).getDay();
}

function isOpenDay(date) {
  return OPEN_DAYS.includes(date.getDay());
}

function isPast(date) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return date < today;
}

// ─── Component ───────────────────────────────────────────────────────────────
export default function ElectrolysisScheduler() {
  const today = new Date();
  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth());
  const [selectedDate, setSelectedDate] = useState(null);
  const [selectedDuration, setSelectedDuration] = useState(null);
  const [selectedSlot, setSelectedSlot] = useState(null);

  // Placeholder booked slots — will come from Supabase in later phases
  const bookedSlots = [];

  const daysInMonth = getDaysInMonth(viewYear, viewMonth);
  const firstDay = getFirstDayOfMonth(viewYear, viewMonth);

  function prevMonth() {
    if (viewMonth === 0) { setViewYear(y => y - 1); setViewMonth(11); }
    else setViewMonth(m => m - 1);
    setSelectedDate(null); setSelectedDuration(null); setSelectedSlot(null);
  }

  function nextMonth() {
    if (viewMonth === 11) { setViewYear(y => y + 1); setViewMonth(0); }
    else setViewMonth(m => m + 1);
    setSelectedDate(null); setSelectedDuration(null); setSelectedSlot(null);
  }

  function selectDate(day) {
    const d = new Date(viewYear, viewMonth, day);
    if (!isOpenDay(d) || isPast(d)) return;
    setSelectedDate(d);
    setSelectedDuration(null);
    setSelectedSlot(null);
  }

  const availableSlots = selectedDate && selectedDuration
    ? getAvailableSlots(selectedDuration, bookedSlots)
    : [];

  const calendarCells = [];
  for (let i = 0; i < firstDay; i++) calendarCells.push(null);
  for (let d = 1; d <= daysInMonth; d++) calendarCells.push(d);

  return (
    <div style={styles.page}>
      {/* Header */}
      <header style={styles.header}>
        <div style={styles.logo}>✦ Smooth by Appointment</div>
        <div style={styles.tagline}>Book your session</div>
      </header>

      <main style={styles.main}>
        {/* Step 1 — Pick duration */}
        <section style={styles.card}>
          <div style={styles.stepLabel}>Step 1</div>
          <h2 style={styles.stepTitle}>How long is your session?</h2>
          <div style={styles.durationGrid}>
            {DURATIONS.map((d) => (
              <button
                key={d.value}
                onClick={() => { setSelectedDuration(d.value); setSelectedSlot(null); }}
                style={{
                  ...styles.durationBtn,
                  ...(selectedDuration === d.value ? styles.durationBtnActive : {}),
                }}
              >
                {d.label}
              </button>
            ))}
          </div>
        </section>

        {/* Step 2 — Pick a date */}
        <section style={{ ...styles.card, opacity: selectedDuration ? 1 : 0.45 }}>
          <div style={styles.stepLabel}>Step 2</div>
          <h2 style={styles.stepTitle}>Pick a date</h2>

          {/* Month nav */}
          <div style={styles.monthNav}>
            <button onClick={prevMonth} style={styles.navBtn}>‹</button>
            <span style={styles.monthLabel}>
              {MONTH_NAMES[viewMonth]} {viewYear}
            </span>
            <button onClick={nextMonth} style={styles.navBtn}>›</button>
          </div>

          {/* Day headers */}
          <div style={styles.calGrid}>
            {DAY_NAMES.map((n) => (
              <div key={n} style={styles.dayHeader}>{n}</div>
            ))}
            {calendarCells.map((day, idx) => {
              if (!day) return <div key={`empty-${idx}`} />;
              const d = new Date(viewYear, viewMonth, day);
              const open = isOpenDay(d) && !isPast(d);
              const isSelected =
                selectedDate &&
                selectedDate.getFullYear() === viewYear &&
                selectedDate.getMonth() === viewMonth &&
                selectedDate.getDate() === day;
              return (
                <button
                  key={day}
                  onClick={() => open && selectedDuration && selectDate(day)}
                  style={{
                    ...styles.dayCell,
                    ...(open && selectedDuration ? styles.dayCellOpen : styles.dayCellClosed),
                    ...(isSelected ? styles.dayCellSelected : {}),
                  }}
                  disabled={!open || !selectedDuration}
                  title={!open ? "Closed" : ""}
                >
                  {day}
                  {open && <span style={styles.dot} />}
                </button>
              );
            })}
          </div>
          <p style={styles.legend}>
            <span style={styles.dot} /> Open days: Sun – Thu &nbsp;|&nbsp; Fri & Sat closed
          </p>
        </section>

        {/* Step 3 — Pick a time */}
        <section style={{ ...styles.card, opacity: selectedDate ? 1 : 0.45 }}>
          <div style={styles.stepLabel}>Step 3</div>
          <h2 style={styles.stepTitle}>
            {selectedDate
              ? `Available times on ${MONTH_NAMES[selectedDate.getMonth()]} ${selectedDate.getDate()}`
              : "Choose a time"}
          </h2>

          {selectedDate && availableSlots.length === 0 && (
            <p style={styles.noSlots}>No available slots for this date.</p>
          )}

          <div style={styles.slotsGrid}>
            {availableSlots.map((slot) => (
              <button
                key={slot.minuteStart}
                onClick={() => setSelectedSlot(slot)}
                style={{
                  ...styles.slotBtn,
                  ...(selectedSlot?.minuteStart === slot.minuteStart
                    ? styles.slotBtnActive
                    : {}),
                }}
              >
                {slot.label}
              </button>
            ))}
          </div>
        </section>

        {/* Proceed CTA */}
        {selectedSlot && (
          <div style={styles.ctaWrapper}>
            <div style={styles.summary}>
              <strong>
                {MONTH_NAMES[selectedDate.getMonth()]} {selectedDate.getDate()},{" "}
                {selectedDate.getFullYear()}
              </strong>{" "}
              at <strong>{selectedSlot.label}</strong> ·{" "}
              {DURATIONS.find((d) => d.value === selectedDuration)?.label}
            </div>
            <button style={styles.ctaBtn}>
              Continue to booking →
            </button>
          </div>
        )}
      </main>
    </div>
  );
}

// ─── Styles ──────────────────────────────────────────────────────────────────
const GOLD = "#C9A96E";
const DARK = "#1A1A2E";
const CREAM = "#FAF7F2";
const MUTED = "#8A8A9A";
const WHITE = "#FFFFFF";
const ACCENT_BG = "#F3EDE3";

const styles = {
  page: {
    minHeight: "100vh",
    background: CREAM,
    fontFamily: "'Georgia', serif",
    color: DARK,
  },
  header: {
    background: DARK,
    color: WHITE,
    padding: "28px 40px 22px",
    borderBottom: `3px solid ${GOLD}`,
  },
  logo: {
    fontSize: "22px",
    letterSpacing: "0.08em",
    fontWeight: "bold",
    color: GOLD,
  },
  tagline: {
    fontSize: "13px",
    color: "#aaa",
    marginTop: "4px",
    fontFamily: "sans-serif",
    letterSpacing: "0.12em",
    textTransform: "uppercase",
  },
  main: {
    maxWidth: "680px",
    margin: "0 auto",
    padding: "40px 20px 80px",
    display: "flex",
    flexDirection: "column",
    gap: "28px",
  },
  card: {
    background: WHITE,
    borderRadius: "12px",
    padding: "28px 28px 24px",
    boxShadow: "0 2px 12px rgba(0,0,0,0.06)",
    transition: "opacity 0.3s",
  },
  stepLabel: {
    fontSize: "11px",
    fontFamily: "sans-serif",
    textTransform: "uppercase",
    letterSpacing: "0.15em",
    color: GOLD,
    marginBottom: "6px",
  },
  stepTitle: {
    margin: "0 0 20px",
    fontSize: "18px",
    fontWeight: "normal",
  },
  durationGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: "10px",
  },
  durationBtn: {
    padding: "10px 16px",
    border: `1.5px solid #ddd`,
    borderRadius: "8px",
    background: WHITE,
    fontFamily: "sans-serif",
    fontSize: "14px",
    cursor: "pointer",
    transition: "all 0.15s",
    color: DARK,
  },
  durationBtnActive: {
    borderColor: GOLD,
    background: ACCENT_BG,
    color: DARK,
    fontWeight: "bold",
  },
  monthNav: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: "16px",
  },
  navBtn: {
    background: "none",
    border: "none",
    fontSize: "22px",
    cursor: "pointer",
    color: DARK,
    padding: "4px 10px",
  },
  monthLabel: {
    fontSize: "16px",
    fontWeight: "bold",
    fontFamily: "sans-serif",
  },
  calGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(7, 1fr)",
    gap: "4px",
  },
  dayHeader: {
    textAlign: "center",
    fontSize: "12px",
    fontFamily: "sans-serif",
    color: MUTED,
    padding: "6px 0",
    fontWeight: "600",
  },
  dayCell: {
    position: "relative",
    textAlign: "center",
    padding: "10px 4px 14px",
    borderRadius: "8px",
    border: "none",
    fontFamily: "sans-serif",
    fontSize: "14px",
    cursor: "default",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: "3px",
  },
  dayCellOpen: {
    background: ACCENT_BG,
    color: DARK,
    cursor: "pointer",
    fontWeight: "500",
  },
  dayCellClosed: {
    background: "none",
    color: "#ccc",
  },
  dayCellSelected: {
    background: GOLD,
    color: WHITE,
    fontWeight: "bold",
  },
  dot: {
    display: "inline-block",
    width: "5px",
    height: "5px",
    borderRadius: "50%",
    background: GOLD,
  },
  legend: {
    marginTop: "14px",
    fontSize: "12px",
    fontFamily: "sans-serif",
    color: MUTED,
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  slotsGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: "10px",
  },
  slotBtn: {
    padding: "10px 18px",
    border: `1.5px solid #ddd`,
    borderRadius: "8px",
    background: WHITE,
    fontFamily: "sans-serif",
    fontSize: "14px",
    cursor: "pointer",
    transition: "all 0.15s",
    color: DARK,
  },
  slotBtnActive: {
    borderColor: GOLD,
    background: ACCENT_BG,
    fontWeight: "bold",
  },
  noSlots: {
    fontFamily: "sans-serif",
    color: MUTED,
    fontSize: "14px",
  },
  ctaWrapper: {
    background: DARK,
    borderRadius: "12px",
    padding: "24px 28px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: "16px",
  },
  summary: {
    color: "#ccc",
    fontFamily: "sans-serif",
    fontSize: "14px",
  },
  ctaBtn: {
    background: GOLD,
    color: DARK,
    border: "none",
    borderRadius: "8px",
    padding: "12px 24px",
    fontFamily: "sans-serif",
    fontWeight: "bold",
    fontSize: "14px",
    cursor: "pointer",
    letterSpacing: "0.04em",
  },
};
