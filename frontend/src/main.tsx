import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "@fontsource-variable/inter";
import "./index.css";
import { AppLayout } from "./components/Layout";
import { RedirectIfSignedIn, RequireAdmin, RequireAuth } from "./components/guards";
import { LoginPage, SignupPage } from "./pages/Auth";
import { ChatPage } from "./pages/Chat";
import { NewWorkspacePage, WorkspacesPage } from "./pages/Workspaces";
import { WorkspacePage } from "./pages/Workspace";
import { RecordingPage } from "./pages/Recording";
import { ProposalPage } from "./pages/Proposal";
import { ToolPage } from "./pages/ToolPage";
import { ExtensionConnectPage, ExtensionPage } from "./pages/Extension";
import { AdminLayout } from "./pages/admin/AdminLayout";
import { AdminOverview } from "./pages/admin/Overview";
import { AdminProviders } from "./pages/admin/Providers";
import { AdminRouting } from "./pages/admin/Routing";
import { AdminCrawlerSettings } from "./pages/admin/CrawlerSettings";
import { AdminUsers } from "./pages/admin/Users";
import { AdminUsage, AdminWorkspaces } from "./pages/admin/Lists";
import { AdminMcpServers } from "./pages/admin/McpServers";
import { AdminChatQuality } from "./pages/admin/ChatQuality";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<RedirectIfSignedIn><LoginPage /></RedirectIfSignedIn>} />
        <Route path="/signup" element={<RedirectIfSignedIn><SignupPage /></RedirectIfSignedIn>} />
        {/* The public customer chat: no login, its own layout. */}
        <Route path="/chat" element={<ChatPage />} />
        <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
          <Route index element={<Navigate to="/workspaces" replace />} />
          <Route path="workspaces" element={<WorkspacesPage />} />
          <Route path="workspaces/new" element={<NewWorkspacePage />} />
          <Route path="workspaces/:id" element={<WorkspacePage />} />
          <Route path="workspaces/:id/recordings/:rid" element={<RecordingPage />} />
          <Route path="workspaces/:id/proposals/:pid" element={<ProposalPage />} />
          <Route path="workspaces/:id/tools/:tid" element={<ToolPage />} />
          <Route path="extension" element={<ExtensionPage />} />
          <Route path="extension/connect" element={<ExtensionConnectPage />} />
          <Route path="admin" element={<RequireAdmin><AdminLayout /></RequireAdmin>}>
            <Route index element={<AdminOverview />} />
            <Route path="providers" element={<AdminProviders />} />
            <Route path="routing" element={<AdminRouting />} />
            <Route path="crawler" element={<AdminCrawlerSettings />} />
            <Route path="users" element={<AdminUsers />} />
            <Route path="workspaces" element={<AdminWorkspaces />} />
            <Route path="mcp-servers" element={<AdminMcpServers />} />
            <Route path="usage" element={<AdminUsage />} />
            <Route path="chat-quality" element={<AdminChatQuality />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
