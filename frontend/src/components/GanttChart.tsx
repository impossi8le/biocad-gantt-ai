import { useLayoutEffect, useRef, useState } from "react";
import type { Task } from "../types";

interface Props {
  tasks: Task[];
  totalDays: number;
  criticalPath: string[];
  onSelect: (t: Task) => void;
}

type ScaleMode = "day" | "week" | "month";

const HEADER_H = 40; // высота шапки таблицы и шкалы (должны совпадать!)

const MONTH_NAMES = [
  "янв", "фев", "мар", "апр", "май", "июн",
  "июл", "авг", "сен", "окт", "ноя", "дек",
];

const MODES: { key: ScaleMode; label: string }[] = [
  { key: "day", label: "День · 1 дн." },
  { key: "week", label: "Неделя · 7 дн." },
  { key: "month", label: "Месяц · 30–31 дн." },
];

/** Дней в месяце: «нечётный» месяц → 31, «чётный» → 30 (месяц 1 = январь). */
function monthDays(month0: number): number {
  return month0 % 2 === 0 ? 31 : 30;
}

function periodSpan(mode: ScaleMode, month0: number): number {
  if (mode === "day") return 1;
  if (mode === "week") return 7;
  return monthDays(month0);
}

/** Полная шкала (для режимов «День» и «Месяц»). */
function buildPeriods(totalDays: number, mode: ScaleMode) {
  const periods: { start: number; label: string; span: number }[] = [];
  let day = 1;
  let month0 = 0; // 0 = январь (нечётный месяц 1)
  let year = 1;
  while (day <= totalDays) {
    const span = Math.min(periodSpan(mode, month0), totalDays - day + 1);
    let label: string;
    if (mode === "day") {
      label = `${day}`;
    } else {
      label = month0 === 0 && year > 1 ? `янв ${year}` : MONTH_NAMES[month0];
    }
    periods.push({ start: day, label, span });
    day += span;
    month0 = (month0 + 1) % 12;
    if (month0 === 0) year += 1;
  }
  return periods;
}

/** Дни выбранной недели (для детального просмотра в режиме «Неделя»). */
function weekPeriods(totalDays: number, week: number) {
  const windowStart = (week - 1) * 7 + 1;
  const windowEnd = Math.min(week * 7, totalDays);
  const periods: { start: number; label: string; span: number }[] = [];
  for (let d = windowStart; d <= windowEnd; d++) {
    periods.push({ start: d, label: `${d}`, span: 1 });
  }
  return { periods, windowStart, windowEnd };
}

