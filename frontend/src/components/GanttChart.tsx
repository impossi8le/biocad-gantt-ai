import type { Task } from "../types";

interface Props {
  tasks: Task[];
  totalDays: number;
  criticalPath: string[];
  onSelect: (t: Task) => void;
}

/** Диаграмма Ганта: левая колонка список задач, правая — бары по дням. */
export default function GanttChart({ tasks, totalDays, criticalPath, onSelect }: Props) {
  const days = Math.max(1, totalDays);
  const barW = 22; // px на день

  return (
    <div className="min-w-full">
      <div className="flex">
        {/* левая колонка */}
        <div style={{ width: 260, minWidth: 260 }} className="pr-3">
          <div className="h-8 flex items-center text-xs text-[#737373] font-medium">
            Задача
          </div>
          {tasks.map((t) => (
            <div key={t.id} className="h-[34px] flex items-center text-[12px] border-b border-[#e5e5e5] truncate">
              <span
                className="cursor-pointer hover:underline truncate"
                title={t.name}
                onClick={() => onSelect(t)}
              >
                {t.name}
              </span>
              <span className="ml-auto text-[#737373] shrink-0">{t.assignee}</span>
            </div>
          ))}
        </div>
        {/* шкала + бары */}
        <div className="flex-1 overflow-x-auto">
          <div style={{ width: days * barW + 8 }} className="relative">
            <div className="h-10 flex items-end text-[10px] text-[#737373]">
              {Array.from({ length: days }).map((_, i) => (
                <div key={i} style={{ width: barW }} className="text-left border-l border-[#e5e5e5] pl-0.5">
                  {i + 1}
                </div>
              ))}
            </div>
            {tasks.map((t) => {
              const start = t.start_day ? t.start_day - 1 : 0;
              const dur = Math.max(1, t.duration_days);
              const left = start * barW;
              const width = Math.max(barW, dur * barW - 2);
              const isCrit = t.critical || criticalPath.includes(t.name);
              return (
                <div key={t.id} className="gantt-row relative" style={{ height: 34 }}>
                  <div
                    className={`gantt-bar ${isCrit ? "critical" : ""}`}
                    style={{ left, width, fontSize: width < 60 ? 9 : width < 110 ? 10 : 11 }}
                    onClick={() => onSelect(t)}
                    title={`${t.name} · дн. ${t.start_day ?? "?"}–${t.end_day ?? "?"}`}
                  >
                    <span className="gantt-bar-label">{t.name}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div className="text-xs text-[#737373] mt-3">
        <span className="mr-4"><span className="inline-block w-3 h-2 rounded bg-[#e7000b] align-middle mr-1" /> критический путь</span>
        <span><span className="inline-block w-3 h-2 rounded bg-[#0a0a0a] align-middle mr-1" /> обычная задача</span>
      </div>
    </div>
  );
}