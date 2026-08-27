import { useRef } from "react";

interface Props {
  busy: boolean;
  onUpload: (file: File) => void;
  onExport: () => void;
  onUndo: () => void;
  onRefresh: () => void;
}

export default function Toolbar({ onUpload, onExport, onUndo, onRefresh }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  return (
    <div className="flex gap-2">
      <input
        ref={fileRef}
        type="file"
        accept=".xlsx,.csv"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onUpload(f);
          e.target.value = "";
        }}
      />
      <button className="btn" onClick={() => fileRef.current?.click()}>
        Загрузить Excel
      </button>
      <button className="btn" onClick={onExport}>
        Экспорт
      </button>
      <button className="btn" onClick={onUndo}>
        Отмена
      </button>
      <button className="btn" onClick={onRefresh}>
        Обновить
      </button>
    </div>
  );
}