import { useEffect, useState } from "react";

export type ThemePref = "light" | "dark" | "system";
const KEY = "oasis.theme";

export function themePref(): ThemePref {
  const v = localStorage.getItem(KEY);
  return v === "light" || v === "dark" ? v : "system";
}

/** Puts the `dark` class on <html>. index.html runs the same logic before the first paint, so the page never flashes light. */
export function applyTheme(pref: ThemePref): void {
  const dark = pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

export function useTheme(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>(themePref);
  useEffect(() => {
    applyTheme(pref);
    if (pref !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = () => applyTheme("system");
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, [pref]);
  return [
    pref,
    (p) => {
      if (p === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, p);
      setPref(p);
    },
  ];
}
