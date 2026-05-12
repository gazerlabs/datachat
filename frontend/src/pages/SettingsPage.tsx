import { useState, useMemo, useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, SchemaPreview, SalesforceConnection, FileSessionResponse, LocalDuckDBStatus } from "@/lib/api";
import { UserAvatar } from "@/components/UserAvatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { ThemeToggle } from "@/components/ThemeToggle";
import { toast } from "sonner";
import {
  Database,
  Plus,
  Trash2,
  RefreshCw,
  CheckCircle,
  XCircle,
  Loader2,
  ArrowLeft,
  Eye,
  EyeOff,
  Check,
  ArrowUpRight,
  Info,
  Shield,
  ShieldCheck,
  ChevronDown,
  ChevronRight,
  Lock,
  Cloud,
  Unplug,
  Upload,
  FileText,
  Mail,
} from "lucide-react";
import postgresqlLogo from "@/assets/postgresql-logo.svg";
import salesforceLogo from "@/assets/salesforce-logo.svg";
import excelLogo from "@/assets/excel-logo.svg";
import duckdbLogo from "@/assets/duckdb-logo.svg";
import redshiftLogo from "@/assets/redshift-logo.png";
import FileUploadZone from "@/components/FileUploadZone";
import { AnthropicKeyCard } from "@/components/AnthropicKeyCard";

// Static warehouse options (fallback if API unavailable)
const staticWarehouseTypes: Record<string, { name: string; description: string; required_fields: string[]; field_hints?: Record<string, string> }> = {
  motherduck: {
    name: "MotherDuck",
    description: "Cloud DuckDB - serverless analytics",
    required_fields: ["token", "database"],
    field_hints: {
      token: "Find your access token at app.motherduck.com → Settings → Access Tokens",
      database: "The name of your MotherDuck database (visible in the left sidebar)",
    },
  },
  bigquery: {
    name: "BigQuery",
    description: "Google Cloud data warehouse",
    required_fields: ["project_id", "credentials_json"],
    field_hints: {
      project_id: "Find in Google Cloud Console → Dashboard (top-left dropdown), e.g. my-project-123",
      credentials_json: "Download from Google Cloud Console → IAM → Service Accounts → Keys → Add Key → JSON",
    },
  },
  snowflake: {
    name: "Snowflake",
    description: "Data Cloud platform",
    required_fields: ["account", "username", "password", "warehouse", "database"],
    field_hints: {
      account: "Your Snowflake account identifier, e.g. xy12345.us-east-1",
      username: "Your Snowflake login username",
      password: "Your Snowflake login password",
      warehouse: "The compute warehouse to use, e.g. COMPUTE_WH",
      database: "The database to query, e.g. ANALYTICS",
    },
  },
  postgresql: {
    name: "PostgreSQL",
    description: "PostgreSQL database",
    required_fields: ["host", "port", "database", "username", "password"],
    field_hints: {
      host: "The hostname or IP address of your PostgreSQL server",
      port: "The port number (default: 5432)",
      database: "The name of the database to connect to",
      username: "Your PostgreSQL username",
      password: "Your PostgreSQL password",
    },
  },
  redshift: {
    name: "Amazon Redshift",
    description: "Amazon Redshift data warehouse",
    required_fields: ["workgroup", "database", "access_key", "secret_key", "region"],
    field_hints: {
      // Serverless
      workgroup: "Redshift Serverless console → Workgroups → your workgroup name",
      // Shared
      database: "Default is 'dev'. Find in Redshift console → Namespace → database name",
      access_key: "IAM → Users → your user → Security credentials → Create access key",
      secret_key: "Shown once when creating the access key — save it securely",
      region: "AWS region, e.g. us-east-1. Must match your Redshift location",
      // Standard
      host: "Cluster endpoint without port/database, e.g. my-cluster.xxxx.us-east-1.redshift.amazonaws.com",
      port: "Default is 5439",
      username: "The admin username set when creating the cluster",
      password: "The admin password set when creating the cluster",
      // IAM
      cluster_identifier: "The name of your provisioned cluster, e.g. my-redshift-cluster",
      db_user: "The database user to connect as, e.g. admin",
    },
  },
};

const warehouseLogos: Record<string, string> = {
  motherduck: "https://asset.brandfetch.io/idbSOOFEXo/idceZ_xUcy.png",
  bigquery: "https://cdn.worldvectorlogo.com/logos/google-bigquery-logo-1.svg",
  snowflake: "https://registry.npmmirror.com/@lobehub/icons-static-png/latest/files/dark/snowflake-color.png",
  postgresql: postgresqlLogo,
  redshift: redshiftLogo,
  salesforce: salesforceLogo,
};

