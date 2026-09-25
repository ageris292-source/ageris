"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/stocks", label: "Stocks" },
];

export function Nav({
  mode,
  email,
  role,
  onSignOut,
}: {
  mode?: string;
  email?: string;
  role?: string;
  onSignOut: () => void;
}) {
  const path = usePathname();
  return (
    <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-2xl font-semibold">Aegis</Link>
          {mode && (
            <span className="rounded border border-line px-2 py-0.5 font-mono text-xs uppercase">
              {mode} mode
            </span>
          )}
        </div>
        <nav className="flex gap-4 text-sm">
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={active ? "text-ink" : "text-muted hover:text-ink"}
                aria-current={active ? "page" : undefined}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex items-center gap-4 text-sm text-muted">
        {email && <span>{email} · {role}</span>}
        <button className="underline" onClick={onSignOut}>Sign out</button>
      </div>
    </header>
  );
}
