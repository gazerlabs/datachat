const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getAuthToken(forceRefresh = false): Promise<string | null> {
  // Get token from Clerk. forceRefresh=true bypasses Clerk's in-memory cache
  // and asks for a freshly minted token — used on 401 to recover from a token
  // that expired between Clerk handing it to us and the request reaching the
  // backend.
  const opts = forceRefresh ? { skipCache: true } : undefined;
  const clerkToken = await window.Clerk?.session?.getToken(opts);
  return clerkToken || null;
}

async function _sendAuthedFetch(
  endpoint: string,
  options: RequestInit,
  signal: AbortSignal | undefined,
  forceRefresh: boolean,
): Promise<Response> {
  const token = await getAuthToken(forceRefresh);

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...options.headers,
  };
  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  return fetch(`${API_URL}${endpoint}`, { ...options, headers, signal });
}

async function fetchWithAuth(endpoint: string, options: RequestInit = {}, signal?: AbortSignal) {
  if (import.meta.env.DEV) {
    console.log(`[API] ${options.method || 'GET'} ${API_URL}${endpoint}`);
  }

  try {
    let response = await _sendAuthedFetch(endpoint, options, signal, false);

    // Recover from a stale cached token: on 401, ask Clerk for a fresh token
    // (skipCache) and retry once. Two 401s in a row means the user really is
    // unauthorized — surface that to the caller.
    if (response.status === 401) {
      if (import.meta.env.DEV) {
        console.log("[API] 401 — retrying with fresh token");
      }
      response = await _sendAuthedFetch(endpoint, options, signal, true);
    }

    if (import.meta.env.DEV) {
      console.log(`[API] Response status: ${response.status}`);
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Request failed" }));
      throw new ApiError(error.detail || `HTTP ${response.status}`, response.status);
    }

    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error(`[API] Error:`, error);
    }
    if (error instanceof TypeError && error.message === "Failed to fetch") {
      throw new ApiError(`Cannot connect to backend server (${API_URL}). Please check if the server is running.`, 0);
    }
    throw error;
  }
}

