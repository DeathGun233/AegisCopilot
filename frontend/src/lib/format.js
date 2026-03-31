export function formatDateTime(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function getConversationPreview(conversation) {
  const latest = conversation?.messages?.[conversation.messages.length - 1];
  return latest?.content || "从空白对话开始";
}

export function truncate(text, length = 120) {
  if (!text) {
    return "";
  }
  if (text.length <= length) {
    return text;
  }
  return `${text.slice(0, length)}...`;
}

export function roleLabel(role) {
  return role === "assistant" ? "助手" : role === "user" ? "用户" : "系统";
}
