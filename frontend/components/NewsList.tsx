import type { NewsItem } from "@/lib/api";

const TONE = {
  positive: { icon: "▲", cls: "text-pass", word: "Positive" },
  negative: { icon: "▼", cls: "text-fail", word: "Negative" },
  neutral: { icon: "●", cls: "text-muted", word: "Neutral" },
} as const;

export function NewsList({ items }: { items: NewsItem[] | null }) {
  if (!items) return null;
  const shown = items.filter((n) => n.duplicate_of === null).slice(0, 12);
  if (!shown.length) {
    return <p className="mb-4 text-sm text-muted">No headlines stored yet. Use “Fetch news”.</p>;
  }
  return (
    <ul className="mb-4 divide-y divide-line text-sm">
      {shown.map((n) => {
        const t = n.sentiment_label ? TONE[n.sentiment_label] : null;
        return (
          <li key={n.id} className="flex gap-3 py-2">
            <span className={`w-20 shrink-0 text-xs ${t?.cls ?? "text-unknown"}`}>
              <span aria-hidden>{t?.icon ?? "?"} </span>
              {t?.word ?? "Unknown"}
            </span>
            <span className="flex-1">
              <a href={n.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                {n.title}
              </a>
              <span className="block text-xs text-muted">
                {n.publisher ?? "unknown source"} ·{" "}
                {n.published_at ? new Date(n.published_at).toLocaleDateString("en-IN") : "undated"} ·{" "}
                {n.event_type.replaceAll("_", " ")}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
