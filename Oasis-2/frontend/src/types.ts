// Keep in sync with the dicts the FastAPI routers return.

export type BusinessType =
  | "restaurant"
  | "cafe"
  | "bar"
  | "hotel"
  | "hostel"
  | "shop"
  | "beauty"
  | "health"
  | "fitness"
  | "services"
  | "professional"
  | "education"
  | "activities"
  | "events"
  | "rental"
  | "online"
  | "other";
export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Day = (typeof DAYS)[number];

export interface DayHours {
  closed: boolean;
  open: string;
  close: string;
}

export interface WorkspaceInput {
  type: BusinessType;
  category_label: string;
  online_only: boolean;
  name: string;
  address: string;
  lat: number | null;
  lng: number | null;
  phone: string;
  hours: Partial<Record<Day, DayHours>>;
  website_url: string;
  test_url: string;
  description: string;
}

export type CrawlStatus = "queued" | "crawling" | "analyzing" | "done" | "failed";
export type AIStatus = "pending" | "running" | "done" | "skipped" | "failed";

export interface ToolReady {
  name: string;
  title: string;
  description_for_ai: string;
  description_for_owner: string;
  source_urls: string[];
  inputs: { name: string; type: string; description: string; required: boolean }[];
  sensitivity: "read_only";
}

export interface TodoFlow {
  flow: string;
  title: string;
  reason: string;
  source_url: string;
}

export interface CrawlSummary {
  overview: string;
  tools_ready: ToolReady[];
  todo: TodoFlow[];
  missing: { topic: string; message: string }[];
  injection_warnings: string[];
  page_errors: number;
}

