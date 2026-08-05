(function () {
  "use strict";

  const root = document.querySelector("[data-game-table]");
  if (!root) return;

  const actionUrl = root.dataset.actionUrl;
  const stateUrl = root.dataset.stateUrl;
  const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;
  const POLL_INTERVAL_MS = 2500;
  const DEAL_STAGGER_MS = 90;

  // Previous hand keys per zone, so polling only animates newly dealt or
  // freshly revealed cards instead of replaying the whole deal each time.
  const previousHands = { dealer: null, seats: {} };
  let yourPreviousStatus = root.dataset.yourStatus || null;
  let resultToastShown = false;

  function cardKey(card) {
    return card.hidden ? "hidden" : card.rank + card.symbol;
  }

  function domCardKey(el) {
    if (el.classList.contains("card-unit--hidden")) return "hidden";
    const rank = el.querySelector(".card-unit__rank");
    const suit = el.querySelector(".card-unit__suit");
    return (rank ? rank.textContent : "") + (suit ? suit.textContent : "");
  }

  function seedPreviousHands() {
    const dealerHand = root.querySelector("[data-dealer-hand]");
    previousHands.dealer = Array.from(dealerHand.children, domCardKey);
    root.querySelectorAll("[data-seat]").forEach((seat) => {
      const hand = seat.querySelector("[data-hand]");
      previousHands.seats[seat.dataset.seat] = Array.from(hand.children, domCardKey);
    });
  }

  function suitClass(color) {
    return color === "red" ? "card-unit--red" : "card-unit--black";
  }

  function renderCard(card, options) {
    const el = document.createElement("div");
    if (card.hidden) {
      el.className = "card-unit card-unit--hidden";
    } else {
      el.className = `card-unit ${suitClass(card.color)}`;
      el.innerHTML = `
        <span class="card-unit__rank">${card.rank}</span>
        <span class="card-unit__pip">${card.symbol}</span>
        <span class="card-unit__suit card-unit__suit--${card.color}">${card.symbol}</span>
      `;
    }
    if (options.enter) {
      el.classList.add("card-unit--enter");
      el.style.animationDelay = `${options.enterIndex * DEAL_STAGGER_MS}ms`;
    }
    if (options.flip) {
      el.classList.add("card-unit--flip");
    }
    return el;
  }

  // Re-renders a hand only when it changed; new cards slide in from the
  // shoe, a card that was hidden and is now visible plays the flip reveal.
  function renderHand(container, cards, prevKeys) {
    const keys = cards.map(cardKey);
    if (prevKeys && keys.join("|") === prevKeys.join("|")) return keys;

    container.innerHTML = "";
    let entering = 0;
    cards.forEach((card, i) => {
      const isNew = !prevKeys || i >= prevKeys.length;
      const wasHidden = Boolean(prevKeys) && prevKeys[i] === "hidden" && !card.hidden;
      const el = renderCard(card, { enter: isNew, enterIndex: entering, flip: wasHidden });
      if (isNew) entering += 1;
      container.appendChild(el);
    });
    return keys;
  }

  function applyState(state) {
    // Lobby phase: the waiting-room block is server-rendered, so reflect
    // seat/status changes (someone joined, host started) with a reload.
    if (root.dataset.status === "EN_ATTENTE") {
      if (state.status !== "EN_ATTENTE" || String(state.players.length) !== root.dataset.players) {
        window.location.reload();
      }
      return;
    }

    const dealerHand = root.querySelector("[data-dealer-hand]");
    previousHands.dealer = renderHand(dealerHand, state.dealer.cards, previousHands.dealer);
    root.querySelector("[data-dealer-total]").textContent =
      state.dealer.total !== null ? state.dealer.total : "?";

    state.players.forEach((player) => {
      const seat = root.querySelector(`[data-seat="${player.seat}"]`);
      if (!seat) return;
      const key = String(player.seat);
      previousHands.seats[key] = renderHand(
        seat.querySelector("[data-hand]"),
        player.hand,
        previousHands.seats[key] || null
      );
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

    notifyOutcomes(state);

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

  // ------------------------------------------------------------- Toasts ---

  function showToast(variant, title, detail) {
    const stack = root.querySelector("[data-toast-stack]");
    if (!stack) return;
    const toast = document.createElement("div");
    toast.className = `toast toast--${variant}`;
    toast.innerHTML = `<span class="toast__title"></span><span class="toast__detail"></span>`;
    toast.querySelector(".toast__title").textContent = title;
    toast.querySelector(".toast__detail").textContent = detail || "";
    stack.appendChild(toast);
    setTimeout(() => toast.classList.add("toast--leaving"), 3800);
    setTimeout(() => toast.remove(), 4200);
  }

  function notifyOutcomes(state) {
    const you = state.players.find((p) => p.is_you);
    if (!you) return;

    if (yourPreviousStatus !== "BUST" && you.status === "BUST") {
      showToast("bust", "BUST !", `Vous dépassez 21 — mise de ${you.bet} jetons perdue.`);
    }
    yourPreviousStatus = you.status;

    if (state.status === "TERMINEE" && !resultToastShown) {
      resultToastShown = true;
      if (you.result === "BLACKJACK") {
        showToast("blackjack", "BLACKJACK !", `Paiement 3:2 sur ${you.bet} jetons.`);
      } else if (you.result === "WIN") {
        showToast("win", "WINNER !", `Vous remportez ${you.bet * 2} jetons.`);
      } else if (you.result === "PUSH") {
        showToast("push", "PUSH", `Égalité — mise de ${you.bet} jetons remboursée.`);
      } else if (you.result === "LOSE" && you.status !== "BUST") {
        showToast("lose", "Perdu…", "Le croupier l'emporte cette fois.");
      }
    }
  }

  // ------------------------------------------------------------ Actions ---

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

  // ------------------------------------------------------------- Polling ---

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

  seedPreviousHands();
  if (root.dataset.status === "EN_COURS" || root.dataset.status === "EN_ATTENTE") {
    startPolling();
  }
})();
