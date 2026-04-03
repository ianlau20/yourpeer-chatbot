const API_URL = "/chat/";

const WELCOME_MESSAGE =
  "Hi, welcome to YourPeer. I can help you find services like food, shelter, showers, and more in your area. Your conversation is private \u2014 I don\u2019t save your name or personal details. You can stop or start over anytime.\n\nWhat are you looking for today?";

const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const chat = document.getElementById("chat");
const statusEl = document.getElementById("status");

let sessionId = null;

// --- Icons (inline SVG strings) ---

const ICONS = {
  location: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>`,
  phone: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>`,
  mail: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>`,
  clock: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`,
  chevronLeft: `\u2039`,
  chevronRight: `\u203A`,
};


// --- Utility ---

function stripMarkdown(text) {
  if (!text) return text;
  let s = String(text);
  s = s.replace(/\*\*([^*]+)\*\*/g, "$1");
  s = s.replace(/\*([^*]+)\*/g, "$1");
  s = s.replace(/\*\*/g, "");
  s = s.replace(/\*/g, "");
  return s;
}


// --- Message rendering ---

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = role === "bot" ? stripMarkdown(text) : text;
  chat.appendChild(div);
  scrollToBottom();
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    chat.scrollTop = chat.scrollHeight;
  });
}


// --- Service card carousel ---

function addServiceCards(services) {
  if (!services || services.length === 0) return;

  const wrapper = document.createElement("div");
  wrapper.className = "carousel-wrapper";

  // Header with counter and nav arrows
  const header = document.createElement("div");
  header.className = "carousel-header";

  const counter = document.createElement("span");
  counter.className = "carousel-counter";
  counter.textContent = `1 of ${services.length}`;

  const nav = document.createElement("div");
  nav.className = "carousel-nav";

  const prevBtn = document.createElement("button");
  prevBtn.className = "carousel-btn";
  prevBtn.innerHTML = ICONS.chevronLeft;
  prevBtn.disabled = true;
  prevBtn.type = "button";

  const nextBtn = document.createElement("button");
  nextBtn.className = "carousel-btn";
  nextBtn.innerHTML = ICONS.chevronRight;
  nextBtn.disabled = services.length <= 1;
  nextBtn.type = "button";

  nav.appendChild(prevBtn);
  nav.appendChild(nextBtn);
  header.appendChild(counter);
  header.appendChild(nav);

  // Card track
  const track = document.createElement("div");
  track.className = "carousel-track";

  services.forEach((svc) => {
    track.appendChild(createServiceCard(svc));
  });

  // Dot indicators
  const dots = document.createElement("div");
  dots.className = "carousel-dots";

  services.forEach((_, i) => {
    const dot = document.createElement("div");
    dot.className = `carousel-dot${i === 0 ? " active" : ""}`;
    dots.appendChild(dot);
  });

  // Wire up scroll tracking
  let currentIndex = 0;

  function updateIndicators(index) {
    currentIndex = index;
    counter.textContent = `${index + 1} of ${services.length}`;
    prevBtn.disabled = index === 0;
    nextBtn.disabled = index >= services.length - 1;

    dots.querySelectorAll(".carousel-dot").forEach((d, i) => {
      d.classList.toggle("active", i === index);
    });
  }

  track.addEventListener("scroll", () => {
    const cardWidth = track.firstElementChild?.offsetWidth || 280;
    const gap = 12;
    const idx = Math.round(track.scrollLeft / (cardWidth + gap));
    if (idx !== currentIndex) {
      updateIndicators(Math.min(idx, services.length - 1));
    }
  });

  prevBtn.addEventListener("click", () => {
    if (currentIndex > 0) {
      const cardWidth = track.firstElementChild?.offsetWidth || 280;
      track.scrollLeft = (currentIndex - 1) * (cardWidth + 12);
    }
  });

  nextBtn.addEventListener("click", () => {
    if (currentIndex < services.length - 1) {
      const cardWidth = track.firstElementChild?.offsetWidth || 280;
      track.scrollLeft = (currentIndex + 1) * (cardWidth + 12);
    }
  });

  wrapper.appendChild(header);
  wrapper.appendChild(track);
  if (services.length > 1) {
    wrapper.appendChild(dots);
  }

  chat.appendChild(wrapper);
  scrollToBottom();
}


