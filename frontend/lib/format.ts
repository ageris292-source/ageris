// Shared number/date formatting. Missing values always render as "—": the UI
// never turns an unknown into a zero.

type Num = number | string | null | undefined;

const toNum = (v: Num): number | null => {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const compactFmt = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

/** ₹1,23,456.78 (Indian digit grouping). */
export function inr(v: Num, digits: 0 | 2 = 2): string {
  const n = toNum(v);
  if (n === null) return "—";
  return `₹${(digits === 0 ? inr0 : inr2).format(n)}`;
}

/** Plain number with Indian grouping. */
export function num(v: Num, digits = 2): string {
  const n = toNum(v);
  if (n === null) return "—";
  return n.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** ₹12.3L / ₹4.5Cr style compact rupees. */
export function inrCompact(v: Num): string {
  const n = toNum(v);
  if (n === null) return "—";
  const a = Math.abs(n);
  const sign = n < 0 ? "−" : "";
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(2)} L`;
  return `${sign}₹${inr0.format(a)}`;
}

export function compact(v: Num): string {
  const n = toNum(v);
  return n === null ? "—" : compactFmt.format(n);
}

/** Fraction → percent: 0.1234 → "12.3%". */
export function pct(v: Num, digits = 1): string {
  const n = toNum(v);
  return n === null ? "—" : `${(n * 100).toFixed(digits)}%`;
}

/** Signed percent for changes: "+1.24%" / "−0.50%". */
export function signedPct(v: Num, digits = 2): string {
  const n = toNum(v);
  if (n === null) return "—";
  const s = (Math.abs(n) * 100).toFixed(digits);
  return n > 0 ? `+${s}%` : n < 0 ? `−${s}%` : `${s}%`;
}

export function signedInr(v: Num): string {
  const n = toNum(v);
  if (n === null) return "—";
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${inr(Math.abs(n))}`;
}

/** Tone class for a signed value; zero and unknown are neutral. */
export function toneOf(v: Num): string {
  const n = toNum(v);
  if (n === null || n === 0) return "text-muted";
  return n > 0 ? "text-pass" : "text-fail";
}

const IST: Intl.DateTimeFormatOptions = { timeZone: "Asia/Kolkata" };

export function istDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    ...IST,
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function istDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(iso + "T00:00:00+05:30") : new Date(iso);
  return d.toLocaleDateString("en-IN", { ...IST, day: "numeric", month: "short", year: "numeric" });
}

export function shortDate(iso: string): string {
  const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "2-digit" });
}

/** "3 min ago", "2 h ago", "5 d ago". */
export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`;
  return istDate(iso);
}

export const humanize = (s: string) => s.replaceAll("_", " ");

export function titleCase(s: string): string {
  return humanize(s)
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
