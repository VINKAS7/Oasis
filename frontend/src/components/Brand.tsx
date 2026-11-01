import { cx } from "./ui";

// The Oasis mark: a ring of eight segments with one teal segment (upper right) around a teal dot.
// The ring takes the text colour (currentColor), so it follows light and dark mode by itself.
const CX = 50;
const R = 38.5;
const GAP = 10; // degrees between segments

function point(deg: number): string {
  const rad = ((deg - 90) * Math.PI) / 180; // 0° is 12 o'clock, clockwise
  return `${(CX + R * Math.cos(rad)).toFixed(2)} ${(CX + R * Math.sin(rad)).toFixed(2)}`;
}

const SEGMENTS = Array.from({ length: 8 }, (_, i) => `M ${point(i * 45 + GAP / 2)} A ${R} ${R} 0 0 1 ${point((i + 1) * 45 - GAP / 2)}`);

export function OasisMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={cx("shrink-0", className)} aria-hidden="true">
      {SEGMENTS.map((d, i) => (
        <path key={i} d={d} fill="none" strokeWidth="10" stroke={i === 1 ? "var(--color-logo-teal)" : "currentColor"} />
      ))}
      <circle cx={CX} cy={CX} r="11.5" fill="var(--color-logo-teal)" />
    </svg>
  );
}

/** Mark plus the lowercase "oasis" wordmark, optionally with the MCP pill from the brand sheet. */
export function OasisLogo({ className, size = "md", mcp = false }: { className?: string; size?: "sm" | "md" | "lg"; mcp?: boolean }) {
  const s = { sm: { mark: "size-5", text: "text-[17px]" }, md: { mark: "size-6", text: "text-[19px]" }, lg: { mark: "size-10", text: "text-[34px]" } }[size];
  return (
    <span className={cx("inline-flex items-center gap-2 text-stone-900", className)}>
      <OasisMark className={s.mark} />
      <span className={cx("leading-none font-semibold tracking-[-0.03em]", s.text)}>oasis</span>
      {mcp && <span className="rounded-full border border-brand-600 px-1.5 py-px text-[11px] font-semibold tracking-wider text-brand-700">MCP</span>}
    </span>
  );
}
