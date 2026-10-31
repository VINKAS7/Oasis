import { useEffect, useState, type FormEvent } from "react";
import { Scale, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import type { OwnerRule, ToolInput } from "../types";
import { Button, ErrorNote, Input, Select } from "./ui";

/** "Ask me before groups over 8": the gateway refuses calls outside the owner's limits. */
export function RulesSection({ businessId, toolId, inputs }: { businessId: string; toolId: string; inputs: ToolInput[] }) {
  const numeric = inputs.filter((i) => i.type === "integer" || i.type === "number");
  const [rules, setRules] = useState<OwnerRule[]>([]);
  const [input, setInput] = useState(numeric[0]?.name ?? "");
  const [kind, setKind] = useState<"max" | "min">("max");
  const [value, setValue] = useState("8");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const base = `/api/workspaces/${businessId}/tools/${toolId}/rules`;

  useEffect(() => {
    api<OwnerRule[]>(base).then(setRules, () => undefined);
  }, [base]);

  if (numeric.length === 0) return null;

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      setRules(await api<OwnerRule[]>(base, { method: "POST", json: { input, kind, value: Number(value), message } }));
      setMessage("");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="mt-10">
      <h2 className="mb-1 flex items-center gap-2 border-b border-line pb-1.5 text-xl font-semibold">
        <Scale className="size-5" /> Your rules
      </h2>
      <p className="mb-3 text-sm text-stone-500">Requests outside these limits are not sent; the customer's assistant gets your message instead.</p>
      <ul className="mb-3 space-y-1 text-sm">
        {rules.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-hover">
            <span>
              <code>{r.input}</code> {r.kind === "max" ? "at most" : "at least"} <b>{r.value}</b>
              {r.message && <span className="text-stone-500">, otherwise: “{r.message}”</span>}
            </span>
            <button
              onClick={async () => {
                await api(`${base}/${r.id}`, { method: "DELETE" });
                setRules(rules.filter((x) => x.id !== r.id));
              }}
              className="rounded p-1 text-stone-400 hover:bg-hover hover:text-stone-700"
              title="Remove rule"
            >
              <Trash2 className="size-4" />
            </button>
          </li>
        ))}
        {rules.length === 0 && <li className="px-2 text-stone-500">No rules yet.</li>}
      </ul>
      <form onSubmit={add} className="flex flex-wrap items-center gap-2 text-sm">
        <Select value={input} onChange={(e) => setInput(e.target.value)} className="w-32">
          {numeric.map((i) => (
            <option key={i.name}>{i.name}</option>
          ))}
        </Select>
        <Select value={kind} onChange={(e) => setKind(e.target.value as "max" | "min")} className="w-28">
          <option value="max">at most</option>
          <option value="min">at least</option>
        </Select>
        <Input type="number" value={value} onChange={(e) => setValue(e.target.value)} className="w-20" />
        <Input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Otherwise tell the customer… (e.g. For more than 8, please call us)" className="min-w-60 flex-1" />
        <Button type="submit" variant="secondary">
          Add rule
        </Button>
      </form>
      <ErrorNote className="mt-2">{error}</ErrorNote>
    </div>
  );
}