/** Гант: единая сетка — левая колонка задач + шкала + бары по дням. */
export default function GanttChart({ tasks, totalDays, criticalPath, onSelect }: Props) {
  const [scale, setScale] = useState<ScaleMode>("month");
  const [week, setWeek] = useState(1);
  const [availW, setAvailW] = useState(600);
  const trackRef = useRef<HTMLDivElement>(null);

  const days = Math.max(1, totalDays);
  const totalWeeks = Math.ceil(days / 7);
  const curWeek = Math.min(Math.max(1, week), totalWeeks);

  // Ширина области шкалы — следим, чтобы бары растягивались на всю панель.
  useLayoutEffect(() => {
    const el = trackRef.current;
    if (!el) return;
    const update = () => setAvailW(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [scale, curWeek]);

  const isWeekView = scale === "week";
  const { periods, windowStart, windowEnd } = isWeekView
    ? weekPeriods(days, curWeek)
    : { periods: buildPeriods(days, scale), windowStart: 1, windowEnd: days };

  // Адаптивная ширина дня: вся доступная панель ÷ видимые дни → без «зажатия»/скролла.
  const visibleDays = isWeekView ? windowEnd - windowStart + 1 : days;
  const barW = Math.max(3, availW / Math.max(1, visibleDays));

  const switchMode = (m: ScaleMode) => {
    setScale(m);
    if (m === "week") setWeek(1);
  };

  return (
    <div className="min-w-full">
      {/* Переключатель масштаба + навигация по неделям */}
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-[#737373] font-medium">
          Масштаб шкалы
          {isWeekView && (
            <span className="ml-2 inline-flex items-center gap-1">
              <button
                type="button"
                onClick={() => setWeek(curWeek - 1)}
                disabled={curWeek <= 1}
                className="w-6 h-6 text-[11px] rounded border border-[#e5e5e5] bg-white text-[#0a0a0a] cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                ‹
              </button>
              <span className="text-[11px] text-[#0a0a0a]">
                Неделя {curWeek} из {totalWeeks} · дни {windowStart}–{windowEnd}
              </span>
              <button
                type="button"
                onClick={() => setWeek(curWeek + 1)}
                disabled={curWeek >= totalWeeks}
                className="w-6 h-6 text-[11px] rounded border border-[#e5e5e5] bg-white text-[#0a0a0a] cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                ›
              </button>
            </span>
          )}
        </div>
        <div className="flex gap-1">
          {MODES.map((m) => (
            <button
              key={m.key}
              type="button"
              onClick={() => switchMode(m.key)}
              className={`px-2 py-1 text-[11px] rounded border cursor-pointer transition-colors ${
                scale === m.key
                  ? "bg-[#0a0a0a] text-white border-[#0a0a0a]"
                  : "bg-white text-[#0a0a0a] border-[#e5e5e5] hover:bg-[#ececec]"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: `${260}px 1fr` }}>
        {/* ── ЛЕВАЯ КОЛОНКА: заголовок + задачи ── */}
        <div className="border-r border-[#e5e5e5]">
          <div
            className="flex items-center px-3 text-xs text-[#737373] font-medium border-b border-[#e5e5e5]"
            style={{ height: HEADER_H }}
          >
            Задача
          </div>
          {tasks.map((t) => (
            <div
              key={t.id}
              className="h-[34px] flex items-center px-3 text-[12px] border-b border-[#e5e5e5]"
            >
              <span
                className="cursor-pointer hover:underline truncate min-w-0"
                title={t.name}
                onClick={() => onSelect(t)}
              >
                {t.name}
              </span>
              <span className="ml-auto text-[#737373] shrink-0 pl-2">{t.assignee}</span>
            </div>
          ))}
        </div>

        {/* ── ОБЛАСТЬ ШКАЛЫ + БАРЫ ── */}
        <div ref={trackRef} className="overflow-x-auto min-w-0">
          <div style={{ width: visibleDays * barW }} className="relative">
            {/* Шкала */}
            <div className="flex items-end" style={{ height: HEADER_H }}>
              {periods.map((p, i) => (
                <div
                  key={i}
                  className="flex items-end justify-start text-[10px] text-[#737373] border-l border-[#e5e5e5] pl-1 pb-0.5 overflow-hidden"
                  style={{ width: p.span * barW }}
                  title={p.span === 1 ? `день ${p.start}` : `дни ${p.start}–${p.start + p.span - 1}`}
                >
                  {p.label}
                </div>
              ))}
            </div>
            {/* Строки баров */}
            {tasks.map((t) => {
              const tStart = t.start_day ?? 1;
              const tEnd = t.end_day ?? tStart + (t.duration_days || 1) - 1;
              const dur = Math.max(1, t.duration_days);
              const isCrit = t.critical || criticalPath.includes(t.name);
              const long = dur >= 30;

              // Позиция относительно начала видимого окна.
              const left = Math.max(0, tStart - windowStart) * barW;
              const rightEdge = Math.min(tEnd, windowEnd) - windowStart + 1;
              const width = Math.max(barW, rightEdge * barW - 2);
              const visible = tEnd >= windowStart && tStart <= windowEnd;
              if (!visible) return null;

              return (
                <div key={t.id} className="gantt-row relative" style={{ height: 34 }}>
                  <div
                    className={`gantt-bar ${isCrit ? "critical" : ""}`}
                    style={{ left, width, fontSize: width < 60 ? 9 : width < 110 ? 10 : 11 }}
                    onClick={() => onSelect(t)}
                    title={`${t.name} · дн. ${tStart}–${tEnd}${long ? " · >1 мес" : ""}`}
                  >
                    <span className="gantt-bar-label">{t.name}</span>
                    {long && <span className="gantt-bar-badge" title="дольше месяца">↗</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div className="text-xs text-[#737373] mt-3 flex gap-4">
        <span className="inline-flex items-center gap-1"><span className="inline-block w-3 h-2 rounded bg-[#e7000b]" /> критический путь</span>
        <span className="inline-flex items-center gap-1"><span className="inline-block w-3 h-2 rounded bg-[#0a0a0a]" /> обычная задача</span>
        <span className="inline-flex items-center gap-1"><span className="inline-block w-3 h-2 rounded bg-[#0a0a0a] relative"><span className="absolute -top-1 right-0 text-[8px] text-[#fff]">↗</span></span> дольше месяца</span>
      </div>
    </div>
  );
}
