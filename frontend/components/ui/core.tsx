"use client";

import Link from "next/link";
import { Loader2 } from "lucide-react";
import { forwardRef, useId } from "react";

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

/* ------------------------------------------------------------------ Button */

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
type Size = "sm" | "md" | "lg";

const VARIANT: Record<Variant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-strong shadow-sm",
  secondary: "border border-line bg-panel text-ink hover:bg-hover shadow-sm",
  ghost: "text-muted hover:bg-hover hover:text-ink",
  danger: "bg-fail text-white hover:opacity-90 shadow-sm",
  success: "bg-pass text-white hover:opacity-90 shadow-sm",
};
const SIZE: Record<Size, string> = {
  sm: "h-9 px-3 text-xs gap-1.5 sm:h-8 sm:px-2.5",
  md: "h-11 px-4 text-sm gap-2 sm:h-9 sm:px-3.5",
  lg: "h-12 px-5 text-[15px] gap-2 sm:h-11 sm:text-sm",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: React.ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cx(
        "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-md font-medium transition-colors disabled:pointer-events-none disabled:opacity-45",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Loader2 size={size === "sm" ? 13 : 15} className="animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export function LinkButton({
  href,
  variant = "secondary",
  size = "md",
  icon,
  className,
  children,
}: {
  href: string;
  variant?: Variant;
  size?: Size;
  icon?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={cx(
        "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-md font-medium transition-colors",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
    >
      {icon}
      {children}
    </Link>
  );
}

export function IconButton({
  label,
  className,
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={cx(
        "inline-flex h-11 w-11 items-center justify-center rounded-md text-muted transition-colors hover:bg-hover hover:text-ink active:bg-hover disabled:opacity-40 sm:h-9 sm:w-9",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

/* -------------------------------------------------------------------- Card */

export function Card({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
  id,
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}) {
  return (
    <section id={id} className={cx("min-w-0 rounded-xl border border-line bg-panel shadow-[var(--shadow-card)]", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3 px-4 pt-4 sm:px-5">
          <div className="min-w-[12rem] flex-1">
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx("px-4 pb-4 sm:px-5 sm:pb-5", title || actions ? "pt-4" : "pt-4 sm:pt-5", bodyClassName)}>{children}</div>
    </section>
  );
}

/* ------------------------------------------------------------------ Badges */

export type Tone = "pass" | "fail" | "warn" | "info" | "neutral" | "accent";

const TONE: Record<Tone, string> = {
  pass: "bg-pass-soft text-pass",
  fail: "bg-fail-soft text-fail",
  warn: "bg-warn-soft text-warn",
  info: "bg-accent-soft text-accent",
  accent: "bg-accent text-on-accent",
  neutral: "bg-sunken text-muted",
};

export function Badge({
  tone = "neutral",
  icon,
  children,
  className,
  title,
}: {
  tone?: Tone;
  icon?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium",
        TONE[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/* ---------------------------------------------------------- Page structure */

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  children,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-6">
      {eyebrow && <div className="mb-2 text-xs text-muted">{eyebrow}</div>}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[22px] font-semibold tracking-tight sm:text-2xl">{title}</h1>
          {description && <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>}
        </div>
        {actions && <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto [&>*]:flex-1 sm:[&>*]:flex-none">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone,
  icon,
  className,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: string;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("min-w-0", className)}>
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted">
        {icon}
        {label}
      </div>
      <div className={cx("mt-1 break-words text-xl font-semibold leading-tight tracking-tight sm:text-2xl", tone)}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function StatCard(props: React.ComponentProps<typeof Stat> & { href?: string }) {
  const inner = (
    <div className="h-full rounded-xl border border-line bg-panel p-3.5 shadow-[var(--shadow-card)] transition-colors sm:p-4">
      <Stat {...props} />
    </div>
  );
  return props.href ? (
    <Link href={props.href} className="block rounded-xl hover:[&>div]:border-line-strong">
      {inner}
    </Link>
  ) : (
    inner
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
  compact,
}: {
  icon?: React.ReactNode;
  title: string;
  body?: React.ReactNode;
  action?: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={cx("flex flex-col items-center justify-center text-center", compact ? "py-6" : "py-12")}>
      {icon && (
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-sunken text-subtle">{icon}</div>
      )}
      <p className="text-sm font-medium">{title}</p>
      {body && <p className="mt-1 max-w-sm text-xs text-muted">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton rounded-md", className)} aria-hidden />;
}

export function LoadingRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2.5" aria-label="Loading" role="status">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-5" />
      ))}
    </div>
  );
}

/** Inline callout. Tone is never colour alone: always an icon and words. */
export function Callout({
  tone = "info",
  icon,
  title,
  children,
  className,
}: {
  tone?: Exclude<Tone, "accent">;
  icon?: React.ReactNode;
  title?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  const border: Record<string, string> = {
    pass: "border-pass/30",
    fail: "border-fail/30",
    warn: "border-warn/30",
    info: "border-accent/25",
    neutral: "border-line",
  };
  return (
    <div className={cx("flex gap-3 rounded-lg border px-4 py-3 text-sm", TONE[tone], border[tone], className)}>
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={cx(title ? "mt-0.5" : "", "text-[13px] opacity-90")}>{children}</div>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- Segmented */

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "sm",
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: React.ReactNode; title?: string }[];
  label: string;
  size?: "sm" | "md";
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex max-w-full overflow-x-auto rounded-lg bg-sunken p-0.5 [scrollbar-width:none]">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.title}
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            "shrink-0 whitespace-nowrap rounded-md font-medium transition-colors",
            size === "sm" ? "px-3 py-2.5 text-xs sm:px-2.5 sm:py-1" : "px-3.5 py-2.5 text-sm sm:px-3 sm:py-1.5",
            o.value === value ? "bg-panel text-ink shadow-sm" : "text-muted hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------- Tabs */

export function Tabs<T extends string>({
  value,
  onChange,
  tabs,
  label,
}: {
  value: T;
  onChange: (v: T) => void;
  tabs: { value: T; label: React.ReactNode; badge?: React.ReactNode }[];
  label: string;
}) {
  return (
    <div className="-mx-4 mb-5 overflow-x-auto border-b border-line [scrollbar-width:none] sm:-mx-1">
      <div role="tablist" aria-label={label} className="flex min-w-max gap-1 px-4 sm:px-1">
        {tabs.map((t) => (
          <button
            key={t.value}
            role="tab"
            aria-selected={t.value === value}
            onClick={() => onChange(t.value)}
            className={cx(
              "-mb-px inline-flex items-center gap-2 border-b-2 px-3 py-3 text-sm font-medium transition-colors sm:py-2.5",
              t.value === value ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink",
            )}
          >
            {t.label}
            {t.badge}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Forms */

const control =
  "w-full rounded-md border border-line bg-panel px-3 text-base text-ink sm:text-sm placeholder:text-subtle transition-colors focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-50";

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={cx(control, "h-11 sm:h-9", className)} {...rest} />;
});

export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(control, "h-11 pr-8 sm:h-9", className)} {...rest}>
      {children}
    </select>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  children: (id: string) => React.ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={cx("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-xs font-medium text-muted">
        {label}
      </label>
      {children(id)}
      {error ? <p className="text-xs text-fail">{error}</p> : hint ? <p className="text-xs text-subtle">{hint}</p> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ Tables */

export function Table({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cx("-mx-4 overflow-x-auto sm:-mx-5", className)}>
      <table className="w-full min-w-full text-sm">{children}</table>
    </div>
  );
}

export function Th({
  children,
  align = "left",
  className,
}: {
  children?: React.ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
}) {
  return (
    <th
      scope="col"
      className={cx(
        "whitespace-nowrap border-b border-line px-3 py-2 text-xs font-medium text-muted first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5",
        align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  align = "left",
  className,
  mono,
  title,
  colSpan,
}: {
  children?: React.ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
  mono?: boolean;
  title?: string;
  colSpan?: number;
}) {
  return (
    <td
      title={title}
      colSpan={colSpan}
      className={cx(
        "border-b border-line px-3 py-2.5 align-middle first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5",
        align === "right" ? "text-right" : align === "center" ? "text-center" : "",
        mono && "font-mono text-[13px]",
        className,
      )}
    >
      {children}
    </td>
  );
}

export function KeyValues({ items, className }: { items: [React.ReactNode, React.ReactNode][]; className?: string }) {
  return (
    <dl className={cx("grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-6 gap-y-2 text-sm", className)}>
      {items.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words text-right">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-subtle">{children}</h3>;
}

/* ------------------------------------------------------ Phone list views */

/** Table-free list for phones (hidden from `sm` up, where the table shows). */
export function MobileList({ children, className }: { children: React.ReactNode; className?: string }) {
  return <ul className={cx("-mx-4 divide-y divide-line border-y border-line sm:hidden", className)}>{children}</ul>;
}

export function MobileItem({
  children,
  onClick,
  href,
  className,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  href?: string;
  className?: string;
}) {
  const cls = cx("block w-full px-4 py-3 text-left", (onClick || href) && "active:bg-hover", className);
  if (href)
    return (
      <li>
        <Link href={href} className={cls}>
          {children}
        </Link>
      </li>
    );
  if (onClick)
    return (
      <li>
        <button type="button" onClick={onClick} className={cls}>
          {children}
        </button>
      </li>
    );
  return <li className={cls}>{children}</li>;
}

/** Wraps a desktop table so phones get the MobileList instead. */
export function DesktopOnly({ children }: { children: React.ReactNode }) {
  return <div className="hidden sm:block">{children}</div>;
}
