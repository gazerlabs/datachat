import { useState, useEffect, useRef, useCallback, useMemo, memo } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, Conversation, Message, VisualizationConfig, FileSessionResponse, SchemaPreview, LocalDuckDBStatus } from "@/lib/api";
import { useStreamingChat } from "@/hooks/use-streaming-chat";
import ResponseMetadata, { formatTimestamp } from "@/components/ResponseMetadata";
import UsageBanner from "@/components/UsageBanner";
import { MissingAnthropicKeyBanner } from "@/components/MissingAnthropicKeyBanner";
import InlineVisualization from "@/components/InlineVisualization";
import SaveVisualizationModal from "@/components/SaveVisualizationModal";

function formatSidebarTimestamp(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();

  if (isToday) return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const yy = String(date.getFullYear()).slice(-2);
  return `${mm}/${dd}/${yy}`;
}

const WELCOME_GREETINGS = [
  "How can I help you today?",
  "What would you like to explore?",
  "Ready to dive into your data?",
  "What insights are you looking for?",
  "How can I assist you?",
];

const ALL_EXAMPLE_QUESTIONS = [
  "What tables are in my database?",
  "Show me the top 10 customers by revenue",
  "What's the trend in orders this month?",
  "What are the top performing stores?",
  "Show me sales by product category",
  "Which customers have the highest lifetime value?",
  "Compare revenue across regions",
  "What products have the best margins?",
];

// Shuffle array using Fisher-Yates algorithm
const shuffleArray = <T,>(array: T[]): T[] => {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
};

// Extract SQL code blocks from markdown content for copy functionality
import {
  ASSISTANT_PROSE_CLASSES,
  CollapsibleSqlContent,
  CopyButton,
  downloadCsv,
  extractSqlBlocks,
  stripSqlBlocks,
} from "@/components/chat/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ThemeToggle } from "@/components/ThemeToggle";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import FileUploadZone from "@/components/FileUploadZone";

import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import postgresqlLogo from "@/assets/postgresql-logo.svg";
import excelLogo from "@/assets/excel-logo.svg";
import duckdbLogo from "@/assets/duckdb-logo.svg";
import salesforceLogo from "@/assets/salesforce-logo.svg";
import redshiftLogo from "@/assets/redshift-logo.png";
import {
  ArrowUp,
  Plus,
  Settings,
  BarChart,
  BarChart3,
  Loader2,
  Database,
  PanelLeft,
  PanelLeftClose,
  Trash2,
  User,
  X,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Pencil,
  AlertTriangle,
  Upload,
  Eye,
  EyeOff,
  Shield,
  Info,
  FileText,
} from "lucide-react";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";

// Conditionally import Clerk components
const CLERK_ENABLED = !!import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

let UserButton: React.ComponentType<{ afterSignOutUrl?: string }> | null = null;
if (CLERK_ENABLED) {
  import("@clerk/clerk-react").then((mod) => {
    UserButton = mod.UserButton;
  });
}

