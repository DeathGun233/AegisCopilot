import { createContext, useContext, useEffect, useState } from "react";
import {
  clearStoredAuthToken,
  fetchJson,
  getStoredAuthToken,
  setStoredAuthToken,
  uploadFile,
  withQuery,
} from "../lib/api";

const AppContext = createContext(null);

function sortConversations(items) {
  return [...items].sort((left, right) => new Date(right.updated_at) - new Date(left.updated_at));
}

function resetSessionState(setters) {
  setters.setAppError("");
  setters.setCurrentUser(null);
  setters.setUsers([]);
  setters.setStats(null);
  setters.setSystemStatus(null);
  setters.setModelCatalog(null);
  setters.setDocuments([]);
  setters.setConversations([]);
  setters.setEvaluationRun(null);
}

export function AppProvider({ children }) {
  const [bootstrapping, setBootstrapping] = useState(true);
  const [appError, setAppError] = useState("");
  const [globalNotice, setGlobalNotice] = useState("");
  const [authToken, setAuthToken] = useState(() => getStoredAuthToken());
  const [currentUser, setCurrentUser] = useState(null);
  const [users, setUsers] = useState([]);
  const [stats, setStats] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const [modelCatalog, setModelCatalog] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [evaluationRun, setEvaluationRun] = useState(null);

  const isAuthenticated = Boolean(authToken && currentUser);
  const isAdmin = currentUser?.role === "admin";

  async function refreshConversations() {
    const data = await fetchJson("/conversations");
    const ordered = sortConversations(data.conversations);
    setConversations(ordered);
    return ordered;
  }

  async function refreshDocuments() {
    const data = await fetchJson("/documents");
    setDocuments(data.documents);
    return data.documents;
  }

  async function queryDocuments(params = {}) {
    const data = await fetchJson(withQuery("/documents", params));
    return data.documents;
  }

  async function refreshStats() {
    const data = await fetchJson("/system/stats");
    setStats(data.stats);
    return data.stats;
  }

  async function refreshSystemStatus() {
    if (!isAdmin) {
      setSystemStatus(null);
      return null;
    }
    const data = await fetchJson("/system/status");
    setSystemStatus(data.status);
    return data.status;
  }

  async function refreshUsers() {
    if (!isAdmin) {
      setUsers([]);
      return [];
    }
    const data = await fetchJson("/users");
    setUsers(data.users);
    return data.users;
  }

  async function refreshApp() {
    const meData = await fetchJson("/auth/me");
    setCurrentUser(meData.user);

    const [statsData, modelsData, documentsData, conversationsData] = await Promise.all([
      refreshStats(),
      fetchJson("/models"),
      refreshDocuments(),
      refreshConversations(),
    ]);
    setModelCatalog(modelsData.catalog);
    setStats(statsData);

    if (meData.user.role === "admin") {
      const [usersData, statusData] = await Promise.all([fetchJson("/users"), fetchJson("/system/status")]);
      setUsers(usersData.users);
      setSystemStatus(statusData.status);
    } else {
      setUsers([]);
      setSystemStatus(null);
    }

    return {
      user: meData.user,
      stats: statsData,
      documents: documentsData,
      conversations: conversationsData,
      models: modelsData.catalog,
    };
  }

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      if (!authToken) {
        resetSessionState({
          setAppError,
          setCurrentUser,
          setUsers,
          setStats,
          setSystemStatus,
          setModelCatalog,
          setDocuments,
          setConversations,
          setEvaluationRun,
        });
        setBootstrapping(false);
        return;
      }

      setBootstrapping(true);
      try {
        await refreshApp();
        if (!cancelled) {
          setAppError("");
        }
      } catch (error) {
        clearStoredAuthToken();
        if (!cancelled) {
          setAuthToken("");
          resetSessionState({
            setAppError,
            setCurrentUser,
            setUsers,
            setStats,
            setSystemStatus,
            setModelCatalog,
            setDocuments,
            setConversations,
            setEvaluationRun,
          });
          setAppError(error.message || "应用数据加载失败");
        }
      } finally {
        if (!cancelled) {
          setBootstrapping(false);
        }
      }
    }

    bootstrap();

    return () => {
      cancelled = true;
    };
  }, [authToken]);

  async function login(username, password) {
    const data = await fetchJson("/auth/login", {
      method: "POST",
      body: { username, password },
    });
    setStoredAuthToken(data.token);
    setAuthToken(data.token);
    setCurrentUser(data.user);
    setGlobalNotice(
      data.demo_mode
        ? "当前为本地演示登录模式，会话仅在当前浏览器页签内有效。"
        : "已启用受限登录态，会话到期后需要重新登录。",
    );
    setAppError("");
    return data.user;
  }

  async function logout() {
    try {
      if (authToken) {
        await fetchJson("/auth/logout", { method: "POST" });
      }
    } catch {
      // 忽略退出失败，仍然清理本地登录态。
    } finally {
      clearStoredAuthToken();
      setAuthToken("");
      resetSessionState({
        setAppError,
        setCurrentUser,
        setUsers,
        setStats,
        setSystemStatus,
        setModelCatalog,
        setDocuments,
        setConversations,
        setEvaluationRun,
      });
    }
  }

  async function createConversation(title = "新对话") {
    const data = await fetchJson("/conversations", {
      method: "POST",
      body: { title },
    });
    await refreshConversations();
    await refreshStats();
    return data.conversation;
  }

  async function deleteConversation(conversationId) {
    await fetchJson(`/conversations/${conversationId}`, {
      method: "DELETE",
    });
    await refreshConversations();
    await refreshStats();
  }

  async function uploadDocumentFile(file) {
    const data = await uploadFile("/documents/upload", file);
    await refreshDocuments();
    await refreshStats();
    return data;
  }

  async function reindexDocument(documentId) {
    const data = await fetchJson(`/documents/${documentId}/reindex`, {
      method: "POST",
    });
    await refreshDocuments();
    await refreshStats();
    return data;
  }

  async function bulkReindexDocuments(mode = "missing_embeddings") {
    const data = await fetchJson("/documents/reindex-batch", {
      method: "POST",
      body: { mode },
    });
    await refreshDocuments();
    await refreshStats();
    return data;
  }

  async function deleteDocument(documentId) {
    await fetchJson(`/documents/${documentId}`, {
      method: "DELETE",
    });
    await refreshDocuments();
    await refreshStats();
  }

  async function fetchDocument(documentId) {
    return fetchJson(`/documents/${documentId}`);
  }

  async function fetchDocumentStatus(documentId) {
    return fetchJson(`/documents/${documentId}/status`);
  }

  async function fetchUploadTask(taskId) {
    return fetchJson(`/documents/upload/tasks/${taskId}`);
  }

  async function fetchAgentTasks(params = {}) {
    const data = await fetchJson(withQuery("/tasks", params));
    return data.tasks;
  }

  async function fetchAgentTask(taskId) {
    return fetchJson(`/tasks/${taskId}`);
  }

  async function fetchRetrievalSettings() {
    const data = await fetchJson("/retrieval/settings");
    return data.settings;
  }

  async function updateRetrievalSettings(payload) {
    const data = await fetchJson("/retrieval/settings", {
      method: "POST",
      body: payload,
    });
    await refreshStats();
    return data.settings;
  }

  async function previewRetrieval(query, topK) {
    return fetchJson("/retrieval/preview", {
      method: "POST",
      body: {
        query,
        top_k: topK || null,
      },
    });
  }

  async function debugRetrieval(payload) {
    const data = await fetchJson("/retrieval/debug", {
      method: "POST",
      body: payload,
    });
    return data.debug;
  }

  async function selectModel(modelId) {
    const data = await fetchJson("/models/select", {
      method: "POST",
      body: { model_id: modelId },
    });
    setModelCatalog(data.catalog);
    await refreshStats();
    return data.catalog;
  }

  async function runEvaluation() {
    const data = await fetchJson("/evaluate/run", {
      method: "POST",
    });
    setEvaluationRun(data.run);
    await refreshStats();
    await refreshConversations();
    return data.run;
  }

  return (
    <AppContext.Provider
      value={{
        appError,
        bootstrapping,
        bulkReindexDocuments,
        conversations,
        createConversation,
        currentUser,
        deleteConversation,
        deleteDocument,
        debugRetrieval,
        documents,
        evaluationRun,
        fetchDocument,
        fetchDocumentStatus,
        fetchRetrievalSettings,
        refreshSystemStatus,
        fetchAgentTask,
        fetchAgentTasks,
        fetchUploadTask,
        globalNotice,
        isAdmin,
        isAuthenticated,
        login,
        logout,
        modelCatalog,
        previewRetrieval,
        queryDocuments,
        refreshApp,
        refreshConversations,
        refreshDocuments,
        refreshStats,
        refreshUsers,
        reindexDocument,
        runEvaluation,
        selectModel,
        setGlobalNotice,
        stats,
        systemStatus,
        updateRetrievalSettings,
        uploadDocumentFile,
        users,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext() {
  const value = useContext(AppContext);
  if (!value) {
    throw new Error("useAppContext must be used inside AppProvider");
  }
  return value;
}
