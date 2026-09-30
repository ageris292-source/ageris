"use client";

import { RotateCcw, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

export default function PageError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <div role="alert" className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-fail-soft text-fail">
        <TriangleAlert size={26} aria-hidden />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">Something went wrong on this page</h1>
      <p className="mt-2 max-w-md text-sm text-muted">
        Nothing was traded and your data is safe. Try again; if it keeps happening, tell your admin
        {error.digest ? ` and quote reference ${error.digest}` : ""}.
      </p>
      <div className="mt-6 flex flex-col gap-2 sm:flex-row">
        <button onClick={reset} className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-accent px-5 text-sm font-medium text-on-accent hover:bg-accent-strong sm:h-9">
          <RotateCcw size={15} aria-hidden /> Try again
        </button>
        <Link href="/" className="inline-flex h-11 items-center justify-center rounded-md border border-line px-5 text-sm font-medium hover:bg-hover sm:h-9">
          Go to dashboard
        </Link>
      </div>
    </div>
  );
}
