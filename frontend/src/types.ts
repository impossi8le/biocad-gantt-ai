export interface Task {
  id: string;
  name: string;
  description: string;
  assignee: string;
  duration_days: number;
  predecessors: string[];
  start_day: number | null;
  end_day: number | null;
  critical: boolean;
}

export interface PlanSchema {
  columns: string[];
  n_tasks: number;
  total_days: number;
  critical_path: string[];
  source_filename: string;
}

export interface PendingOp {
  pending_id?: string;
  tool: string;
  reason: string;
  affected_count: number;
  arguments?: Record<string, unknown>;
}

export interface SessionState {
  schema: PlanSchema;
  tasks: Task[];
  pending: PendingOp[];
  version_head: number;
}

export interface SessionResponse {
  session_id: string;
  state: SessionState;
}

export type ChatEvent =
  | { type: "intent"; action: string; explanation?: string }
  | { type: "update"; applied: boolean; result: unknown; state?: SessionState }
  | { type: "pending"; pending_id: string; reason: string; affected_count: number }
  | { type: "delta"; text: string }
  | { type: "done" };

export type ChatEventHandler = (ev: ChatEvent) => void;