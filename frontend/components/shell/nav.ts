import {
  Activity,
  Bell,
  BriefcaseBusiness,
  FlaskConical,
  Gauge,
  GitCompareArrows,
  History,
  LayoutDashboard,
  LifeBuoy,
  LineChart,
  NotebookPen,
  ScrollText,
  Settings2,
  ShieldCheck,
  Trophy,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  adminOnly?: boolean;
  keywords?: string;
}

export const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Overview",
    items: [{ href: "/", label: "Dashboard", icon: LayoutDashboard, keywords: "home watchlist" }],
  },
  {
    group: "Research",
    items: [
      { href: "/stocks", label: "Stocks", icon: LineChart, keywords: "screener search universe" },
      { href: "/ranking", label: "Opportunities", icon: Trophy, keywords: "ranking daily qualified" },
      { href: "/compare", label: "Compare", icon: GitCompareArrows, keywords: "side by side versus vs peers" },
      { href: "/backtests", label: "Backtests & model", icon: FlaskConical, keywords: "walk forward lightgbm calibration" },
    ],
  },
  {
    group: "Trading",
    items: [
      { href: "/paper", label: "Paper trading", icon: Wallet, keywords: "orders fills positions theses approve" },
      { href: "/trade", label: "New trade", icon: ShieldCheck, keywords: "proposal risk engine gates evaluate cost" },
      { href: "/portfolios", label: "Portfolios", icon: BriefcaseBusiness, keywords: "holdings what-if exposure" },
      { href: "/journal", label: "Journal", icon: NotebookPen, keywords: "notes trade journal diary lessons" },
    ],
  },
  {
    group: "Operations",
    items: [
      { href: "/alerts", label: "Alerts", icon: Bell, keywords: "notifications price alerts rsi" },
      { href: "/activity", label: "Activity log", icon: History, keywords: "audit trail history sign-ins" },
      { href: "/monitoring", label: "Model monitoring", icon: Activity, adminOnly: true, keywords: "drift psi calibration" },
      { href: "/system", label: "System", icon: Gauge, keywords: "kill switch data sources macro live readiness" },
      { href: "/users", label: "Users", icon: Users, adminOnly: true, keywords: "invite team roles" },
      { href: "/help", label: "Help", icon: LifeBuoy, keywords: "faq guide glossary support terms disclaimer" },
    ],
  },
];

export const ACCOUNT_ITEM: NavItem = { href: "/account", label: "Account settings", icon: Settings2, keywords: "password theme profile" };
export const DOCS_ITEM: NavItem = { href: "/system", label: "How Aegis decides", icon: ScrollText };

export function isActive(path: string, href: string) {
  return href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
}