function createServiceCard(svc) {
  const card = document.createElement("div");
  card.className = "service-card";

  // Name
  const name = document.createElement("div");
  name.className = "card-name";
  name.textContent = svc.service_name || "Service";
  card.appendChild(name);

  // Organization
  if (svc.organization) {
    const org = document.createElement("div");
    org.className = "card-org";
    org.textContent = svc.organization;
    card.appendChild(org);
  }

  // Hours / open status
  const hoursRow = document.createElement("div");
  hoursRow.className = "card-hours";

  const badge = document.createElement("span");
  if (svc.is_open === "open") {
    badge.className = "status-badge status-open";
    badge.textContent = "Open now";
  } else if (svc.is_open === "closed") {
    badge.className = "status-badge status-closed";
    badge.textContent = "Closed";
  } else {
    badge.className = "status-badge status-unknown";
    badge.textContent = "Hours not available";
  }
  hoursRow.appendChild(badge);

  if (svc.hours_today) {
    const times = document.createElement("span");
    times.className = "card-hours-text";
    times.innerHTML = `${ICONS.clock}<span>${escapeHtml(svc.hours_today)}</span>`;
    hoursRow.appendChild(times);
  }

  card.appendChild(hoursRow);

  // Address
  if (svc.address) {
    const detail = document.createElement("div");
    detail.className = "card-detail";
    detail.innerHTML = `${ICONS.location}<span>${escapeHtml(svc.address)}</span>`;
    card.appendChild(detail);
  }

  // Phone
  if (svc.phone) {
    const detail = document.createElement("div");
    detail.className = "card-detail";
    detail.innerHTML = `${ICONS.phone}<span>${escapeHtml(svc.phone)}</span>`;
    card.appendChild(detail);
  }

  // Email
  if (svc.email) {
    const detail = document.createElement("div");
    detail.className = "card-detail";
    detail.innerHTML = `${ICONS.mail}<span>${escapeHtml(svc.email)}</span>`;
    card.appendChild(detail);
  }

  // Description
  if (svc.description) {
    const desc = document.createElement("div");
    desc.className = "card-desc";
    desc.textContent = svc.description;
    card.appendChild(desc);
  }

  // Fees badge
  if (svc.fees) {
    const fee = document.createElement("span");
    fee.className = "card-fee";
    fee.textContent = svc.fees;
    card.appendChild(fee);
  }

  // Learn More button (links to YourPeer listing)
  if (svc.yourpeer_url) {
    const learnMore = document.createElement("a");
    learnMore.className = "card-action-btn learn-more";
    learnMore.href = svc.yourpeer_url;
    learnMore.target = "_blank";
    learnMore.rel = "noopener";
    learnMore.textContent = "Learn More on YourPeer";
    card.appendChild(learnMore);
  }

  // Action buttons
  const actions = document.createElement("div");
  actions.className = "card-actions";

  if (svc.phone) {
    const callBtn = document.createElement("a");
    callBtn.className = "card-action-btn primary";
    callBtn.href = `tel:${svc.phone.replace(/\D/g, "")}`;
    callBtn.textContent = "Call";
    actions.appendChild(callBtn);
  }

  if (svc.address) {
    const dirBtn = document.createElement("a");
    dirBtn.className = "card-action-btn";
    dirBtn.href = `https://maps.google.com/?q=${encodeURIComponent(svc.address)}`;
    dirBtn.target = "_blank";
    dirBtn.rel = "noopener";
    dirBtn.textContent = "Directions";
    actions.appendChild(dirBtn);
  }

  if (svc.website) {
    const webBtn = document.createElement("a");
    webBtn.className = "card-action-btn";
    webBtn.href = svc.website;
    webBtn.target = "_blank";
    webBtn.rel = "noopener";
    webBtn.textContent = "Website";
    actions.appendChild(webBtn);
  }

  if (actions.children.length > 0) {
    card.appendChild(actions);
  }

  return card;
}


function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}


// --- Quick-reply buttons ---

function addQuickReplies(replies) {
  if (!replies || replies.length === 0) return;

  // Remove any existing quick-reply containers (only latest set is active)
  chat.querySelectorAll(".quick-replies").forEach((el) => {
    el.classList.add("used");
    el.querySelectorAll(".quick-reply-btn").forEach((btn) => {
      btn.classList.add("used");
    });
  });

  const container = document.createElement("div");
  container.className = "quick-replies";

  replies.forEach((qr) => {
    const btn = document.createElement("button");
    btn.className = "quick-reply-btn";
    btn.textContent = qr.label;
    btn.type = "button";

    btn.addEventListener("click", () => {
      // Disable all buttons in this set
      container.querySelectorAll(".quick-reply-btn").forEach((b) => {
        b.classList.add("used");
      });

      // Send the value as a user message
      sendMessage(qr.value);
    });

    container.appendChild(btn);
  });

  chat.appendChild(container);
  scrollToBottom();
}


