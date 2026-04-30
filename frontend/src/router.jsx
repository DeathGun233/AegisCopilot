import { Navigate, Outlet, createBrowserRouter, useLocation } from "react-router-dom";
import { WorkspaceShell } from "./components/layout/WorkspaceShell";
import { useAppContext } from "./context/AppContext";
import { ChatPage } from "./pages/ChatPage";
import { LoginPage } from "./pages/LoginPage";
import { AdminLayout } from "./pages/admin/AdminLayout";
import { DashboardPage } from "./pages/admin/DashboardPage";
import { DocumentDetailPage } from "./pages/admin/DocumentDetailPage";
import { EvaluationPage } from "./pages/admin/EvaluationPage";
import { KnowledgePage } from "./pages/admin/KnowledgePage";
import { RetrievalDebugPage } from "./pages/admin/RetrievalDebugPage";
import { TracePage } from "./pages/admin/TracePage";
import { UsersPage } from "./pages/admin/UsersPage";

function withShell(element) {
  return <WorkspaceShell>{element}</WorkspaceShell>;
}

function FullScreenState({ title, message }) {
  return (
    <div className="auth-screen">
      <div className="auth-card auth-card--compact">
        <span className="hero-pill">AegisCopilot</span>
        <h1>{title}</h1>
        <p>{message}</p>
      </div>
    </div>
  );
}

function RequireAuth() {
  const { bootstrapping, isAuthenticated } = useAppContext();
  const location = useLocation();

  if (bootstrapping) {
    return <FullScreenState title="正在加载工作台" message="正在检查登录状态..." />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}

function RequireAdmin() {
  const { bootstrapping, isAuthenticated, isAdmin } = useAppContext();
  const location = useLocation();

  if (bootstrapping) {
    return <FullScreenState title="正在加载工作台" message="正在检查访问权限..." />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (!isAdmin) {
    return <Navigate to="/chat" replace />;
  }

  return <Outlet />;
}

function GuestOnly() {
  const { bootstrapping, isAuthenticated } = useAppContext();

  if (bootstrapping) {
    return <FullScreenState title="正在加载工作台" message="正在准备登录页面..." />;
  }

  if (isAuthenticated) {
    return <Navigate to="/chat" replace />;
  }

  return <Outlet />;
}

export const router = createBrowserRouter([
  {
    element: <GuestOnly />,
    children: [{ path: "/login", element: <LoginPage /> }],
  },
  {
    element: <RequireAuth />,
    children: [
      {
        path: "/",
        element: <Navigate to="/chat" replace />,
      },
      {
        path: "/chat",
        element: withShell(<ChatPage />),
      },
      {
        path: "/chat/:conversationId",
        element: withShell(<ChatPage />),
      },
      {
        element: <RequireAdmin />,
        children: [
          {
            path: "/admin",
            element: withShell(<AdminLayout />),
            children: [
              { index: true, element: <Navigate to="/admin/overview" replace /> },
              { path: "overview", element: <DashboardPage /> },
              { path: "knowledge", element: <KnowledgePage /> },
              { path: "knowledge/:documentId", element: <DocumentDetailPage /> },
              { path: "retrieval-debug", element: <RetrievalDebugPage /> },
              { path: "traces", element: <TracePage /> },
              { path: "users", element: <UsersPage /> },
              { path: "evaluation", element: <EvaluationPage /> },
            ],
          },
        ],
      },
    ],
  },
]);
