import { ClerkProvider, SignedIn, SignedOut, ClerkLoaded, ClerkLoading, useAuth } from "@clerk/clerk-react";
import { dark } from "@clerk/themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ThemeProvider, useTheme, isDarkTheme } from "@/hooks/use-theme";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { ErrorBoundary } from "@/components/ErrorBoundary";

// Pages
import SignInPage from "@/pages/SignInPage";
import SignUpPage from "@/pages/SignUpPage";
import DashboardPage from "@/pages/DashboardPage";
import ChatPage from "@/pages/ChatPage";
import SettingsPage from "@/pages/SettingsPage";
import UsagePage from "@/pages/UsagePage";
import AdminPage from "@/pages/AdminPage";
import ReportsPage from "@/pages/ReportsPage";
import ReportDetailPage from "@/pages/ReportDetailPage";
import ChangelogPage from "@/pages/ChangelogPage";
import ContextPage from "@/pages/ContextPage";
import NotFound from "@/pages/NotFound";

const CLERK_PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60,
      gcTime: 1000 * 60 * 5, // 5 minutes garbage collection to prevent memory bloat
      retry: 1,
    },
  },
});

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  // If Clerk is not configured, allow access (dev mode)
  if (!CLERK_PUBLISHABLE_KEY) {
    return <>{children}</>;
  }

  return (
    <>
      <SignedIn>{children}</SignedIn>
      <SignedOut>
        <Navigate to="/sign-in" replace />
      </SignedOut>
    </>
  );
}

function LandingOrChat() {
  if (!CLERK_PUBLISHABLE_KEY) return <Navigate to="/chat" replace />;
  const { isSignedIn } = useAuth();
  return <Navigate to={isSignedIn ? "/chat" : "/sign-in"} replace />;
}

function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public routes */}
        <Route path="/" element={<LandingOrChat />} />
        <Route path="/sign-in/*" element={<SignInPage />} />
        <Route path="/sign-up/*" element={<SignUpPage />} />
        <Route path="/demo" element={<Navigate to="/sign-up" replace />} />
        <Route path="/changelog" element={<ChangelogPage />} />
        {/* Protected routes */}
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <DashboardPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/chat"
          element={
            <ProtectedRoute>
              <ChatPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/chat/:conversationId"
          element={
            <ProtectedRoute>
              <ChatPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings"
          element={
            <ProtectedRoute>
              <SettingsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/usage"
          element={
            <ProtectedRoute>
              <UsagePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute>
              <AdminPage />
            </ProtectedRoute>
          }
        />
        <Route path="/onboarding" element={<Navigate to="/chat" replace />} />
        <Route
          path="/reports"
          element={
            <ProtectedRoute>
              <ReportsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/reports/:reportId"
          element={
            <ProtectedRoute>
              <ReportDetailPage />
            </ProtectedRoute>
          }
        />
        <Route path="/visualizations" element={<Navigate to="/reports" replace />} />
        <Route path="/team" element={<Navigate to="/settings" replace />} />
        <Route
          path="/context"
          element={
            <ProtectedRoute>
              <ContextPage />
            </ProtectedRoute>
          }
        />
        {/* Redirects for removed pages */}
        <Route path="/memory" element={<Navigate to="/context" replace />} />
        <Route path="/integrations" element={<Navigate to="/context" replace />} />

        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}

function AppContent() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={0}>
        <ErrorBoundary>
          <AppRoutes />
        </ErrorBoundary>
        <Toaster position="top-right" />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

function useResolvedTheme(): "dark" | "light" {
  const { theme } = useTheme();
  return isDarkTheme(theme) ? "dark" : "light";
}

function ClerkWithTheme({ children }: { children: React.ReactNode }) {
  const resolved = useResolvedTheme();

  return (
    <ClerkProvider
      publishableKey={CLERK_PUBLISHABLE_KEY!}
      appearance={{
        baseTheme: resolved === "dark" ? dark : undefined,
        variables: {
          colorPrimary: "hsl(var(--primary))",
          colorBackground: "hsl(var(--background))",
          colorText: "hsl(var(--foreground))",
          colorInputBackground: "hsl(var(--card))",
          colorInputText: "hsl(var(--foreground))",
        },
      }}
    >
      <ClerkLoading>
        <div className="min-h-screen flex items-center justify-center">
          <div className="animate-pulse text-muted-foreground">Loading...</div>
        </div>
      </ClerkLoading>
      <ClerkLoaded>
        {children}
      </ClerkLoaded>
    </ClerkProvider>
  );
}

const App = () => {
  // If Clerk is not configured, render without it
  if (!CLERK_PUBLISHABLE_KEY) {
    console.warn("Clerk not configured - running in dev mode without auth");
    return (
      <ThemeProvider defaultTheme="midnight-ocean" storageKey="datachat-theme">
        <AppContent />
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider defaultTheme="dark" storageKey="datachat-theme">
      <ClerkWithTheme>
        <AppContent />
      </ClerkWithTheme>
    </ThemeProvider>
  );
};

export default App;
