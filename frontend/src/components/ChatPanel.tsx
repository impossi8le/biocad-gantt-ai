import { useEffect, useRef, useState } from "react";
import * as api from "../api";
import type { ChatEventHandler } from "../types";

interface Props {
  sessionId: string;
  onEvent: ChatEventHandler;
}

export default function ChatPanel({ sessionId, onEvent }: Props) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const autoResize = () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const next = Math.min(ta.scrollHeight, 180);
    ta.style.height = `${next}px`;
  };

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setBusy(true);
    // временное окно ассистента
    setMessages((m) => [...m, { role: "assistant", text: "" }]);
    const userSay = text;
    try {
      await api.streamChat(sessionId, userSay, (ev) => {
        if (ev.type === "delta") {
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1].text += ev.text;
            return copy;
          });
        }
        if (ev.type === "done") setBusy(false);
        if (ev.type === "update" && ev.state) onEvent(ev);
        if (ev.type === "pending") onEvent(ev);
      });
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: `Ошибка: ${(e as Error).message}` }]);
      setBusy(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="flex flex-col min-h-0 flex-1">
      <div className="px-4 py-3 border-b border-[#e5e5e5] text-sm font-medium">
        Редактирование плана
        {busy && <span className="ml-2 text-xs text-[#737373]">набирает…</span>}
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
        <div className="text-xs text-[#737373]">
          Примеры: «перенеси Разработку бэкенда на 2 дня позже», «сделай Дизайн
          предшественником Интеграции», «добавь задачу Документация дизайнеру»,
          «удали задачу Релиз», «передай исполнителя на Анну».
        </div>
        {messages.map((m, i) => (
          <div
            key={i}
            className={`px-3 py-2 rounded-[12px] text-[13px] max-w-[85%] whitespace-pre-wrap ${
              m.role === "user"
                ? "self-end bg-[#0a0a0a] text-white"
                : "self-start bg-[#f5f5f5] border border-[#e5e5e5]"
            }`}
          >
            {m.text || (busy ? "…" : "")}
          </div>
        ))}
      </div>
      <div className="p-3 border-t border-[#e5e5e5] flex gap-2 items-end">
        <textarea
          ref={textareaRef}
          className="input flex-1 resize-none overflow-y-auto min-h-[38px] max-h-[180px] leading-[1.4] py-[9px]"
          placeholder="Опишите изменение…"
          value={input}
          rows={1}
          onChange={(e) => {
            setInput(e.target.value);
            autoResize();
          }}
          onKeyDown={handleKeyDown}
        />
        <button className="btn btn-accent shrink-0" onClick={send} disabled={busy}>
          Отправить
        </button>
      </div>
    </div>
  );
}