// Fetch without auth for public endpoints
async function fetchPublic(endpoint: string, options: RequestInit = {}) {
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...options.headers,
  };

  try {
    const response = await fetch(`${API_URL}${endpoint}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Request failed" }));
      throw new ApiError(error.detail || `HTTP ${response.status}`, response.status);
    }

    return response.json();
  } catch (error) {
    if (error instanceof TypeError && error.message === "Failed to fetch") {
      throw new ApiError(`Cannot connect to backend server (${API_URL}). Please check if the server is running.`, 0);
    }
    throw error;
  }
}

// Warehouse types
export interface WarehouseType {
  name: string;
  description: string;
  required_fields: string[];
  auth_type: string;
}

export interface Warehouse {
  id: string;
  warehouse_type: string;
  name: string;
  connection_status: string;
  is_read_only: boolean | null;
  is_demo?: boolean;
  last_tested_at: string | null;
  created_at: string;
}

export interface SchemaColumn {
  name: string;
  data_type: string;
}

export interface SchemaTable {
  dataset: string;
  table: string;
  columns: SchemaColumn[];
}

export interface SchemaPreview {
  datasets_count: number;
  tables_count: number;
  tables: SchemaTable[];
}

export interface Conversation {
  id: string;
  title: string;
  warehouse_id: string | null;
  warehouse_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface VisualizationConfig {
  chart_type: string;
  title: string;
  x_column: string;
  y_column: string;
  reasoning?: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  duration_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  feedback?: "like" | "dislike" | null;
  visualization?: VisualizationConfig | null;
  chart_data?: Record<string, any>[] | null;
}

export interface UsageSummary {
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  total_conversations: number;
  total_messages: number;
  current_month_tokens: number;
  current_month_weighted_tokens: number;
  token_limit: number;
  plan: string;
  plan_display_name: string;
  usage_percent: number;
}

export interface DailyUsage {
  date: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface QueryHistoryItem {
  id: string;
  conversation_title: string;
  input_tokens: number;
  output_tokens: number;
  weighted_tokens: number;
  cost_usd: number;
  model: string;
  created_at: string;
}

export interface ChatResponse {
  success: boolean;
  response: string;
  conversation_id: string;
  message_id?: string;
  input_tokens?: number;
  output_tokens?: number;
  weighted_tokens?: number;
  duration_ms?: number;
  usage_warning?: string;
  usage_percent?: number;
  sql_queries?: string[];
  visualization?: VisualizationConfig | null;
  chart_data?: Record<string, any>[] | null;
}

export interface SavedVisualization {
  id: string;
  name: string;
  description?: string | null;
  chart_type: string;
  chart_config: string;
  sql_query: string;
  warehouse_id?: string | null;
  local_duckdb_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface VisualizationRefreshResponse {
  id: string;
  chart_data: Record<string, any>[];
}

export type ReportCadence = "daily" | "weekly" | "monthly";

export interface ReportSchedule {
  cadence: ReportCadence;
  time_of_day: string;
  timezone: string;
  day_of_week: number | null;
  day_of_month: number | null;
  enabled: boolean;
  last_sent_at: string | null;
  next_send_at: string | null;
}

export interface ReportItem {
  id: string;
  saved_visualization_id: string;
  position: number;
}

export interface Report {
  id: string;
  name: string;
  description: string | null;
  warehouse_id: string | null;
  created_at: string;
  updated_at: string;
  items: ReportItem[];
  schedule: ReportSchedule | null;
}

export interface ContextFile {
  id: string;
  filename: string;
  content: string;
  source: "user" | "integration";
  integration_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContextFileList {
  files: ContextFile[];
}

export interface FileSessionTable {
  // For .duckdb-backed sessions:
  schema?: string;
  type?: string;
  // For multi-file upload sessions, each entry represents one uploaded file:
  filename?: string;
  // Common fields:
  name: string;
  row_count: number | null;
  columns: { name: string; type: string }[];
}

export interface FileSessionMetadata {
  filename: string;
  row_count?: number;
  column_count?: number;
  columns?: { name: string; type: string }[];
  table_count?: number;
  tables?: FileSessionTable[];
}

export interface FileSessionResponse {
  session_id: string;
  source_type: "excel_csv" | "local_upload" | "duckdb";
  metadata: FileSessionMetadata;
}

export interface LocalDuckDBTableInfo {
  id: string;
  table_name: string;
  original_filename: string;
  source_type: "excel_csv" | "local_upload";
  row_count: number;
  columns: { name: string; type: string }[];
  is_demo?: boolean;
  created_at: string;
}

export interface LocalDuckDBStatus {
  exists: boolean;
  id: string | null;
  tables: LocalDuckDBTableInfo[];
}

export interface LocalDuckDBUploadResponse {
  local_duckdb_id: string;
  table: LocalDuckDBTableInfo;
}

export interface CurrentUsage {
  plan: string;
  plan_display_name: string;
  billing_cycle_start: string;
  billing_cycle_end: string;
  weighted_tokens_used: number;
  weighted_token_limit: number;
  usage_percent: number;
}

export interface MaturityAssessmentData {
  company_size: string;
  has_warehouse: string;
  dbt_status: string;
  data_sources?: string;
}

export interface MaturityAssessmentResponse {
  id: string;
  routing_result: "ready" | "needs_dbt" | "needs_full_stack";
}

export interface ConsultingInquiryData {
  name: string;
  email: string;
  company?: string;
  message?: string;
  maturity_assessment_id?: string;
}

export interface SalesforceConnection {
  id: string;
  instance_url: string;
  org_name: string | null;
  username: string | null;
  connection_status: string;
  created_at: string;
}

export interface Integration {
  id: string;
  integration_type: string;
  name: string;
  connection_status: string;
  last_synced_at: string | null;
  created_at: string;
}

export interface IntegrationSync {
  id: string;
  integration_id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
  metadata_count: number;
}


export interface ModelOption {
  id: string;
  display_name: string;
}

export interface ModelsResponse {
  models: ModelOption[];
  default: string;
}

export interface AnthropicKeyStatus {
  configured: boolean;
  effective: boolean;
  source: "database" | "env" | null;
  masked: string | null;
}

async function fetchStreamWithAuth(endpoint: string, options: RequestInit = {}, signal?: AbortSignal): Promise<Response> {
  let response = await _sendAuthedFetch(endpoint, options, signal, false);
  if (response.status === 401) {
    response = await _sendAuthedFetch(endpoint, options, signal, true);
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new ApiError(error.detail || `HTTP ${response.status}`, response.status);
  }

  return response;
}

export interface StreamEvent {
  event: "text_delta" | "tool_call_start" | "tool_call_result" | "done" | "error";
  data: any;
}

export interface StreamDoneData {
  conversation_id: string;
  message_id: string;
  response_text: string;
  input_tokens: number;
  output_tokens: number;
  weighted_tokens: number;
  duration_ms: number;
  visualization: VisualizationConfig | null;
  chart_data: Record<string, any>[] | null;
  usage_warning?: string;
  usage_percent?: number;
}

// API functions
export const api = {
  // Models
  getModels: (): Promise<ModelsResponse> =>
    fetchPublic("/api/models"),

  // App settings (admin)
  getAnthropicKeyStatus: (): Promise<AnthropicKeyStatus> =>
    fetchWithAuth("/api/settings/anthropic-key"),

  setAnthropicKey: (apiKey: string): Promise<AnthropicKeyStatus> =>
    fetchWithAuth("/api/settings/anthropic-key", {
      method: "PUT",
      body: JSON.stringify({ api_key: apiKey }),
    }),

  deleteAnthropicKey: (): Promise<AnthropicKeyStatus> =>
    fetchWithAuth("/api/settings/anthropic-key", { method: "DELETE" }),

  // Warehouse
  getWarehouseTypes: (): Promise<Record<string, WarehouseType>> =>
    fetchWithAuth("/api/warehouse/types"),

  listWarehouses: (): Promise<Warehouse[]> =>
    fetchWithAuth("/api/warehouse/list"),

  configureWarehouse: (data: {
    warehouse_type: string;
    name: string;
    credentials: Record<string, string>;
  }): Promise<Warehouse> =>
    fetchWithAuth("/api/warehouse/configure", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  testWarehouse: (id: string): Promise<{ success: boolean; message?: string; error?: string }> =>
    fetchWithAuth(`/api/warehouse/${id}/test`, { method: "POST" }),

  deleteWarehouse: (id: string): Promise<{ success: boolean }> =>
    fetchWithAuth(`/api/warehouse/${id}`, { method: "DELETE" }),

  getWarehouseSchema: (id: string): Promise<SchemaPreview> =>
    fetchWithAuth(`/api/warehouse/${id}/schema`),

  verifyReadOnly: (id: string): Promise<{ is_read_only: boolean }> =>
    fetchWithAuth(`/api/warehouse/${id}/verify-readonly`, { method: "POST" }),

  getWarehouseAllowlist: (id: string): Promise<{ allowed_tables: string[] | null }> =>
    fetchWithAuth(`/api/warehouse/${id}/allowlist`),

  updateWarehouseAllowlist: (id: string, tables: string[] | null): Promise<{ success: boolean; allowed_tables: string[] | null }> =>
    fetchWithAuth(`/api/warehouse/${id}/allowlist`, {
      method: "PUT",
      body: JSON.stringify({ allowed_tables: tables }),
    }),

  // Files
  uploadFile: async (file: File): Promise<FileSessionResponse> => {
    const token = await getAuthToken();
    const formData = new FormData();
    formData.append("file", file);
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const response = await fetch(`${API_URL}/api/files/upload`, {
      method: "POST",
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Upload failed" }));
      throw new ApiError(error.detail || `HTTP ${response.status}`, response.status);
    }
    return response.json();
  },

  getFileSession: (sessionId: string): Promise<FileSessionResponse> =>
    fetchWithAuth(`/api/files/${sessionId}`),

  deleteFileSession: (sessionId: string): Promise<{ success: boolean }> =>
    fetchWithAuth(`/api/files/${sessionId}`, { method: "DELETE" }),

  appendFileToSession: async (sessionId: string, file: File): Promise<FileSessionResponse> => {
    const token = await getAuthToken();
    const formData = new FormData();
    formData.append("file", file);
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const response = await fetch(`${API_URL}/api/files/${sessionId}/append`, {
      method: "POST",
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Upload failed" }));
      throw new ApiError(error.detail || `HTTP ${response.status}`, response.status);
    }
    return response.json();
  },

  // Persistent per-user LocalDuckDB
  getLocalDuckdb: (): Promise<LocalDuckDBStatus> =>
    fetchWithAuth("/api/local-duckdb"),

  uploadLocalFile: async (file: File): Promise<LocalDuckDBUploadResponse> => {
    const token = await getAuthToken();
    const formData = new FormData();
    formData.append("file", file);
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const response = await fetch(`${API_URL}/api/local-duckdb/upload`, {
      method: "POST",
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Upload failed" }));
      throw new ApiError(error.detail || `HTTP ${response.status}`, response.status);
    }
    return response.json();
  },

  deleteLocalTable: (tableId: string): Promise<{ success: boolean }> =>
    fetchWithAuth(`/api/local-duckdb/tables/${tableId}`, { method: "DELETE" }),

  deleteLocalDuckdb: (): Promise<{ success: boolean }> =>
    fetchWithAuth("/api/local-duckdb", { method: "DELETE" }),

  // Chat
  sendMessage: (data: {
    message: string;
    conversation_id?: string;
    warehouse_id?: string;
    salesforce_id?: string;
    file_session_id?: string;
    local_duckdb_id?: string;
    model?: string;
    signal?: AbortSignal;
  }): Promise<ChatResponse> =>
    fetchWithAuth("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message: data.message,
        conversation_id: data.conversation_id,
        warehouse_id: data.warehouse_id,
        salesforce_id: data.salesforce_id,
        file_session_id: data.file_session_id,
        local_duckdb_id: data.local_duckdb_id,
        model: data.model,
      }),
    }, data.signal),

  sendMessageStream: (data: {
    message: string;
    conversation_id?: string;
    warehouse_id?: string;
    salesforce_id?: string;
    file_session_id?: string;
    local_duckdb_id?: string;
    model?: string;
    signal?: AbortSignal;
  }): Promise<Response> =>
    fetchStreamWithAuth("/api/chat/stream", {
      method: "POST",
      body: JSON.stringify({
        message: data.message,
        conversation_id: data.conversation_id,
        warehouse_id: data.warehouse_id,
        salesforce_id: data.salesforce_id,
        file_session_id: data.file_session_id,
        local_duckdb_id: data.local_duckdb_id,
        model: data.model,
      }),
    }, data.signal),

  // Conversations
  createConversation: (data: {
    warehouse_id?: string;
    salesforce_id?: string;
    title?: string;
  }): Promise<Conversation> =>
    fetchWithAuth("/api/conversations", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  listConversations: (): Promise<Conversation[]> =>
    fetchWithAuth("/api/conversations"),

  getConversationMessages: (id: string): Promise<Message[]> =>
    fetchWithAuth(`/api/conversations/${id}/messages`),

  deleteConversation: (id: string): Promise<{ success: boolean }> =>
    fetchWithAuth(`/api/conversations/${id}`, { method: "DELETE" }),

  renameConversation: (id: string, title: string): Promise<{ success: boolean }> =>
    fetchWithAuth(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  // Usage
  getUsageSummary: (): Promise<UsageSummary> =>
    fetchWithAuth("/api/usage/summary"),

  getDailyUsage: (days: number = 30): Promise<DailyUsage[]> =>
    fetchWithAuth(`/api/usage/daily?days=${days}`),

  getUsageHistory: (limit: number = 50): Promise<QueryHistoryItem[]> =>
    fetchWithAuth(`/api/usage/history?limit=${limit}`),

  getCurrentUsage: (): Promise<CurrentUsage> =>
    fetchWithAuth("/api/usage/current"),

  // Admin
  getAdminUsers: (): Promise<any[]> =>
    fetchWithAuth("/api/admin/users"),

  getAdminUsage: (): Promise<any> =>
    fetchWithAuth("/api/admin/usage"),

  updateUser: (userId: string, data: { plan?: string; is_admin?: boolean }): Promise<{ success: boolean }> =>
    fetchWithAuth(`/api/admin/users/${userId}?${new URLSearchParams(data as any)}`, {
      method: "PATCH",
    }),

  // Account
  deleteAccount: (): Promise<{ success: boolean }> =>
    fetchWithAuth("/api/account", { method: "DELETE" }),

  // Maturity Assessment
  getMaturityAssessmentStatus: (): Promise<{ completed: boolean; routing_result: string | null }> =>
    fetchWithAuth("/api/maturity-assessment/status"),

  submitMaturityAssessment: (data: MaturityAssessmentData): Promise<MaturityAssessmentResponse> =>
    fetchWithAuth("/api/maturity-assessment", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Consulting Inquiry (public - no auth)
  submitConsultingInquiry: (data: ConsultingInquiryData): Promise<{ success: boolean; id: string }> =>
    fetchPublic("/api/consulting-inquiry", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Feedback
  submitFeedback: (messageId: string, rating: "like" | "dislike"): Promise<{ success: boolean; rating: string }> =>
    fetchWithAuth("/api/feedback", {
      method: "POST",
      body: JSON.stringify({ message_id: messageId, rating }),
    }),

  removeFeedback: (messageId: string): Promise<{ success: boolean }> =>
    fetchWithAuth(`/api/feedback/${messageId}`, { method: "DELETE" }),

  // Salesforce
  getSalesforceStatus: (): Promise<SalesforceConnection | null> =>
    fetchWithAuth("/api/salesforce/status"),

  connectSalesforce: (): Promise<{ authorize_url: string }> =>
    fetchWithAuth("/api/salesforce/connect"),

  testSalesforce: (): Promise<{ success: boolean; message?: string; error?: string }> =>
    fetchWithAuth("/api/salesforce/test", { method: "POST" }),

  disconnectSalesforce: (): Promise<{ success: boolean }> =>
    fetchWithAuth("/api/salesforce/disconnect", { method: "DELETE" }),

  getSalesforceObjects: (): Promise<{ objects: { name: string; label: string }[] }> =>
    fetchWithAuth("/api/salesforce/objects"),

  getSalesforceAllowlist: (): Promise<{ allowed_objects: string[] | null }> =>
    fetchWithAuth("/api/salesforce/allowlist"),

  updateSalesforceAllowlist: (objects: string[] | null): Promise<{ success: boolean; allowed_objects: string[] | null }> =>
    fetchWithAuth("/api/salesforce/allowlist", {
      method: "PUT",
      body: JSON.stringify({ allowed_objects: objects }),
    }),

  // Visualizations
  listVisualizations: (): Promise<SavedVisualization[]> =>
    fetchWithAuth("/api/visualizations"),

  saveVisualization: (data: {
    name: string;
    description?: string;
    chart_type: string;
    chart_config: string;
    sql_query: string;
    warehouse_id?: string;
    local_duckdb_id?: string;
  }): Promise<SavedVisualization> =>
    fetchWithAuth("/api/visualizations", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  deleteVisualization: (id: string): Promise<{ success: boolean }> =>
    fetchWithAuth(`/api/visualizations/${id}`, { method: "DELETE" }),

  refreshVisualization: (id: string): Promise<VisualizationRefreshResponse> =>
    fetchWithAuth(`/api/visualizations/${id}/refresh`, { method: "POST" }),

  // Reports
  listReports: (): Promise<Report[]> =>
    fetchWithAuth("/api/reports"),

  getReport: (id: string): Promise<Report> =>
    fetchWithAuth(`/api/reports/${id}`),

  createReport: (data: {
    name: string;
    description?: string;
    warehouse_id?: string;
  }): Promise<Report> =>
    fetchWithAuth("/api/reports", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateReport: (id: string, data: { name?: string; description?: string }): Promise<Report> =>
    fetchWithAuth(`/api/reports/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteReport: (id: string): Promise<{ success: boolean }> =>
    fetchWithAuth(`/api/reports/${id}`, { method: "DELETE" }),

  addReportItem: (reportId: string, savedVisualizationId: string): Promise<Report> =>
    fetchWithAuth(`/api/reports/${reportId}/items`, {
      method: "POST",
      body: JSON.stringify({ saved_visualization_id: savedVisualizationId }),
    }),

  removeReportItem: (reportId: string, itemId: string): Promise<Report> =>
    fetchWithAuth(`/api/reports/${reportId}/items/${itemId}`, { method: "DELETE" }),

  setReportSchedule: (reportId: string, data: {
    cadence: ReportCadence;
    time_of_day: string;
    timezone: string;
    day_of_week?: number | null;
    day_of_month?: number | null;
    enabled: boolean;
  }): Promise<Report> =>
    fetchWithAuth(`/api/reports/${reportId}/schedule`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  disableReportSchedule: (reportId: string): Promise<Report> =>
    fetchWithAuth(`/api/reports/${reportId}/schedule`, { method: "DELETE" }),

  sendReportNow: (reportId: string): Promise<{ success: boolean; message_id: string }> =>
    fetchWithAuth(`/api/reports/${reportId}/send-now`, { method: "POST" }),

  // Context Files
  listContextFiles: (): Promise<ContextFileList> =>
    fetchWithAuth("/api/context"),

  getContextFile: (filename: string): Promise<ContextFile> =>
    fetchWithAuth(`/api/context/${encodeURIComponent(filename)}`),

  updateContextFile: (filename: string, content: string): Promise<ContextFile> =>
    fetchWithAuth(`/api/context/${encodeURIComponent(filename)}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),

  deleteContextFile: (filename: string): Promise<{ success: boolean }> =>
    fetchWithAuth(`/api/context/${encodeURIComponent(filename)}`, { method: "DELETE" }),

  // Integrations
  listIntegrations: (): Promise<Integration[]> =>
    fetchWithAuth("/api/integrations"),

  createIntegration: (data: {
    integration_type: string;
    name: string;
    config: { repo_url: string; branch?: string; auth_token?: string };
  }): Promise<Integration> =>
    fetchWithAuth("/api/integrations", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getIntegration: (id: string): Promise<Integration> =>
    fetchWithAuth(`/api/integrations/${id}`),

  deleteIntegration: (id: string): Promise<{ success: boolean }> =>
    fetchWithAuth(`/api/integrations/${id}`, { method: "DELETE" }),

  syncIntegration: (id: string): Promise<IntegrationSync> =>
    fetchWithAuth(`/api/integrations/${id}/sync`, { method: "POST" }),

  getIntegrationSyncStatus: (id: string): Promise<IntegrationSync> =>
    fetchWithAuth(`/api/integrations/${id}/sync/status`),


  // Changelog
  getChangelog: (): Promise<{ entries: { slug: string; title: string; date: string; version: string; tags: string[]; body: string }[] }> =>
    fetchPublic("/api/changelog"),

  // Runtime config (feature flags driven by backend env)
  getConfig: (): Promise<{ billing_enabled: boolean; email_enabled: boolean }> =>
    fetchPublic("/api/config"),

  // Organization
  getOrganization: (): Promise<Organization> => fetchWithAuth("/api/organization"),

  listOrganizationMembers: (): Promise<{ members: OrganizationMember[] }> =>
    fetchWithAuth("/api/organization/members"),

  inviteTeammate: (email: string): Promise<{ success: boolean; message: string }> =>
    fetchWithAuth("/api/organization/invite", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
};

export interface Organization {
  id: string;
  name: string;
  domain: string | null;
  is_personal: boolean;
  member_count: number;
  can_invite: boolean;
  created_at: string;
}

export interface OrganizationMember {
  id: string;
  email: string;
  name: string | null;
  is_admin: boolean;
  joined_at: string;
}

// Extend window for Clerk
declare global {
  interface Window {
    Clerk?: {
      session?: {
        getToken: (opts?: { skipCache?: boolean; template?: string }) => Promise<string | null>;
      };
      signOut: () => Promise<void>;
    };
  }
}
