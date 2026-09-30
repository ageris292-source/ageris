"use client";

import { CheckCircle2, Info, TriangleAlert, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState } from "react";

export type ToastTone = "success" | "error" | "info" | "warning";
interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  body?: string;
}

const Ctx = createContext<(t: Omit<Toast, "id">) => void>(() => {});

const STYLE: Record<ToastTone, { icon: React.ReactNode; cls: string }> = {
  success: { icon: <CheckCircle2 size={18} className="text-pass" aria-hidden />, cls: "border-l-pass" },
  error: { icon: <XCircle size={18} className="text-fail" aria-hidden />, cls: "border-l-fail" },
  warning: { icon: <TriangleAlert size={18} className="text-warn" aria-hidden />, cls: "border-l-warn" },
  info: { icon: <Info size={18} className="text-accent" aria-hidden />, cls: "border-l-accent" },
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const next = useRef(1);
  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (t: Omit<Toast, "id">) => {
      const id = next.current++;
      setItems((xs) => [...xs.slice(-3), { ...t, id }]);
      setTimeout(() => dismiss(id), t.tone === "error" ? 9000 : 5000);
    },
    [dismiss],
  );
  return (
    <Ctx.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-[80] flex w-[min(92vw,380px)] flex-col gap-2"
      >
        {items.map((t) => (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            className={`animate-in pointer-events-auto flex gap-3 rounded-lg border border-line border-l-4 bg-elevated p-3 shadow-[var(--shadow-pop)] ${STYLE[t.tone].cls}`}
          >
            <span className="mt-0.5 shrink-0">{STYLE[t.tone].icon}</span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{t.title}</p>
              {t.body && <p className="mt-0.5 break-words text-xs text-muted">{t.body}</p>}
            </div>
            <button
              onClick={() => dismiss(t.id)}
              className="shrink-0 rounded p-0.5 text-subtle hover:bg-hover hover:text-ink"
              aria-label="Dismiss notification"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