export interface CrawlRun {
  id: number;
  business_id: string;
  start_url: string;
  status: CrawlStatus;
  max_pages: number;
  pages_found: number;
  pages_done: number;
  pages_analyzed: number;
  error: string | null;
  ai_status: AIStatus;
  ai_error: string | null;
  summary: CrawlSummary | null;
  documents: { url: string; text: string }[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface CrawlPageRow {
  id: number;
  url: string;
  depth: number;
  status_code: number | null;
  title: string;
  error: string | null;
  has_screenshot: boolean;
  form_count: number;
  text_length: number;
  page_kind: string | null;
  purpose: string | null;
  analysis_error: string | null;
  injection_suspected: boolean;
}

export interface CrawlDetail extends CrawlRun {
  pages: CrawlPageRow[];
}

export interface PageAnalysis {
  purpose: string;
  page_kind: string;
  information: { topic: string; summary: string; facts: string[] }[];
  actions: { name: string; description: string; kind: string; form_ref: string }[];
  injection_suspected: boolean;
  error?: string;
}

export interface FormField {
  tag: string;
  type: string;
  name: string;
  id: string;
  label: string;
  required: boolean;
  options?: string[];
}

export interface PageDetail {
  id: number;
  url: string;
  title: string;
  meta_description: string;
  text: string;
  headings: { level: string; text: string }[];
  forms: { ref: string; action: string; method: string; fields: FormField[] }[];
  buttons: string[];
  json_ld: string[];
  analysis: PageAnalysis | null;
  has_screenshot: boolean;
  error: string | null;
}

export interface Workspace extends Omit<WorkspaceInput, "hours"> {
  id: string;
  owner_id: string;
  hours: Partial<Record<Day, DayHours>>;
  status: "draft" | "live";
  created_at: string;
  updated_at: string;
  latest_run: CrawlRun | null;
}

// --- admin -------------------------------------------------------------------------------

export type ProviderKind = "anthropic" | "openai" | "openai_compatible";

export interface Provider {
  id: string;
  name: string;
  kind: ProviderKind;
  base_url: string;
  api_key_hint: string;
  has_key: boolean;
  default_model: string;
  supports_vision: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface TaskInfo {
  task: string;
  label: string;
  description: string;
  max_tokens: number | null;
}

export interface RouteRow {
  task: string;
  provider_id: string | null;
  model: string;
  effort: string;
  max_tokens: number | null;
  enabled: boolean;
}

export interface Overview {
  users: number;
  admins: number;
  workspaces: number;
  crawls: number;
  crawls_running: number;
  providers: number;
  tools: number;
  alerts_24h: number;
  ai_ready: Record<string, boolean>;
  ai_24h: { calls: number; errors: number; input_tokens: number; output_tokens: number };
}

export interface AICall {
  id: number;
  task: string;
  user_email: string | null;
  business_id: string | null;
  provider_name: string | null;
  provider_kind: string | null;
  model: string | null;
  ok: boolean;
  error: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  created_at: string;
}

export interface PlatformSettings {
  "crawler.max_pages": number;
  "crawler.max_depth": number;
  "crawler.page_timeout_s": number;
  "crawler.respect_robots": boolean;
  "crawler.allow_private_urls": boolean;
  "recorder.enabled": boolean;
  "recorder.max_minutes": number;
  "ai.analyze_pages": boolean;
  "ai.send_screenshots": boolean;
  "ai.user_requests_per_minute": number;
}

export interface AdminWorkspace {
  id: string;
  name: string;
  type: BusinessType;
  website_url: string;
  status: string;
  created_at: string;
  owner_email: string | null;
  crawl_status: CrawlStatus | null;
  ai_status: AIStatus | null;
}

export interface AdminMcpServer {
  id: string;
  name: string;
  type: BusinessType;
  category_label: string;
  online_only: boolean;
  status: "draft" | "live";
  published_at: string | null;
  created_at: string;
  owner_email: string | null;
  calls_7d: number;
  server_url: string;
  tools: { id: string; name: string; title: string | null; badge: string | null; sensitivity: string | null; enabled: boolean; published: boolean }[];
}

// --- recordings (Part C) -----------------------------------------------------------------

export interface RecordingAction {
  type: "click" | "fill" | "select" | "check" | "uncheck" | "press" | "submit" | string;
  selector?: string;
  value?: string;
  option_text?: string;
  label?: string;
  name?: string;
  text?: string;
  key?: string;
  personal?: boolean;
  frame_url?: string;
}

export interface RecordingRequest {
  method: string;
  url: string;
  type?: string;
  body: unknown;
  response?: { status: number; content_type: string; body: unknown };
  error?: string;
}

export interface RecordingStep {
  n: number;
  page: string;
  url: string;
  owner_note: string;
  screenshot: string | null;
  actions: RecordingAction[];
  requests: RecordingRequest[];
}

export interface RecordingDoc {
  format: string;
  flow: string;
  title: string;
  business_id: string;
  recording_id: string;
  recorded_at: string;
  site: string;
  source: "browser" | "upload" | "extension";
  steps: RecordingStep[];
}

export interface Recording {
  id: string;
  business_id: string;
  flow_name: string;
  title: string;
  source: "browser" | "upload" | "extension";
  status: "recording" | "finished" | "failed";
  file_path: string | null;
  steps_count: number;
  actions_count: number;
  requests_count: number;
  error: string | null;
  uploaded_at: string;
  finished_at: string | null;
  processed: number;
  live_steps?: RecordingStep[];
}

export interface RecordingDetail extends Recording {
  document: RecordingDoc | null;
}

export interface FlowComparison {
  inputs: { name: string; type: string; examples: unknown[]; where: string[]; personal: boolean }[];
  fixed: { where: string; value: unknown }[];
  candidates: { step: number; method: string; url: string; status: number | null }[];
  likely_request: { step: number; method: string; url: string; status: number | null } | null;
  warnings: string[];
  recordings: { id: string; title: string; uploaded_at: string }[];
}

// --- tool registry (Part D) --------------------------------------------------------------

export type Sensitivity = "read_only" | "booking" | "personal_data" | "payment";

export interface ToolInput {
  name: string;
  type: string;
  description: string;
  required: boolean;
  personal: boolean;
}

export interface ToolVersion {
  id: string;
  tool_id: string;
  version: number;
  title: string;
  description_for_ai: string;
  description_for_owner: string;
  input_schema: Record<string, unknown>;
  inputs: ToolInput[];
  runner: Record<string, unknown> & { kind: string };
  runner_summary: string;
  sensitivity: Sensitivity;
  badge: BadgeValue;
  verified: boolean;
  checked_at: string | null;
  rate_limit: number | null;
  latest_check?: ToolCheck | null;
  created_from: string;
  proposal_id: string | null;
  reason: string;
  created_at: string;
}

export interface Tool {
  id: string;
  name: string;
  enabled: boolean;
  current_version: number | null;
  latest_version: number | null;
  waiting_version: number | null;
  versions_count: number;
  current: ToolVersion | null;
  checking: boolean;
  sample_inputs: Record<string, string | number | boolean>;
  created_at: string;
  updated_at: string;
  versions?: ToolVersion[];
}

export interface ProposalFlag {
  kind: "blocked" | "conflict" | "warning" | "note";
  message: string;
  tool_id?: string;
}

export interface ProposedTool {
  name: string;
  title: string;
  description_for_ai: string;
  description_for_owner: string;
  input_schema: { properties: Record<string, { type?: string; format?: string; description?: string; "x-personal"?: boolean }>; required: string[] };
  runner: Record<string, unknown> & { kind: string };
  sensitivity: Sensitivity;
}

export interface ProposalItem {
  index: number;
  action: "add" | "update" | "no_change";
  tool_name: string;
  reason: string;
  tool: ProposedTool | null;
  runner_summary?: string;
  target_tool_id: string | null;
  flags: ProposalFlag[];
  decision: null | "approved" | "rejected" | "noted";
  result?: { tool_id: string; version: number; in_use: boolean };
}

export interface Proposal {
  id: string;
  business_id: string;
  source: "crawl" | "recording";
  source_id: string;
  status: "generating" | "pending" | "applied" | "dismissed" | "failed";
  summary: string;
  items: ProposalItem[];
  written_by: "ai" | "platform" | "";
  error: string | null;
  created_at: string;
  decided_at: string | null;
}

// --- checks and badges (Part E) ----------------------------------------------------------

export type BadgeValue = "unchecked" | "safe_working" | "sensitive" | "not_working" | "blocked" | "untested";

export interface SecurityFinding {
  rule: string;
  ok: boolean;
  message: string;
  value?: string | number;
}

export interface CheckTest {
  mode?: "real" | "staging" | "live_then_cancel" | "live_owner" | "dry" | "security_only";
  mode_text?: string;
  inputs?: Record<string, unknown>;
  ok?: boolean;
  message?: string;
  status?: number | null;
  failed_step?: number | null;
  request?: { method: string; url: string; body: unknown } | null;
  output?: unknown;
  sent?: boolean;
  cancelled?: { ok: boolean; message: string } | null;
  injection?: { suspicious: boolean; quotes: string[]; reason?: string; by: string[]; note: string } | null;
  owner_message?: string;
  promoted?: boolean;
}

export interface ToolCheck {
  id: string;
  tool_id: string;
  version_id: string;
  version: number;
  trigger: "change" | "daily" | "owner" | "live_test";
  mode: "auto" | "live";
  status: "queued" | "running" | "done" | "error";
  badge: BadgeValue | null;
  verified: boolean;
  security: SecurityFinding[];
  test: CheckTest | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Alert {
  id: number;
  business_id: string;
  tool_id: string | null;
  tool_name?: string | null;
  business_name?: string;
  version: number | null;
  level: "blocked" | "broken";
  message: string;
  created_at: string;
  seen_at: string | null;
}

// --- MCP gateway (Part F) ----------------------------------------------------------------

export interface AgentCall {
  id: number;
  tool_name: string;
  version: number | null;
  outcome: "ok" | "failed" | "needs_confirmation" | "rule" | "rate_limited" | "not_published" | "bad_input";
  inputs: Record<string, unknown>;
  message: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface LiveInfo {
  status: "draft" | "live";
  published_at: string | null;
  mcp_url: string;
  /** The business's own MCP server (its tools directly), served while it is live. */
  server_url: string;
  public_key: string;
  tools: { id: string; name: string; title: string | null; published: boolean; reason: string }[];
  activity: AgentCall[];
  demand: { keyword: string; n: number }[];
  stats_7d: { calls: number; ok: number };
}

export interface OwnerRule {
  id: number;
  tool_id: string;
  input: string;
  kind: "max" | "min";
  value: number;
  message: string;
  active: number;
  created_at: string;
}

// --- Customer chat (/chat) ---------------------------------------------------------------

/** A business as find_nearby / search_businesses return it through the MCP gateway. */
export interface ChatBusiness {
  business_id: string;
  name: string;
  kind: string;
  online_only: boolean;
  address: string;
  website: string;
  description: string;
  distance_km?: number;
  open_at_requested_time?: boolean | null;
}

export interface ChatConfirm {
  business_id: string;
  business_name: string;
  tool: string;
  inputs: Record<string, unknown>;
  would_send: Record<string, unknown>;
}

/** One NDJSON line from POST /api/chat. */
export type ChatEvent =
  | { type: "step"; tool: string; arguments: Record<string, unknown> }
  | { type: "result"; tool: string; ok: boolean; summary: string; businesses?: ChatBusiness[] }
  | ({ type: "confirm" } & ChatConfirm)
  | { type: "reply"; text: string }
  | { type: "error"; message: string }
  | { type: "done" };

export interface ChatStep {
  tool: string;
  arguments: Record<string, unknown>;
  done: boolean;
  ok?: boolean;
  summary?: string;
}

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  text: string;
  steps?: ChatStep[];
  businesses?: ChatBusiness[];
  confirm?: ChatConfirm & { state: "pending" | "confirmed" | "cancelled" };
  error?: string;
}

export interface ChatThread {
  id: string;
  title: string;
  turns: ChatTurn[];
  updated_at: string;
}
