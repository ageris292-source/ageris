"use client";

// Last-resort boundary: replaces the root layout, so it carries its own
// <html>/<body> and plain inline styles (no app CSS is guaranteed here).
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en-IN">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", background: "#0d0d0d", color: "#f5f5f4" }}>
        <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 24, textAlign: "center" }}>
          <h1 style={{ fontSize: 22, margin: 0 }}>Aegis hit an unexpected error</h1>
          <p style={{ color: "#a8a69f", maxWidth: 420, fontSize: 14 }}>Nothing was traded and your data is safe. Reload to continue.</p>
          <button onClick={reset} style={{ marginTop: 12, height: 44, padding: "0 20px", borderRadius: 8, border: 0, background: "#3987e5", color: "#fff", fontSize: 14, cursor: "pointer" }}>
            Reload
          </button>
        </main>
      </body>
    </html>
  );
}
