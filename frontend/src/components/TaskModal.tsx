import type { Task } from "../types";

interface Props {
  task: Task;
  onClose: () => void;
}

/** Модалка с деталями задачи (US-9): состав — наше решение. */
export default function TaskModal({ task, onClose }: Props) {
  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="card p-6 w-[420px] max-w-[90vw] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-3">
          <h2 className="text-base font-semibold m-0">{task.name}</h2>
          <button className="btn bg-transparent border-0 text-[#737373] px-2" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="flex flex-col gap-3 text-[13px]">
          <div>
            <div className="text-xs text-[#737373] uppercase mb-0.5">Описание</div>
            <div>{task.description || "—"}</div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-[#737373] uppercase mb-0.5">Исполнитель</div>
              <div>{task.assignee || "—"}</div>
            </div>
            <div>
              <div className="text-xs text-[#737373] uppercase mb-0.5">Длительность</div>
              <div>{task.duration_days} дн.</div>
            </div>
          </div>
          <div>
            <div className="text-xs text-[#737373] uppercase mb-0.5">Предшественники</div>
            <div>{task.predecessors.length ? task.predecessors.join(", ") : "—"}</div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-[#737373] uppercase mb-0.5">Начало</div>
              <div>день {task.start_day ?? "—"}</div>
            </div>
            <div>
              <div className="text-xs text-[#737373] uppercase mb-0.5">Конец</div>
              <div>день {task.end_day ?? "—"}</div>
            </div>
          </div>
          <div>
            <span
              className={`inline-block px-2 py-0.5 rounded text-xs ${
                task.critical ? "bg-[#e7000b] text-white" : "bg-[#f5f5f5] text-[#737373] border border-[#e5e5e5]"
              }`}
            >
              {task.critical ? "Критический путь" : "Не критическая"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}