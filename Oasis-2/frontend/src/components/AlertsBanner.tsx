import { Link } from "react-router-dom";
import { Ban, Wrench } from "lucide-react";
import { api, timeAgo } from "../lib/api";
import type { Alert } from "../types";
import { Button, Card } from "./ui";

export function AlertsBanner({ businessId, alerts, onSeen }: { businessId: string; alerts: Alert[]; onSeen: () => void }) {
  if (alerts.length === 0) return null;
  return (
    <Card className="border-red-200 bg-red-50/60">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
        <ul className="space-y-2 text-sm text-red-900">
          {alerts.map((a) => (
            <li key={a.id} className="flex items-start gap-2">
              {a.level === "blocked" ? <Ban className="mt-0.5 size-4 shrink-0" /> : <Wrench className="mt-0.5 size-4 shrink-0" />}
              <span>
                {a.message}{" "}
                {a.tool_id && (
                  <Link to={`/workspaces/${businessId}/tools/${a.tool_id}`} className="font-medium underline">
                    Open {a.tool_name}
                  </Link>
                )}
                <span className="ml-1 text-xs text-red-700/70">{timeAgo(a.created_at)}</span>
              </span>
            </li>
          ))}
        </ul>
        <Button
          variant="secondary"
          onClick={async () => {
            await api(`/api/workspaces/${businessId}/alerts/seen`, { method: "POST" });
            onSeen();
          }}
        >
          Got it
        </Button>
      </div>
    </Card>
  );
}
