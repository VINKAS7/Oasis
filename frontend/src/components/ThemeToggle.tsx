import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme, type ThemePref } from "../lib/theme";
import { cx } from "./ui";

const NEXT: Record<ThemePref, ThemePref> = { light: "dark", dark: "system", system: "light" };
const LABEL: Record<ThemePref, string> = { light: "Light", dark: "Dark", system: "Same as your system" };

/** Light → dark → system. Remembered in this browser. */
export function ThemeToggle({ className }: { className?: string }) {
  const [pref, setPref] = useTheme();
  const Icon = pref === "light" ? Sun : pref === "dark" ? Moon : Monitor;
  return (
    <button
      type="button"
      onClick={() => setPref(NEXT[pref])}
      className={cx("rounded-md p-1.5 text-stone-500 hover:bg-hover hover:text-stone-800", className)}
      title={`Theme: ${LABEL[pref]} (click to change)`}
      aria-label={`Theme: ${LABEL[pref]}. Switch to ${LABEL[NEXT[pref]]}`}
    >
      <Icon className="size-4" />
    </button>
  );
}
