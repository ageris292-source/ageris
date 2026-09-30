import type { Metadata } from "next";

export const metadata: Metadata = { title: "Terms, disclaimer & privacy" };

const UPDATED = "30 September 2026";

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 rounded-xl border border-line bg-panel p-5 shadow-[var(--shadow-card)] sm:p-6">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <div className="mt-3 space-y-3 text-sm leading-relaxed text-muted [&_li]:ml-5 [&_li]:list-disc [&_strong]:text-ink">{children}</div>
    </section>
  );
}

export default function LegalPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight sm:text-2xl">Terms, risk disclaimer &amp; privacy</h1>
        <p className="mt-1 text-sm text-muted">Last updated {UPDATED}.</p>
        <nav aria-label="On this page" className="mt-3 flex flex-wrap gap-x-4 text-sm">
          <a href="#disclaimer" className="inline-block py-2 text-accent hover:underline">Risk disclaimer</a>
          <a href="#terms" className="inline-block py-2 text-accent hover:underline">Terms of use</a>
          <a href="#privacy" className="inline-block py-2 text-accent hover:underline">Privacy</a>
        </nav>
      </div>

      <Section id="disclaimer" title="Risk disclaimer">
        <p>
          <strong>Aegis is a research and simulation tool. It is not investment advice.</strong> Nothing in Aegis is a recommendation, solicitation or offer to buy
          or sell any security, and nothing in it is an investment adviser&apos;s advice or a research analyst&apos;s report under the SEBI (Investment Advisers)
          Regulations or the SEBI (Research Analysts) Regulations.
        </p>
        <ul>
          <li>Investing in equities involves risk, including the loss of your capital. Past performance, backtests and paper-trading results do not predict future results.</li>
          <li>Paper trading is simulated. Simulated fills, fees and slippage are estimates and can differ from real market outcomes.</li>
          <li>Data can be delayed, incomplete, revised or wrong, including data from unlicensed sources marked as such. Aegis shows unknown values as unknown and fails closed, but it cannot guarantee accuracy.</li>
          <li>Model outputs and AI-written text can be wrong. Only the deterministic Trade Risk Engine decides whether a trade passes, and a human approves every order.</li>
          <li>Live trading is disabled. Aegis does not place real orders with any broker.</li>
        </ul>
        <p>Make your own decisions, and speak to a SEBI-registered investment adviser before investing.</p>
      </Section>

      <Section id="terms" title="Terms of use">
        <ul>
          <li>Access is by invitation only. Keep your password private. You are responsible for activity on your account; use <strong>Sign out everywhere</strong> on the Account page if you suspect misuse.</li>
          <li>Use Aegis only for lawful research and education. Don&apos;t try to bypass its controls, probe its security, scrape it in bulk, or use it to manipulate markets.</li>
          <li>Market data and news remain subject to their providers&apos; licences. Don&apos;t redistribute data marked unlicensed.</li>
          <li>Admins may invite, change or deactivate accounts, and every administrative action is recorded in the audit log.</li>
          <li>Aegis is provided “as is”, without warranties. To the extent the law allows, its operators are not liable for losses arising from its use.</li>
          <li>These terms may change. Material changes are shown here with a new date.</li>
        </ul>
      </Section>

      <Section id="privacy" title="Privacy: what Aegis stores">
        <ul>
          <li><strong>Account:</strong> your email, role, a salted password hash (never the password itself), and when you last signed in.</li>
          <li><strong>Security log:</strong> sign-ins and failed attempts with IP address and browser type, plus an append-only audit trail of actions (for example trades evaluated, orders approved, settings changed). The audit trail can&apos;t be edited or deleted.</li>
          <li><strong>Your content:</strong> watchlists, price alerts and journal entries. Journal text is private to you. The audit trail records that an entry exists, never its text.</li>
          <li><strong>On your device:</strong> your sign-in token for this browser session, your theme choice, and a few view preferences. There are no advertising or third-party tracking cookies.</li>
          <li><strong>Notifications:</strong> if your admin enables Telegram or email alerts, alert titles and text are sent through those services.</li>
          <li>You can download your own data from the Account page. To have your account removed, ask an admin.</li>
        </ul>
      </Section>
    </div>
  );
}
