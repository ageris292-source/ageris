"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type ThemePref = "light" | "dark" | "system";
type Resolved = "light" | "dark";

const KEY = "aegis.theme";

const Ctx = createContext<{ pref: ThemePref; resolved: Resolved; setPref: (p: ThemePref) => void }>({
  pref: "system",
  resolved: "dark",
  setPref: () => {},
});

function systemTheme(): Resolved {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "dark";
  }
}

/** Runs before first paint (inlined in <head>) so there is no theme flash. */
export const themeBootScript = `(function(){try{var p=localStorage.getItem("${KEY}")||"system";var d=p==="dark"||(p==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.setAttribute("data-theme",d?"dark":"light")}catch(e){document.documentElement.setAttribute("data-theme","dark")}})();`;

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>("system");
  const [resolved, setResolved] = useState<Resolved>("dark");

  useEffect(() => {
    let p: ThemePref = "system";
    try {
      const v = localStorage.getItem(KEY);
      if (v === "light" || v === "dark" || v === "system") p = v;
    } catch {
      /* storage unavailable: follow the system */
    }
    setPrefState(p);
  }, []);

  useEffect(() => {
    const apply = () => {
      const r = pref === "system" ? systemTheme() : pref;
      setResolved(r);
      document.documentElement.setAttribute("data-theme", r);
    };
    apply();
    if (pref !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [pref]);

  const setPref = useCallback((p: ThemePref) => {
    setPrefState(p);
    try {
      localStorage.setItem(KEY, p);
    } catch {
      /* not persisted; still applied for this visit */
    }
  }, []);

  return <Ctx.Provider value={{ pref, resolved, setPref }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);

/** Chart colours per theme: the validated reference palette (slots 1-3) and chrome. */
export function useChartColors() {
  const { resolved } = useTheme();
  return resolved === "dark"
    ? { s1: "#3987e5", s2: "#d95926", s3: "#199e70", grid: "#2c2c2a", axis: "#898781", surface: "#1a1a19", muted: "#939189", pass: "#0ca30c", fail: "#d03b3b" }
    : { s1: "#2a78d6", s2: "#eb6834", s3: "#1baf7a", grid: "#e1e0d9", axis: "#898781", surface: "#ffffff", muted: "#7a7873", pass: "#0ca30c", fail: "#d03b3b" };
}
