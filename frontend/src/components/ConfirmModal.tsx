interface Props {
  reason: string;
  count: number;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Подтверждение массовой/деструктивной операции (policy → pending). */
export default function ConfirmModal({ reason, count, onConfirm, onCancel }: Props) {
  const label =
    reason === "destructive"
      ? "деструктивная операция"
      : reason === "mass_operation"
        ? "массовая операция"
        : "операция";
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="card p-6 w-[420px] max-w-[90vw] shadow-xl">
        <h2 className="text-base font-semibold m-0 mb-2">Подтвердите {label}</h2>
        <p className="text-[13px] text-[#737373] mb-5">
          Действие затрагивает <b>{count}</b> {plural(count, "задачу", "задачи", "задач")}. Это
          изменит план. Продолжить?
        </p>
        <div className="flex gap-2 justify-end">
          <button className="btn" onClick={onCancel}>
            Отмена
          </button>
          <button className="btn btn-danger" onClick={onConfirm}>
            Подтвердить
          </button>
        </div>
      </div>
    </div>
  );
}

function plural(n: number, one: string, few: string, many: string) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}