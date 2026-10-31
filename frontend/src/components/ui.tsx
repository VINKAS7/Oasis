import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { AlertCircle, Loader2 } from "lucide-react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-700 text-white hover:bg-brand-800",
  secondary: "bg-white text-stone-800 border border-stone-200 hover:bg-hover",
  ghost: "text-stone-500 hover:bg-hover hover:text-stone-800",
  danger: "bg-white text-danger border border-stone-200 hover:bg-soft-red",
};

export function Button({
  variant = "primary",
  loading = false,
  className,
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        className,
      )}
    >
      {loading && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

const FIELD =
  "rounded-md border border-stone-200 bg-stone-50 px-2.5 py-1.5 text-sm text-stone-800 placeholder:text-stone-400 " +
  "focus:border-brand-600 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-600/25 disabled:opacity-60";

// Full width unless the caller sets a width (Tailwind can't tell which of two width classes wins).
const width = (className?: string) => (/(^|\s)(w-|min-w-|flex-1)/.test(className ?? "") ? "" : "w-full");

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(FIELD, width(className), className)} />;
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(FIELD, width(className), "min-h-24", className)} />;
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...props} className={cx(FIELD, width(className), "pr-8", className)}>
      {children}
    </select>
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cx("block", className)}>
      <span className="mb-1 block text-sm text-stone-500">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-stone-400">{hint}</span>}
    </label>
  );
}

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cx("relative mt-0.5 inline-flex h-[18px] w-8 shrink-0 rounded-full transition-colors", checked ? "bg-brand-700" : "bg-stone-300")}
      >
        <span className={cx("absolute top-[2px] size-[14px] rounded-full bg-white shadow-sm transition-transform", checked ? "translate-x-[16px]" : "translate-x-[2px]")} />
      </button>
      <span>
        <span className="block text-sm text-stone-800">{label}</span>
        {hint && <span className="block text-xs text-stone-500">{hint}</span>}
      </span>
    </label>
  );
}

/** A block with a quiet border, like a Notion database or callout container. */
export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-lg border border-stone-200 bg-white", className)}>{children}</div>;
}

export function CardHeader({ title, description, action }: { title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
      <div>
        <h2 className="text-[15px] font-semibold text-stone-800">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-stone-500">{description}</p>}
      </div>
      {action}
    </div>
  );
}

/** Notion-style section heading inside a page. */
export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mt-10 mb-2 flex items-center justify-between gap-3 border-b border-line pb-1.5">
      <h2 className="text-xl font-semibold text-stone-800">{children}</h2>
      {action}
    </div>
  );
}

type Tone = "neutral" | "green" | "amber" | "red" | "blue" | "teal";
// Notion's tag colours.
const TONES: Record<Tone, string> = {
  neutral: "bg-tag-gray text-tag-gray-ink",
  green: "bg-tag-green text-tag-green-ink",
  amber: "bg-tag-amber text-tag-amber-ink",
  red: "bg-tag-red text-tag-red-ink",
  blue: "bg-tag-blue text-tag-blue-ink",
  teal: "bg-tag-purple text-tag-purple-ink",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1 rounded px-1.5 py-px text-xs font-normal whitespace-nowrap", TONES[tone], className)}>{children}</span>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("size-5 animate-spin text-stone-400", className)} />;
}

export function PageLoader() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <Spinner className="size-6" />
    </div>
  );
}

type CalloutTone = "gray" | "red" | "yellow" | "green" | "blue";
const CALLOUTS: Record<CalloutTone, string> = {
  gray: "bg-soft-gray text-stone-800",
  red: "bg-soft-red text-soft-red-ink",
  yellow: "bg-soft-yellow text-soft-yellow-ink",
  green: "bg-soft-green text-soft-green-ink",
  blue: "bg-soft-blue text-soft-blue-ink",
};

export function Callout({ tone = "gray", icon, children, className }: { tone?: CalloutTone; icon?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cx("flex items-start gap-2.5 rounded-md px-3.5 py-3 text-sm", CALLOUTS[tone], className)}>
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function ErrorNote({ children, className }: { children: ReactNode; className?: string }) {
  if (!children) return null;
  return (
    <div role="alert">
      <Callout tone="red" icon={<AlertCircle className="size-4" />} className={className}>
        {children}
      </Callout>
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 text-stone-400">{icon}</div>
      <h3 className="text-sm font-medium text-stone-800">{title}</h3>
      {children && <div className="mt-1 max-w-sm text-sm text-stone-500">{children}</div>}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-stone-200 px-4 py-3">
      <div className="text-xs text-stone-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-stone-800 tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-stone-500">{hint}</div>}
    </div>
  );
}
