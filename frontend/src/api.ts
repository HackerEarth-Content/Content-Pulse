import type {
  Adherence,
  AreaByMember,
  AreaStat,
  Aging,
  EffortBreakdown,
  QualityMix,
  ContentRequest,
  CurrentUser,
  CustomerStat,
  CycleTime,
  DataQuality,
  DueRisk,
  Entry,
  Lookup,
  Member,
  MemberProfile,
  MemberStat,
  OpenItem,
  Page,
  PipelineStat,
  QuickLink,
  PlanDailyStatus,
  Status,
  Summary,
  SyncStatus,
  TaskTypeStat,
  TodayStatus,
  TrendPoint,
  Skill,
  SkillGraphData,
  SkillRatings,
  SkillWindow,
  WeeklyPlanCompletion,
  WeeklyPlanItem,
  WorkLogRow,
} from "./types";

/** Errors carry the backend's `{code, detail}` so callers can branch on
 * `code === "no_plan"` instead of matching on message text. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly extra: Record<string, unknown> = {}
  ) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | null | undefined>;

function qs(params: Params = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
  });
  if (!res.ok) {
    let code = String(res.status);
    let message = res.statusText;
    let extra: Record<string, unknown> = {};
    try {
      const body = await res.json();
      const detail = body?.detail;
      if (detail && typeof detail === "object") {
        const { code: c, detail: d, ...rest } = detail;
        code = c ?? code;
        message = d ?? message;
        extra = rest;
      } else if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(body?.detail)) {
        message = body.detail.map((e: { msg: string }) => e.msg).join("; ");
      }
    } catch {
      /* non-JSON error body — keep the status text */
    }
    throw new ApiError(res.status, code, message, extra);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const get = <T>(path: string, params?: Params) => request<T>(`${path}${qs(params)}`);
const send = <T>(method: string, path: string, body?: unknown) =>
  request<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

