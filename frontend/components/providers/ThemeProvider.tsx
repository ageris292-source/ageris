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
    ? { s1: "#1f9c84", s2: "#c98020", s3: "#4f80d0", grid: "rgba(255,255,255,0.08)", axis: "#8a867d", surface: "#1b201e", muted: "#918d84", pass: "#a4d867", fail: "#ff7a6e" }
    : { s1: "#008a76", s2: "#b35f00", s3: "#3a6fd0", grid: "rgba(70,58,40,0.12)", axis: "#7a7468", surface: "#efece5", muted: "#655f54", pass: "#3b7414", fail: "#b3261e" };
}
