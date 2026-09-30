"use client";

import { useId } from "react";

export function BrandMark({ size = 28 }: { size?: number }) {
  // Unique gradient id per instance: a gradient defined inside a hidden copy
  // (e.g. the desktop sidebar on phones) would otherwise not render.
  const gid = `aegis-g-${useId().replace(/:/g, "")}`;
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3987e5" />
          <stop offset="1" stopColor="#1c5cab" />
        </linearGradient>
      </defs>
      <path d="M16 2.5 4.5 6.8v8.4c0 7.2 4.9 12.4 11.5 14.3 6.6-1.9 11.5-7.1 11.5-14.3V6.8L16 2.5Z" fill={`url(#${gid})`} />
      <path d="m10.5 19.5 4-5.2 3 2.6 4.2-6.1" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Brand() {
  return (
    <span className="flex items-center gap-2.5">
      <BrandMark />
      <span className="text-[17px] font-semibold tracking-tight">Aegis</span>
    </span>
  );
}
