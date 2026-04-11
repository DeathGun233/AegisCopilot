const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8002";
const AUTH_TOKEN_KEY = "aegis.auth.token";

export function getStoredAuthToken() {
  const legacyToken = window.localStorage.getItem(AUTH_TOKEN_KEY);
  if (legacyToken) {
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
  }
  return window.sessionStorage.getItem(AUTH_TOKEN_KEY) || "";
}

export function setStoredAuthToken(token) {
  if (token) {
    window.sessionStorage.setItem(AUTH_TOKEN_KEY, token);
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
    return;
  }
  window.sessionStorage.removeItem(AUTH_TOKEN_KEY);
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
}

export function clearStoredAuthToken() {
  window.sessionStorage.removeItem(AUTH_TOKEN_KEY);
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
}

function buildHeaders(extraHeaders = {}) {
  const token = getStoredAuthToken();
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extraHeaders,
  };
}

async function parseJson(response) {
  if (!response.ok) {
    const raw = await response.text();
    try {
      const payload = JSON.parse(raw);
      throw new Error(payload.detail || raw || `?????${response.status}`);
    } catch (error) {
      if (error instanceof SyntaxError) {
        const text = (raw || "").trim();
        if (response.status === 404 && text === "Not Found") {
          if (response.url.endsWith("/auth/login")) {
            throw new Error("???????????????????????");
          }
          throw new Error("????????????");
        }
        throw new Error(raw || `?????${response.status}`);
      }
      throw error;
    }
  }
  return response.json();
}

export async function fetchJson(path, { method = "GET", body, headers = {} } = {}) {
  const init = {
    method,
    headers: buildHeaders(headers),
  };

  if (body !== undefined) {
    if (body instanceof FormData) {
      init.body = body;
    } else {
      init.body = typeof body === "string" ? body : JSON.stringify(body);
      init.headers = {
        "Content-Type": "application/json",
        ...init.headers,
      };
    }
  }

  const response = await fetch(`${API_BASE}${path}`, init);
  return parseJson(response);
}

export function withQuery(path, params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

export async function uploadFile(path, file) {
  const formData = new FormData();
  formData.append("file", file);
  return fetchJson(path, {
    method: "POST",
    body: formData,
  });
}

export async function streamChat({ query, conversationId }, { onConversation, onStatus, onDelta, onDone }) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildHeaders(),
    },
    body: JSON.stringify({
      query,
      conversation_id: conversationId || null,
    }),
  });

  if (!response.ok || !response.body) {
    const detail = await response.text();
    throw new Error(detail || `???????${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";

    for (const frame of frames) {
      if (!frame.startsWith("data: ")) {
        continue;
      }

      const payload = JSON.parse(frame.slice(6));
      if (payload.type === "conversation") {
        onConversation?.(payload);
      }
      if (payload.type === "status") {
        onStatus?.(payload);
      }
      if (payload.type === "delta") {
        onDelta?.(payload);
      }
      if (payload.type === "done") {
        onDone?.(payload);
      }
    }
  }
}
