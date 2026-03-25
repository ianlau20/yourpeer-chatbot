const API_URL = "http://127.0.0.1:8000/chat/";

const WELCOME_MESSAGE =
  "Welcome to YourPeer. Let me know what you're looking for and I'll do my best to help.";

const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const chat = document.getElementById("chat");
const statusEl = document.getElementById("status");

let sessionId = null;

/** Strip common Markdown-style asterisks from model text (plain chat has no renderer). */
// TODO: This is a hack to remove the asterisks from the model text. It should be removed when the model text is cleaned up.
function stripMarkdownAsterisks(text) {
  if (!text) return text;
  let s = String(text);
  s = s.replace(/\*\*([^*]+)\*\*/g, "$1");
  s = s.replace(/\*([^*]+)\*/g, "$1");
  s = s.replace(/\*\*/g, "");
  s = s.replace(/\*/g, "");
  return s;
}

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = role === "bot" ? stripMarkdownAsterisks(text) : text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function setLoading(isLoading) {
  sendBtn.disabled = isLoading;
  input.disabled = isLoading;
  statusEl.className = "status";
  statusEl.textContent = isLoading ? "Thinking..." : "";
}

function setError(message) {
  statusEl.className = "status error";
  statusEl.textContent = message;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const message = input.value.trim();
  if (!message) return;

  addMessage("user", message);
  input.value = "";
  setLoading(true);

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        message,
        session_id: sessionId
      })
    });

    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }

    const data = await response.json();
    sessionId = data.session_id || sessionId;
    console.log("chat response", data);
    addMessage("bot", data.response || "(No response text)");
  } catch (err) {
    setError(`Error: ${err.message}`);
    addMessage("bot", "Sorry, something went wrong.");
  } finally {
    setLoading(false);
    input.focus();
  }
});

addMessage("bot", WELCOME_MESSAGE);