async function download(path: string, params: Params, filename: string): Promise<void> {
  const res = await fetch(`/api${path}${qs(params)}`);
  if (!res.ok) throw new ApiError(res.status, "export_failed", "Export failed");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export interface EntryFilters extends Params {
  pipeline?: string;
  from?: string;
  to?: string;
  member_id?: number;
  kind?: string;
  status?: string;
  task_type_id?: number;
  customer?: string;
  q?: string;
  page?: number;
  page_size?: number;
}

export const api = {
  me: () => get<CurrentUser>("/users/me"),
  logout: () => send<void>("POST", "/auth/logout"),

  members: (params?: Params) => get<Member[]>("/members", params),
  memberProfile: (id: number, p: Params) => get<MemberProfile>(`/members/${id}/profile`, p),
  createMember: (body: unknown) => send<Member>("POST", "/members", body),
  patchMember: (id: number, body: unknown) => send<Member>("PATCH", `/members/${id}`, body),
  removeMember: (id: number) =>
    send<{ deleted: boolean; entries: number; detail: string }>("DELETE", `/members/${id}`),
  taskTypes: () => get<Lookup[]>("/meta/lookups/task-types"),
  workTypes: () => get<{ key: string; label: string }[]>("/meta/work-types"),
  questionTypes: () => get<Lookup[]>("/meta/lookups/question-types"),
  lookups: (kind: string, includeInactive = false) =>
    get<Lookup[]>(`/meta/lookups/${kind}`, { include_inactive: includeInactive }),
  createLookup: (kind: string, body: unknown) => send<Lookup>("POST", `/meta/lookups/${kind}`, body),
  patchLookup: (kind: string, id: number, body: unknown) =>
    send<Lookup>("PATCH", `/meta/lookups/${kind}/${id}`, body),

  today: () => get<TodayStatus>("/today"),
  workLog: (f: EntryFilters) => get<Page<WorkLogRow>>("/work-log", f),
  entries: (f: EntryFilters) => get<Page<Entry>>("/entries", f),
  entry: (id: number) => get<Entry>(`/entries/${id}`),
  planFor: (member_id: number, on: string) => get<Entry>("/entries/plan", { member_id, on }),
  createPlan: (body: unknown) => send<Entry>("POST", "/entries/plans", body),
  createUpdate: (body: unknown) => send<Entry>("POST", "/entries/updates", body),
  patchItem: (id: number, body: unknown) => send<unknown>("PATCH", `/entry-items/${id}`, body),
  deleteItem: (id: number) => send<void>("DELETE", `/entry-items/${id}`),
  itemHistory: (id: number) =>
    get<{ from_status: Status | null; to_status: Status; changed_at: string; note: string | null }[]>(
      `/entry-items/${id}/history`
    ),
  jiraState: (entryId: number) =>
    get<{
      items: { id: number; jira_state: string; jira_issue_key: string | null;
                jira_issue_url: string | null }[];
      pending: boolean;
    }>(`/entries/${entryId}/jira-state`),

  summary: (p: Params) => get<Summary>("/analytics/summary", p),
  trend: (p: Params) => get<TrendPoint[]>("/analytics/trend", p),
  byMember: (p: Params) => get<MemberStat[]>("/analytics/by-member", p),
  byArea: (p: Params) => get<AreaStat[]>("/analytics/by-area", p),
  byRequestType: (p: Params) =>
    get<{ request_type: string; tasks: number; effort_minutes: number }[]>(
      "/analytics/by-request-type", p),
  byPipeline: (p: Params) => get<PipelineStat[]>("/analytics/by-pipeline", p),
  byTaskType: (p: Params) => get<TaskTypeStat[]>("/analytics/by-task-type", p),
  byQuestionType: (p: Params) =>
    get<{ question_type: string; tasks: number; volume: number }[]>("/analytics/by-question-type", p),
  byCustomer: (p: Params) => get<CustomerStat[]>("/analytics/by-customer", p),
  statusFlow: (p: Params) =>
    get<{ from: Status; to: Status; count: number }[]>("/analytics/status-flow", p),
  effortBreakdown: (p: Params) => get<EffortBreakdown>("/analytics/effort-breakdown", p),
  areaByMember: (p: Params) => get<AreaByMember[]>("/analytics/area-by-member", p),
  qualityMix: (p: Params) => get<QualityMix>("/analytics/quality-mix", p),
  cycleTime: (p: Params) => get<CycleTime>("/analytics/cycle-time", p),
  adherence: (p: Params) => get<Adherence[]>("/analytics/plan-adherence", p),
  planDailyStatus: (p: Params) => get<PlanDailyStatus[]>("/analytics/plan-daily-status", p),
  aging: (p: Params) => get<Aging>("/analytics/aging", p),
  dueRisk: (p: Params) => get<DueRisk>("/analytics/due-risk", p),
  throughput: (p: Params) => get<{ date: string; closed: number }[]>("/analytics/throughput", p),
  workload: (p: Params) =>
    get<{ member: string; date: string; tasks: number; volume: number; effort_minutes: number }[]>(
      "/analytics/workload",
      p
    ),
  openItems: (p: Params) => get<OpenItem[]>("/analytics/open-items", p),
  dataQuality: (p: Params) => get<DataQuality>("/analytics/data-quality", p),

  contentRequests: (p: Params) => get<Page<ContentRequest>>("/content-requests", p),
  contentRequestFilters: () =>
    get<{ statuses: string[]; assignees: string[]; priorities: string[]; issue_types: string[] }>(
      "/content-requests/filters"
    ),
  contentRequestStats: (p: Params) =>
    get<{
      total: number;
      open_backlog: number;
      by_status: { key: string; count: number }[];
      by_assignee: { key: string; count: number }[];
      by_priority: { key: string; count: number }[];
    }>("/content-requests/stats", p),
  syncContentRequests: () => send<{ ok: boolean; synced?: number; reason?: string }>(
    "POST",
    "/content-requests/sync"
  ),
  syncStatus: () => get<SyncStatus[]>("/meta/sync-status"),
  syncJira: (force = false) =>
    send<{ started: boolean; reason?: string }>(
      "POST", `/integrations/jira/sync${force ? "?force=true" : ""}`),
  jiraHealth: () =>
    get<{ ok: boolean; account?: string | null; error?: string | null }>("/integrations/jira/health"),
  retryPendingJira: () => send<{ retried: number }>("POST", "/integrations/jira/retry-pending"),
  slackDigest: (kind: string, dryRun: boolean) =>
    send<Record<string, unknown>>("POST", "/integrations/slack/digest", { kind, dry_run: dryRun }),
  slackRollCall: (phase: "morning" | "evening") =>
    send<Record<string, unknown>>("POST", "/integrations/slack/roll-call", { phase }),

  exportWorkLog: (f: EntryFilters, format: "xlsx" | "csv") =>
    download(`/exports/work-log.${format}`, f, `work-log-${f.from}_${f.to}.${format}`),
  exportAnalytics: (p: Params) =>
    download("/exports/analytics.xlsx", p, `analytics-${p.from}_${p.to}.xlsx`),  exportContentRequests: (p: Params) =>
    download("/exports/content-requests.xlsx", p, "content-requests.xlsx"),
  exportOverview: (p: Params) =>
    download("/exports/overview.xlsx", p, `team-overview-${p.from}_${p.to}.xlsx`),
  exportMemberOverview: (memberId: number, memberName: string, p: Params) =>
    download(
      "/exports/member.xlsx",
      { ...p, member_id: memberId },
      `${memberName}-${p.from}_${p.to}.xlsx`
    ),

  weeklyPlan: (week: string, memberId?: number) =>
    get<WeeklyPlanItem[]>("/weekly-plan", { week, member_id: memberId }),
  createWeeklyPlanItem: (week_start: string, action: string) =>
    send<WeeklyPlanItem>("POST", "/weekly-plan/items", { week_start, action }),
  patchWeeklyPlanItem: (id: number, body: { status?: string; achievement?: string }) =>
    send<WeeklyPlanItem>("PATCH", `/weekly-plan/items/${id}`, body),
  weeklyPlanCompletion: (week: string) =>
    get<WeeklyPlanCompletion>("/weekly-plan/completion", { week }),

  skills: () => get<Skill[]>("/skills"),
  createSkill: (body: { name: string; category: string; sub_domain?: string | null; sort_order?: number }) =>
    send<Skill>("POST", "/skills", body),
  patchSkill: (id: number, body: unknown) => send<Skill>("PATCH", `/skills/${id}`, body),
  skillWindow: () => get<SkillWindow>("/skills/window"),
  setSkillWindow: (body: { open_weekdays?: number[]; excluded_member_ids?: number[] }) =>
    send<SkillWindow>("PATCH", "/skills/window", body),
  mySkillRatings: () => get<SkillRatings>("/skills/ratings/me"),
  saveMySkillRatings: (ratings: { skill_id: number; level: number }[]) =>
    send<SkillRatings>("PUT", "/skills/ratings/me", { ratings }),
  skillGraph: () => get<SkillGraphData>("/skills/graph"),

  quickLinks: (memberId?: number) => get<QuickLink[]>("/quick-links", { member_id: memberId }),
  createQuickLink: (body: { name: string; url: string }) =>
    send<QuickLink>("POST", "/quick-links", body),
  patchQuickLink: (id: number, body: { name?: string; url?: string }) =>
    send<QuickLink>("PATCH", `/quick-links/${id}`, body),
  deleteQuickLink: (id: number) => send<void>("DELETE", `/quick-links/${id}`),
};
