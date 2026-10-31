import { Loader2 } from "lucide-react";
import type { CrawlRun } from "../types";
import { Badge } from "./ui";

export const ACTIVE = new Set(["queued", "crawling", "analyzing"]);

export function CrawlBadge({ run }: { run: Pick<CrawlRun, "status" | "ai_status"> }) {
  if (ACTIVE.has(run.status)) {
    return (
      <Badge tone="blue">
        <Loader2 className="size-3 animate-spin" />
        {run.status === "analyzing" ? "Analysing" : run.status === "queued" ? "Queued" : "Reading site"}
      </Badge>
    );
  }
  if (run.status === "failed") return <Badge tone="red">Crawl failed</Badge>;
  if (run.ai_status === "done") return <Badge tone="green">Tools suggested</Badge>;
  if (run.ai_status === "failed") return <Badge tone="amber">Analysis failed</Badge>;
  return <Badge tone="neutral">Site read</Badge>;
}
