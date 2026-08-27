import type {
  ChatEventHandler,
  SessionResponse,
  SessionState,
} from "./types";

const BASE = "/api";

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const body = await r.json();
      if (body?.detail) msg = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export async function createSession(): Promise<SessionResponse> {
  return json<SessionResponse>(await fetch(`${BASE}/session`, { method: "POST" }));
}

export async function getState(id: string): Promise<SessionResponse> {
  return json<SessionResponse>(await fetch(`${BASE}/session/${id}`));
}

export async function uploadExcel(id: string, file: File): Promise<SessionResponse & { warnings?: string[] }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${BASE}/session/${id}/upload`, { method: "POST", body: fd });
  return json(r);
}

export async function undoPlan(id: string): Promise<SessionResponse> {
  return json<SessionResponse>(await fetch(`${BASE}/session/${id}/undo`, { method: "POST" }));
}

export async function confirmPending(id: string): Promise<SessionResponse> {
  return json<SessionResponse>(await fetch(`${BASE}/pending/${id}/confirm`, { method: "POST" }));
}

export async function cancelPending(id: string): Promise<SessionResponse> {
  return json<SessionResponse>(await fetch(`${BASE}/pending/${id}/cancel`, { method: "POST" }));
}

/* SSE-поток чата через fetch + ReadableStream (POST, не EventSource). */
export async function streamChat(
  id: string,
  text: string,
  onEvent: ChatEventHandler,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${BASE}/chat/${id}/stream?text=${encodeURIComponent(text)}`, {
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`chat stream failed: ${r.status}`);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)));
      } catch {
        /* skip malformed */
      }
    }
  }
}

/** Разовое (не-потоковое) выполнение — fallback и для тестов. */
export async function chatOnce(id: string, text: string): Promise<{ events: unknown[] } | SessionState> {
  return json(await fetch(`${BASE}/chat/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  }));
}

export async function downloadExcel(id: string) {
  const r = await fetch(`${BASE}/export/xlsx?session_id=${id}`);
  if (!r.ok) throw new Error("export failed");
  const blob = await r.blob();
  const cd = r.headers.get("Content-Disposition") ?? "";
  const m = cd.match(/filename\*=UTF-8''([^;]+)/) ?? cd.match(/filename="?([^"]+)"?/);
  const name = m ? decodeURIComponent(m[1]) : "план.xlsx";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}