import { ExternalLink, Minus, TrendingDown, TrendingUp, CircleHelp } from "lucide-react";
import type { NewsItem } from "@/lib/api";
import { Badge, type Tone } from "@/components/ui/core";
import { ago, humanize } from "@/lib/format";

const TONE: Record<string, { icon: React.ReactNode; tone: Tone; word: string }> = {
  positive: { icon: <TrendingUp size={12} aria-hidden />, tone: "pass", word: "Positive" },
  negative: { icon: <TrendingDown size={12} aria-hidden />, tone: "fail", word: "Negative" },
  neutral: { icon: <Minus size={12} aria-hidden />, tone: "neutral", word: "Neutral" },
};

export function NewsList({ items }: { items: NewsItem[] | null }) {
  if (!items) return null;
  const shown = items.filter((n) => n.duplicate_of === null).slice(0, 15);
  if (!shown.length) return <p className="text-sm text-muted">No headlines stored yet. Use “Fetch news”.</p>;
  return (
    <ul className="-mx-2 divide-y divide-line">
      {shown.map((n) => {
        const t = n.sentiment_label ? TONE[n.sentiment_label] : null;
        return (
          <li key={n.id}>
            <a href={n.url} target="_blank" rel="noopener noreferrer" className="group flex gap-3 rounded-lg px-2 py-3 hover:bg-hover">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium leading-snug group-hover:underline">{n.title}</p>
                <p className="mt-1 text-xs text-muted">
                  {n.publisher ?? "Unknown source"} · {ago(n.published_at)} · {humanize(n.event_type)}
                </p>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-2">
                {t ? (
                  <Badge tone={t.tone} icon={t.icon}>{t.word}</Badge>
                ) : (
                  <Badge icon={<CircleHelp size={12} aria-hidden />} title="Sentiment model unavailable">Unscored</Badge>
                )}
                <ExternalLink size={13} className="text-subtle" aria-hidden />
              </div>
            </a>
          </li>
        );
      })}
    </ul>
  );
}
