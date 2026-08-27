import { useState } from "react";
import type { Task } from "../types";

interface Props {
  tasks: Task[];
  totalDays: number;
  criticalPath: string[];
  onSelect: (t: Task) => void;
}

type ScaleMode = "day" | "week" | "month" | "quarter";

const HEADER_H = 40; // высота шапки таблицы и шкалы (должны совпадать!)

const MONTH_NAMES = [
  "янв", "фев", "мар", "апр", "май", "июн",
  "июл", "авг", "сен", "окт", "ноя", "дек",
];

const MODES: { key: ScaleMode; label: string }[] = [
  { key: "day", label: "День · 1 дн." },
  { key: "week", label: "Неделя · 7 дн." },
  { key: "month", label: "Месяц · 30–31 дн." },
  { key: "quarter", label: "Квартал · 90–92 дн." },
];

// px на день — меньше для крупных периодов, чтобы в экран влезало несколько.
const BAR_W: Record<ScaleMode, number> = { day: 22, week: 14, month: 9, quarter: 3 };

/** Дней в месяце: «нечётный» месяц → 31, «чётный» → 30 (месяц 1 = январь). */
function monthDays(month0: number): number {
  return month0 % 2 === 0 ? 31 : 30;
}

function periodSpan(mode: ScaleMode, month0: number): number {
  if (mode === "day") return 1;
  if (mode === "week") return 7;
  if (mode === "month") return monthDays(month0);
  // квартал = сумма трёх месяцев (в среднем 90–92)
  return monthDays(month0) + monthDays((month0 + 1) % 12) + monthDays((month0 + 2) % 12);
}

/** Разбивает последовательность дней на периоды выбранного масштаба. */
function buildPeriods(totalDays: number, mode: ScaleMode) {
  const periods: { start: number; label: string; span: number }[] = [];
  let day = 1;
  let month0 = 0; // 0 = январь (нечётный месяц 1)
  let year = 1;
  const step = mode === "quarter" ? 3 : 1;
  while (day <= totalDays) {
    const span = Math.min(periodSpan(mode, month0), totalDays - day + 1);
    let label: string;
    if (mode === "day") {
      label = `${day}`;
    } else if (mode === "week") {
      label = `нед ${Math.floor((day - 1) / 7) + 1}`;
    } else if (mode === "month") {
      label = month0 === 0 && year > 1 ? `янв ${year}` : MONTH_NAMES[month0];
    } else {
      label = `кв ${Math.ceil(day / 90)}`;
    }
    periods.push({ start: day, label, span });
    day += span;
    month0 = (month0 + step) % 12;
    if (month0 === 0) year += 1;
  }
  return periods;
}

/** Гант: единая сетка — левая колонка задач + шкала (годы/месяцы) + бары по дням. */
export default function GanttChart({ tasks, totalDays, criticalPath, onSelect }: Props) {
  const [scale, setScale] = useState<ScaleMode>("month");
  const days = Math.max(1, totalDays);
  const barW = BAR_W[scale];
  const periods = buildPeriods(days, scale);

  return (
    <div className="min-w-full">
      {/* Переключатель масштаба */}
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-[#737373] font-medium">Масштаб шкалы</div>
        <div className="flex gap-1">
          {MODES.map((m) => (
            <button
              key={m.key}
              type="button"
              onClick={() => setScale(m.key)}
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
        <div className="overflow-x-auto">
          <div style={{ width: days * barW + 8 }} className="relative">
            {/* Шкала: периоды выбранного масштаба */}
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
              const start = t.start_day ? t.start_day - 1 : 0;
              const dur = Math.max(1, t.duration_days);
              const left = start * barW;
              const width = Math.max(barW, dur * barW - 2);
              const isCrit = t.critical || criticalPath.includes(t.name);
              // Если задача длиннее месяца (30+ дней) — помечаем значком
              const long = dur >= 30;
              return (
                <div key={t.id} className="gantt-row relative" style={{ height: 34 }}>
                  <div
                    className={`gantt-bar ${isCrit ? "critical" : ""}`}
                    style={{ left, width, fontSize: width < 60 ? 9 : width < 110 ? 10 : 11 }}
                    onClick={() => onSelect(t)}
                    title={`${t.name} · дн. ${t.start_day ?? "?"}–${t.end_day ?? "?"}${long ? " · >1 мес" : ""}`}
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
