export type Status = "open" | "in_progress" | "blocked" | "closed";
export type Kind = "plan" | "update";
export type Period = "today" | "yesterday" | "week" | "month" | "quarter";

export interface Member {
  id: number;
  display_name: string;
  email: string | null;
  role: string;
  is_active: boolean;
  slack_user_id: string | null;
}

export interface CurrentUser {
  id: string;
  email: string;
  name: string | null;
  member: { id: number; display_name: string; role: string } | null;
}

export interface Lookup {
  id: number;
  name: string;
  is_active: boolean;
}

export interface Item {
  id: number;
  plan_item_id: number | null;
  task_type_id: number;
  task_type: string;
  title: string;
  pipeline: string;
  work_type: string;
  question_types: string[];
  customer: string | null;
  count: number | null;
  notes: string | null;
  due_at: string | null;
  effort_minutes: number | null;
  status: Status;
  jira_issue_key: string | null;
  jira_issue_url: string | null;
  jira_state: "none" | "pending" | "ok" | "failed";
  jira_error: string | null;
  jira_missing: boolean;
  parent_issue_key: string | null;
  parent_issue_url: string | null;
}

export interface Entry {
  id: number;
  entry_date: string;
  kind: Kind;
  status: Status;
  member_id: number;
  member: string;
  raw_text: string | null;
  source: string;
  updated_at: string;
  items: Item[];
}

export interface Holiday {
  date: string;
  name: string;
}

export interface TodayStatus {
  date: string;
  you: {
    member_id: number | null;
    member: string | null;
    planned: boolean;
    updated: boolean;
    plan_entry_id: number | null;
    planned_count: number;
    updated_count: number;
  };
  planned: number;
  updated: number;
  awaiting_update: { member_id: number; member: string }[];
  no_plan_yet: { member_id: number; member: string }[];
  team_size: number;
  /** Set when today itself is a company-wide holiday — its name. */
  holiday: string | null;
  /** The soonest upcoming holiday, today included if today is one. */
  next_holiday: Holiday | null;
}

