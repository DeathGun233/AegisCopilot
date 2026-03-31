import { createContext, useContext, useEffect, useState } from "react";
import {
  clearStoredAuthToken,
  fetchJson,
  getStoredAuthToken,
  setStoredAuthToken,
  uploadFile,
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

  async function refreshStats() {
    const data = await fetchJson("/system/stats");
    setStats(data.stats);
    return data.stats;
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

    const [statsData, modelsData] = await Promise.all([refreshStats(), fetchJson("/models")]);
    const [documentsData, conversationsData] = await Promise.all([refreshDocuments(), refreshConversations()]);
    setModelCatalog(modelsData.catalog);
    setStats(statsData);

    if (meData.user.role === "admin") {
      const usersData = await fetchJson("/users");
      setUsers(usersData.users);
    } else {
      setUsers([]);
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
            setModelCatalog,
            setDocuments,
            setConversations,
            setEvaluationRun,
          });
          setAppError(error.message || "Failed to load application data.");
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
    setAppError("");
    return data.user;
  }

  async function logout() {
    try {
      if (authToken) {
        await fetchJson("/auth/logout", { method: "POST" });
      }
    } catch {
      // Ignore logout failures and clear the local session anyway.
    } finally {
      clearStoredAuthToken();
      setAuthToken("");
      resetSessionState({
        setAppError,
        setCurrentUser,
        setUsers,
        setStats,
        setModelCatalog,
        setDocuments,
        setConversations,
        setEvaluationRun,
      });
    }
  }

  async function createConversation(title = "New conversation") {
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
        conversations,
        createConversation,
        currentUser,
        deleteConversation,
        deleteDocument,
        documents,
        evaluationRun,
        fetchDocument,
        globalNotice,
        isAdmin,
        isAuthenticated,
        login,
        logout,
        modelCatalog,
        refreshApp,
        refreshConversations,
        refreshDocuments,
        refreshStats,
        refreshUsers,
        runEvaluation,
        selectModel,
        setGlobalNotice,
        stats,
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
