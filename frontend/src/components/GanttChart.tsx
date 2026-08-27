import type { Task } from "../types";

interface Props {
  tasks: Task[];
  totalDays: number;
  criticalPath: string[];
  onSelect: (t: Task) => void;
}

const BAR_W = 22; // px на день
const HEADER_H = 40; // высота шапки таблицы и шкалы (должны совпадать!)

const MONTH_NAMES = [
  "янв", "фев", "мар", "апр", "май", "июн",
  "июл", "авг", "сен", "окт", "ноя", "дек",
];

/** Разбивает последовательность дней на периоды: {start_day, label, span} */
function buildPeriods(totalDays: number) {
  const periods: { start: number; label: string; span: number }[] = [];
  let day = 1;
  while (day <= totalDays) {
    const monthIdx = (day - 1) % 12; // 0 = январь условно
    const isYearStart = day === 1 || ((day - 1) % 12 === 0 && day > 1);
    const year = Math.floor((day - 1) / 12) + 1;
    // Заголовок: год (для нового года) или месяц
    const label = isYearStart ? `${year}` : MONTH_NAMES[monthIdx];
    // Продолжительность периода: до конца месяца (остаток до 12) или до конца шкалы
    const daysToMonthEnd = 12 - monthIdx;
    const span = Math.min(daysToMonthEnd, totalDays - day + 1);
    periods.push({ start: day, label, span });
    day += span;
  }
  return periods;
}

/** Гант: единая сетка — левая колонка задач + шкала (годы/месяцы) + бары по дням. */
export default function GanttChart({ tasks, totalDays, criticalPath, onSelect }: Props) {
  const days = Math.max(1, totalDays);
  const periods = buildPeriods(days);

  return (
    <div className="min-w-full">
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
          <div style={{ width: days * BAR_W + 8 }} className="relative">
            {/* Шкала: годы/месяцы */}
            <div className="flex items-end" style={{ height: HEADER_H }}>
              {periods.map((p, i) => (
                <div
                  key={i}
                  className="flex items-end justify-start text-[10px] text-[#737373] border-l border-[#e5e5e5] pl-1 pb-0.5 overflow-hidden"
                  style={{ width: p.span * BAR_W }}
                  title={`день ${p.start}`}
                >
                  {p.label}
                </div>
              ))}
            </div>
            {/* Строки баров */}
            {tasks.map((t) => {
              const start = t.start_day ? t.start_day - 1 : 0;
              const dur = Math.max(1, t.duration_days);
              const left = start * BAR_W;
              const width = Math.max(BAR_W, dur * BAR_W - 2);
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
