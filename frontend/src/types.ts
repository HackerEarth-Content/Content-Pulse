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
  question_type: string | null;
  customer: string | null;
  count: number | null;
  notes: string | null;
  due_at: string | null;
  effort_minutes: number | null;
  status: Status;
  jira_issue_key: string | null;
  jira_issue_url: string | null;
  jira_state: "none" | "pending" | "ok" | "failed";
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

export interface CycleTime {
  closed_tasks: number;
  median_hours: number | null;
  p90_hours: number | null;
  by_member: { member: string; closed_tasks: number; median_hours: number | null }[];
  by_task_type: { task_type: string; closed_tasks: number; median_hours: number | null }[];
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