// --- Feedback (thumbs up/down) ---

function addFeedbackRow() {
  const row = document.createElement("div");
  row.className = "feedback-row";

  const label = document.createElement("span");
  label.className = "feedback-label";
  label.textContent = "Were these results helpful?";

  const thumbsUp = document.createElement("button");
  thumbsUp.className = "feedback-btn";
  thumbsUp.setAttribute("aria-label", "Thumbs up");
  thumbsUp.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z"/><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>`;

  const thumbsDown = document.createElement("button");
  thumbsDown.className = "feedback-btn";
  thumbsDown.setAttribute("aria-label", "Thumbs down");
  thumbsDown.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z"/><path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg>`;

  function submitFeedback(rating) {
    // Disable both buttons immediately
    thumbsUp.disabled = true;
    thumbsDown.disabled = true;
    thumbsUp.classList.toggle("feedback-selected-up", rating === "up");
    thumbsDown.classList.toggle("feedback-selected-down", rating === "down");

    // Show thank-you inline
    label.textContent = rating === "up" ? "Thanks for the feedback! 👍" : "Thanks — we'll work to improve. 👎";

    // Fire and forget — no need to block the UI
    fetch("/chat/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, rating }),
    }).catch(() => {/* silent — feedback loss is acceptable */});
  }

  thumbsUp.addEventListener("click", () => submitFeedback("up"));
  thumbsDown.addEventListener("click", () => submitFeedback("down"));

  row.appendChild(label);
  row.appendChild(thumbsUp);
  row.appendChild(thumbsDown);

  chat.appendChild(row);
  scrollToBottom();
}

function setLoading(isLoading) {
  sendBtn.disabled = isLoading;
  input.disabled = isLoading;
  statusEl.className = "status";
  statusEl.textContent = isLoading ? "Searching..." : "";
}

function setError(message) {
  statusEl.className = "status error";
  statusEl.textContent = message;
}


// --- Send message (shared by form submit and quick-reply taps) ---

async function sendMessage(text) {
  if (!text || !text.trim()) return;
  const message = text.trim();

  addMessage("user", message);
  setLoading(true);

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: sessionId,
      }),
    });

    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }

    const data = await response.json();
    sessionId = data.session_id || sessionId;
    console.log("chat response", data);

    // Always show the text response
    addMessage("bot", data.response || "(No response text)");

    // If there are service cards, render the carousel + feedback prompt
    if (data.services && data.services.length > 0) {
      addServiceCards(data.services);
      addFeedbackRow();
    }

    // If there are quick replies, render them
    if (data.quick_replies && data.quick_replies.length > 0) {
      addQuickReplies(data.quick_replies);
    }
  } catch (err) {
    setError(`Error: ${err.message}`);
    addMessage("bot", "Sorry, something went wrong. Please try again.");
  } finally {
    setLoading(false);
    input.focus();
  }
}


// --- Form submission ---

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const message = input.value.trim();
  if (!message) return;

  input.value = "";

  // Disable any active quick-reply buttons when user types manually
  chat.querySelectorAll(".quick-replies").forEach((el) => {
    el.querySelectorAll(".quick-reply-btn").forEach((btn) => {
      btn.classList.add("used");
    });
  });

  await sendMessage(message);
});


// --- Welcome message ---
addMessage("bot", WELCOME_MESSAGE);
addQuickReplies([
  { label: "🍽️ Food", value: "I need food" },
  { label: "🏠 Shelter", value: "I need shelter" },
  { label: "🚿 Showers", value: "I need a shower" },
  { label: "👕 Clothing", value: "I need clothing" },
  { label: "🏥 Health Care", value: "I need health care" },
  { label: "💼 Jobs", value: "I need help finding a job" },
  { label: "⚖️ Legal Help", value: "I need legal help" },
  { label: "🧠 Mental Health", value: "I need mental health support" },
  { label: "📋 Other", value: "I need other services" },
]);
