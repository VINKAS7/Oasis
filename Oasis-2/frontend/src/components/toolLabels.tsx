import { Loader2 } from "lucide-react";
import type { BadgeValue, Sensitivity } from "../types";
import { Badge } from "./ui";

const SENSITIVITY: Record<Sensitivity, { label: string; tone: "green" | "amber" | "red"; hint: string }> = {
  read_only: { label: "Read-only", tone: "green", hint: "Gives information, changes nothing." },
  booking: { label: "Takes action", tone: "amber", hint: "Books, orders, requests or sends something. The customer's assistant must ask first." },
  personal_data: { label: "Personal data", tone: "amber", hint: "Sends a customer's name, phone or email. The customer's assistant must ask first." },
  payment: { label: "Handles money", tone: "red", hint: "Involves a payment. The customer's assistant must ask first." },
};

export const BADGES: Record<BadgeValue, { label: string; tone: "neutral" | "green" | "amber" | "red"; hint: string }> = {
  unchecked: { label: "Not checked yet", tone: "neutral", hint: "The checks have not run yet." },
  safe_working: { label: "Safe and working", tone: "green", hint: "Passed the security rules and a real test. Goes live." },
  sensitive: { label: "Sensitive", tone: "amber", hint: "Works, but takes action, uses personal data or money. Goes live; the customer's assistant must ask first." },
  untested: { label: "Needs a test run", tone: "amber", hint: "Passed the security rules, but has not run for real yet. Not published until it does." },
  not_working: { label: "Not working", tone: "red", hint: "The test failed. Not published." },
  blocked: { label: "Blocked", tone: "red", hint: "Broke a security rule. Never published." },
};

export function SensitivityBadge({ value }: { value: Sensitivity }) {
  const s = SENSITIVITY[value];
  return (
    <Badge tone={s.tone}>
      <span title={s.hint}>{s.label}</span>
    </Badge>
  );
}

export function CheckBadge({ badge, checking = false }: { badge: BadgeValue; checking?: boolean }) {
  if (checking)
    return (
      <Badge tone="blue">
        <Loader2 className="size-3 animate-spin" /> Checking
      </Badge>
    );
  const b = BADGES[badge] ?? BADGES.unchecked;
  return (
    <Badge tone={b.tone}>
      <span title={b.hint}>{b.label}</span>
    </Badge>
  );
}

export function signature(name: string, inputs: { name: string }[]): string {
  return `${name}(${inputs.map((i) => i.name).join(", ")})`;
}
