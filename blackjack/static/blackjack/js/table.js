(function () {
  "use strict";

  const root = document.querySelector("[data-game-table]");
  if (!root) return;

  const gameCode = root.dataset.gameCode;
  const actionUrl = root.dataset.actionUrl;
  const stateUrl = root.dataset.stateUrl;
  const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;
  const POLL_INTERVAL_MS = 2500;

  function suitClass(color) {
    return color === "red" ? "card-unit--red" : "card-unit--black";
  }

  function renderCard(card) {
    const el = document.createElement("div");
    if (card.hidden) {
      el.className = "card-unit card-unit--hidden";
      return el;
    }
    el.className = `card-unit ${suitClass(card.color)}`;
    el.innerHTML = `
      <span class="card-unit__rank">${card.rank}</span>
      <span class="card-unit__suit card-unit__suit--${card.color}">${card.symbol}</span>
    `;
    return el;
  }

  function renderHand(container, cards) {
    container.innerHTML = "";
    cards.forEach((card) => container.appendChild(renderCard(card)));
  }

  function applyState(state) {
    const dealerHand = root.querySelector("[data-dealer-hand]");
    renderHand(dealerHand, state.dealer.cards);
    root.querySelector("[data-dealer-total]").textContent =
      state.dealer.total !== null ? state.dealer.total : "?";

    state.players.forEach((player) => {
      const seat = root.querySelector(`[data-seat="${player.seat}"]`);
      if (!seat) return;
      renderHand(seat.querySelector("[data-hand]"), player.hand);
      seat.querySelector("[data-total]").textContent = player.total ?? "0";
      seat.classList.toggle("seat--active-turn", player.is_turn);

      const badge = seat.querySelector("[data-status-badge]");
      badge.textContent = player.result !== "PENDING" ? player.result_label : player.status_label;
      badge.className = "badge " + resultBadgeClass(player);
    });

    const actionZone = root.querySelector("[data-action-zone]");
    if (actionZone) {
      actionZone.querySelectorAll("button[data-action]").forEach((btn) => {
        btn.disabled = !state.your_turn;
      });
    }

    const statusLabel = root.querySelector("[data-game-status]");
    if (statusLabel) statusLabel.textContent = state.status_label;

    if (state.status === "TERMINEE") {
      stopPolling();
      const banner = root.querySelector("[data-round-over]");
      if (banner) banner.hidden = false;
    }
  }

  function resultBadgeClass(player) {
    if (player.result === "WIN" || player.result === "BLACKJACK") return "badge--win";
    if (player.result === "LOSE") return "badge--lose";
    if (player.result === "PUSH") return "badge--push";
    if (player.status === "BUST") return "badge--bust";
    if (player.is_turn) return "badge--active";
    return "";
  }

  async function sendAction(action) {
    const res = await fetch(actionUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify({ action }),
    });
    const data = await res.json();
    if (!res.ok) {
      showError(data.error || "Action refusée.");
      return;
    }
    applyState(data);
  }

  function showError(message) {
    const box = root.querySelector("[data-error-box]");
    if (!box) return;
    box.textContent = message;
    box.hidden = false;
    setTimeout(() => {
      box.hidden = true;
    }, 3000);
  }

  root.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => sendAction(btn.dataset.action));
  });

  let pollHandle = null;

  async function refreshState() {
    const res = await fetch(stateUrl);
    if (!res.ok) return;
    const data = await res.json();
    applyState(data);
  }

  function startPolling() {
    pollHandle = window.setInterval(refreshState, POLL_INTERVAL_MS);
  }

  function stopPolling() {
    if (pollHandle) window.clearInterval(pollHandle);
  }

  if (root.dataset.status === "EN_COURS") {
    startPolling();
  }
})();