export default function ChatPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);
  const detachScrollListenerRef = useRef<(() => void) | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [input, setInput] = useState("");
  const [selectedWarehouse, setSelectedWarehouse] = useState<string | null>(
    () => localStorage.getItem("datachat_selected_warehouse")
  );
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(conversationId || null);
  const [localMessages, setLocalMessages] = useState<Message[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(256); // 256px = w-64
  const [isResizing, setIsResizing] = useState(false);
  const [ClerkUserButton, setClerkUserButton] = useState<React.ComponentType<{ afterSignOutUrl?: string }> | null>(null);

  // Model selection — fetched from backend
  const { data: modelsData } = useQuery({
    queryKey: ["models"],
    queryFn: api.getModels,
    staleTime: Infinity,
  });
  const [selectedModel, setSelectedModel] = useState<string | null>(null);

  // Set default model once loaded
  useEffect(() => {
    if (modelsData && !selectedModel) {
      setSelectedModel(modelsData.default);
    }
  }, [modelsData, selectedModel]);

  // Rotating welcome greeting (picked once per session)
  const [greetingIndex] = useState(() => Math.floor(Math.random() * WELCOME_GREETINGS.length));
  // Shuffle and pick 2 example questions once per session (top row rotates)
  const [exampleQuestions] = useState(() => shuffleArray(ALL_EXAMPLE_QUESTIONS).slice(0, 2));

  // Command history for up/down arrow navigation
  const [commandHistory, setCommandHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [tempInput, setTempInput] = useState("");

  // Resync textarea height when `input` changes programmatically (e.g. command
  // history navigation), since onChange's inline resize doesn't fire then.
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 150) + "px";
  }, [input]);

  // Streaming chat
  const streaming = useStreamingChat();
  const isSendingRef = useRef(false);

  // Persistent per-user LocalDuckDB (excel/csv/parquet/json files share one DuckDB instance)
  const { data: localDb } = useQuery<LocalDuckDBStatus>({
    queryKey: ["localDuckdb"],
    queryFn: api.getLocalDuckdb,
    staleTime: 30_000,
  });

  // File sessions state — only used for .duckdb file uploads now (excel/csv/parquet/json
  // are stored in the persistent LocalDuckDB above). Older entries from the prior multi-file
  // session model are filtered out at load time.
  const [fileSessions, setFileSessionsRaw] = useState<FileSessionResponse[]>(() => {
    try {
      const stored = localStorage.getItem("datachat_file_sessions");
      if (stored) {
        const parsed = JSON.parse(stored) as FileSessionResponse[];
        return parsed.filter((s) => s.source_type === "duckdb");
      }
    } catch {}
    return [];
  });

  const setFileSessions = useCallback((sessions: FileSessionResponse[]) => {
    setFileSessionsRaw(sessions);
    if (sessions.length > 0) {
      localStorage.setItem("datachat_file_sessions", JSON.stringify(sessions));
    } else {
      localStorage.removeItem("datachat_file_sessions");
    }
  }, []);

  const addFileSession = useCallback((session: FileSessionResponse) => {
    setFileSessions([...fileSessions, session]);
  }, [fileSessions, setFileSessions]);

  const removeFileSession = useCallback((sessionId: string) => {
    api.deleteFileSession(sessionId).catch(() => {});
    setFileSessions(fileSessions.filter((s) => s.session_id !== sessionId));
  }, [fileSessions, setFileSessions]);

  // Add Data Source dialog state
  const [addSourceOpen, setAddSourceOpen] = useState(false);
  const [addSourceStep, setAddSourceStep] = useState(1);
  const [addSourceType, setAddSourceType] = useState<string | null>(null);
  const [addSourceName, setAddSourceName] = useState("");
  const [addSourceCreds, setAddSourceCreds] = useState<Record<string, string>>({});
  const [addSourceShowSecrets, setAddSourceShowSecrets] = useState<Record<string, boolean>>({});
  const [addSourceAuthMode, setAddSourceAuthMode] = useState<string | null>(null);
  const [fileUploadMode, setFileUploadMode] = useState<"excel_csv" | "local_upload" | "duckdb" | null>(null);
  const [isFileUploading, setIsFileUploading] = useState(false);

  const { data: rawWarehouseTypes } = useQuery({
    queryKey: ["warehouseTypes"],
    queryFn: api.getWarehouseTypes,
    staleTime: Infinity,
  });

  const fieldHints: Record<string, Record<string, string>> = {
    motherduck: {
      token: "Find your access token at app.motherduck.com → Settings → Access Tokens",
      database: "The name of your MotherDuck database (visible in the left sidebar)",
    },
    bigquery: {
      project_id: "Find in Google Cloud Console → Dashboard (top-left dropdown), e.g. my-project-123",
      credentials_json: "Download from Google Cloud Console → IAM → Service Accounts → Keys → Add Key → JSON",
    },
    snowflake: {
      account: "Your Snowflake account identifier, e.g. xy12345.us-east-1",
      username: "Your Snowflake login username",
      password: "Your Snowflake login password",
      warehouse: "The compute warehouse to use, e.g. COMPUTE_WH",
      database: "The database to query, e.g. ANALYTICS",
    },
    postgresql: {
      host: "The hostname or IP address of your PostgreSQL server",
      port: "The port number (default: 5432)",
      database: "The name of the database to connect to",
      username: "Your PostgreSQL username",
      password: "Your PostgreSQL password",
    },
    redshift: {
      workgroup: "Redshift Serverless console → Workgroups → your workgroup name",
      database: "Default is 'dev'. Find in Redshift console → Namespace → database name",
      access_key: "IAM → Users → your user → Security credentials → Create access key",
      secret_key: "Shown once when creating the access key — save it securely",
      region: "AWS region, e.g. us-east-1. Must match your Redshift location",
      host: "Cluster endpoint without port/database, e.g. my-cluster.xxxx.us-east-1.redshift.amazonaws.com",
      port: "Default is 5439",
      username: "The admin username set when creating the cluster",
      password: "The admin password set when creating the cluster",
      cluster_identifier: "The name of your provisioned cluster, e.g. my-redshift-cluster",
      db_user: "The database user to connect as, e.g. admin",
    },
  };

  const warehouseTypes = rawWarehouseTypes
    ? Object.fromEntries(
        Object.entries(rawWarehouseTypes).map(([key, config]) => [
          key,
          { ...config, field_hints: fieldHints[key] || {} },
        ])
      )
    : null;

  const warehouseLogos: Record<string, string> = {
    motherduck: "https://asset.brandfetch.io/idbSOOFEXo/idceZ_xUcy.png",
    bigquery: "https://cdn.worldvectorlogo.com/logos/google-bigquery-logo-1.svg",
    snowflake: "https://registry.npmmirror.com/@lobehub/icons-static-png/latest/files/dark/snowflake-color.png",
    postgresql: postgresqlLogo,
    redshift: redshiftLogo,
  };

  const resetAddSource = () => {
    setAddSourceStep(1);
    setAddSourceType(null);
    setAddSourceName("");
    setAddSourceCreds({});
    setAddSourceShowSecrets({});
    setAddSourceAuthMode(null);
    setFileUploadMode(null);
  };

  const sfConnectMutation = useMutation({
    mutationFn: api.connectSalesforce,
    onSuccess: (data) => {
      window.location.href = data.authorize_url;
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const addWarehouseMutation = useMutation({
    mutationFn: api.configureWarehouse,
    onSuccess: () => {
      toast.success("Warehouse connected!");
      queryClient.invalidateQueries({ queryKey: ["warehouses"] });
      setAddSourceOpen(false);
      resetAddSource();
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const handleFileUpload = async (file: File) => {
    setIsFileUploading(true);
    try {
      if (fileUploadMode === "duckdb") {
        // .duckdb files stay in the legacy in-memory file-session flow.
        const result = await api.uploadFile(file);
        addFileSession(result);
        setSelectedWarehouse(`file_${result.session_id}`);
      } else {
        // CSV / Excel / Parquet / JSON go into the persistent per-user LocalDuckDB.
        const result = await api.uploadLocalFile(file);
        await queryClient.invalidateQueries({ queryKey: ["localDuckdb"] });
        setSelectedWarehouse(`local_${result.local_duckdb_id}`);
      }
      toast.success("File loaded successfully!");
      setAddSourceOpen(false);
      resetAddSource();
    } catch (error: any) {
      toast.error(error.message || "Failed to upload file");
    } finally {
      setIsFileUploading(false);
    }
  };

  // Add-another-file flow: opens the Add Data Source dialog pre-pointed at the
  // CSV/Excel upload mode, which appends to the user's persistent LocalDuckDB.
  const handleAddLocalFileShortcut = () => {
    setFileUploadMode("excel_csv");
    setAddSourceOpen(true);
  };

  const selectedAddSourceConfig = addSourceType && warehouseTypes ? warehouseTypes[addSourceType] : null;

  // Inline rename state
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  // Visualization state
  const [expandedSqlMessages, setExpandedSqlMessages] = useState<Set<string>>(new Set());
  const [expandedVizMessages, setExpandedVizMessages] = useState<Set<string>>(new Set());
  const [saveVizData, setSaveVizData] = useState<{
    visualization: VisualizationConfig;
    chartData: Record<string, any>[];
    sqlQuery: string;
  } | null>(null);

  const saveVisualizationMutation = useMutation({
    mutationFn: api.saveVisualization,
    onSuccess: () => {
      setSaveVizData(null);
      toast.success("Visualization saved");
    },
    onError: (error: any) => {
      const msg = error?.status === 409 ? "This visualization has already been saved" : "Failed to save visualization";
      toast.error(msg);
    },
  });

  // Sidebar resize handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  };

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;
      const newWidth = Math.min(Math.max(e.clientX, 200), 500); // min 200px, max 500px
      setSidebarWidth(newWidth);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    if (isResizing) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
    }

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing]);

  // Load Clerk UserButton dynamically
  useEffect(() => {
    if (CLERK_ENABLED) {
      import("@clerk/clerk-react").then((mod) => {
        setClerkUserButton(() => mod.UserButton);
      });
    }
  }, []);

  // Fetch warehouses
  const { data: warehouses, isLoading: isLoadingWarehouses } = useQuery({
    queryKey: ["warehouses"],
    queryFn: api.listWarehouses,
  });

  // Fetch Salesforce status
  const { data: salesforceConnection } = useQuery({
    queryKey: ["salesforce"],
    queryFn: api.getSalesforceStatus,
  });

  // Fetch conversations
  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: api.listConversations,
  });

  // Fetch messages for current conversation
  const { data: messages, isFetching: isLoadingMessages } = useQuery({
    queryKey: ["messages", currentConversationId],
    queryFn: () => api.getConversationMessages(currentConversationId!),
    enabled: !!currentConversationId,
  });

  // Set initial data source (prefer localStorage, fall back to first connected source)
  useEffect(() => {
    // Validate the persistent LocalDuckDB selection
    if (selectedWarehouse && selectedWarehouse.startsWith("local_")) {
      const localId = selectedWarehouse.replace("local_", "");
      if (localDb && localDb.exists && localDb.id === localId) {
        return; // valid local selection
      }
      // Stale local selection — clear and let the auto-pick logic below run
      setSelectedWarehouse(null);
      return;
    }

    // Validate the .duckdb file session selection
    if (selectedWarehouse && selectedWarehouse.startsWith("file_")) {
      const fileId = selectedWarehouse.replace("file_", "");
      if (!fileSessions.find((fs) => fs.session_id === fileId)) {
        setSelectedWarehouse(null);
      } else {
        return;
      }
    }
    if (!selectedWarehouse) {
      // Prefer the persistent local DuckDB if any tables are loaded
      if (localDb?.exists && localDb.tables.length > 0 && localDb.id) {
        setSelectedWarehouse(`local_${localDb.id}`);
        return;
      }
      // Then any .duckdb file sessions (most recently added)
      if (fileSessions.length > 0) {
        setSelectedWarehouse(`file_${fileSessions[fileSessions.length - 1].session_id}`);
        return;
      }
      if (warehouses && warehouses.length > 0) {
        const connected = warehouses.find((w) => w.connection_status === "connected");
        if (connected) {
          setSelectedWarehouse(connected.id);
          return;
        }
      }
      if (salesforceConnection && salesforceConnection.connection_status === "connected") {
        setSelectedWarehouse(`sf_${salesforceConnection.id}`);
      }
    }
    // If saved selection no longer exists, reset
    if (selectedWarehouse && selectedWarehouse.startsWith("sf_")) {
      const sfId = selectedWarehouse.replace("sf_", "");
      if (salesforceConnection?.id !== sfId) {
        const connected = warehouses?.find((w) => w.connection_status === "connected");
        setSelectedWarehouse(connected?.id || null);
      }
    } else if (
      warehouses &&
      selectedWarehouse &&
      !selectedWarehouse.startsWith("file_") &&
      !selectedWarehouse.startsWith("local_") &&
      !warehouses.find((w) => w.id === selectedWarehouse)
    ) {
      const connected = warehouses.find((w) => w.connection_status === "connected");
      setSelectedWarehouse(connected?.id || (salesforceConnection ? `sf_${salesforceConnection.id}` : null));
    }
  }, [warehouses, selectedWarehouse, salesforceConnection, fileSessions, localDb]);

  // Persist warehouse selection
  useEffect(() => {
    if (selectedWarehouse) {
      localStorage.setItem("datachat_selected_warehouse", selectedWarehouse);
    }
  }, [selectedWarehouse]);

  // Sync currentConversationId with URL param
  useEffect(() => {
    setCurrentConversationId(conversationId || null);
    if (!conversationId) {
      setLocalMessages([]);
    }
  }, [conversationId]);

  // Update local messages when fetched (skip while sending to preserve optimistic state)
  useEffect(() => {
    if (messages && !isSendingRef.current) {
      setLocalMessages(messages);
    }
  }, [messages]);

  // Track whether the user is near the bottom of the message list. If they
  // scroll up during streaming, we stop forcing them back down. Uses a callback
  // ref because the ScrollArea is conditionally mounted.
  const scrollAreaRefCallback = useCallback((node: HTMLDivElement | null) => {
    detachScrollListenerRef.current?.();
    detachScrollListenerRef.current = null;
    if (!node) return;
    const viewport = node.querySelector<HTMLDivElement>("[data-radix-scroll-area-viewport]");
    if (!viewport) return;
    const onScroll = () => {
      const distance = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
      isNearBottomRef.current = distance < 80;
    };
    viewport.addEventListener("scroll", onScroll, { passive: true });
    detachScrollListenerRef.current = () => viewport.removeEventListener("scroll", onScroll);
  }, []);

  // Reset to auto-scroll when switching conversations
  useEffect(() => {
    isNearBottomRef.current = true;
  }, [currentConversationId]);

  // Auto-scroll only when the user is at (or near) the bottom. Use "auto"
  // instead of "smooth" so streaming chunks don't churn an animation, and so
  // intermediate animation positions don't get misread as user scrolling away.
  useEffect(() => {
    if (isNearBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
    }
  }, [localMessages, streaming.streamingText, streaming.toolCalls]);

  // Cancel query handler
  const handleCancel = useCallback(() => {
    streaming.cancel();
    isSendingRef.current = false;
    toast.info("Query cancelled");
  }, [streaming]);

  // Handle streaming completion — convert to final message
  useEffect(() => {
    if (streaming.doneData) {
      const data = streaming.doneData;
      isSendingRef.current = false;

      setLocalMessages((prev) => [
        ...prev,
        {
          id: data.message_id || crypto.randomUUID(),
          role: "assistant",
          content: data.response_text,
          created_at: new Date().toISOString(),
          duration_ms: data.duration_ms,
          input_tokens: data.input_tokens,
          output_tokens: data.output_tokens,
          visualization: data.visualization,
          chart_data: data.chart_data,
        },
      ]);

      if (!currentConversationId && data.conversation_id) {
        setCurrentConversationId(data.conversation_id);
        navigate(`/chat/${data.conversation_id}`, { replace: true });
      }

      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["messages", currentConversationId || data.conversation_id] });
      queryClient.invalidateQueries({ queryKey: ["currentUsage"] });

      if (data.usage_warning) {
        toast.warning(data.usage_warning);
      }

      streaming.reset();
    }
  }, [streaming.doneData]);

  // Handle streaming errors
  useEffect(() => {
    if (streaming.error) {
      isSendingRef.current = false;
      if (streaming.error.includes("Monthly limit") || streaming.error.includes("429")) {
        toast.error("Monthly limit reached. Please upgrade your plan.");
      } else {
        toast.error(streaming.error);
      }
      setLocalMessages((prev) => prev.slice(0, -1));
      streaming.reset();
    }
  }, [streaming.error]);

  // Escape key listener for cancelling queries
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && streaming.isStreaming) {
        handleCancel();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [streaming.isStreaming, handleCancel]);

  const handleSend = useCallback(async (messageOverride?: string) => {
    const message = messageOverride || input;
    if (!message.trim() || streaming.isStreaming) return;

    // Add to command history (avoid duplicates of last command)
    setCommandHistory((prev) => {
      if (prev[prev.length - 1] !== message) {
        return [...prev, message];
      }
      return prev;
    });
    setHistoryIndex(-1);
    setTempInput("");

    isSendingRef.current = true;
    // User just sent a message — re-anchor to the bottom for the new response.
    isNearBottomRef.current = true;

    setLocalMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: message,
        created_at: new Date().toISOString(),
      },
    ]);

    // Determine selection type: local DuckDB, file session, Salesforce, or warehouse
    const isSalesforce = selectedWarehouse?.startsWith("sf_");
    const isFileSource = selectedWarehouse?.startsWith("file_");
    const isLocalDuckdb = selectedWarehouse?.startsWith("local_");
    const warehouseId = (isSalesforce || isFileSource || isLocalDuckdb) ? undefined : (selectedWarehouse || undefined);
    const salesforceId = isSalesforce ? selectedWarehouse!.replace("sf_", "") : undefined;
    const fileSessionId = isFileSource ? selectedWarehouse!.replace("file_", "") : undefined;
    const localDuckdbId = isLocalDuckdb ? selectedWarehouse!.replace("local_", "") : undefined;

    // If this is a new conversation, create it first so it appears in the sidebar immediately
    let conversationId = currentConversationId || undefined;
    if (!conversationId) {
      try {
        const title = message.length > 50 ? message.slice(0, 50) + "..." : message;
        const newConversation = await api.createConversation({
          warehouse_id: warehouseId,
          salesforce_id: salesforceId,
          title,
        });
        conversationId = newConversation.id;
        setCurrentConversationId(newConversation.id);
        navigate(`/chat/${newConversation.id}`, { replace: true });
        queryClient.invalidateQueries({ queryKey: ["conversations"] });
      } catch (err) {
        // If conversation creation fails, fall back to letting the backend create it
        console.error("Failed to pre-create conversation:", err);
      }
    }

    streaming.sendMessage({
      message: message,
      conversation_id: conversationId,
      warehouse_id: warehouseId,
      salesforce_id: salesforceId,
      file_session_id: fileSessionId,
      local_duckdb_id: localDuckdbId,
      model: selectedModel || modelsData?.default,
    });

    setInput("");
    // Reset textarea height so the input box collapses back to its original size
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [input, streaming, currentConversationId, selectedWarehouse, selectedModel, modelsData]);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setInput(e.target.value);
    // Reset history navigation when user types
    if (historyIndex !== -1) {
      setHistoryIndex(-1);
      setTempInput("");
    }
  }, [historyIndex]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
      return;
    }

    // For multi-line prompts, only navigate command history when the cursor is
    // on the first/last line. Otherwise let the browser move the cursor within
    // the textarea normally.
    const target = e.currentTarget;
    const value = target.value;
    const start = target.selectionStart ?? 0;
    const end = target.selectionEnd ?? 0;
    const onFirstLine = !value.slice(0, start).includes("\n");
    const onLastLine = !value.slice(end).includes("\n");

    if (e.key === "ArrowUp" && onFirstLine) {
      if (commandHistory.length === 0) return;
      e.preventDefault();

      if (historyIndex === -1) {
        setTempInput(input);
      }

      const newIndex = historyIndex === -1
        ? commandHistory.length - 1
        : Math.max(0, historyIndex - 1);

      setHistoryIndex(newIndex);
      setInput(commandHistory[newIndex]);
    } else if (e.key === "ArrowDown" && onLastLine) {
      if (historyIndex === -1) return;
      e.preventDefault();

      const newIndex = historyIndex + 1;

      if (newIndex >= commandHistory.length) {
        setHistoryIndex(-1);
        setInput(tempInput);
      } else {
        setHistoryIndex(newIndex);
        setInput(commandHistory[newIndex]);
      }
    }
  }, [handleSend, commandHistory, historyIndex, input, tempInput]);

  const handleNewChat = useCallback(() => {
    setCurrentConversationId(null);
    setLocalMessages([]);
    navigate("/chat");
  }, [navigate]);

  const handleSelectConversation = useCallback((conv: Conversation) => {
    setCurrentConversationId(conv.id);
    if (conv.warehouse_id) {
      setSelectedWarehouse(conv.warehouse_id);
    }
    navigate(`/chat/${conv.id}`);
  }, [navigate]);

  const deleteConversation = useMutation({
    mutationFn: api.deleteConversation,
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (currentConversationId === deletedId) {
        // Navigate to the most recent remaining conversation
        const remaining = conversations?.filter((c) => c.id !== deletedId);
        if (remaining && remaining.length > 0) {
          handleSelectConversation(remaining[0]);
        } else {
          handleNewChat();
        }
      }
    },
  });

  const renameConversation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      api.renameConversation(id, title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setEditingConversationId(null);
    },
  });

  const handleStartRename = useCallback((conv: Conversation, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingConversationId(conv.id);
    setEditingTitle(conv.title);
  }, []);

  const handleSaveRename = useCallback((id: string) => {
    const trimmed = editingTitle.trim();
    if (trimmed && trimmed !== conversations?.find((c) => c.id === id)?.title) {
      renameConversation.mutate({ id, title: trimmed });
    } else {
      setEditingConversationId(null);
    }
  }, [editingTitle, conversations, renameConversation]);

  const hasDataSources =
    (warehouses && warehouses.length > 0) ||
    (salesforceConnection && salesforceConnection.connection_status === "connected") ||
    fileSessions.length > 0 ||
    !!(localDb?.exists && localDb.tables.length > 0);
  const currentConversation = useMemo(
    () => conversations?.find(c => c.id === currentConversationId),
    [conversations, currentConversationId]
  );
  // Only lock the conversation when its original warehouse is gone AND the user
  // has no other data source to fall back on. If they reconnect (or pick another
  // source) we re-route the new message through the current selection instead of
  // refusing to send.
  const isWarehouseDeleted = !!(
    currentConversation &&
    currentConversation.warehouse_id === null &&
    localMessages.length > 0 &&
    !hasDataSources
  );

  const handleFeedbackChange = useCallback((msgId: string, newFeedback: "like" | "dislike" | null) => {
    setLocalMessages((prev) =>
      prev.map((m) =>
        m.id === msgId ? { ...m, feedback: newFeedback } : m
      )
    );
  }, []);

  return (
    <div className={`h-screen flex bg-background ${isResizing ? "select-none" : ""}`}>
      {/* Sidebar */}
      <div
        className={`relative flex flex-col border-r ${!isResizing ? "transition-all duration-300" : ""}`}
        style={{ width: sidebarOpen ? sidebarWidth : 56 }}
      >
        {/* Resize handle - only when expanded */}
        {sidebarOpen && (
          <div
            className="absolute top-0 right-0 w-2 h-full cursor-col-resize z-10"
            style={{ transform: "translateX(50%)" }}
            onMouseDown={handleMouseDown}
          />
        )}

        {/* Collapsed sidebar - icon rail */}
        {!sidebarOpen && (
          <div className="flex flex-col items-center h-full w-full py-2">
            {/* Logo */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Link to="/chat" className="flex items-center justify-center h-10 w-10 mb-2">
                  <span className="text-lg font-semibold">dc</span>
                </Link>
              </TooltipTrigger>
              <TooltipContent side="right">datachat</TooltipContent>
            </Tooltip>

            {/* Expand sidebar */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-10 w-10 mb-1"
                  onClick={() => setSidebarOpen(true)}
                >
                  <PanelLeft className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">Expand sidebar</TooltipContent>
            </Tooltip>

            {/* New Chat */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon"
                  className="h-10 w-10 mb-1"
                  onClick={handleNewChat}
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">New Chat</TooltipContent>
            </Tooltip>

            {/* Spacer */}
            <div className="flex-1" />

            {/* Bottom nav icons */}
            <div className="flex flex-col items-center gap-1 pt-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Link to="/reports">
                    <Button variant="ghost" size="icon" className="h-10 w-10">
                      <BarChart3 className="h-4 w-4" />
                    </Button>
                  </Link>
                </TooltipTrigger>
                <TooltipContent side="right">Reports</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Link to="/context">
                    <Button variant="ghost" size="icon" className="h-10 w-10">
                      <FileText className="h-4 w-4" />
                    </Button>
                  </Link>
                </TooltipTrigger>
                <TooltipContent side="right">Context</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Link to="/settings">
                    <Button variant="ghost" size="icon" className="h-10 w-10">
                      <Settings className="h-4 w-4" />
                    </Button>
                  </Link>
                </TooltipTrigger>
                <TooltipContent side="right">Settings</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Link to="/usage">
                    <Button variant="ghost" size="icon" className="h-10 w-10">
                      <BarChart className="h-4 w-4" />
                    </Button>
                  </Link>
                </TooltipTrigger>
                <TooltipContent side="right">Usage</TooltipContent>
              </Tooltip>
            </div>
          </div>
        )}

        {/* Expanded sidebar - full content */}
        {sidebarOpen && (
          <div className="flex flex-col h-full w-full overflow-hidden">
            <div className="h-14 px-4 border-b flex items-center justify-between">
              <Link to="/chat" className="flex items-center">
                <span className="font-semibold">datachat</span>
              </Link>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => setSidebarOpen(false)}
              >
                <PanelLeftClose className="h-4 w-4" />
              </Button>
            </div>

            <div className="p-2">
              <Button className="w-full justify-start gap-2" onClick={handleNewChat}>
                <Plus className="h-4 w-4" />
                New Chat
              </Button>
            </div>

            <div className="flex-1 overflow-y-auto overflow-x-hidden p-2">
              <div className="space-y-1">
                {conversations?.map((conv) => (
                  <div
                    key={conv.id}
                    className={`group relative flex items-center gap-2 p-2 rounded-lg cursor-pointer hover:bg-muted ${
                      conv.id === currentConversationId ? "bg-muted" : ""
                    }`}
                    onClick={() => handleSelectConversation(conv)}
                  >
                    {editingConversationId === conv.id ? (
                      <input
                        className="flex-1 text-sm bg-background border border-border rounded px-1 py-0.5 outline-none focus:ring-1 focus:ring-ring"
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") handleSaveRename(conv.id);
                          if (e.key === "Escape") setEditingConversationId(null);
                        }}
                        onBlur={() => handleSaveRename(conv.id)}
                        onClick={(e) => e.stopPropagation()}
                        autoFocus
                      />
                    ) : (
                      <>
                        <div className="flex-1 min-w-0 flex items-center gap-2">
                          <span className="truncate text-sm">{conv.title}</span>
                          {isLoadingMessages && conv.id === currentConversationId && (
                            <Loader2 className="h-3 w-3 animate-spin shrink-0 text-muted-foreground" />
                          )}
                          <span className="text-[10px] text-muted-foreground whitespace-nowrap shrink-0">
                            {formatSidebarTimestamp(conv.created_at)}
                          </span>
                        </div>
                      </>
                    )}
                    {editingConversationId !== conv.id && (
                      <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 bg-muted rounded px-0.5">
                        <button
                          className="p-1 hover:text-blue-400"
                          onClick={(e) => handleStartRename(conv, e)}
                          title="Rename"
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                        <button
                          className="p-1 hover:text-destructive"
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteConversation.mutate(conv.id);
                          }}
                          title="Delete"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="p-4 space-y-1">
              <Link to="/reports">
                <Button variant="ghost" className="w-full justify-start gap-2">
                  <BarChart3 className="h-4 w-4" />
                  Reports
                </Button>
              </Link>
              <Link to="/context">
                <Button variant="ghost" className="w-full justify-start gap-2">
                  <FileText className="h-4 w-4" />
                  Context
                </Button>
              </Link>
              <Link to="/settings">
                <Button variant="ghost" className="w-full justify-start gap-2">
                  <Settings className="h-4 w-4" />
                  Settings
                </Button>
              </Link>
              <Link to="/usage">
                <Button variant="ghost" className="w-full justify-start gap-2">
                  <BarChart className="h-4 w-4" />
                  Usage
                </Button>
              </Link>
            </div>
          </div>
        )}
      </div>

      {/* Main content */}
      <div className="flex-1 flex flex-col">
        <MissingAnthropicKeyBanner />
        {/* Header */}
        <header className="h-14 border-b flex items-center justify-between px-4">
          <div className="flex items-center gap-2">
            {(hasDataSources || isWarehouseDeleted) && (
              <>
                {isWarehouseDeleted ? (
                  <div className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground border rounded-md min-w-48 opacity-60">
                    <Database className="h-4 w-4 shrink-0" />
                    <span>No warehouse connected</span>
                  </div>
                ) : (
                  <Select
                    value={selectedWarehouse || ""}
                    onValueChange={(val) => {
                      if (val === "__add_source__") {
                        setAddSourceOpen(true);
                      } else {
                        setSelectedWarehouse(val);
                      }
                    }}
                  >
                    <SelectTrigger className="w-auto min-w-48 max-w-72">
                      <Database className="h-4 w-4 mr-2 shrink-0" />
                      <SelectValue placeholder="Select data source" />
                    </SelectTrigger>
                    <SelectContent>
                      {localDb?.exists && localDb.id && localDb.tables.length > 0 && (
                        <>
                          <SelectItem
                            key={`local_${localDb.id}`}
                            value={`local_${localDb.id}`}
                          >
                            CSV/Local ({localDb.tables.length})
                          </SelectItem>
                          <div className="border-t my-1" />
                        </>
                      )}
                      {fileSessions.length > 0 && (
                        <>
                          {fileSessions.map((fs) => (
                            <SelectItem
                              key={`file_${fs.session_id}`}
                              value={`file_${fs.session_id}`}
                            >
                              {fs.metadata.filename}
                            </SelectItem>
                          ))}
                          <div className="border-t my-1" />
                        </>
                      )}
                      {warehouses?.map((w) => (
                        <SelectItem key={w.id} value={w.id}>
                          <span className="flex items-center gap-2">
                            {w.name}
                            {w.is_demo && (
                              <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                                Demo
                              </span>
                            )}
                          </span>
                        </SelectItem>
                      ))}
                      {salesforceConnection && salesforceConnection.connection_status === "connected" && (
                        <SelectItem
                          key={`sf_${salesforceConnection.id}`}
                          value={`sf_${salesforceConnection.id}`}
                          className={selectedWarehouse === `sf_${salesforceConnection.id}` ? "font-bold" : ""}
                        >
                          Salesforce - {salesforceConnection.org_name || "Connected"}
                        </SelectItem>
                      )}
                      <div className="border-t my-1" />
                      <SelectItem value="__add_source__">
                        <span className="flex items-center gap-2">
                          <Plus className="h-4 w-4" />
                          Add data source
                        </span>
                      </SelectItem>
                    </SelectContent>
                  </Select>
                )}
                {modelsData && selectedModel && (
                  <Select value={selectedModel} onValueChange={setSelectedModel}>
                    <SelectTrigger className="w-auto min-w-36">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {modelsData.models.map((m) => (
                        <SelectItem key={m.id} value={m.id}>{m.display_name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
                {selectedWarehouse?.startsWith("local_") && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="icon"
                        className="h-9 w-9"
                        onClick={handleAddLocalFileShortcut}
                        title="Add another file"
                      >
                        <Plus className="h-4 w-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Add another file (cross-file joins supported)</TooltipContent>
                  </Tooltip>
                )}
              </>
            )}
          </div>

          <div className="flex items-center gap-2">
            <ThemeToggle />
            {ClerkUserButton ? (
              <ClerkUserButton afterSignOutUrl="/" />
            ) : (
              <Button variant="ghost" size="icon">
                <User className="h-4 w-4" />
              </Button>
            )}
          </div>
        </header>


        {/* Welcome screens - centered */}
        {isLoadingWarehouses ? (
          <div className="flex-1 flex flex-col items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : !hasDataSources && !currentConversationId ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-4">
            <Database className="h-12 w-12 text-muted-foreground mb-4" />
            <h2 className="text-xl font-semibold mb-2">No Data Source Connected</h2>
            <p className="text-muted-foreground mb-4">
              Connect a data warehouse or database to start asking questions.
            </p>
            <Button onClick={() => setAddSourceOpen(true)}>Connect Data Source</Button>
          </div>
        ) : localMessages.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-4">
            <h1 className="text-3xl md:text-4xl font-semibold mb-8">
              {WELCOME_GREETINGS[greetingIndex]}
            </h1>
            <div className="w-full max-w-2xl mb-8">
              <div className="flex gap-2 items-end">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => { handleInputChange(e as any); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 150) + "px"; }}
                  placeholder="Ask a question about your data..."
                  onKeyDown={handleKeyDown as any}
                  disabled={streaming.isStreaming}
                  rows={1}
                  className="flex-1 min-h-[48px] max-h-[150px] resize-none rounded-md border border-input bg-background px-3 py-3 text-base ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                />
                {streaming.isStreaming ? (
                  <Button
                    onClick={handleCancel}
                    variant="outline"
                    className="group h-12 w-12"
                    title="Cancel query (Esc)"
                  >
                    <Loader2 className="h-4 w-4 animate-spin group-hover:hidden" />
                    <X className="h-4 w-4 hidden group-hover:block text-red-500" />
                  </Button>
                ) : (
                  <Button onClick={() => handleSend()} disabled={!input.trim()} className="h-12 w-12">
                    <ArrowUp className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {exampleQuestions.map((q) => (
                <button
                  key={q}
                  type="button"
                  className="px-3 py-1.5 text-sm bg-muted hover:bg-accent text-muted-foreground hover:text-foreground rounded-full border border-border transition-colors"
                  onClick={() => handleSend(q)}
                >
                  {q}
                </button>
              ))}
              <button
                type="button"
                className="px-3 py-1.5 text-sm bg-muted hover:bg-accent text-muted-foreground hover:text-foreground rounded-full border border-border transition-colors"
                onClick={() => handleSend("Validate my data")}
              >
                Validate my data
              </button>
              <button
                type="button"
                className="px-3 py-1.5 text-sm bg-muted hover:bg-accent text-muted-foreground hover:text-foreground rounded-full border border-border transition-colors"
                onClick={() => handleSend("Show me what tables I have")}
              >
                Show me what tables I have
              </button>
            </div>
          </div>
        ) : (
          /* Messages */
          <div className="flex-1 flex flex-col overflow-hidden relative">
            <UsageBanner />
            <ScrollArea ref={scrollAreaRefCallback} className="flex-1 p-4">
            <div className="max-w-3xl mx-auto space-y-4">
              {isWarehouseDeleted && (
                <div className="sticky top-0 z-10 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg flex items-center gap-2 text-sm text-amber-600 dark:text-amber-400 backdrop-blur-md">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span>The data warehouse connection for this conversation has been deleted. You can view the message history, but new messages cannot be sent.</span>
                </div>
              )}
              {localMessages.map((msg) => {
                // Extract SQL from content
                const sqlQueries = msg.role === "assistant" ? extractSqlBlocks(msg.content) : [];
                // Strip SQL from display content
                const displayContent = msg.role === "assistant" && sqlQueries.length > 0
                  ? stripSqlBlocks(msg.content)
                  : msg.content;

                return (
                  <div
                    key={msg.id}
                    className={`group/msg flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div className={msg.role === "user" ? "max-w-[80%]" : "max-w-[95%]"}>
                      <div
                        className={`rounded-lg px-4 py-2 text-sm ${
                          msg.role === "user"
                            ? "bg-accent text-foreground"
                            : "bg-muted text-foreground/90"
                        }`}
                      >
                        {msg.role === "assistant" ? (
                          <div className="[&>*]:mb-4 [&>*:last-child]:mb-0 [&_p]:leading-relaxed [&_p]:mb-4 [&_ul]:list-disc [&_ul]:pl-4 [&_ul]:mb-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_ol]:mb-4 [&_table]:w-full [&_table]:border-collapse [&_table]:my-5 [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1.5 [&_th]:bg-muted/50 [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1.5 [&_strong]:font-semibold [&_code]:bg-muted/50 [&_code]:px-1 [&_code]:rounded [&_pre]:bg-muted/50 [&_pre]:p-3 [&_pre]:rounded [&_pre]:overflow-x-auto [&_pre]:text-xs [&_pre]:my-5">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {displayContent}
                            </ReactMarkdown>
                          </div>
                        ) : (
                          <div className="whitespace-pre-wrap break-words">{msg.content}</div>
                        )}
                      </div>
                      {msg.role === "assistant" && (() => {
                        const sqlOpen = expandedSqlMessages.has(msg.id);
                        const hasViz = !!(msg.visualization && msg.chart_data);
                        const hasData = !!(msg.chart_data && msg.chart_data.length > 0);
                        const vizOpen = expandedVizMessages.has(msg.id);
                        const toggleSql = () => setExpandedSqlMessages(prev => {
                          const next = new Set(prev);
                          if (next.has(msg.id)) next.delete(msg.id);
                          else next.add(msg.id);
                          return next;
                        });
                        const toggleViz = () => setExpandedVizMessages(prev => {
                          const next = new Set(prev);
                          if (next.has(msg.id)) next.delete(msg.id);
                          else next.add(msg.id);
                          return next;
                        });
                        return (
                          <>
                            <div className="mt-2 flex items-center gap-3 flex-wrap">
                              {sqlQueries.length > 0 && (
                                <button
                                  onClick={toggleSql}
                                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                                >
                                  {sqlOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                                  <span>SQL {sqlQueries.length > 1 ? `(${sqlQueries.length} queries)` : "Query"}</span>
                                </button>
                              )}
                              {hasViz && !sqlOpen && (
                                <button
                                  onClick={toggleViz}
                                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                                >
                                  {vizOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                                  Visualize
                                </button>
                              )}
                              {hasData && (
                                <button
                                  onClick={() => downloadCsv(msg.chart_data!, `query-${msg.id.slice(0, 8)}.csv`)}
                                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                                  title="Download query results as CSV"
                                >
                                  <Upload className="h-3 w-3 rotate-180" />
                                  <span>Export/CSV</span>
                                </button>
                              )}
                              <CopyButton text={displayContent} label="Copy" />
                            </div>
                            {sqlOpen && (
                              <CollapsibleSqlContent queries={sqlQueries} />
                            )}
                            {hasViz && sqlOpen && (
                              <button
                                onClick={toggleViz}
                                className="mt-2 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                              >
                                {vizOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                                Visualize
                              </button>
                            )}
                            {hasViz && vizOpen && (
                              <InlineVisualization
                                visualization={msg.visualization!}
                                chartData={msg.chart_data!}
                                onSave={() => {
                                  const lastSql = sqlQueries[sqlQueries.length - 1] || "";
                                  setSaveVizData({
                                    visualization: msg.visualization!,
                                    chartData: msg.chart_data!,
                                    sqlQuery: lastSql,
                                  });
                                }}
                              />
                            )}
                          </>
                        );
                      })()}
                      {msg.role === "assistant" ? (
                        <ResponseMetadata
                          messageId={msg.id}
                          createdAt={msg.created_at}
                          durationMs={msg.duration_ms}
                          inputTokens={msg.input_tokens}
                          outputTokens={msg.output_tokens}
                          feedback={msg.feedback}
                          onFeedbackChange={(newFeedback) => handleFeedbackChange(msg.id, newFeedback)}
                        />
                      ) : (
                        <div className="mt-1 flex items-center justify-end gap-2 text-xs text-muted-foreground">
                          <div className="opacity-0 group-hover/msg:opacity-100 transition-opacity">
                            <CopyButton text={msg.content} label="Copy" />
                          </div>
                          <span>{formatTimestamp(msg.created_at)}</span>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
              {streaming.isStreaming && (
                <div className="flex justify-start">
                  <div className="max-w-[95%]">
                    {streaming.streamingText ? (
                      <div className="rounded-lg px-4 py-2 text-sm bg-muted text-foreground/90">
                        <div className="[&>*]:mb-4 [&>*:last-child]:mb-0 [&_p]:leading-relaxed [&_p]:mb-4 [&_ul]:list-disc [&_ul]:pl-4 [&_ul]:mb-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_ol]:mb-4 [&_table]:w-full [&_table]:border-collapse [&_table]:my-5 [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1.5 [&_th]:bg-muted/50 [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1.5 [&_strong]:font-semibold [&_code]:bg-muted/50 [&_code]:px-1 [&_code]:rounded [&_pre]:bg-muted/50 [&_pre]:p-3 [&_pre]:rounded [&_pre]:overflow-x-auto [&_pre]:text-xs [&_pre]:my-5">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {streaming.streamingText}
                          </ReactMarkdown>
                          <span className="streaming-cursor" />
                        </div>
                      </div>
                    ) : (
                      <div className="p-4">
                        <span className="loading-shimmer text-sm font-medium">
                          {streaming.toolCalls.length > 0
                            ? `Running ${streaming.toolCalls[streaming.toolCalls.length - 1].tool_name === "execute_sql" ? "SQL query" : streaming.toolCalls[streaming.toolCalls.length - 1].tool_name.replace(/_/g, " ")}...`
                            : streaming.statusMessage || "Preparing your query..."}
                        </span>
                      </div>
                    )}
                    {streaming.toolCalls.length > 0 && (
                      <div className="flex flex-wrap gap-2 mt-2 px-1">
                        {streaming.toolCalls.map((tc, i) => (
                          <div
                            key={i}
                            className="flex items-center gap-1.5 text-xs px-2 py-1 rounded-md bg-muted/50 border border-border text-muted-foreground"
                          >
                            {tc.status === "running" ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : tc.status === "completed" ? (
                              <Check className="h-3 w-3 text-green-500" />
                            ) : (
                              <X className="h-3 w-3 text-red-500" />
                            )}
                            <span>{tc.tool_name === "execute_sql" || tc.tool_name === "execute_query" ? "SQL" : tc.tool_name.replace(/_/g, " ")}</span>
                            {tc.tool_input?.sql && (
                              <span className="max-w-[200px] truncate text-muted-foreground/70 font-mono">
                                {tc.tool_input.sql.slice(0, 60)}
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>
          </div>
        )}

        {/* Input - only shown when in a conversation (greeting screen has its own input) */}
        {(hasDataSources || isWarehouseDeleted) && localMessages.length > 0 && (
          <div className="p-4 border-t">
            <div className="max-w-3xl mx-auto flex gap-2 items-end">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => { handleInputChange(e as any); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 150) + "px"; }}
                placeholder={isWarehouseDeleted ? "Chat disabled — warehouse connection deleted" : "Ask a question about your data..."}
                onKeyDown={handleKeyDown as any}
                disabled={streaming.isStreaming || isWarehouseDeleted}
                rows={1}
                className="flex-1 min-h-[36px] max-h-[150px] resize-none rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              />
              {streaming.isStreaming ? (
                <Button
                  onClick={handleCancel}
                  variant="outline"
                  className="group"
                  title="Cancel query (Esc)"
                >
                  <Loader2 className="h-4 w-4 animate-spin group-hover:hidden" />
                  <X className="h-4 w-4 hidden group-hover:block text-red-500" />
                </Button>
              ) : (
                <Button onClick={() => handleSend()} disabled={!input.trim() || isWarehouseDeleted}>
                  <ArrowUp className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        )}
      </div>

      {saveVizData && (
        <SaveVisualizationModal
          visualization={saveVizData.visualization}
          chartData={saveVizData.chartData}
          sqlQuery={saveVizData.sqlQuery}
          warehouseId={
            selectedWarehouse &&
            !selectedWarehouse.startsWith("local_") &&
            !selectedWarehouse.startsWith("file_") &&
            !selectedWarehouse.startsWith("sf_")
              ? selectedWarehouse
              : null
          }
          localDuckdbId={
            selectedWarehouse?.startsWith("local_")
              ? selectedWarehouse.replace("local_", "")
              : null
          }
          onSave={(data) => saveVisualizationMutation.mutate(data)}
          onClose={() => setSaveVizData(null)}
          isSaving={saveVisualizationMutation.isPending}
        />
      )}


      {/* Add Data Source Dialog */}
      <Dialog open={addSourceOpen} onOpenChange={(open) => {
        setAddSourceOpen(open);
        if (!open) resetAddSource();
      }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Data Source</DialogTitle>
            <DialogDescription>
              {fileUploadMode
                ? "Upload a file to start chatting with your data"
                : `Step ${addSourceStep} of 3: ${addSourceStep === 1 ? "Choose data source" : addSourceStep === 2 ? "Enter credentials" : "Name your connection"}`}
            </DialogDescription>
          </DialogHeader>

          {!fileUploadMode && (
            <div className="flex gap-2 mb-4">
              {[1, 2, 3].map((s) => (
                <div key={s} className={`flex-1 h-1 rounded ${s <= addSourceStep ? "bg-primary" : "bg-muted"}`} />
              ))}
            </div>
          )}

          {/* Step 1: Select data source */}
          {addSourceStep === 1 && !fileUploadMode && warehouseTypes && (
            <div className="grid md:grid-cols-2 gap-4">
              {Object.entries(warehouseTypes).map(([type, config]) => (
                <Card key={type} className="cursor-pointer hover:border-primary transition-colors" onClick={() => { setAddSourceType(type); setAddSourceCreds({}); setAddSourceStep(2); }}>
                  <CardHeader className="flex flex-row items-center gap-4">
                    <div className="w-12 h-12 rounded-lg bg-muted flex items-center justify-center overflow-hidden">
                      <img src={warehouseLogos[type]} alt={config.name} className="h-8 w-8 object-contain" />
                    </div>
                    <div>
                      <CardTitle className="text-lg">{config.name}</CardTitle>
                      <CardDescription>{config.description}</CardDescription>
                    </div>
                  </CardHeader>
                </Card>
              ))}
              <Card className="cursor-pointer hover:border-primary transition-colors" onClick={() => setFileUploadMode("duckdb")}>
                <CardHeader className="flex flex-row items-center gap-4">
                  <div className="w-12 h-12 rounded-lg bg-muted flex items-center justify-center overflow-hidden">
                    <img src={duckdbLogo} alt="DuckDB" className="h-8 w-8 object-contain" />
                  </div>
                  <div>
                    <CardTitle className="text-lg">DuckDB</CardTitle>
                    <CardDescription>Upload a .duckdb file</CardDescription>
                  </div>
                </CardHeader>
              </Card>
              {/* Salesforce */}
              <Card
                className={`cursor-pointer hover:border-primary transition-colors ${salesforceConnection ? "opacity-50 pointer-events-none" : ""}`}
                onClick={() => {
                  if (!salesforceConnection) {
                    setAddSourceOpen(false);
                    sfConnectMutation.mutate();
                  }
                }}
              >
                <CardHeader className="flex flex-row items-center gap-4">
                  <div className="w-12 h-12 rounded-lg bg-muted flex items-center justify-center overflow-hidden">
                    <img src={salesforceLogo} alt="Salesforce" className="h-8 w-8 object-contain" />
                  </div>
                  <div>
                    <CardTitle className="text-lg">Salesforce</CardTitle>
                    <CardDescription>{salesforceConnection ? "Already connected" : "CRM data via OAuth"}</CardDescription>
                  </div>
                </CardHeader>
              </Card>
              <Card className="cursor-pointer hover:border-primary transition-colors" onClick={() => setFileUploadMode("excel_csv")}>
                <CardHeader className="flex flex-row items-center gap-4">
                  <div className="w-12 h-12 rounded-lg bg-muted flex items-center justify-center overflow-hidden">
                    <img src={excelLogo} alt="Excel / CSV" className="h-8 w-8 object-contain" />
                  </div>
                  <div>
                    <CardTitle className="text-lg">Excel / CSV</CardTitle>
                    <CardDescription>Upload a spreadsheet or CSV file</CardDescription>
                  </div>
                </CardHeader>
              </Card>
              <Card className="cursor-pointer hover:border-primary transition-colors" onClick={() => setFileUploadMode("local_upload")}>
                <CardHeader className="flex flex-row items-center gap-4">
                  <div className="w-12 h-12 rounded-lg bg-muted flex items-center justify-center">
                    <Upload className="h-7 w-7 text-blue-500" />
                  </div>
                  <div>
                    <CardTitle className="text-lg">Local Upload</CardTitle>
                    <CardDescription>Parquet, JSON, or NDJSON files</CardDescription>
                  </div>
                </CardHeader>
              </Card>
            </div>
          )}

          {/* File upload flow */}
          {addSourceStep === 1 && fileUploadMode && (
            <FileUploadZone
              mode={fileUploadMode}
              onFileSelected={handleFileUpload}
              isUploading={isFileUploading}
              onBack={() => setFileUploadMode(null)}
            />
          )}

          {/* Step 2: Enter credentials */}
          {addSourceStep === 2 && selectedAddSourceConfig && (() => {
            const authModes = (selectedAddSourceConfig as any).auth_modes as Record<string, { label: string; required_fields: string[] }> | undefined;
            const currentAuthMode = authModes ? (addSourceAuthMode || Object.keys(authModes)[0]) : null;
            const activeFields = authModes && currentAuthMode
              ? authModes[currentAuthMode].required_fields
              : selectedAddSourceConfig.required_fields;
            return (
            <div className="space-y-4">
              <div className="flex items-center gap-2 mb-4">
                <Database className="h-5 w-5" />
                <span className="font-medium">{selectedAddSourceConfig.name} Credentials</span>
              </div>
              <div className="p-4 bg-green-500/5 border border-green-500/20 rounded-lg space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium text-green-600 dark:text-green-400">
                  <Shield className="h-4 w-4" />
                  Your credentials are secure
                </div>
                <ul className="text-xs text-muted-foreground space-y-1 ml-6 list-disc">
                  <li>Encrypted with AES-256 before storage</li>
                  <li>Never logged or exposed in responses</li>
                  <li>Only you can access your warehouse connection</li>
                  <li>We recommend using a read-only service account</li>
                  <li>Select which datasets and tables are queryable for full data governance control</li>
                </ul>
              </div>
              {authModes && (
                <div className="space-y-2">
                  <Label>Authentication Mode</Label>
                  <div className="flex gap-2">
                    {Object.entries(authModes).map(([mode, config]) => (
                      <button
                        key={mode}
                        type="button"
                        onClick={() => {
                          setAddSourceAuthMode(mode);
                          setAddSourceCreds({});
                          setAddSourceShowSecrets({});
                        }}
                        className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
                          (currentAuthMode) === mode
                            ? "border-primary bg-primary/10 text-primary font-medium"
                            : "border-border hover:border-primary/50"
                        }`}
                      >
                        {config.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {addSourceType === "redshift" && (
                <div className="p-3 bg-blue-500/5 border border-blue-500/20 rounded-lg space-y-1">
                  <p className="text-xs font-medium text-blue-600 dark:text-blue-400">Setup checklist</p>
                  <ul className="text-[10px] text-muted-foreground space-y-0.5 ml-4 list-disc">
                    {currentAuthMode === "serverless" && (
                      <>
                        <li>Create an IAM user with <span className="font-medium">AmazonRedshiftFullAccess</span> policy and generate access keys</li>
                        <li>In Redshift Serverless → Workgroup → Network & security: enable <span className="font-medium">Publicly accessible</span></li>
                      </>
                    )}
                    {currentAuthMode === "standard" && (
                      <li>Ensure the cluster is <span className="font-medium">Publicly accessible</span> (Cluster → Actions → Modify)</li>
                    )}
                    {currentAuthMode === "iam" && (
                      <>
                        <li>Create an IAM user with <span className="font-medium">AmazonRedshiftFullAccess</span> policy and generate access keys</li>
                        <li>Ensure the cluster is <span className="font-medium">Publicly accessible</span></li>
                      </>
                    )}
                    <li>VPC security group must allow <span className="font-medium">inbound TCP on port 5439</span></li>
                  </ul>
                </div>
              )}
              {activeFields.map((field: string) => {
                const isSecret = field.toLowerCase().includes("token") || field.toLowerCase().includes("password") || field.toLowerCase().includes("secret") || field.toLowerCase().includes("credentials");
                const isJson = field.toLowerCase().includes("json");
                const hint = addSourceType && (selectedAddSourceConfig as any)?.field_hints?.[field];
                return (
                  <div key={field} className="space-y-2">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor={field} className="capitalize">
                        {field.replace(/_/g, " ").replace(/\bjson\b/gi, "JSON").replace(/\bid\b/gi, "ID")}
                      </Label>
                      {hint && (
                        <div className="relative group">
                          <Info className="h-3.5 w-3.5 text-muted-foreground" />
                          <div className="absolute left-5 top-1/2 -translate-y-1/2 z-50 hidden group-hover:block w-64 px-3 py-1.5 text-sm rounded-md border bg-popover text-popover-foreground shadow-md">
                            {hint}
                          </div>
                        </div>
                      )}
                    </div>
                    <div className="relative">
                      {isJson ? (
                        <textarea
                          id={field}
                          value={addSourceCreds[field] || ""}
                          onChange={(e) => setAddSourceCreds((prev) => ({ ...prev, [field]: e.target.value }))}
                          placeholder="Paste your JSON here"
                          className="w-full min-h-[120px] px-3 py-2 text-sm rounded-md border border-input bg-background font-mono resize-y"
                        />
                      ) : (
                        <Input
                          id={field}
                          type={isSecret && !addSourceShowSecrets[field] ? "password" : "text"}
                          value={addSourceCreds[field] || ""}
                          onChange={(e) => setAddSourceCreds((prev) => ({ ...prev, [field]: e.target.value }))}
                          placeholder={`Enter ${field.replace(/_/g, " ")}`}
                          className="pr-10"
                        />
                      )}
                      {isSecret && !isJson && (
                        <button
                          type="button"
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          onClick={() => setAddSourceShowSecrets((prev) => ({ ...prev, [field]: !prev[field] }))}
                        >
                          {addSourceShowSecrets[field] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
              <div className="flex gap-3 pt-4">
                <Button variant="outline" onClick={() => setAddSourceStep(1)}>Back</Button>
                <Button onClick={() => setAddSourceStep(3)} disabled={!activeFields.every((f: string) => addSourceCreds[f])}>Continue</Button>
              </div>
            </div>
            );
          })()}

          {/* Step 3: Name connection */}
          {addSourceStep === 3 && selectedAddSourceConfig && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="conn-name">Connection Name</Label>
                <Input
                  id="conn-name"
                  value={addSourceName}
                  onChange={(e) => setAddSourceName(e.target.value)}
                  placeholder={`e.g., Production ${selectedAddSourceConfig.name}`}
                />
              </div>
              <div className="flex gap-3 pt-4">
                <Button variant="outline" onClick={() => setAddSourceStep(2)}>Back</Button>
                <Button
                  onClick={() => addWarehouseMutation.mutate({ warehouse_type: addSourceType!, name: addSourceName, credentials: addSourceCreds })}
                  disabled={!addSourceName || addWarehouseMutation.isPending}
                >
                  {addWarehouseMutation.isPending ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Connecting...</> : "Connect"}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
