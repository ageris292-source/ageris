import { Compass } from "lucide-react";
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-sunken text-subtle">
        <Compass size={26} aria-hidden />
      </div>
      <p className="font-mono text-sm text-subtle">404</p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight">Page not found</h1>
      <p className="mt-2 max-w-sm text-sm text-muted">The link may be old, or the page may have moved. Search for a stock or page with the search bar at the top.</p>
      <div className="mt-6 flex flex-col gap-2 sm:flex-row">
        <Link href="/" className="inline-flex h-11 items-center justify-center rounded-md bg-accent px-5 text-sm font-medium text-on-accent hover:bg-accent-strong sm:h-9">
          Go to dashboard
        </Link>
        <Link href="/help" className="inline-flex h-11 items-center justify-center rounded-md border border-line px-5 text-sm font-medium hover:bg-hover sm:h-9">
          Help
        </Link>
      </div>
    </div>
  );
}
