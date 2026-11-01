import { Globe } from "lucide-react";
import { LANGS, setLang, useT, type Lang } from "../lib/i18n";
import { cx } from "./ui";

/** English, French, Italian or German. Remembered in this browser (shared with /mcp). Shows the
 *  short code; the transparent native select on top gives the full list and keyboard support. */
export function LanguagePicker({ className }: { className?: string }) {
  const { lang, t } = useT();
  return (
    <label
      className={cx("relative flex items-center gap-1 rounded-md px-1.5 py-1 text-[13px] font-medium text-stone-500 hover:bg-hover hover:text-stone-800", className)}
      title={t("chat.language")}
    >
      <Globe className="size-4" />
      {lang.toUpperCase()}
      <select value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label={t("chat.language")} className="absolute inset-0 cursor-pointer opacity-0">
        {LANGS.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}
