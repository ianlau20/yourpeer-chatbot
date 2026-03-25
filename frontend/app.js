const API_URL = "http://127.0.0.1:8000/chat/";

const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const chat = document.getElementById("chat");
const statusEl = document.getElementById("status");

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
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
      body: JSON.stringify({ message })
    });

    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }

    const data = await response.json();
    addMessage("bot", data.response || "(No response text)");
  } catch (err) {
    setError(`Error: ${err.message}`);
    addMessage("bot", "Sorry, something went wrong.");
  } finally {
    setLoading(false);
    input.focus();
  }
});