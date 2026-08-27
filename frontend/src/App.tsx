import { useCallback, useEffect, useRef, useState } from "react";
import type { SessionState, Task } from "./types";
import * as api from "./api";
import GanttChart from "./components/GanttChart";
import ChatPanel from "./components/ChatPanel";
import TaskModal from "./components/TaskModal";
import ConfirmModal from "./components/ConfirmModal";
import Toolbar from "./components/Toolbar";

export default function App() {
  const [sessionId, setSessionId] = useState<string>("");
  const [state, setState] = useState<SessionState | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Task | null>(null);
  const [pending, setPending] = useState<{ tool: string; reason: string; n: number } | null>(null);
  const startedRef = useRef(false);

  const applyState = useCallback((s: SessionState) => setState(s), []);
  const refresh = useCallback(
    async (id: string) => {
      const r = await api.getState(id);
      applyState(r.state);
    },
    [applyState],
  );

  // Инициализация: создаём сессию с закешированным стартовым планом (US-1).
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    (async () => {
      try {
        const s = await api.createSession();
        setSessionId(s.session_id);
        applyState(s.state);
      } finally {
        setLoading(false);
      }
    })();
  }, [applyState]);

  const onUpload = useCallback(
    async (file: File) => {
      const r = await api.uploadExcel(sessionId, file);
      applyState(r.state);
      if (r.warnings?.length) {
        alert("Предупреждения при загрузке:\n" + r.warnings.join("\n"));
      }
    },
    [sessionId, applyState],
  );

  const onChatEvent = useCallback(
    (ev: Parameters<Parameters<typeof api.streamChat>[2]>[0]) => {
      if (ev.type === "update" && ev.state) applyState(ev.state);
      if (ev.type === "pending") setPending({ tool: (ev as { reason: string }).reason as any, reason: (ev as any).reason, n: (ev as any).affected_count ?? 1 });
    },
    [applyState],
  );

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-[#737373]">
        Загрузка плана…
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col" style={{ padding: 20, gap: 16 }}>
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold m-0">Gantt AI Plan</h1>
          <div className="text-xs text-[#737373]">
            {state?.schema.source_filename || "Демо-план"} · {state?.schema.n_tasks} задач ·{" "}
            {state?.schema.total_days} дн. · критический путь:{" "}
            {state?.schema.critical_path.join(" → ") || "—"}
          </div>
        </div>
        <Toolbar
          busy={loading}
          onUpload={onUpload}
          onExport={() => api.downloadExcel(sessionId)}
          onUndo={async () => { const r = await api.undoPlan(sessionId); applyState(r.state); }}
          onRefresh={() => refresh(sessionId)}
        />
      </header>

      <main className="flex-1 min-h-0 grid gap-4" style={{ gridTemplateColumns: "1fr 380px" }}>
        <section className="card overflow-auto p-4">
          {state && (
            <GanttChart
              tasks={state.tasks}
              totalDays={state.schema.total_days}
              criticalPath={state.schema.critical_path}
              onSelect={setSelected}
            />
          )}
        </section>
        <section className="card flex flex-col min-h-0">
          <ChatPanel
            sessionId={sessionId}
            onEvent={onChatEvent}
          />
        </section>
      </main>

      {selected && <TaskModal task={selected} onClose={() => setSelected(null)} />}
      {pending && (
        <ConfirmModal
          reason={pending.reason}
          count={pending.n}
          onConfirm={async () => { await api.confirmPending(sessionId); setPending(null); refresh(sessionId); }}
          onCancel={async () => { await api.cancelPending(sessionId); setPending(null); refresh(sessionId); }}
        />
      )}
    </div>
  );
}