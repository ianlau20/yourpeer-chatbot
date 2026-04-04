// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

export interface QuickReply {
  label: string;
  value: string;
}

export interface ServiceResult {
  service_name?: string;
  organization?: string;
  address?: string;
  phone?: string;
  email?: string;
  website?: string;
  description?: string;
  hours_today?: string;
  is_open?: "open" | "closed" | "unknown";
  fees?: string;
  requires_membership?: boolean;
  yourpeer_url?: string;
}

export interface ChatResponse {
  session_id: string;
  response: string;
  services?: ServiceResult[];
  quick_replies?: QuickReply[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "bot";
  text: string;
  services?: ServiceResult[];
  quick_replies?: QuickReply[];
  showFeedback?: boolean;
}

export type FeedbackRating = "up" | "down";

// Admin types

export interface AdminStats {
  unique_sessions: number;
  total_turns: number;
  total_queries: number;
  total_crises: number;
  total_escalations: number;
  relaxed_query_rate: number;
  feedback_up: number;
  feedback_down: number;
  feedback_score: number | null;
}

export interface ConversationSummary {
  session_id: string;
  turn_count: number;
  services_delivered: number;
  crisis_detected: boolean;
  final_slots: Record<string, string>;
  last_seen: string;
}

export interface AuditEvent {
  type: "conversation_turn" | "query_execution" | "crisis_detected" | "session_reset";
  timestamp: string;
  session_id?: string;
  user_message?: string;
  bot_response?: string;
  template_name?: string;
  result_count?: number;
  execution_ms?: number;
  relaxed?: boolean;
  crisis_category?: string;
  slots?: Record<string, string | null>;
  services_count?: number;
  quick_replies?: string[];
}

export interface QueryLogEntry {
  timestamp: string;
  session_id?: string;
  template_name: string;
  params: Record<string, unknown>;
  result_count: number;
  execution_ms: number;
  relaxed: boolean;
}

export interface EvalDimensionScore {
  average: number;
  count: number;
}

export interface EvalScenarioResult {
  name: string;
  category?: string;
  average_score: number;
  overall_notes?: string;
  error?: string;
  scores?: Record<string, { score: number; justification: string }>;
}

export interface EvalReport {
  summary: {
    overall_average: number;
    scenarios_evaluated: number;
    critical_failure_count: number;
    scenarios_with_errors: number;
    dimension_averages: Record<string, EvalDimensionScore>;
    category_averages: Record<string, number>;
  };
  critical_failures?: Array<{ scenario: string; failure: string }>;
  scenarios?: EvalScenarioResult[];
}

export interface EvalRunStatus {
  running: boolean;
  message?: string;
  total?: number;
  completed?: number;
  started_at?: string;
  finished_at?: string;
}