const PLAN_LIMITS: Record<string, { warehouses: string; tokens: string; displayName: string }> = {
  free: { warehouses: "1", tokens: "1M tokens", displayName: "Free" },
  starter: { warehouses: "Unlimited", tokens: "5M tokens", displayName: "Starter" },
  pro: { warehouses: "Unlimited", tokens: "25M tokens", displayName: "Pro" },
};

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [step, setStep] = useState(1);
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [authMode, setAuthMode] = useState<string | null>(null);
  const [upgradeError, setUpgradeError] = useState<string | null>(null);

  // Schema preview state
  const [expandedWarehouse, setExpandedWarehouse] = useState<string | null>(null);
  const [schemaData, setSchemaData] = useState<Record<string, SchemaPreview>>({});
  const [schemaLoading, setSchemaLoading] = useState<string | null>(null);
  const [expandedDatasets, setExpandedDatasets] = useState<Set<string>>(new Set());
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set());

  // Read-only verification state
  const [verifyingWarehouse, setVerifyingWarehouse] = useState<string | null>(null);

  // Allowlist dialog state
  const [allowlistWarehouse, setAllowlistWarehouse] = useState<string | null>(null);
  const [allowlistSchema, setAllowlistSchema] = useState<SchemaPreview | null>(null);
  const [allowlistLoading, setAllowlistLoading] = useState(false);
  const [allowlistSaving, setAllowlistSaving] = useState(false);
  const [selectedTables, setSelectedTables] = useState<Set<string>>(new Set());
  const [allowlistMode, setAllowlistMode] = useState<"all" | "selected">("all");

  // Salesforce allowlist state
  const [sfAllowlistOpen, setSfAllowlistOpen] = useState(false);
  const [sfAllowlistLoading, setSfAllowlistLoading] = useState(false);
  const [sfAllowlistSaving, setSfAllowlistSaving] = useState(false);
  const [sfObjects, setSfObjects] = useState<{ name: string; label: string }[]>([]);
  const [sfSelectedObjects, setSfSelectedObjects] = useState<Set<string>>(new Set());
  const [sfAllowlistMode, setSfAllowlistMode] = useState<"all" | "selected">("all");

  // File upload state
  const [fileUploadMode, setFileUploadMode] = useState<"excel_csv" | "local_upload" | "duckdb" | null>(null);
  const [isFileUploading, setIsFileUploading] = useState(false);

  // .duckdb file sessions from localStorage. Excel/CSV/Parquet/JSON now live in
  // the persistent per-user LocalDuckDB (queried separately via React Query below).
  const [fileSessions, setFileSessions] = useState<FileSessionResponse[]>(() => {
    try {
      const raw: FileSessionResponse[] = JSON.parse(localStorage.getItem("datachat_file_sessions") || "[]");
      return raw.filter((s) => s.source_type === "duckdb");
    } catch { return []; }
  });

  const removeLocalFileSession = (sessionId: string) => {
    api.deleteFileSession(sessionId).catch(() => {});
    const updated = fileSessions.filter((s) => s.session_id !== sessionId);
    setFileSessions(updated);
    if (updated.length > 0) {
      localStorage.setItem("datachat_file_sessions", JSON.stringify(updated));
    } else {
      localStorage.removeItem("datachat_file_sessions");
    }
    // Clear selection if this was selected
    const selected = localStorage.getItem("datachat_selected_warehouse");
    if (selected === `file_${sessionId}`) {
      localStorage.removeItem("datachat_selected_warehouse");
    }
  };

  // Delete account state
  const [deleteStep, setDeleteStep] = useState<0 | 1 | 2>(0);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");

  const [searchParams, setSearchParams] = useSearchParams();

  const { data: warehouses, isLoading } = useQuery({
    queryKey: ["warehouses"],
    queryFn: api.listWarehouses,
  });

  const { data: warehouseTypes } = useQuery({
    queryKey: ["warehouseTypes"],
    queryFn: api.getWarehouseTypes,
  });

  const { data: usage } = useQuery({
    queryKey: ["usage"],
    queryFn: api.getUsageSummary,
  });

  const { data: runtimeConfig } = useQuery({
    queryKey: ["runtime-config"],
    queryFn: api.getConfig,
    staleTime: Infinity,
  });
  const billingEnabled = runtimeConfig?.billing_enabled !== false; // default true while loading, hide only when explicitly false

  const { data: salesforceConnection, isLoading: sfLoading } = useQuery({
    queryKey: ["salesforce"],
    queryFn: api.getSalesforceStatus,
  });

  const { data: localDb } = useQuery<LocalDuckDBStatus>({
    queryKey: ["localDuckdb"],
    queryFn: api.getLocalDuckdb,
    staleTime: 30_000,
  });

  // Handle URL params for checkout and Salesforce OAuth callback
  useEffect(() => {
    if (searchParams.get("checkout") === "success") {
      toast.success("Subscription activated!");
      queryClient.invalidateQueries({ queryKey: ["usage"] });
      searchParams.delete("checkout");
      setSearchParams(searchParams, { replace: true });
    }
    if (searchParams.get("salesforce") === "success") {
      toast.success("Salesforce connected!");
      queryClient.invalidateQueries({ queryKey: ["salesforce"] });
      searchParams.delete("salesforce");
      setSearchParams(searchParams, { replace: true });
    }
    if (searchParams.get("salesforce") === "error") {
      const reason = searchParams.get("reason") || "unknown error";
      toast.error(`Salesforce connection failed: ${reason}`);
      searchParams.delete("salesforce");
      searchParams.delete("reason");
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams, queryClient]);

  const testMutation = useMutation({
    mutationFn: api.testWarehouse,
    onSuccess: (data) => {
      if (data.success) {
        toast.success("Connection successful!");
      } else {
        toast.error(data.error || "Connection failed", { duration: Infinity });
      }
      queryClient.invalidateQueries({ queryKey: ["warehouses"] });
    },
    onError: (error: Error) => {
      toast.error(error.message, { duration: Infinity });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: api.deleteWarehouse,
    onSuccess: () => {
      toast.success("Warehouse deleted");
      queryClient.invalidateQueries({ queryKey: ["warehouses"] });
    },
    onError: (error: Error) => {
      toast.error(error.message, { duration: Infinity });
    },
  });

  const deleteAccountMutation = useMutation({
    mutationFn: api.deleteAccount,
    onSuccess: async () => {
      setDeleteStep(0);
      setDeleteConfirmText("");
      toast.success("Account deleted successfully");
      // Sign out via Clerk if available, then redirect
      try {
        await window.Clerk?.signOut();
      } catch {
        // Clerk not available (dev mode)
      }
      navigate("/");
    },
    onError: (error: Error) => {
      toast.error(error.message, { duration: Infinity });
    },
  });

  const sfConnectMutation = useMutation({
    mutationFn: api.connectSalesforce,
    onSuccess: (data) => {
      window.location.href = data.authorize_url;
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const sfTestMutation = useMutation({
    mutationFn: api.testSalesforce,
    onSuccess: (data) => {
      if (data.success) {
        toast.success("Salesforce connection active!");
      } else {
        toast.error(data.error || "Connection test failed");
      }
      queryClient.invalidateQueries({ queryKey: ["salesforce"] });
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const sfDisconnectMutation = useMutation({
    mutationFn: api.disconnectSalesforce,
    onSuccess: () => {
      toast.success("Salesforce disconnected");
      queryClient.invalidateQueries({ queryKey: ["salesforce"] });
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const addMutation = useMutation({
    mutationFn: api.configureWarehouse,
    onSuccess: () => {
      toast.success("Warehouse connected!");
      queryClient.invalidateQueries({ queryKey: ["warehouses"] });
      setAddDialogOpen(false);
      resetForm();
    },
    onError: (error: Error) => {
      // Check if it's a warehouse limit error - show in dialog instead of navigating away
      if (error.message.includes("warehouse connection") || error.message.includes("Upgrade")) {
        setUpgradeError(error.message);
      } else {
        toast.error(error.message, { duration: Infinity });
      }
    },
  });

  const handleFileSelected = async (file: File) => {
    setIsFileUploading(true);
    try {
      if (fileUploadMode === "duckdb") {
        // .duckdb files stay in the legacy in-memory file-session flow.
        const result = await api.uploadFile(file);
        const updated = [...fileSessions, result];
        setFileSessions(updated);
        localStorage.setItem("datachat_file_sessions", JSON.stringify(updated));
        localStorage.setItem("datachat_selected_warehouse", `file_${result.session_id}`);
      } else {
        // CSV / Excel / Parquet / JSON go into the persistent per-user LocalDuckDB.
        const result = await api.uploadLocalFile(file);
        await queryClient.invalidateQueries({ queryKey: ["localDuckdb"] });
        localStorage.setItem("datachat_selected_warehouse", `local_${result.local_duckdb_id}`);
      }
      toast.success("File loaded successfully!");
      setAddDialogOpen(false);
      resetForm();
    } catch (error: any) {
      toast.error(error.message || "Failed to upload file");
    } finally {
      setIsFileUploading(false);
    }
  };

  const handleDeleteLocalTable = async (tableId: string) => {
    try {
      await api.deleteLocalTable(tableId);
      await queryClient.invalidateQueries({ queryKey: ["localDuckdb"] });
      toast.success("Table removed");
    } catch (error: any) {
      toast.error(error.message || "Failed to remove table");
    }
  };

  const handleDeleteAllLocal = async () => {
    try {
      await api.deleteLocalDuckdb();
      await queryClient.invalidateQueries({ queryKey: ["localDuckdb"] });
      const selected = localStorage.getItem("datachat_selected_warehouse");
      if (selected?.startsWith("local_")) {
        localStorage.removeItem("datachat_selected_warehouse");
      }
      toast.success("Local data source removed");
    } catch (error: any) {
      toast.error(error.message || "Failed to remove local data source");
    }
  };

  const resetForm = () => {
    setStep(1);
    setSelectedType(null);
    setName("");
    setCredentials({});
    setShowSecrets({});
    setAuthMode(null);
    setUpgradeError(null);
    setFileUploadMode(null);
  };

  const handleSelectType = (type: string) => {
    setSelectedType(type);
    setCredentials({});
    setAuthMode(null);
    setStep(2);
  };

  const handleCredentialChange = (field: string, value: string) => {
    setCredentials((prev) => ({ ...prev, [field]: value }));
  };

  // Use API data if available, otherwise fall back to static options
  // Merge static field_hints into API data since the API doesn't return them
  const allWarehouseTypes = useMemo(() =>
    warehouseTypes
      ? Object.fromEntries(
          Object.entries(warehouseTypes).map(([key, config]) => [
            key,
            { ...config, field_hints: { ...staticWarehouseTypes[key]?.field_hints, ...config.field_hints } },
          ])
        )
      : staticWarehouseTypes,
    [warehouseTypes]
  );

  // Schema preview handlers
  const handleToggleSchema = async (warehouseId: string) => {
    if (expandedWarehouse === warehouseId) {
      setExpandedWarehouse(null);
      return;
    }
    setExpandedWarehouse(warehouseId);
    if (!schemaData[warehouseId]) {
      setSchemaLoading(warehouseId);
      try {
        const data = await api.getWarehouseSchema(warehouseId);
        setSchemaData((prev) => ({ ...prev, [warehouseId]: data }));
      } catch (error: any) {
        toast.error(error.message || "Failed to fetch schema");
        setExpandedWarehouse(null);
      } finally {
        setSchemaLoading(null);
      }
    }
  };

  const toggleDataset = (key: string) => {
    setExpandedDatasets((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleTable = (key: string) => {
    setExpandedTables((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Read-only verification
  const handleVerifyReadOnly = async (warehouseId: string) => {
    setVerifyingWarehouse(warehouseId);
    try {
      const result = await api.verifyReadOnly(warehouseId);
      if (result.is_read_only) {
        toast.success("Verified: read-only access");
      } else {
        toast("This account has write access. Consider using a read-only service account.");
      }
      queryClient.invalidateQueries({ queryKey: ["warehouses"] });
    } catch (error: any) {
      toast.error(error.message || "Verification failed");
    } finally {
      setVerifyingWarehouse(null);
    }
  };

  // Allowlist handlers
  const handleOpenAllowlist = async (warehouseId: string) => {
    setAllowlistWarehouse(warehouseId);
    setAllowlistLoading(true);
    try {
      const [schema, allowlist] = await Promise.all([
        schemaData[warehouseId]
          ? Promise.resolve(schemaData[warehouseId])
          : api.getWarehouseSchema(warehouseId),
        api.getWarehouseAllowlist(warehouseId),
      ]);
      setAllowlistSchema(schema);
      if (!schemaData[warehouseId]) {
        setSchemaData((prev) => ({ ...prev, [warehouseId]: schema }));
      }
      if (allowlist.allowed_tables) {
        setAllowlistMode("selected");
        setSelectedTables(new Set(allowlist.allowed_tables));
      } else {
        setAllowlistMode("all");
        const allTables = new Set(
          schema.tables.map((t) => `${t.dataset}.${t.table}`)
        );
        setSelectedTables(allTables);
      }
    } catch (error: any) {
      toast.error(error.message || "Failed to load allowlist");
      setAllowlistWarehouse(null);
    } finally {
      setAllowlistLoading(false);
    }
  };

  const handleSaveAllowlist = async () => {
    if (!allowlistWarehouse) return;
    setAllowlistSaving(true);
    try {
      const tables =
        allowlistMode === "all" ? null : Array.from(selectedTables);
      await api.updateWarehouseAllowlist(allowlistWarehouse, tables);
      toast.success(
        allowlistMode === "all"
          ? "All tables are now accessible"
          : `Access restricted to ${selectedTables.size} table(s)`
      );
      setAllowlistWarehouse(null);
    } catch (error: any) {
      toast.error(error.message || "Failed to save allowlist");
    } finally {
      setAllowlistSaving(false);
    }
  };

  // Salesforce allowlist handlers
  const handleOpenSfAllowlist = async () => {
    setSfAllowlistOpen(true);
    setSfAllowlistLoading(true);
    try {
      const [objectsData, allowlistData] = await Promise.all([
        api.getSalesforceObjects(),
        api.getSalesforceAllowlist(),
      ]);
      setSfObjects(objectsData.objects);
      if (allowlistData.allowed_objects) {
        setSfAllowlistMode("selected");
        setSfSelectedObjects(new Set(allowlistData.allowed_objects));
      } else {
        setSfAllowlistMode("all");
        setSfSelectedObjects(new Set(objectsData.objects.map((o) => o.name)));
      }
    } catch (error: any) {
      toast.error(error.message || "Failed to load Salesforce objects");
      setSfAllowlistOpen(false);
    } finally {
      setSfAllowlistLoading(false);
    }
  };

  const handleSaveSfAllowlist = async () => {
    setSfAllowlistSaving(true);
    try {
      const objects = sfAllowlistMode === "all" ? null : Array.from(sfSelectedObjects);
      await api.updateSalesforceAllowlist(objects);
      toast.success(
        sfAllowlistMode === "all"
          ? "All objects are now accessible"
          : `Access restricted to ${sfSelectedObjects.size} object(s)`
      );
      setSfAllowlistOpen(false);
    } catch (error: any) {
      toast.error(error.message || "Failed to save allowlist");
    } finally {
      setSfAllowlistSaving(false);
    }
  };

  const handleAddWarehouse = () => {
    if (!selectedType || !name) return;
    addMutation.mutate({
      warehouse_type: selectedType,
      name,
      credentials,
    });
  };

  const selectedConfig = selectedType && allWarehouseTypes ? allWarehouseTypes[selectedType] : null;
  const activeRequiredFields = (() => {
    const modes = (selectedConfig as any)?.auth_modes;
    if (modes) {
      const mode = authMode || Object.keys(modes)[0];
      return modes[mode]?.required_fields || selectedConfig?.required_fields;
    }
    return selectedConfig?.required_fields;
  })();
  const isFormValid = selectedType && name && activeRequiredFields?.every((f: string) => credentials[f]);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link to="/chat">
              <Button variant="ghost" size="icon">
                <ArrowLeft className="h-4 w-4" />
              </Button>
            </Link>
            <span className="font-semibold">Settings</span>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <UserAvatar afterSignOutUrl="/" />
          </div>
        </div>
      </header>

      <main className="container max-w-3xl mx-auto py-8 px-4">
        {/* Anthropic API key (admin only — card hides itself for non-admins) */}
        <AnthropicKeyCard />

        {/* Data Sources Section */}
        <Card className="mb-8">
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Database className="h-5 w-5" />
                Connected Data Sources
              </CardTitle>
              <CardDescription>
                Manage your data connections
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Dialog open={addDialogOpen} onOpenChange={(open) => {
                setAddDialogOpen(open);
                if (!open) resetForm();
              }}>
                <DialogTrigger asChild>
                  <Button className="gap-2">
                    <Plus className="h-4 w-4" />
                    Add Data Source
                  </Button>
                </DialogTrigger>
              <DialogContent className="max-w-2xl">
                <DialogHeader>
                  <DialogTitle>Add Data Source</DialogTitle>
                  <DialogDescription>
                    Step {step} of 3: {step === 1 ? "Choose data source" : step === 2 ? "Enter credentials" : "Name your connection"}
                  </DialogDescription>
                </DialogHeader>

                {/* Progress */}
                <div className="flex gap-2 mb-4">
                  {[1, 2, 3].map((s) => (
                    <div
                      key={s}
                      className={`flex-1 h-1 rounded ${s <= step ? "bg-primary" : "bg-muted"}`}
                    />
                  ))}
                </div>

                {/* Step 1: Select Data Source */}
                {step === 1 && !fileUploadMode && (
                  <div className="grid md:grid-cols-2 gap-4">
                    {Object.entries(allWarehouseTypes).map(([type, config]) => (
                      <Card
                        key={type}
                        className="cursor-pointer hover:border-primary transition-colors"
                        onClick={() => handleSelectType(type)}
                      >
                        <CardHeader className="flex flex-row items-center gap-4">
                          <div className="w-12 h-12 rounded-lg bg-muted flex items-center justify-center overflow-hidden">
                            <img
                              src={warehouseLogos[type]}
                              alt={config.name}
                              className="h-8 w-8 object-contain"
                            />
                          </div>
                          <div>
                            <CardTitle className="text-lg">{config.name}</CardTitle>
                            <CardDescription>{config.description}</CardDescription>
                          </div>
                        </CardHeader>
                      </Card>
                    ))}
                    {/* DuckDB */}
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
                    {/* Salesforce option */}
                    <Card
                      className={`cursor-pointer hover:border-primary transition-colors ${salesforceConnection ? "opacity-50 pointer-events-none" : ""}`}
                      onClick={() => {
                        if (!salesforceConnection) {
                          setAddDialogOpen(false);
                          sfConnectMutation.mutate();
                        }
                      }}
                    >
                      <CardHeader className="flex flex-row items-center gap-4">
                        <div className="w-12 h-12 rounded-lg bg-muted flex items-center justify-center overflow-hidden">
                          <img
                            src={warehouseLogos.salesforce}
                            alt="Salesforce"
                            className="h-8 w-8 object-contain"
                          />
                        </div>
                        <div>
                          <CardTitle className="text-lg">Salesforce</CardTitle>
                          <CardDescription>
                            {salesforceConnection ? "Already connected" : "CRM data via OAuth"}
                          </CardDescription>
                        </div>
                      </CardHeader>
                    </Card>
                    {/* Excel / CSV */}
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
                    {/* Local Upload */}
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

                {/* File Upload flow */}
                {step === 1 && fileUploadMode && (
                  <FileUploadZone
                    mode={fileUploadMode}
                    onFileSelected={handleFileSelected}
                    isUploading={isFileUploading}
                    onBack={() => setFileUploadMode(null)}
                  />
                )}

                {/* Step 2: Enter Credentials */}
                {step === 2 && selectedConfig && (() => {
                  const cfgAuthModes = (selectedConfig as any).auth_modes as Record<string, { label: string; required_fields: string[] }> | undefined;
                  const currentMode = cfgAuthModes ? (authMode || Object.keys(cfgAuthModes)[0]) : null;
                  const activeFields = cfgAuthModes && currentMode
                    ? cfgAuthModes[currentMode].required_fields
                    : selectedConfig.required_fields;
                  return (
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 mb-4">
                      <Database className="h-5 w-5" />
                      <span className="font-medium">{selectedConfig.name} Credentials</span>
                    </div>
                    <p className="text-sm text-muted-foreground mb-4">
                      Enter your connection details. Credentials are encrypted at rest.
                    </p>
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

                    {cfgAuthModes && (
                      <div className="space-y-2">
                        <Label>Authentication Mode</Label>
                        <div className="flex gap-2">
                          {Object.entries(cfgAuthModes).map(([mode, config]) => (
                            <button
                              key={mode}
                              type="button"
                              onClick={() => {
                                setAuthMode(mode);
                                setCredentials({});
                                setShowSecrets({});
                              }}
                              className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
                                currentMode === mode
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

                    {selectedType === "redshift" && (
                      <div className="p-3 bg-blue-500/5 border border-blue-500/20 rounded-lg space-y-1">
                        <p className="text-xs font-medium text-blue-600 dark:text-blue-400">Setup checklist</p>
                        <ul className="text-[10px] text-muted-foreground space-y-0.5 ml-4 list-disc">
                          {currentMode === "serverless" && (
                            <>
                              <li>Create an IAM user with <span className="font-medium">AmazonRedshiftFullAccess</span> policy and generate access keys</li>
                              <li>In Redshift Serverless → Workgroup → Network & security: enable <span className="font-medium">Publicly accessible</span></li>
                            </>
                          )}
                          {currentMode === "standard" && (
                            <li>Ensure the cluster is <span className="font-medium">Publicly accessible</span> (Cluster → Actions → Modify)</li>
                          )}
                          {currentMode === "iam" && (
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
                      const isSecret =
                        field.toLowerCase().includes("token") ||
                        field.toLowerCase().includes("password") ||
                        field.toLowerCase().includes("secret") ||
                        field.toLowerCase().includes("credentials");
                      const isJson = field.toLowerCase().includes("json");
                      const hint = (selectedConfig as any).field_hints?.[field];

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
                                value={credentials[field] || ""}
                                onChange={(e) => handleCredentialChange(field, e.target.value)}
                                placeholder="Paste your JSON here"
                                className="w-full min-h-[120px] px-3 py-2 text-sm rounded-md border border-input bg-background font-mono resize-y"
                              />
                            ) : (
                              <Input
                                id={field}
                                type={isSecret && !showSecrets[field] ? "password" : "text"}
                                value={credentials[field] || ""}
                                onChange={(e) => handleCredentialChange(field, e.target.value)}
                                placeholder={`Enter ${field.replace(/_/g, " ")}`}
                                className="pr-10"
                              />
                            )}
                            {isSecret && !isJson && (
                              <button
                                type="button"
                                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                onClick={() =>
                                  setShowSecrets((prev) => ({
                                    ...prev,
                                    [field]: !prev[field],
                                  }))
                                }
                              >
                                {showSecrets[field] ? (
                                  <EyeOff className="h-4 w-4" />
                                ) : (
                                  <Eye className="h-4 w-4" />
                                )}
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}

                    {/* Free tier limit warning — only when billing is configured */}
                    {billingEnabled && (!usage?.plan || usage?.plan === "free") && warehouses && warehouses.length >= 1 && (
                      <div className="p-4 bg-muted/50 border rounded-lg">
                        <p className="text-sm text-muted-foreground">
                          Free plan allows 1 warehouse connection. You'll need to upgrade to add more.
                        </p>
                        <Link to="/pricing" className="text-sm text-blue-400 hover:text-blue-300 hover:underline flex items-center gap-1 mt-2 font-medium">
                          Upgrade your plan <ArrowUpRight className="h-3 w-3" />
                        </Link>
                      </div>
                    )}

                    <div className="flex gap-3 pt-4">
                      <Button variant="outline" onClick={() => setStep(1)}>
                        Back
                      </Button>
                      <Button
                        onClick={() => setStep(3)}
                        disabled={!activeFields.every((f: string) => credentials[f])}
                      >
                        Continue
                      </Button>
                    </div>
                  </div>
                  );
                })()}

                {/* Step 3: Name Connection */}
                {step === 3 && selectedConfig && (
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 mb-4">
                      <Check className="h-5 w-5 text-green-500" />
                      <span className="font-medium">Name Your Connection</span>
                    </div>
                    <p className="text-sm text-muted-foreground mb-4">
                      Give this connection a friendly name you'll recognize.
                    </p>

                    <div className="space-y-2">
                      <Label htmlFor="name">Connection Name</Label>
                      <Input
                        id="name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder={`e.g., Production ${selectedConfig.name}`}
                      />
                    </div>

                    {/* Free tier limit warning — only when billing is configured */}
                    {billingEnabled && (!usage?.plan || usage?.plan === "free") && warehouses && warehouses.length >= 1 && !upgradeError && (
                      <div className="p-4 bg-muted/50 border rounded-lg">
                        <p className="text-sm text-muted-foreground">
                          Free plan allows 1 warehouse connection. You'll need to upgrade to add more.
                        </p>
                        <Link to="/pricing" className="text-sm text-blue-400 hover:text-blue-300 hover:underline flex items-center gap-1 mt-2 font-medium">
                          Upgrade your plan <ArrowUpRight className="h-3 w-3" />
                        </Link>
                      </div>
                    )}

                    {/* Upgrade error - shown after attempting to connect */}
                    {upgradeError && (
                      <div className="p-4 bg-destructive/10 border border-destructive/50 rounded-lg">
                        <p className="text-sm font-medium text-destructive">
                          {upgradeError}
                        </p>
                        <Link to="/pricing" className="text-sm text-blue-400 hover:text-blue-300 hover:underline flex items-center gap-1 mt-2 font-medium">
                          Upgrade your plan <ArrowUpRight className="h-3 w-3" />
                        </Link>
                      </div>
                    )}

                    <div className="flex gap-3 pt-4">
                      <Button variant="outline" onClick={() => setStep(2)}>
                        Back
                      </Button>
                      <Button
                        onClick={handleAddWarehouse}
                        disabled={!isFormValid || addMutation.isPending}
                      >
                        {addMutation.isPending ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            Connecting...
                          </>
                        ) : (
                          "Connect Warehouse"
                        )}
                      </Button>
                    </div>
                  </div>
                )}
              </DialogContent>
            </Dialog>
              <Link to="/context">
                <Button className="gap-2">
                  <FileText className="h-4 w-4" />
                  Context
                </Button>
              </Link>
            </div>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : warehouses && warehouses.length > 0 ? (
              <div className="space-y-3">
                {warehouses.map((warehouse) => {
                  const schema = schemaData[warehouse.id];
                  const isExpanded = expandedWarehouse === warehouse.id;

                  // Group tables by dataset for tree view
                  const datasetMap: Record<string, typeof schema.tables> = {};
                  if (schema) {
                    for (const t of schema.tables) {
                      if (!datasetMap[t.dataset]) datasetMap[t.dataset] = [];
                      datasetMap[t.dataset].push(t);
                    }
                  }

                  return (
                    <div key={warehouse.id} className="border rounded-lg">
                      <div className="flex items-center justify-between p-4">
                        <div className="flex items-center gap-3">
                          <div
                            className={`w-2 h-2 rounded-full ${
                              warehouse.connection_status === "connected"
                                ? "bg-green-500"
                                : "bg-red-500"
                            }`}
                          />
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-medium">{warehouse.name}</span>
                              {warehouse.is_demo && (
                                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20">
                                  Demo
                                </span>
                              )}
                              {warehouse.is_read_only === true && (
                                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-green-500/10 text-green-600 dark:text-green-400 border border-green-500/20">
                                  <Lock className="h-3 w-3" />
                                  Read-only
                                </span>
                              )}
                              {warehouse.is_read_only === false && (
                                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 border border-yellow-500/20">
                                  Write access
                                </span>
                              )}
                            </div>
                            <div className="text-sm text-muted-foreground">
                              {warehouse.warehouse_type}
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            title="View Schema"
                            onClick={() => handleToggleSchema(warehouse.id)}
                          >
                            {schemaLoading === warehouse.id ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Eye className="h-4 w-4" />
                            )}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            title="Verify Read-Only"
                            onClick={() => handleVerifyReadOnly(warehouse.id)}
                            disabled={verifyingWarehouse === warehouse.id}
                          >
                            {verifyingWarehouse === warehouse.id ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <ShieldCheck className="h-4 w-4" />
                            )}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            title="Manage Access"
                            onClick={() => handleOpenAllowlist(warehouse.id)}
                            className="text-xs gap-1"
                          >
                            <Lock className="h-3.5 w-3.5" />
                            Access
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => testMutation.mutate(warehouse.id)}
                            disabled={testMutation.isPending}
                            title="Test Connection"
                          >
                            {testMutation.isPending ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <RefreshCw className="h-4 w-4" />
                            )}
                          </Button>
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button variant="ghost" size="icon" title="Delete">
                                <Trash2 className="h-4 w-4 text-destructive" />
                              </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>Delete Warehouse</AlertDialogTitle>
                                <AlertDialogDescription>
                                  Are you sure you want to delete "{warehouse.name}"? This action cannot be undone.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Cancel</AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={() => deleteMutation.mutate(warehouse.id)}
                                >
                                  Delete
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </div>
                      </div>

                      {/* Schema tree */}
                      {isExpanded && schema && (
                        <div className="px-4 pb-4 border-t pt-3">
                          <div className="text-xs text-muted-foreground mb-2">
                            {schema.datasets_count} dataset(s), {schema.tables_count} table(s)
                          </div>
                          <div className="space-y-1 max-h-64 overflow-y-auto">
                            {Object.entries(datasetMap).map(([dataset, tables]) => (
                              <div key={dataset}>
                                <button
                                  className="flex items-center gap-1 text-sm font-medium hover:text-foreground text-muted-foreground w-full text-left"
                                  onClick={() => toggleDataset(dataset)}
                                >
                                  {expandedDatasets.has(dataset) ? (
                                    <ChevronDown className="h-3 w-3" />
                                  ) : (
                                    <ChevronRight className="h-3 w-3" />
                                  )}
                                  {dataset}
                                  <span className="text-xs text-muted-foreground ml-1">({tables.length})</span>
                                </button>
                                {expandedDatasets.has(dataset) && (
                                  <div className="ml-4 space-y-0.5">
                                    {tables.map((t) => {
                                      const tKey = `${dataset}.${t.table}`;
                                      return (
                                        <div key={tKey}>
                                          <button
                                            className="flex items-center gap-1 text-xs hover:text-foreground text-muted-foreground w-full text-left py-0.5"
                                            onClick={() => toggleTable(tKey)}
                                          >
                                            {expandedTables.has(tKey) ? (
                                              <ChevronDown className="h-2.5 w-2.5" />
                                            ) : (
                                              <ChevronRight className="h-2.5 w-2.5" />
                                            )}
                                            {t.table}
                                            <span className="text-muted-foreground ml-1">({t.columns.length})</span>
                                          </button>
                                          {expandedTables.has(tKey) && (
                                            <div className="ml-4 text-xs text-muted-foreground space-y-0.5">
                                              {t.columns.map((c) => (
                                                <div key={c.name} className="flex gap-2">
                                                  <span>{c.name}</span>
                                                  <span className="opacity-50">{c.data_type}</span>
                                                </div>
                                              ))}
                                            </div>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {isExpanded && schemaLoading === warehouse.id && (
                        <div className="px-4 pb-4 flex justify-center">
                          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : !salesforceConnection && fileSessions.length === 0 && !(localDb?.exists && localDb.tables.length > 0) ? (
              <div className="text-center py-8 text-muted-foreground">
                No data sources connected. Add a warehouse, upload a file, or connect Salesforce to get started.
              </div>
            ) : null}

            {/* Salesforce row */}
            {sfLoading ? (
              <div className="flex justify-center py-4">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            ) : salesforceConnection ? (
              <div className="border rounded-lg mt-3">
                <div className="flex items-center justify-between p-4">
                  <div className="flex items-center gap-3">
                    <div
                      className={`w-2 h-2 rounded-full ${
                        salesforceConnection.connection_status === "connected"
                          ? "bg-green-500"
                          : "bg-red-500"
                      }`}
                    />
                    <div>
                      <div className="font-medium">
                        Salesforce - {salesforceConnection.org_name || "Connected"}
                      </div>
                      <div className="text-sm text-muted-foreground">
                        {salesforceConnection.username || salesforceConnection.instance_url}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      title="Manage Access"
                      onClick={handleOpenSfAllowlist}
                      className="text-xs gap-1"
                    >
                      <Lock className="h-3.5 w-3.5" />
                      Access
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => sfTestMutation.mutate()}
                      disabled={sfTestMutation.isPending}
                      title="Test Connection"
                    >
                      {sfTestMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw className="h-4 w-4" />
                      )}
                    </Button>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="icon" title="Disconnect">
                          <Unplug className="h-4 w-4 text-destructive" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Disconnect Salesforce</AlertDialogTitle>
                          <AlertDialogDescription>
                            Are you sure you want to disconnect your Salesforce org? You can reconnect at any time.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction
                            onClick={() => sfDisconnectMutation.mutate()}
                          >
                            Disconnect
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </div>
              </div>
            ) : null}

            {/* Local files: one persistent DuckDB per user holding all CSV/Excel/
                Parquet/JSON uploads as queryable tables. Cross-file joins work
                natively because everything lives in the same DuckDB instance. */}
            {localDb?.exists && localDb.tables.length > 0 && (
              <div className="border rounded-lg mt-3">
                <details className="group" open>
                  <summary className="flex items-center gap-3 p-4 cursor-pointer list-none">
                    <div className="w-2 h-2 rounded-full bg-green-500" />
                    <div className="flex-1">
                      <div className="font-medium">Local files</div>
                      <div className="text-sm text-muted-foreground">
                        DuckDB instance ({localDb.tables.length} table{localDb.tables.length !== 1 ? "s" : ""} connected)
                      </div>
                      {localDb.id && (
                        <div className="font-mono text-xs text-muted-foreground mt-0.5">
                          id: {localDb.id}
                        </div>
                      )}
                    </div>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          title="Remove all local files"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Remove all local files</AlertDialogTitle>
                          <AlertDialogDescription>
                            Delete all uploaded local files and the underlying DuckDB instance? This can't be undone.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction onClick={handleDeleteAllLocal}>
                            Remove all
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                    <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-90" />
                  </summary>
                  <div className="border-t px-4 py-2">
                    {localDb.tables.map((t) => (
                      <div key={t.id} className="flex items-center justify-between py-2 px-3 hover:bg-muted/50 rounded">
                        <div className="text-sm flex items-center gap-2">
                          <span className="font-mono">{t.table_name}</span>
                          {t.is_demo && (
                            <span className="inline-flex items-center text-xs px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20">
                              Demo
                            </span>
                          )}
                          <span className="text-muted-foreground">
                            {t.original_filename} · {t.row_count.toLocaleString()} rows · {t.columns.length} cols
                          </span>
                        </div>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-7 w-7" title="Remove">
                              <Trash2 className="h-3.5 w-3.5 text-destructive" />
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Remove table</AlertDialogTitle>
                              <AlertDialogDescription>
                                Remove "{t.original_filename}" (table <span className="font-mono">{t.table_name}</span>)? Claude will no longer be able to query this data.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Cancel</AlertDialogCancel>
                              <AlertDialogAction onClick={() => handleDeleteLocalTable(t.id)}>
                                Remove
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            )}

            {/* Uploaded .duckdb files — each is its own data source (separate flow) */}
            {fileSessions.length > 0 && (
              <div className="space-y-3 mt-3">
                {fileSessions.map((fs) => (
                  <div key={fs.session_id} className="border rounded-lg">
                    <div className="flex items-center justify-between p-4">
                      <div className="flex items-center gap-3">
                        <div className="w-2 h-2 rounded-full bg-green-500" />
                        <div>
                          <div className="font-medium">{fs.metadata.filename}</div>
                          <div className="text-sm text-muted-foreground">DuckDB · {fs.metadata.table_count} table{fs.metadata.table_count !== 1 ? "s" : ""}</div>
                        </div>
                      </div>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="icon" title="Remove">
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Remove uploaded file</AlertDialogTitle>
                            <AlertDialogDescription>
                              Remove "{fs.metadata.filename}"? Claude will no longer be able to query this data.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction onClick={() => removeLocalFileSession(fs.session_id)}>
                              Remove
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Plan Section — hidden when billing isn't configured (self-hosted) */}
        {billingEnabled && (
        <Card>
          <CardContent className="pt-6 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-lg font-semibold">
                  {PLAN_LIMITS[usage?.plan || "free"]?.displayName || (usage?.plan || "free").charAt(0).toUpperCase() + (usage?.plan || "free").slice(1)} Plan
                </div>
                <div className="text-sm text-muted-foreground mt-1">
                  {PLAN_LIMITS[usage?.plan || "free"]?.warehouses} warehouse connection{PLAN_LIMITS[usage?.plan || "free"]?.warehouses !== "1" ? "s" : ""} &bull; {PLAN_LIMITS[usage?.plan || "free"]?.tokens}/month
                </div>
              </div>
              {usage?.plan && usage.plan !== "free" ? (
                <Link to="/pricing">
                  <Button
                    size="sm"
                    className="gap-1"
                  >
                    Manage Subscription <ArrowUpRight className="h-4 w-4" />
                  </Button>
                </Link>
              ) : (
                <Link to="/pricing">
                  <Button variant="default" size="sm" className="gap-1">
                    Upgrade <ArrowUpRight className="h-4 w-4" />
                  </Button>
                </Link>
              )}
            </div>
            {usage && (
              <div className="space-y-1">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>{usage.usage_percent.toFixed(0)}% of monthly limit</span>
                  <Link to="/usage" className="hover:underline">View details</Link>
                </div>
                <Progress
                  value={Math.min(usage.usage_percent, 100)}
                  className={`h-2 ${
                    usage.usage_percent >= 100 ? "[&>div]:bg-red-500" :
                    usage.usage_percent >= 80 ? "[&>div]:bg-orange-500" :
                    usage.usage_percent >= 60 ? "[&>div]:bg-yellow-500" : ""
                  }`}
                />
              </div>
            )}
            <div className="text-sm text-muted-foreground">
              Using {warehouses?.length || 0} of {PLAN_LIMITS[usage?.plan || "free"]?.warehouses} warehouse connection{PLAN_LIMITS[usage?.plan || "free"]?.warehouses !== "1" ? "s" : ""}
            </div>
          </CardContent>
        </Card>
        )}

        {/* Account Section */}
        <Card className="mt-8">
          <CardHeader>
            <CardTitle>Account</CardTitle>
            <CardDescription>
              Manage your account settings
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">Profile & Security</div>
                <div className="text-sm text-muted-foreground">
                  Manage your profile, password, and security settings
                </div>
              </div>
              <UserAvatar afterSignOutUrl="/" />
            </div>
            <TeamRow />
            <div className="flex items-center justify-between border-t pt-4">
              <div>
                <div className="font-medium">Changelog</div>
                <div className="text-sm text-muted-foreground">
                  See the latest features and updates
                </div>
              </div>
              <Link to="/changelog">
                <Button size="sm" className="gap-1">
                  Changelog <ArrowUpRight className="h-4 w-4" />
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>


        {/* Danger Zone */}
        <Card className="mt-8 border-destructive/50">
          <CardHeader>
            <CardTitle className="text-destructive">Danger Zone</CardTitle>
            <CardDescription>
              Irreversible actions for your account
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">Delete Account</div>
                <div className="text-sm text-muted-foreground">
                  Permanently delete your account and all associated data
                </div>
              </div>
              <Button
                variant="destructive"
                onClick={() => setDeleteStep(1)}
              >
                Delete Account
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Delete Account Step 1: Warning */}
        <AlertDialog open={deleteStep === 1} onOpenChange={(open) => { if (!open) setDeleteStep(0); }}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Are you sure?</AlertDialogTitle>
              <AlertDialogDescription>
                This action is permanent and cannot be undone. All your data
                including warehouse connections, conversations, and usage
                history will be permanently deleted.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel onClick={() => setDeleteStep(0)}>Cancel</AlertDialogCancel>
              <AlertDialogAction
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                onClick={(e) => { e.preventDefault(); setDeleteStep(2); }}
              >
                Continue
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Delete Account Step 2: Type "delete" to confirm */}
        <Dialog open={deleteStep === 2} onOpenChange={(open) => { if (!open) { setDeleteStep(0); setDeleteConfirmText(""); } }}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Confirm Account Deletion</DialogTitle>
              <DialogDescription>
                Type <span className="font-semibold text-foreground">delete</span> below to confirm.
              </DialogDescription>
            </DialogHeader>
            <Input
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder='Type "delete" to confirm'
              autoFocus
            />
            <DialogFooter>
              <Button variant="outline" onClick={() => { setDeleteStep(0); setDeleteConfirmText(""); }}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                disabled={deleteConfirmText !== "delete" || deleteAccountMutation.isPending}
                onClick={() => deleteAccountMutation.mutate()}
              >
                {deleteAccountMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  "Delete My Account"
                )}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Allowlist Dialog */}
        <Dialog
          open={!!allowlistWarehouse}
          onOpenChange={(open) => {
            if (!open) setAllowlistWarehouse(null);
          }}
        >
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>Manage Table Access</DialogTitle>
              <DialogDescription>
                Choose which tables are queryable. Restricting access prevents queries to other tables.
              </DialogDescription>
            </DialogHeader>
            {allowlistLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : allowlistSchema ? (
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <Button
                    variant={allowlistMode === "all" ? "default" : "outline"}
                    size="sm"
                    onClick={() => {
                      setAllowlistMode("all");
                      setSelectedTables(
                        new Set(allowlistSchema.tables.map((t) => `${t.dataset}.${t.table}`))
                      );
                    }}
                  >
                    All Tables
                  </Button>
                  <Button
                    variant={allowlistMode === "selected" ? "default" : "outline"}
                    size="sm"
                    onClick={() => setAllowlistMode("selected")}
                  >
                    Selected Only
                  </Button>
                </div>
                {allowlistMode === "selected" && (
                  <>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setSelectedTables(
                            new Set(allowlistSchema.tables.map((t) => `${t.dataset}.${t.table}`))
                          )
                        }
                      >
                        Select All
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setSelectedTables(new Set())}
                      >
                        Deselect All
                      </Button>
                    </div>
                    <div className="max-h-64 overflow-y-auto space-y-1 border rounded-lg p-2">
                      {allowlistSchema.tables.map((t) => {
                        const key = `${t.dataset}.${t.table}`;
                        return (
                          <label
                            key={key}
                            className="flex items-center gap-2 text-sm py-1 px-2 rounded hover:bg-muted cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={selectedTables.has(key)}
                              onChange={() => {
                                setSelectedTables((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(key)) next.delete(key);
                                  else next.add(key);
                                  return next;
                                });
                              }}
                              className="rounded"
                            />
                            <span className="text-muted-foreground">{t.dataset}.</span>
                            <span>{t.table}</span>
                          </label>
                        );
                      })}
                    </div>
                  </>
                )}
                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="outline" onClick={() => setAllowlistWarehouse(null)}>
                    Cancel
                  </Button>
                  <Button onClick={handleSaveAllowlist} disabled={allowlistSaving}>
                    {allowlistSaving ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Saving...
                      </>
                    ) : (
                      "Save"
                    )}
                  </Button>
                </div>
              </div>
            ) : null}
          </DialogContent>
        </Dialog>

        {/* Salesforce Allowlist Dialog */}
        <Dialog
          open={sfAllowlistOpen}
          onOpenChange={(open) => {
            if (!open) setSfAllowlistOpen(false);
          }}
        >
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>Manage Salesforce Object Access</DialogTitle>
              <DialogDescription>
                Choose which Salesforce objects are queryable. Restricting access prevents queries to other objects.
              </DialogDescription>
            </DialogHeader>
            {sfAllowlistLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : sfObjects.length > 0 ? (
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <Button
                    variant={sfAllowlistMode === "all" ? "default" : "outline"}
                    size="sm"
                    onClick={() => {
                      setSfAllowlistMode("all");
                      setSfSelectedObjects(new Set(sfObjects.map((o) => o.name)));
                    }}
                  >
                    All Objects
                  </Button>
                  <Button
                    variant={sfAllowlistMode === "selected" ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSfAllowlistMode("selected")}
                  >
                    Selected Only
                  </Button>
                </div>
                {sfAllowlistMode === "selected" && (
                  <>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setSfSelectedObjects(new Set(sfObjects.map((o) => o.name)))}
                      >
                        Select All
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setSfSelectedObjects(new Set())}
                      >
                        Deselect All
                      </Button>
                    </div>
                    <div className="max-h-64 overflow-y-auto space-y-1 border rounded-lg p-2">
                      {sfObjects.map((obj) => (
                        <label
                          key={obj.name}
                          className="flex items-center gap-2 text-sm py-1 px-2 rounded hover:bg-muted cursor-pointer"
                        >
                          <input
                            type="checkbox"
                            checked={sfSelectedObjects.has(obj.name)}
                            onChange={() => {
                              setSfSelectedObjects((prev) => {
                                const next = new Set(prev);
                                if (next.has(obj.name)) next.delete(obj.name);
                                else next.add(obj.name);
                                return next;
                              });
                            }}
                            className="rounded"
                          />
                          <span>{obj.label}</span>
                          <span className="text-muted-foreground text-xs">({obj.name})</span>
                        </label>
                      ))}
                    </div>
                  </>
                )}
                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="outline" onClick={() => setSfAllowlistOpen(false)}>
                    Cancel
                  </Button>
                  <Button onClick={handleSaveSfAllowlist} disabled={sfAllowlistSaving}>
                    {sfAllowlistSaving ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Saving...
                      </>
                    ) : (
                      "Save"
                    )}
                  </Button>
                </div>
              </div>
            ) : null}
          </DialogContent>
        </Dialog>
      </main>
    </div>
  );
}


function TeamRow() {
  const qc = useQueryClient();
  const [membersOpen, setMembersOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");

  const { data: org } = useQuery({
    queryKey: ["organization"],
    queryFn: api.getOrganization,
  });

  const { data: membersData } = useQuery({
    queryKey: ["organization-members"],
    queryFn: api.listOrganizationMembers,
    enabled: membersOpen,
  });

  const inviteMutation = useMutation({
    mutationFn: (email: string) => api.inviteTeammate(email),
    onSuccess: (res) => {
      toast.success(res.message);
      setInviteEmail("");
      qc.invalidateQueries({ queryKey: ["organization-members"] });
    },
    onError: (e: { message?: string }) => toast.error(e?.message || "Failed to send invite"),
  });

  const handleInvite = (e: React.FormEvent) => {
    e.preventDefault();
    const email = inviteEmail.trim();
    if (!email) return;
    inviteMutation.mutate(email);
  };

  const subtitle = !org
    ? "Loading workspace…"
    : org.is_personal
      ? "Personal workspace — only you have access"
      : org.domain
        ? `Shared workspace for everyone on @${org.domain}`
        : "";

  return (
    <div className="border-t pt-4 space-y-4">
      <div>
        <div className="font-medium">Team</div>
        <div className="text-sm text-muted-foreground truncate">{subtitle}</div>
      </div>
      {org && (
        <>
          {!org.is_personal && org.can_invite ? (
            <form onSubmit={handleInvite} className="space-y-2">
              <div className="flex gap-2">
                <Input
                  id="invite-email"
                  type="email"
                  placeholder={`name@${org.domain}`}
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  disabled={inviteMutation.isPending}
                />
                <Button type="submit" disabled={inviteMutation.isPending || !inviteEmail.trim()}>
                  {inviteMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      <Mail className="h-4 w-4 mr-1.5" />
                      Send invite
                    </>
                  )}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Only emails on @{org.domain} can join this workspace.
              </p>
            </form>
          ) : org.is_personal ? (
            <p className="text-sm text-muted-foreground">
              Invitations are only available on a verified work-domain workspace.
            </p>
          ) : null}
          <div>
            <button
              type="button"
              onClick={() => setMembersOpen((v) => !v)}
              className="text-sm font-medium flex items-center gap-1 hover:text-foreground/80"
            >
              {membersOpen ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
              Members ({org.member_count})
            </button>
            {membersOpen && (
              <div className="mt-2">
                {!membersData ? (
                  <div className="flex justify-center py-3">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : !membersData.members.length ? (
                  <p className="text-sm text-muted-foreground">No members yet.</p>
                ) : (
                  <ul className="divide-y divide-border/40">
                    {membersData.members.map((m) => (
                      <li key={m.id} className="flex items-center justify-between py-2">
                        <div className="min-w-0">
                          <div className="text-sm font-medium truncate">{m.name || m.email}</div>
                          {m.name && (
                            <div className="text-xs text-muted-foreground truncate">{m.email}</div>
                          )}
                        </div>
                        {m.is_admin && (
                          <span className="text-xs text-muted-foreground shrink-0 ml-2">Admin</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