export interface WorkLogRow {
  id: number;
  entry_id: number;
  entry_date: string;
  kind: Kind;
  member_id: number;
  member: string;
  task_type_id: number;
  task_type: string;
  title: string;
  question_types: string[];
  customer: string | null;
  count: number | null;
  effort_minutes: number | null;
  notes: string | null;
  due_at: string | null;
  status: Status;
  pipeline: string;
  work_type: string;
  external_issue_type: string | null;
  request_type: string | null;
  jira_issue_key: string | null;
  jira_issue_url: string | null;
  jira_state: "none" | "pending" | "ok" | "failed";
  jira_error: string | null;
  jira_missing: boolean;
  parent_issue_key: string | null;
  parent_issue_url: string | null;
  plan_item_id: number | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Summary {
  range: { from: string; to: string };
  members: number;
  tasks: number;
  volume: number;
  effort_minutes: number;
  plans: number;
  updates: number;
  open: number;
  in_progress: number;
  blocked: number;
  closed: number;
  completion_rate: number | null;
}

export interface TrendPoint {
  date: string;
  tasks: number;
  volume: number;
  effort_minutes: number;
  closed: number;
  plans: number;
  updates: number;
}

export interface MemberStat {
  member_id: number;
  member: string;
  tasks: number;
  volume: number;
  effort_minutes: number;
  open: number;
  in_progress: number;
  blocked: number;
  closed: number;
  completion_rate: number | null;
}

export interface AreaStat {
  area: string;
  label: string;
  tasks: number;
  volume: number;
  effort_minutes: number;
  members: number;
  customers: number;
  open: number;
  in_progress: number;
  blocked: number;
  closed: number;
}

export interface PipelineStat {
  pipeline: string;
  label: string;
  tasks: number;
  volume: number;
  effort_minutes: number;
  members: number;
  customers: number;
  open: number;
  in_progress: number;
  blocked: number;
  closed: number;
}

export interface TaskTypeStat {
  task_type: string;
  tasks: number;
  volume: number;
  effort_minutes: number;
  open: number;
  in_progress: number;
  blocked: number;
  closed: number;
}

export interface CustomerStat {
  customer: string;
  tasks: number;
  volume: number;
  effort_minutes: number;
  outstanding: number;
}

export interface MemberProfile {
  member: { id: number; display_name: string; role: string; email: string | null };
  range: { from: string; to: string };
  totals: Summary;
  share_of_team: { tasks: number | null; effort: number | null };
  by_pipeline: PipelineStat[];
  by_task_type: TaskTypeStat[];
  by_question_type: { question_type: string; tasks: number; volume: number }[];
  by_customer: CustomerStat[];
  by_area: AreaStat[];
  effort_breakdown: EffortBreakdown;
  quality: QualityMix;
  cycle_time: CycleTime;
  adherence: Adherence | null;
  trend: TrendPoint[];
}

export interface Adherence {
  member_id: number;
  member: string;
  planned: number;
  reported: number;
  closed: number;
  no_update: number;
  report_rate: number | null;
  close_rate: number | null;
}

export interface PlanDailyStatus {
  member_id: number;
  member: string;
  entry_date: string;
  planned: boolean;
  updated: boolean;
  created: number;
  closed: number;
}

export interface CycleTime {
  /** Tasks the median is actually computed over. */
  closed_tasks: number;
  /** Finished tasks in range — the denominator for `coverage`. */
  measured_of_closed: number;
  /** Created and resolved within two minutes: filed after the work, so
   *  excluded from the median. Show this, or the number reads as complete. */
  filed_retroactively: number;
  coverage: number | null;
  median_hours: number | null;
  p90_hours: number | null;
  by_member: { member: string; closed_tasks: number; median_hours: number | null }[];
  by_task_type: { task_type: string; closed_tasks: number; median_hours: number | null }[];
}

/** One slice of a total — by area, task type, customer or person. */
export interface EffortSlice {
  key: string;
  label: string;
  tasks: number;
  effort_minutes: number;
}

export interface EffortTicket {
  id: number;
  notes: string | null;
  effort_minutes: number;
  suspect: boolean;
  jira_issue_key: string | null;
  jira_issue_url: string | null;
  customer: string | null;
  status: Status;
  entry_date: string;
  member: string;
  area: string;
  area_label: string;
}

/** What a headline effort figure is made of. Every slice sums back to
 *  `effort_minutes`, so the parts reconcile with the whole. */
export interface EffortBreakdown {
  effort_minutes: number;
  tasks: number;
  tasks_without_effort: number;
  tasks_with_suspect_effort: number;
  by_area: EffortSlice[];
  by_task_type: EffortSlice[];
  by_customer: EffortSlice[];
  by_member: EffortSlice[];
  top_tickets: EffortTicket[];
}

/** A stream, and who spent the time in it. */
export interface AreaByMember {
  area: string;
  label: string;
  tasks: number;
  effort_minutes: number;
  members: {
    member_id: number;
    member: string;
    tasks: number;
    effort_minutes: number;
    closed: number;
    share_of_area: number | null;
  }[];
}

export interface QualityMix {
  by_priority: { key: string; tasks: number; effort_minutes: number }[];
  sla_met: number;
  sla_missed: number;
  /** Jira only rates about half the issues, so this is a rate over the rated
   *  ones — not over everything. */
  sla_rate: number | null;
}

export interface OpenItem {
  id: number;
  member: string;
  task_type: string;
  status: Status;
  customer: string | null;
  count: number | null;
  notes: string | null;
  entry_date: string;
  due_at: string | null;
  age_days: number;
  overdue: boolean;
}

export interface DueRisk {
  overdue: number;
  due_today: number;
  due_this_week: number;
  no_due_date: number;
}

export interface Aging {
  buckets: { bucket: string; tasks: number }[];
}

export interface DataQuality {
  tasks: number;
  missing: Record<string, number>;
  plans_with_unreported_tasks: number;
  tasks_on_retired_task_types: number;
}

export interface ContentRequest {
  issue_key: string;
  summary: string;
  status: string;
  status_category: string | null;
  assignee: string | null;
  reporter: string | null;
  priority: string | null;
  issue_type: string | null;
  labels: string[];
  created_at: string | null;
  updated_at: string | null;
  due_date: string | null;
  resolved_at: string | null;
  url: string;
}

export interface SyncStatus {
  key: string;
  last_synced_at: string | null;
  status: string | null;
  error: string | null;
}

export type WeeklyPlanStatus = "yet_to_start" | "in_progress" | "blocked" | "completed";

export interface WeeklyPlanItem {
  id: number;
  member_id: number;
  member: string;
  week_start: string;
  action: string;
  achievement: string | null;
  status: WeeklyPlanStatus;
  updated_at: string;
}

export interface WeeklyPlanCompletion {
  active: number;
  filed: number;
  updated: number;
}

export interface QuickLink {
  id: number;
  member_id: number;
  name: string;
  url: string;
  sort_order: number;
  updated_at: string;
}

export type SkillCategory = "tech" | "ai" | "nontech";

export interface Skill {
  id: number;
  name: string;
  category: SkillCategory;
  sub_domain: string | null;
}

export interface SkillWindow {
  open: boolean;
  open_weekdays: number[];
  excluded_member_ids: number[];
}

/** Keyed by skill id; a skill missing from the map hasn't been rated. */
export type SkillRatings = Record<number, number>;

export interface MemberSkillRatings {
  member_id: number;
  display_name: string;
  role: string;
  ratings: SkillRatings;
}

export interface SkillGraphData {
  skills: Skill[];
  members: MemberSkillRatings[];
}

/** How the HE question library is actually performing — candidate usage,
 *  feedback, and topic coverage, synced from Redash. */
export interface ContentHealthType {
  problem_type: string;
  question_type_id: number | null;
  tests_published: number | null;
  tests_with_qt: number | null;
  tests_with_library: number | null;
  library_questions_used: number | null;
  candidates_attempted: number | null;
}

export interface ContentHealthOverview {
  problem_types: ContentHealthType[];
  feedback: { total_slugs: number; slugs_with_rating: number; avg_rating: number | null } | null;
  synced_at: string | null;
}

export type CoverageAction = "add" | "top_up" | "prune" | "balanced";

export interface CoverageTopic {
  topic: string;
  questions: number;
  active: number;
  dead_pct: number;
  attempts: number;
  att_per_q: number;
  avg_health: number | null;
  difficulty: { easy: number; medium: number; hard: number };
  action: CoverageAction;
  action_label: string;
}

export interface ContentHealthCoverage {
  topics: CoverageTopic[];
  summary: { total_questions: number; total_attempts: number; topics: number; dead_questions: number };
  verdicts: Record<CoverageAction, number>;
}

export interface ContentHealthCompanies {
  value_label: string | null;
  companies: { company: string; value: number | null }[];
}
