import { useLayoutEffect, useRef, useState } from "react";
import type { Task } from "../types";

interface Props {
  tasks: Task[];
  totalDays: number;
  criticalPath: string[];
  onSelect: (t: Task) => void;
}

type ViewMode = "week" | "weeks5" | "month";

const HEADER_H = 40; // высота шапки таблицы и шкалы (должны совпадать!)

const MONTH_NAMES = [
  "янв", "фев", "мар", "апр", "май", "июн",
  "июл", "авг", "сен", "окт", "ноя", "дек",
];

const MODES: { key: ViewMode; label: string }[] = [
  { key: "week", label: "1 неделя" },
  { key: "weeks5", label: "Недели · 5" },
  { key: "month", label: "Месяц" },
];

// px на день — стандартно для Ганта: фиксированная ширина дня.
const DAY_W = 22;

/** Дней в месяце: «нечётный» месяц → 31, «чётный» → 30 (месяц 1 = январь). */
function monthDays(month0: number): number {
  return month0 % 2 === 0 ? 31 : 30;
}

/** Разбивает последовательность дней на месяцы (для подписей шкалы). */
function monthLabels(totalDays: number) {
  const labels: { start: number; span: number; label: string }[] = [];
  let day = 1;
  let month0 = 0;
  let year = 1;
  while (day <= totalDays) {
    const span = Math.min(monthDays(month0), totalDays - day + 1);
    labels.push({ start: day, span, label: month0 === 0 && year > 1 ? `янв ${year}` : MONTH_NAMES[month0] });
    day += span;
    month0 = (month0 + 1) % 12;
    if (month0 === 0) year += 1;
  }
  return labels;
}

/** Окно видимой шкалы: {startDay, endDay} для выбранного режима. */
function windowFor(view: ViewMode, days: number, week: number) {
  if (view === "week") {
    const start = (week - 1) * 7 + 1;
    return { start, end: Math.min(week * 7, days), weeks: Math.ceil(days / 7) };
  }
  if (view === "weeks5") {
    const start = (week - 1) * 35 + 1;
    return { start, end: Math.min(week * 35, days), weeks: Math.ceil(days / 35) };
  }
  return { start: 1, end: days, weeks: 1 };
}

/** Гант: стандартная логика — бары по дням; переключатель вида окна. */
export default function GanttChart({ tasks, totalDays, criticalPath, onSelect }: Props) {
  const [view, setView] = useState<ViewMode>("month");
  const [page, setPage] = useState(1);
  const [availW, setAvailW] = useState(900);
  const trackRef = useRef<HTMLDivElement>(null);

  const days = Math.max(1, totalDays);
  const { start: wStart, end: wEnd, weeks: totalPages } = windowFor(view, days, page);
  const curPage = Math.min(Math.max(1, page), totalPages);

  const visibleDays = wEnd - wStart + 1;
  // Режимы-окна (1 неделя / 5 недель) растягиваем на всю ширину панели;
  // «Месяц» — стандартная шкала со скроллом (фиксированная ширина дня).
  const stretch = view !== "month";
  const barW = stretch ? Math.max(4, availW / visibleDays) : DAY_W;

  // Следим за шириной области шкалы, чтобы окна заполняли панель по горизонтали.
  useLayoutEffect(() => {
    if (!stretch) return;
    const el = trackRef.current;
    if (!el) return;
    const update = () => setAvailW(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [stretch, view, curPage]);

  const labels = view === "month" ? monthLabels(days) : null;

  const switchView = (m: ViewMode) => {
    setView(m);
    setPage(1);
  };

  return (
    <div className="min-w-full">
      {/* Переключатель вида + навигация по страницам */}
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-[#737373] font-medium">
          Показывать
          {view !== "month" && (
            <span className="ml-2 inline-flex items-center gap-1">
              <button
                type="button"
                onClick={() => setPage(curPage - 1)}
                disabled={curPage <= 1}
                className="w-6 h-6 text-[11px] rounded border border-[#e5e5e5] bg-white text-[#0a0a0a] cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                ‹
              </button>
              <span className="text-[11px] text-[#0a0a0a]">
                {view === "week" ? `Неделя ${curPage} из ${totalPages} · дни ${wStart}–${wEnd}` : `Стр. ${curPage} из ${totalPages} · недели ${((curPage - 1) * 5) + 1}–${Math.min(curPage * 5, Math.ceil(days / 7))}`}
              </span>
              <button
                type="button"
                onClick={() => setPage(curPage + 1)}
                disabled={curPage >= totalPages}
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
              onClick={() => switchView(m.key)}
              className={`px-2 py-1 text-[11px] rounded border cursor-pointer transition-colors ${
                view === m.key
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
        {/* ── ЛЕВАЯ КОЛОНКА ── */}
        <div className="border-r border-[#e5e5e5]">
          <div
            className="flex items-center px-3 text-xs text-[#737373] font-medium border-b border-[#e5e5e5]"
            style={{ height: HEADER_H }}
          >
            Задача
          </div>
          {tasks.map((t) => (
            <div key={t.id} className="h-[34px] flex items-center px-3 text-[12px] border-b border-[#e5e5e5]">
              <span className="cursor-pointer hover:underline truncate min-w-0" title={t.name} onClick={() => onSelect(t)}>
                {t.name}
              </span>
              <span className="ml-auto text-[#737373] shrink-0 pl-2">{t.assignee}</span>
            </div>
          ))}
        </div>

        {/* ── ШКАЛА + БАРЫ ── */}
        <div ref={trackRef} className="overflow-x-auto min-w-0">
          <div style={{ width: visibleDays * barW }} className="relative">
            {/* Шкала: месяцы (в режиме «Месяц») или дни (в 1-неделя/5-недель) */}
            <div className="flex items-end" style={{ height: HEADER_H }}>
              {view === "month"
                ? labels!.map((l, i) => (
                    <div
                      key={i}
                      className="flex items-end justify-start text-[10px] text-[#737373] border-l border-[#e5e5e5] pl-1 pb-0.5 overflow-hidden"
                      style={{ width: l.span * barW }}
                      title={`дни ${l.start}–${l.start + l.span - 1}`}
                    >
                      {l.label}
                    </div>
                  ))
                : Array.from({ length: visibleDays }).map((_, i) => {
                    const d = wStart + i;
                    return (
                      <div
                        key={d}
                        className="flex items-end justify-start text-[10px] text-[#737373] border-l border-[#e5e5e5] pl-1 pb-0.5 overflow-hidden"
                        style={{ width: barW }}
                        title={`день ${d}`}
                      >
                        {d}
                      </div>
                    );
                  })}
            </div>
            {/* Строки баров */}
            {tasks.map((t) => {
              const tStart = t.start_day ?? 1;
              const tEnd = t.end_day ?? tStart + (t.duration_days || 1) - 1;
              const dur = Math.max(1, t.duration_days);
              const isCrit = t.critical || criticalPath.includes(t.name);
              const long = dur >= 30;

              const left = (tStart - wStart) * barW;
              const width = Math.max(barW, dur * barW - 2);
              // Показываем только задачи, пересекающиеся с выбранным окном.
              const visible = tStart <= wEnd && tEnd >= wStart;
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
