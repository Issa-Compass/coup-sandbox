const CARD_SHORT = {
  duke: "Duke",
  assassin: "Assassin",
  captain: "Captain",
  ambassador: "Ambassador",
  contessa: "Contessa",
};

const ACTION_CLAIM = {
  tax: "duke",
  assassinate: "assassin",
  steal: "captain",
  exchange: "ambassador",
};

const ACTION_LABEL = {
  income: "Income",
  foreign_aid: "Foreign Aid",
  coup: "Coup",
  tax: "Tax",
  assassinate: "Assassinate",
  steal: "Steal",
  exchange: "Exchange",
};

const SPEEDS = [
  { label: "2s", ms: 2000 },
  { label: "1s", ms: 1000 },
  { label: "0.5s", ms: 500 },
  { label: "0.25s", ms: 250 },
];

const DEFAULT_AGENTS = [
  { id: "random", name: "random_bot", kind: "example" },
  { id: "honest", name: "honest_bot", kind: "example" },
  { id: "bluffer", name: "bluffer_bot", kind: "example" },
  { id: "challenger", name: "challenger_bot", kind: "example" },
];

function defaultSetup() {
  return {
    agents: [],
    games: 40,
    seed: null,
    timeout: 1,
    tableSize: 5,
  };
}

function randomSeed() {
  return Math.floor(Math.random() * (2 ** 31 - 1)) + 1;
}

/** Mirror of coup.runner.schedule.choose_sizes — split N into equal-play tables of 2–6. */
function chooseSizes(playerCount, prefer = 5) {
  if (playerCount < 2) return null;
  if (!(prefer >= 2 && prefer <= 6)) prefer = 5;
  if (playerCount <= 6) return [playerCount];
  const tiers = [
    new Set([4, 5, 6]),
    new Set([3, 4, 5, 6]),
    new Set([2, 3, 4, 5, 6]),
  ];
  for (const allowed of tiers) {
    const found = bestSplit(playerCount, allowed, prefer);
    if (found) return found;
  }
  return null;
}

function splitCost(sizes, prefer) {
  const drift = sizes.reduce((sum, size) => sum + Math.abs(size - prefer), 0);
  const hits = sizes.reduce((sum, size) => sum + (size === prefer ? 1 : 0), 0);
  return [drift, -hits, sizes.length];
}

function costBetter(a, b) {
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] < b[i]) return true;
    if (a[i] > b[i]) return false;
  }
  return false;
}

function bestSplit(playerCount, allowed, prefer) {
  const bestAt = { 0: [] };
  for (let total = 0; total < playerCount; total += 1) {
    const sizes = bestAt[total];
    if (!sizes) continue;
    for (const part of [...allowed].sort((a, b) => a - b)) {
      const nxt = total + part;
      if (nxt > playerCount) continue;
      const candidate = sizes.concat(part);
      const old = bestAt[nxt];
      if (!old || costBetter(splitCost(candidate, prefer), splitCost(old, prefer))) {
        bestAt[nxt] = candidate;
      }
    }
  }
  return bestAt[playerCount] || null;
}

function seatingPlan(agentCount, prefer, gamesPerAgent) {
  const sizes = chooseSizes(agentCount, prefer);
  if (!sizes) return null;
  const tablesPerWave = sizes.length;
  const sorted = [...sizes].sort((a, b) => b - a);
  return {
    sizes: sorted,
    tablesPerWave,
    totalTables: tablesPerWave * gamesPerAgent,
    gamesPerAgent,
    singleTable: sizes.length === 1,
  };
}

const state = {
  runs: [],
  runId: null,
  round: null,
  view: "scoreboard",
  standings: null,
  roundSummaries: {},
  runRounds: [],
  games: [],
  playback: null,
  agents: [],
  session: null,
  setupOpen: false,
  setupMode: "round", // "tournament" = pick agents; "round" = play next games
  setupMenuOpen: false,
  setup: defaultSetup(),
  setupError: null,
  rulesOpen: false,
  rulesText: null,
  copyFlash: null,
};

let playTimer = null;
let liveTimer = null;
let liveInFlight = false;

const app = document.getElementById("app");

async function init() {
  window.addEventListener("hashchange", () => route());
  await Promise.all([loadRuns(), loadAgents(), loadSession()]);
  syncLivePolling();
  route();
}

function sessionIsLive() {
  return state.session?.status === "running";
}

function syncLivePolling() {
  if (sessionIsLive()) {
    if (!liveTimer) {
      liveTimer = setInterval(() => {
        refreshLive();
      }, 400);
      queueMicrotask(() => refreshLive());
    }
    return;
  }
  if (liveTimer) {
    clearInterval(liveTimer);
    liveTimer = null;
  }
}

async function refreshLive() {
  if (liveInFlight) return;
  liveInFlight = true;
  try {
    const wasLive = sessionIsLive();
    const prevGame = state.session?.current_game;
    const prevMessage = state.session?.message;
    const prevGamesLen = state.games.length;
    await loadSession({ quiet: true });
    const live = sessionIsLive();
    const sameRun = state.session?.run_id && state.session.run_id === state.runId;

    if (sameRun) {
      if (state.view === "games") {
        if (live && state.session.current_round && state.round !== state.session.current_round) {
          state.round = state.session.current_round;
          const hash = `#/games/${encodeURIComponent(state.runId)}/${state.round}`;
          if (location.hash !== hash) {
            location.hash = hash;
            syncLivePolling();
            return;
          }
        }
        await loadGames({ quiet: true });
      } else if (state.view === "scoreboard") {
        await loadRuns({ quiet: true });
        await loadScoreboard({ quiet: true });
      }
      if (wasLive && !live) {
        await loadRuns({ quiet: true });
        if (state.view === "scoreboard") await loadScoreboard({ quiet: true });
        if (state.view === "games") await loadGames({ quiet: true });
      }
    }

    syncLivePolling();
    const changed =
      wasLive !== live ||
      state.session?.current_game !== prevGame ||
      state.session?.message !== prevMessage ||
      state.games.length !== prevGamesLen;
    if (changed || live) render();
  } finally {
    liveInFlight = false;
  }
}

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const parts = raw.split("/").filter(Boolean);
  if (parts[0] === "play" && parts.length >= 4) {
    return { view: "play", runId: parts[1], round: Number(parts[2]), gameId: parts[3] };
  }
  if (parts[0] === "games" && parts.length >= 3) {
    return { view: "games", runId: parts[1], round: Number(parts[2]) };
  }
  if (parts[0] === "run" && parts.length >= 2) {
    return {
      view: "scoreboard",
      runId: parts[1],
      round: parts[2] === "standings" || parts[2] == null ? null : Number(parts[2]),
    };
  }
  return { view: "scoreboard", runId: state.runId, round: state.round };
}

async function route() {
  stopPlaybackTimer();
  const next = parseHash();
  state.view = next.view;
  if (next.runId) state.runId = next.runId;
  if (!state.runId && state.runs.length) state.runId = state.runs[0].id;
  if (next.view === "scoreboard") {
    state.round = Number.isFinite(next.round) ? next.round : null;
    await loadScoreboard();
  } else if (next.view === "games") {
    state.round = next.round;
    await loadGames();
  } else if (next.view === "play") {
    state.round = next.round;
    await loadPlayback(next.gameId);
  }
  render();
}

async function loadRuns({ quiet = false } = {}) {
  try {
    const data = await fetchJson("/api/runs");
    state.runs = data.runs || [];
    if (!state.runId && state.runs.length) state.runId = state.runs[0].id;
  } catch (err) {
    if (!quiet) console.error(err);
  }
}

async function loadAgents({ quiet = false } = {}) {
  try {
    const data = await fetchJson("/api/agents");
    const fromApi = (data.agents || []).filter(
      (agent) =>
        agent.kind === "example" || agent.kind === "local" || agent.kind === "submission"
    );
    const byId = new Map(DEFAULT_AGENTS.map((agent) => [agent.id, { ...agent }]));
    for (const agent of fromApi) byId.set(agent.id, agent);
    // Keep the four examples first, then local + submissions.
    const examples = DEFAULT_AGENTS.map((agent) => byId.get(agent.id)).filter(Boolean);
    const extras = [...byId.values()].filter((agent) => !DEFAULT_AGENTS.some((d) => d.id === agent.id));
    state.agents = [...examples, ...extras];
  } catch (err) {
    if (!quiet) console.error(err);
    state.agents = [...DEFAULT_AGENTS];
  }
}

async function loadSession({ quiet = false } = {}) {
  try {
    state.session = await fetchJson("/api/session");
  } catch (err) {
    if (!quiet) console.error(err);
  }
}

async function loadScoreboard({ quiet = false } = {}) {
  if (!state.runId) {
    state.standings = null;
    state.roundSummaries = {};
    state.runRounds = [];
    return;
  }
  try {
    let rounds = [];
    try {
      const meta = await fetchJson(`/api/runs/${encodeURIComponent(state.runId)}`);
      rounds = meta.rounds || [];
    } catch {
      rounds = [];
    }
    if (state.session?.status === "running" && state.session.run_id === state.runId) {
      for (const round of state.session.rounds || []) {
        if (round?.number && !rounds.includes(round.number)) rounds.push(round.number);
      }
      if (state.session.current_round && !rounds.includes(state.session.current_round)) {
        rounds.push(state.session.current_round);
      }
    }
    rounds = [...new Set(rounds)].sort((a, b) => a - b);
    state.runRounds = rounds;

    try {
      state.standings = await fetchJson(`/api/runs/${encodeURIComponent(state.runId)}/standings`);
    } catch {
      state.standings = null;
    }

    const summaries = {};
    await Promise.all(
      rounds.map(async (round) => {
        try {
          summaries[round] = await fetchJson(
            `/api/runs/${encodeURIComponent(state.runId)}/rounds/${round}`
          );
        } catch {
          summaries[round] = null;
        }
      })
    );
    state.roundSummaries = summaries;
  } catch (err) {
    if (!quiet) console.error(err);
    state.standings = null;
    state.roundSummaries = {};
    state.runRounds = [];
  }
}

async function loadGames({ quiet = false } = {}) {
  if (!state.runId || !state.round) {
    state.games = [];
    return;
  }
  try {
    const data = await fetchJson(
      `/api/runs/${encodeURIComponent(state.runId)}/rounds/${state.round}/games`
    );
    state.games = data.games || [];
  } catch (err) {
    if (!quiet) console.error(err);
    state.games = [];
  }
}

async function loadPlayback(gameId) {
  const data = await fetchJson(
    `/api/runs/${encodeURIComponent(state.runId)}/rounds/${state.round}/games/${encodeURIComponent(gameId)}`
  );
  const lines = data.lines || [];
  const header = lines.find((row) => row.type === "game") || {};
  const result = lines.find((row) => row.type === "result") || null;
  const events = lines.filter((row) => row.type === "event");
  const hasHands = events.some((row) => row.state?.players?.some((p) => Array.isArray(p.hand)));
  state.playback = {
    header,
    result,
    events,
    index: 0,
    playing: false,
    speedMs: 1000,
    reveal: false,
    hasHands,
  };
}

async function fetchJson(url, options) {
  const res = await fetch(url, { cache: "no-store", ...options });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `${res.status} ${url}`);
  }
  return res.json();
}

function render() {
  if (state.view === "play" && state.playback) {
    app.innerHTML = renderPlayback();
    bindPlayback();
    return;
  }
  if (state.view === "games") {
    app.innerHTML = renderGames();
    bindChrome();
    return;
  }
  app.innerHTML = renderScoreboard();
  bindChrome();
}

function currentRun() {
  return state.runs.find((run) => run.id === state.runId) || null;
}

function renderToggle({ id = "", checked = false, label = "", disabled = false, attrs = "" } = {}) {
  return `<label class="toggle control-chip ${disabled ? "is-disabled" : ""}">
    <input ${id ? `id="${escapeAttr(id)}"` : ""} class="toggle-input" type="checkbox" ${
      checked ? "checked" : ""
    } ${disabled ? "disabled" : ""} ${attrs}>
    <span class="toggle-box" aria-hidden="true"></span>
    <span class="toggle-text">${escapeHtml(label)}</span>
  </label>`;
}

function renderChrome(title, subtitle, extra = "") {
  const runOptions = state.runs.length
    ? state.runs
        .map(
          (run) =>
            `<option value="${escapeAttr(run.id)}" ${
              run.id === state.runId ? "selected" : ""
            }>${escapeHtml(run.id)}</option>`
        )
        .join("")
    : state.runId
      ? `<option value="${escapeAttr(state.runId)}" selected>${escapeHtml(state.runId)}</option>`
      : `<option value="">No runs yet</option>`;
  return `
    <div class="shell">
      <header class="topbar">
        <div>
          <p class="brand">Coup<span class="brand-nav">
            ${escapeHtml(subtitle)}
            <span class="brand-sep" aria-hidden="true">·</span>
            <button type="button" class="brand-link" id="open-rules">
              Game rules ${bookIcon()}
            </button>
          </span></p>
        </div>
        <div class="controls">
          <div class="field">
            <label for="run-select">Run</label>
            <select id="run-select">${runOptions}</select>
          </div>
          <div class="field">
            <label for="toggle-setup">Play</label>
            <div class="play-group">
              <button class="btn primary ${state.setupOpen && state.setupMode === "round" ? "active" : ""}" id="toggle-setup" type="button">Play Games</button>
              <div class="menu ${state.setupMenuOpen ? "open" : ""}">
                <button class="btn icon-btn ${state.setupOpen && state.setupMode === "tournament" ? "active" : ""}" id="setup-menu-btn" type="button" aria-label="Tournament settings" aria-expanded="${state.setupMenuOpen ? "true" : "false"}" title="Settings">
                  ${settingsIcon()}
                </button>
                <div class="menu-panel" role="menu">
                  <button class="menu-item" type="button" id="new-tournament" role="menuitem">New tournament</button>
                </div>
              </div>
            </div>
          </div>
          ${extra}
        </div>
      </header>
      ${renderSessionBanner()}
      ${state.setupOpen ? renderSetup() : ""}
      ${title}
      ${state.rulesOpen ? renderRulesModal() : ""}
    </div>
  `;
}

function renderSessionBanner() {
  const session = state.session;
  if (!session || session.status !== "running") return "";
  if (session.run_id && state.runId && session.run_id !== state.runId) {
    return `<div class="session-live-banner">
      <div class="session-live-dot" aria-hidden="true"></div>
      <div class="session-live-text">
        <strong>Live on another run</strong>
        <span class="muted">${escapeHtml(session.message || session.run_id)}</span>
      </div>
      <a class="btn" href="#/games/${encodeURIComponent(session.run_id)}/${session.current_round || 1}">Watch</a>
    </div>`;
  }
  const round = session.current_round;
  const progress =
    session.games_in_round > 0
      ? `${session.current_game}/${session.games_in_round}`
      : "starting";
  return `<div class="session-live-banner">
    <div class="session-live-dot" aria-hidden="true"></div>
    <div class="session-live-text">
      <strong>Live</strong>
      <span class="muted">${escapeHtml(session.message || `Round ${round || "?"} · ${progress}`)}</span>
    </div>
    ${
      round
        ? `<a class="btn" href="#/games/${encodeURIComponent(state.runId)}/${round}">Watch games</a>`
        : ""
    }
  </div>`;
}

function settingsIcon() {
  return `<svg class="icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="12" cy="12" r="3"></circle>
    <path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6"></path>
  </svg>`;
}

function bookIcon() {
  return `<svg class="icon brand-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
    <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v15H6.5A2.5 2.5 0 0 0 4 19.5z"></path>
  </svg>`;
}

function copyIcon() {
  return `<svg class="icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2"></rect>
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
  </svg>`;
}

function crownIcon() {
  return `<svg class="icon crown-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path d="M3 19h18"></path>
    <path d="M5 19V10l3.5 2.5L12 6l3.5 6.5L19 10v9"></path>
  </svg>`;
}

function renderGameWinner(winnerName) {
  if (!winnerName) return "";
  return `<span class="game-winner" title="Winner">
    ${crownIcon()}
    <span class="game-winner-label">Winner</span>
    <span class="game-winner-name">${escapeHtml(winnerName)}</span>
  </span>`;
}

function renderPlayerRoster(players, { turnSeat = null } = {}) {
  const list = players || [];
  if (!list.length) return "";
  const chips = list
    .map((player, index) => {
      const name = typeof player === "string" ? player : player.name;
      const seat = typeof player === "string" ? index : (player.seat ?? index);
      const out = typeof player === "object" && (player.influence || 0) === 0;
      const isTurn = turnSeat != null && seat === turnSeat && !out;
      const classes = ["player-chip", out && "is-out", isTurn && "is-turn"]
        .filter(Boolean)
        .join(" ");
      const status = isTurn ? "Current turn" : out ? "Eliminated" : null;
      return `<span role="listitem" class="${classes}"${status ? ` title="${status}"` : ""}>
        <span class="player-seat">${String(seat + 1).padStart(2, "0")}</span>
        <span class="player-name">${escapeHtml(name)}</span>
        ${isTurn ? `<span class="player-status">Turn</span>` : ""}
      </span>`;
    })
    .join("");
  return `
    <div class="player-roster" role="list" aria-label="Agents">${chips}</div>`;
}

function renderRulesModal() {
  const body = state.rulesText
    ? `<pre class="rules-body">${escapeHtml(state.rulesText)}</pre>`
    : `<div class="empty">Loading rules…</div>`;
  const copied = state.copyFlash === "rules";
  return `
    <div class="modal-backdrop" id="rules-backdrop" role="presentation">
      <div class="modal rules-modal" role="dialog" aria-modal="true" aria-labelledby="rules-title">
        <div class="panel-head">
          <h2 id="rules-title">Game rules</h2>
          <div class="controls">
            <button type="button" class="btn" id="copy-rules" ${state.rulesText ? "" : "disabled"}>
              ${copied ? "Copied" : "Copy"} ${copyIcon()}
            </button>
            <button type="button" class="btn" id="close-rules">Close</button>
          </div>
        </div>
        <div class="rules-scroll">${body}</div>
      </div>
    </div>`;
}

function timestampRunId() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function ensureRunInList(id) {
  if (!id) return;
  if (!state.runs.some((run) => run.id === id)) {
    state.runs = [{ id, rounds: [] }, ...state.runs];
  }
}

function availableAgents() {
  return state.agents.length ? state.agents : DEFAULT_AGENTS;
}

function agentById(id) {
  return availableAgents().find((agent) => agent.id === id) || { id, kind: "example" };
}

function agentKindLabel(agent) {
  if (agent.kind === "local") return "local";
  if (agent.kind === "submission") return "submitted";
  return "base";
}

function agentSeatClass(agent) {
  if (agent.kind === "local") return "local";
  if (agent.kind === "submission") return "submitted";
  return "standard";
}

function isStandardAgent(agent) {
  return agent.kind === "example" || !agent.kind;
}

function renderAgentPickerChip(agent, selected) {
  const count = selected.filter((id) => id === agent.id).length;
  const kindLabel = agentKindLabel(agent);
  const title =
    count > 0
      ? `Add another ${agent.id} (${count} in roster)`
      : `Add ${agent.id}`;
  return `
    <button
      class="agent-pick"
      type="button"
      data-add-agent="${escapeAttr(agent.id)}"
      title="${escapeAttr(title)}"
    >
      <span class="agent-pick-plus" aria-hidden="true">+</span>
      <span class="agent-id">${escapeHtml(agent.id)}</span>
      <span class="agent-kind">${escapeHtml(kindLabel)}</span>
    </button>`;
}

function renderSetupRoster(editable) {
  const selected = state.setup.agents;
  const count = selected.length;
  if (count === 0) {
    return editable
      ? `<div class="agent-roster-empty muted">No agents yet. Add from the catalog below.</div>`
      : `<div class="agent-roster-empty muted">No agents on this tournament. Use New tournament to pick a field.</div>`;
  }
  return `<div class="agent-roster ${editable ? "" : "locked"}">${selected
    .map((id, index) => {
      const agent = agentById(id);
      const kindLabel = agentKindLabel(agent);
      const remove = editable
        ? `<button class="agent-remove" type="button" data-remove-index="${index}" aria-label="Remove ${escapeAttr(id)}">×</button>`
        : "";
      return `
        <div class="agent-seat ${agentSeatClass(agent)}">
          <span class="agent-id">${escapeHtml(id)}</span>
          <span class="agent-kind">${escapeHtml(kindLabel)}</span>
          ${remove}
        </div>`;
    })
    .join("")}</div>`;
}

function renderAgentCatalog() {
  const agents = availableAgents();
  const selected = state.setup.agents;
  const standard = agents.filter(isStandardAgent);
  const local = agents.filter((agent) => agent.kind === "local");
  const submitted = agents.filter((agent) => agent.kind === "submission");
  const standardPicks = standard.map((agent) => renderAgentPickerChip(agent, selected)).join("");
  const localPicks = local.length
    ? local.map((agent) => renderAgentPickerChip(agent, selected)).join("")
    : `<div class="muted agent-catalog-empty">No agents in agents/local yet.</div>`;
  const submittedPicks = submitted.length
    ? submitted.map((agent) => renderAgentPickerChip(agent, selected)).join("")
    : `<div class="muted agent-catalog-empty">No submissions in agents/submissions yet.</div>`;
  return `
    <div class="agent-catalog">
      <div class="agent-catalog-group">
        <div class="agent-catalog-label">
          <span>Base set</span>
          <button class="btn ghost tiny" type="button" id="add-all-standard">Add all</button>
        </div>
        <div class="agent-grid">${standardPicks}</div>
      </div>
      <div class="agent-catalog-group">
        <div class="agent-catalog-label">
          <span>Local</span>
          <button class="btn ghost tiny" type="button" id="add-all-local" ${local.length ? "" : "disabled"}>Add all</button>
        </div>
        <div class="agent-grid">${localPicks}</div>
      </div>
      <div class="agent-catalog-group">
        <div class="agent-catalog-label"><span>Submitted</span></div>
        <div class="agent-grid">${submittedPicks}</div>
      </div>
    </div>`;
}

function renderSeatingBlock() {
  const s = state.setup;
  const count = s.agents.length;
  const prefer = Math.min(6, Math.max(2, Number(s.tableSize) || 5));
  const gamesPerAgent = Math.max(1, Number(s.games) || 1);
  const plan = count >= 2 ? seatingPlan(count, prefer, gamesPerAgent) : null;
  const preferButtons = [4, 5, 6]
    .map(
      (size) =>
        `<button class="btn tiny ${prefer === size ? "primary" : "ghost"}" type="button" data-prefer-size="${size}">${size}</button>`
    )
    .join("");

  let seatingHtml = "";
  if (count < 2) {
    seatingHtml = `<div class="seating-note muted">Need at least 2 agents to plan tables.</div>`;
  } else if (!plan) {
    seatingHtml = `<div class="seating-note muted">Cannot seat ${count} agents into tables of 2–6.</div>`;
  } else {
    const sizeChips = plan.sizes
      .map((size, index) => `<span class="table-chip">Table ${index + 1} · ${size}</span>`)
      .join("");
    const splitLabel = plan.singleTable
      ? `One table of ${plan.sizes[0]}`
      : `Each wave: ${plan.sizes.join(" + ")}`;
    const balanceNote = plan.singleTable
      ? "Everyone shares the same table."
      : "Seating rebalances each wave so agents meet evenly (poker-style).";
    seatingHtml = `
      <div class="seating-plan">
        <div class="seating-sizes">${sizeChips}</div>
        <p class="seating-note">${escapeHtml(splitLabel)}. Every agent plays <strong>${gamesPerAgent}</strong> game${gamesPerAgent === 1 ? "" : "s"} · ${plan.totalTables} table${plan.totalTables === 1 ? "" : "s"} this round. ${escapeHtml(balanceNote)}</p>
      </div>`;
  }

  return `
    <div class="seating-block">
      <div class="agent-setup-head">
        <div class="setup-label">Tables</div>
        <div class="prefer-row">
          <span class="muted">Prefer</span>
          ${preferButtons}
        </div>
      </div>
      ${seatingHtml}
    </div>`;
}

function renderSetup() {
  const s = state.setup;
  const picking = state.setupMode === "tournament";
  const count = s.agents.length;
  const seedValue = s.seed == null || s.seed === "" ? "" : s.seed;
  const title = picking ? "New Tournament" : "Play Games";
  const blurb = picking
    ? "Pick the field for this tournament. Large fields split into equal-play tables of 2–6."
    : "Same agents, next round. Set games, hit Run.";
  const agentSection = `
    <div class="agent-setup">
      <div class="agent-setup-head">
        <div class="setup-label">${picking ? "Agents" : "Field"}</div>
        <div class="agent-count">${count} selected${picking ? `<span class="muted"> · need 2+</span>` : ""}</div>
      </div>
      ${renderSetupRoster(picking)}
      ${picking ? renderAgentCatalog() : ""}
    </div>`;

  return `
    <section class="panel setup-panel">
      <div class="panel-head">
        <h2>${title}</h2>
        <p class="muted">${escapeHtml(blurb)}</p>
      </div>
      <div class="setup-body">
        ${agentSection}
        ${renderSeatingBlock()}
        <div class="setup-grid setup-grid-simple">
          <div class="field">
            <label for="setup-seed">Seed <span class="muted">(blank = random)</span></label>
            <input id="setup-seed" type="number" placeholder="random" value="${seedValue}">
          </div>
          <div class="field">
            <label for="setup-timeout">Timeout (s)</label>
            <input id="setup-timeout" type="number" min="0.1" step="0.1" value="${s.timeout}">
          </div>
          <div class="field">
            <label for="setup-games">Games / agent</label>
            <input id="setup-games" type="number" min="1" value="${s.games}">
          </div>
        </div>
        ${state.setupError ? `<div class="session-error">${escapeHtml(state.setupError)}</div>` : ""}
        <div class="controls">
          <button class="btn primary" type="button" id="start-session" ${sessionIsLive() ? "disabled" : ""}>Run</button>
          <button class="btn" type="button" id="close-setup">Close</button>
        </div>
      </div>
    </section>
  `;
}

function renderScoreboard() {
  const rounds = [...state.runRounds].sort((a, b) => b - a);
  const standingsRows = state.standings?.agents || [];
  const finishedRounds =
    typeof state.standings?.rounds === "number"
      ? state.standings.rounds
      : rounds.filter((r) => state.roundSummaries[r]?.agents?.length).length;

  if (!state.runId) {
    return renderChrome(
      `<section class="panel">
        <div class="panel-head"><h2>Latest Standings</h2></div>
        <div class="empty">No tournament results yet. New tournament from settings to pick agents, then Play Games.</div>
      </section>`,
      "Organizer scoreboard"
    );
  }

  const standingsBody = standingsRows.length
    ? renderBoardTable(standingsRows)
    : `<div class="empty">${
        rounds.length
          ? "Standings appear after a round finishes."
          : "No rounds yet. Play Games to run the next round."
      }</div>`;

  const standingsPanel = `
    <section class="panel" id="standings">
      <div class="panel-head">
        <h2>Latest Standings</h2>
        <div class="muted panel-note">Through ${finishedRounds || 0} finished round${finishedRounds === 1 ? "" : "s"}</div>
      </div>
      ${standingsBody}
    </section>`;

  const roundPanels = rounds
    .map((round) => {
      const summary = state.roundSummaries[round];
      const rows = summary?.agents || [];
      const inProgress =
        state.session?.status === "running" &&
        state.session.run_id === state.runId &&
        state.session.current_round === round &&
        !rows.length;
      const body = inProgress
        ? `<div class="empty">Round ${round} in progress — open Games to watch finished tables while it runs.</div>`
        : rows.length
          ? renderBoardTable(rows)
          : `<div class="empty">No results for round ${round} yet.</div>`;
      return `
        <section class="panel" id="round-${round}">
          <div class="panel-head">
            <h2>Round ${round}</h2>
            <a class="btn" href="#/games/${encodeURIComponent(state.runId)}/${round}">Games</a>
          </div>
          ${body}
        </section>`;
    })
    .join("");

  return renderChrome(
    `<div class="score-stack">${standingsPanel}${roundPanels}</div>`,
    "Organizer scoreboard"
  );
}

function renderBoardTable(rows) {
  return `<div class="table-wrap"><table class="board">
    <thead>
      <tr>
        <th>Rank</th><th>Agent</th><th>Games</th><th>Points</th><th>Avg</th>
        <th>Wins</th><th>Win%</th><th>Illegal</th><th>Errors</th><th>Timeouts</th><th>Avg ms</th>
      </tr>
    </thead>
    <tbody>${rows.map((row, index) => scoreRow(row, index + 1)).join("")}</tbody>
  </table></div>`;
}

function scoreRow(row, rank) {
  const games = row.games || 0;
  return `<tr>
    <td>${rank}</td>
    <td class="agent-name">${escapeHtml(row.name)}</td>
    <td>${games}</td>
    <td>${row.points}</td>
    <td>${avg(row.points, games)}</td>
    <td>${row.wins}</td>
    <td>${pct(row.wins, games)}</td>
    <td>${row.illegal}</td>
    <td>${row.errors}</td>
    <td>${row.timeouts}</td>
    <td>${avgMs(row)}</td>
  </tr>`;
}

function renderGames() {
  const sessionLive =
    state.session?.status === "running" &&
    state.session.run_id === state.runId &&
    state.session.current_round === state.round;
  const copiedAll = state.copyFlash === "all-logs";
  const list = state.games.length
    ? `<div class="games-list">${state.games
        .map((game) => {
          const copied = state.copyFlash === `game:${game.id}`;
          return `
        <div class="game-row">
          <div class="game-id">${escapeHtml(game.id)}</div>
          <div>
            <div>${escapeHtml((game.players || []).join(" · "))}</div>
            <div class="muted" style="margin-top:0.25rem">Winner: ${escapeHtml(game.winner || "—")} · ${game.turns ?? "?"} turns${game.capped ? " (capped)" : ""}</div>
          </div>
          <div class="game-actions">
            <a class="pill" href="#/play/${encodeURIComponent(state.runId)}/${state.round}/${encodeURIComponent(game.id)}">Watch</a>
            <button
              type="button"
              class="btn icon-btn copy-btn"
              data-copy-game="${escapeAttr(game.id)}"
              title="${copied ? "Copied" : "Copy game log"}"
              aria-label="${copied ? "Copied" : `Copy log for ${escapeAttr(game.id)}`}"
            >${copyIcon()}</button>
          </div>
        </div>`;
        })
        .join("")}</div>`
    : `<div class="empty">${sessionLive ? "Waiting for the first finished game…" : "No games in this round yet."}</div>`;

  return renderChrome(
    `<section class="panel">
      <div class="panel-head">
        <div class="panel-head-main">
          <h2>Round ${state.round} games${sessionLive ? " · live" : ""}</h2>
          <button
            type="button"
            class="btn icon-btn copy-btn"
            id="copy-all-logs"
            title="${copiedAll ? "Copied" : "Copy all game logs"}"
            aria-label="${copiedAll ? "Copied" : "Copy all game logs"}"
            ${state.games.length ? "" : "disabled"}
          >${copyIcon()}</button>
          <span class="muted copy-hint">${copiedAll ? "Copied" : "Copy all logs"}</span>
        </div>
        <a class="btn" href="#/run/${encodeURIComponent(state.runId)}/standings">Scoreboard</a>
      </div>
      ${list}
    </section>`,
    "Game browser"
  );
}

function renderPlayback() {
  const pb = state.playback;
  const event = pb.events[pb.index] || null;
  const board = boardAt(pb, pb.index);
  const players = board?.players || (pb.header.players || []).map((name, seat) => ({
    seat,
    name,
    coins: 0,
    influence: 2,
    revealed: [],
    hand: [],
  }));
  const n = players.length || 2;
  const roles = actionRoles(event, board);
  const actionTone = actionToneClass(event);
  const claimsBySeat = claimsThrough(pb.events, pb.index);

  const seats = players
    .map((player, i) => {
      const pos = seatPosition(i, n);
      const out = (player.influence || 0) === 0;
      const isTurn = roles.turn === player.seat;
      const isActor = roles.actor === player.seat;
      const isTarget = roles.target === player.seat;
      const isChallenger = roles.challenger === player.seat;
      const role =
        (isActor && "actor") ||
        (isTarget && "target") ||
        (isChallenger && "challenger") ||
        "";
      const tags = [];
      if (isActor) tags.push(`<span class="seat-badge">Act</span>`);
      if (isTarget) tags.push(`<span class="seat-badge target">Target</span>`);
      if (isChallenger) tags.push(`<span class="seat-badge challenger">Challenge</span>`);
      if (isTurn) tags.push(`<span class="seat-turn" title="This player's turn">Turn</span>`);
      const claims = claimsBySeat.get(player.seat) || [];
      return `
        <div class="seat ${out ? "out" : ""} ${role} ${isTurn ? "turn" : ""}" style="left:${pos.x}%;top:${pos.y}%" data-seat="${player.seat}">
          <div class="seat-card">
            ${tags.length ? `<div class="seat-tags">${tags.join("")}</div>` : ""}
            <div class="seat-name">${escapeHtml(player.name)}</div>
            <div class="seat-meta">
              <span class="coins">${player.coins ?? "?"}¢</span>
              <span>${player.influence ?? "?"} inf</span>
            </div>
            ${renderCards(player, pb.reveal && pb.hasHands)}
            ${renderClaims(claims)}
          </div>
        </div>`;
    })
    .join("");

  return `
    <div class="shell play-shell">
      <header class="play-topbar">
        <a class="back-link" href="#/games/${encodeURIComponent(state.runId)}/${state.round}">← Games</a>
        <div class="play-title">
          <div class="play-title-row">
            <h1>${escapeHtml(pb.header.id || "Game")}</h1>
            ${renderGameWinner(pb.result?.winner)}
          </div>
          ${renderPlayerRoster(players, { turnSeat: roles.turn })}
        </div>
        <div class="play-progress muted">${pb.events.length ? pb.index + 1 : 0} / ${pb.events.length}</div>
      </header>
      <div class="playback">
        <div class="table-stage ${actionTone}">
          <div class="action-hud">${actionHud(event, players, roles)}</div>
          <div class="table-arena">
            ${actionArcs(roles, n)}
            <div class="table-ring" aria-hidden="true"></div>
            ${seats}
          </div>
        </div>
        <aside class="side-rail">
          <div class="transport">
            <div class="transport-row transport-controls">
              <button class="btn" data-act="start" title="Start">⏮</button>
              <button class="btn" data-act="prev" title="Previous">◀</button>
              <button class="btn primary" data-act="toggle">${pb.playing ? "Pause" : "Play"}</button>
              <button class="btn" data-act="next" title="Next">▶</button>
              <button class="btn" data-act="end" title="End">⏭</button>
            </div>
            <div class="transport-row transport-meta">
              <label class="meta-chip" for="speed">
                <span class="meta-label">Speed</span>
                <select id="speed">
                  ${SPEEDS.map(
                    (item) =>
                      `<option value="${item.ms}" ${item.ms === pb.speedMs ? "selected" : ""}>${item.label}/event</option>`
                  ).join("")}
                </select>
              </label>
              ${renderToggle({
                id: "reveal",
                checked: pb.reveal,
                disabled: !pb.hasHands,
                label: pb.hasHands ? "Reveal" : "Reveal (n/a)",
              })}
            </div>
            <div class="transport-row transport-scrub">
              <input class="scrub" id="scrub" type="range" min="0" max="${Math.max(pb.events.length - 1, 0)}" value="${pb.index}" aria-label="Event position">
              <span class="scrub-count">${pb.events.length ? pb.index + 1 : 0}/${pb.events.length}</span>
            </div>
          </div>
          <div class="event-rail">
            <h3>Event log</h3>
            <div class="event-list" id="event-list">
              ${pb.events
                .map((item, index) => {
                  const kind = escapeAttr(item.event || "event");
                  return `
                <div class="event-item ${index === pb.index ? "current" : ""}" data-index="${index}">
                  <span class="turn">T${item.turn ?? "—"}</span>
                  <span class="event-kind kind-${kind}">${escapeHtml(item.event || "event")}</span>
                  <span class="event-msg">${formatEventMessage(item)}</span>
                </div>`;
                })
                .join("")}
            </div>
          </div>
        </aside>
      </div>
    </div>
  `;
}

function renderCards(player, reveal) {
  const revealed = player.revealed || [];
  const hand = player.hand || [];
  const influence = player.influence ?? hand.length;
  const lost = revealed.map(
    (card) =>
      `<div class="card-chip lost ${escapeAttr(card)}" title="Lost: ${CARD_SHORT[card] || card}">${shortLabel(card)}</div>`
  );
  const held = [];
  if (reveal && hand.length) {
    for (const card of hand) {
      held.push(
        `<div class="card-chip held ${escapeAttr(card)}" title="${CARD_SHORT[card] || card}">${shortLabel(card)}</div>`
      );
    }
  } else {
    for (let i = 0; i < influence; i += 1) {
      held.push(`<div class="card-chip held back" title="Hidden">?</div>`);
    }
  }
  if (!lost.length && !held.length) return `<span class="muted">out</span>`;
  return `
    <div class="cards-row">
      ${held.length ? `<div class="card-group held-group" aria-label="Influence">${held.join("")}</div>` : ""}
      ${lost.length ? `<div class="card-group lost-group" aria-label="Lost">${lost.join("")}</div>` : ""}
    </div>`;
}

/** Public character claims up to `index` (action claims + block claims). */
function claimsThrough(events, index) {
  const bySeat = new Map();
  let open = null;
  const closeOpen = (outcome = "passed") => {
    if (!open) return;
    if (open.outcome === "open") open.outcome = outcome;
    open = null;
  };
  const push = (seat, card, kind) => {
    if (seat == null || !card) return;
    closeOpen("passed");
    const claim = { card, kind, outcome: "open" };
    if (!bySeat.has(seat)) bySeat.set(seat, []);
    bySeat.get(seat).push(claim);
    open = claim;
  };
  for (let i = 0; i <= index; i += 1) {
    const event = events[i];
    if (!event) continue;
    if (event.event === "action") {
      push(event.seat, ACTION_CLAIM[event.action], "action");
    } else if (event.event === "block") {
      push(event.seat, event.card, "block");
    } else if (event.event === "challenge" && open) {
      open.outcome = event.success ? "bluff" : "proven";
      open = null;
    } else if (event.event === "prove" && open) {
      closeOpen("proven");
    } else if (
      event.event === "coins" ||
      event.event === "steal" ||
      event.event === "exchange" ||
      event.event === "lose" ||
      event.event === "eliminate" ||
      event.event === "winner" ||
      event.event === "turn_cap"
    ) {
      closeOpen("passed");
    }
  }
  return bySeat;
}

function renderClaims(claims) {
  // Empty claims add height without info — omit until someone claims.
  if (!claims.length) return "";
  // One chip per role (first-seen order); count badge when claimed 2+.
  const order = [];
  const byCard = new Map();
  for (const claim of claims) {
    const existing = byCard.get(claim.card);
    if (!existing) {
      byCard.set(claim.card, {
        card: claim.card,
        count: 1,
        kinds: [claim.kind],
        outcomes: [claim.outcome],
      });
      order.push(claim.card);
    } else {
      existing.count += 1;
      existing.kinds.push(claim.kind);
      existing.outcomes.push(claim.outcome);
    }
  }
  const chips = order
    .map((card) => {
      const group = byCard.get(card);
      const name = CARD_SHORT[card] || card;
      const tip =
        group.count > 1
          ? `${name} ×${group.count}`
          : `${name} (${group.kinds[0] === "block" ? "block" : "action"}${
              group.outcomes[0] && group.outcomes[0] !== "open"
                ? `, ${group.outcomes[0]}`
                : ""
            })`;
      const outcome = group.outcomes.every((o) => o === group.outcomes[0])
        ? group.outcomes[0]
        : "";
      const countBadge =
        group.count >= 2
          ? `<span class="claim-count" aria-label="${group.count} times">${group.count}</span>`
          : "";
      return `<span class="claim-chip ${escapeAttr(card)} ${escapeAttr(outcome)}" title="${escapeAttr(tip)}">${shortLabel(card)}${countBadge}</span>`;
    })
    .join("");
  return `
    <div class="seat-claims" aria-label="Previous claims">
      <span class="claims-label">Claims</span>
      <div class="claims-row">${chips}</div>
    </div>`;
}

function shortLabel(card) {
  const label = CARD_SHORT[card] || card;
  return label.slice(0, 3);
}

function actionRoles(event, board) {
  const turn = board?.current ?? board?.actor ?? null;
  if (!event) {
    return {
      turn,
      actor: board?.actor ?? turn,
      target: null,
      challenger: null,
    };
  }
  // ACT = who owns the turn's action (not event.seat — that can be a loser/blocker).
  const actor =
    board?.actor ??
    event.claimer ??
    (event.action || event.event === "action" || event.event === "coins" || event.event === "exchange"
      ? event.seat
      : null) ??
    turn;
  return {
    turn,
    actor,
    target: event.target ?? board?.pending_action?.target ?? event.pending_action?.target ?? null,
    challenger: event.challenger ?? null,
  };
}

function actionToneClass(event) {
  const key = event?.action || event?.card || event?.event || "";
  if (["tax", "duke"].includes(key)) return "tone-duke";
  if (["assassinate", "assassin"].includes(key)) return "tone-assassin";
  if (["steal", "captain"].includes(key)) return "tone-captain";
  if (["exchange", "ambassador"].includes(key)) return "tone-ambassador";
  if (["contessa", "block"].includes(key)) return "tone-contessa";
  if (key === "coup") return "tone-coup";
  return "tone-neutral";
}

function actionHud(event, players, roles) {
  const turnName = players.find((p) => p.seat === roles.turn)?.name;
  if (!event) {
    return `<div class="eyebrow">Ready</div><div class="headline">Press play</div>${
      turnName ? `<div class="cast-row"><span class="cast turn">${escapeHtml(turnName)}'s turn</span></div>` : ""
    }`;
  }
  const actorName = players.find((p) => p.seat === roles.actor)?.name;
  const targetName = players.find((p) => p.seat === roles.target)?.name;
  const challengerName = players.find((p) => p.seat === roles.challenger)?.name;
  const action = event.action ? ACTION_LABEL[event.action] || event.action : null;
  const card = event.card ? CARD_SHORT[event.card] || event.card : null;
  const kind = event.event || "event";

  let headline =
    action ||
    (kind === "challenge" ? "Challenge" : null) ||
    (kind === "block" ? "Block" : null) ||
    (kind === "lose_influence" || kind === "lose" ? "Lose influence" : null) ||
    (kind === "start" ? "Game start" : null) ||
    kind;

  const chips = [];
  if (card) chips.push(`<span class="hud-chip card-${escapeAttr(event.card || "")}">${escapeHtml(card)}</span>`);
  if (event.success === true) chips.push(`<span class="hud-chip ok">Succeeds</span>`);
  if (event.success === false) chips.push(`<span class="hud-chip fail">Fails</span>`);
  if (event.amount != null) chips.push(`<span class="hud-chip">${escapeHtml(String(event.amount))}¢</span>`);

  const cast = [];
  if (turnName) cast.push(`<span class="cast turn">${escapeHtml(turnName)}'s turn</span>`);
  if (actorName && actorName !== turnName) cast.push(`<span class="cast actor">${escapeHtml(actorName)}</span>`);
  else if (actorName && !turnName) cast.push(`<span class="cast actor">${escapeHtml(actorName)}</span>`);
  if (targetName) cast.push(`<span class="cast arrow">→</span><span class="cast target">${escapeHtml(targetName)}</span>`);
  if (challengerName) cast.push(`<span class="cast challenger">⚔ ${escapeHtml(challengerName)}</span>`);

  return `
    <div class="eyebrow">${escapeHtml(kind)} · turn ${event.turn ?? "—"}</div>
    <div class="headline-row">
      <div class="headline">${escapeHtml(headline)}</div>
      ${chips.length ? `<div class="hud-chips">${chips.join("")}</div>` : ""}
    </div>
    ${cast.length ? `<div class="cast-row">${cast.join("")}</div>` : ""}
    <div class="sub">${escapeHtml(event.message || "")}</div>
  `;
}

function actionArcs(roles, count) {
  const links = [];
  if (roles.actor != null && roles.target != null && roles.actor !== roles.target) {
    links.push(["actor-target", roles.actor, roles.target]);
  }
  if (roles.challenger != null && roles.actor != null && roles.challenger !== roles.actor) {
    links.push(["challenger-actor", roles.challenger, roles.actor]);
  }
  if (!links.length) return "";
  const lines = links
    .map(([kind, from, to]) => {
      // Pull endpoints inward so strokes stop at seat edges, not through card text.
      const a = seatEdgePoint(from, count, to);
      const b = seatEdgePoint(to, count, from);
      return `<line class="arc ${kind}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />`;
    })
    .join("");
  return `
    <svg class="action-arcs" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <marker id="arc-arrow" markerWidth="4" markerHeight="4" refX="3.2" refY="2" orient="auto">
          <path d="M0,0 L4,2 L0,4 Z" fill="currentColor"></path>
        </marker>
      </defs>
      ${lines}
    </svg>`;
}

function boardAt(pb, index) {
  for (let i = index; i >= 0; i -= 1) {
    if (pb.events[i]?.state) return pb.events[i].state;
  }
  return null;
}

function seatPosition(index, count) {
  const angle = -Math.PI / 2 + (index / count) * Math.PI * 2;
  // % of `.table-arena`. Keep the ellipse inset so cards clear the rim.
  const rx = count <= 3 ? 28 : count === 4 ? 29 : count === 5 ? 31 : 33;
  const ry = count <= 3 ? 26 : count === 4 ? 27 : count === 5 ? 29 : 31;
  const x = 50 + Math.cos(angle) * rx;
  const y = 50 + Math.sin(angle) * ry;
  return { x, y };
}

/** Point on the path from `index` toward `toward`, stopped short of the seat card. */
function seatEdgePoint(index, count, toward) {
  const from = seatPosition(index, count);
  const to = seatPosition(toward, count);
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const dist = Math.hypot(dx, dy) || 1;
  // Compact seat cards — stop the stroke just outside the face.
  const inset = Math.min(9, dist * 0.28);
  return {
    x: +(from.x + (dx / dist) * inset).toFixed(2),
    y: +(from.y + (dy / dist) * inset).toFixed(2),
  };
}

function bindChrome() {
  const runSelect = document.getElementById("run-select");
  if (runSelect) {
    runSelect.addEventListener("change", () => {
      state.runId = runSelect.value || null;
      state.round = null;
      state.setupMenuOpen = false;
      location.hash = state.runId ? `#/run/${encodeURIComponent(state.runId)}/standings` : "#/";
    });
  }
  document.getElementById("setup-menu-btn")?.addEventListener("click", (event) => {
    event.stopPropagation();
    state.setupMenuOpen = !state.setupMenuOpen;
    render();
  });
  document.getElementById("new-tournament")?.addEventListener("click", () => {
    startNewTournament();
  });
  if (state.setupMenuOpen) {
    const closer = (event) => {
      const menu = document.querySelector(".menu");
      if (menu && menu.contains(event.target)) return;
      state.setupMenuOpen = false;
      document.removeEventListener("click", closer);
      render();
    };
    setTimeout(() => document.addEventListener("click", closer), 0);
  }
  document.getElementById("open-rules")?.addEventListener("click", () => openRules());
  document.getElementById("close-rules")?.addEventListener("click", () => closeRules());
  document.getElementById("rules-backdrop")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeRules();
  });
  document.getElementById("copy-rules")?.addEventListener("click", () => {
    if (!state.rulesText) return;
    copyText(state.rulesText, "rules");
  });
  document.getElementById("copy-all-logs")?.addEventListener("click", () => copyAllGameLogs());
  document.querySelectorAll("[data-copy-game]").forEach((btn) => {
    btn.addEventListener("click", () => copyGameLog(btn.getAttribute("data-copy-game")));
  });
  bindRulesEscape();
  bindSessionControls();
  bindSetup();
}

let rulesKeyHandler = null;

function bindRulesEscape() {
  if (rulesKeyHandler) {
    document.removeEventListener("keydown", rulesKeyHandler);
    rulesKeyHandler = null;
  }
  if (!state.rulesOpen) return;
  rulesKeyHandler = (event) => {
    if (event.key === "Escape") closeRules();
  };
  document.addEventListener("keydown", rulesKeyHandler);
}

async function openRules() {
  state.rulesOpen = true;
  render();
  if (state.rulesText == null) {
    try {
      const data = await fetchJson("/api/rules");
      state.rulesText = data.text || "";
    } catch (err) {
      state.rulesText = `Failed to load rules: ${err.message}`;
    }
    if (state.rulesOpen) render();
  }
}

function closeRules() {
  state.rulesOpen = false;
  if (state.copyFlash === "rules") state.copyFlash = null;
  if (rulesKeyHandler) {
    document.removeEventListener("keydown", rulesKeyHandler);
    rulesKeyHandler = null;
  }
  render();
}

async function fetchGameLogText(gameId) {
  const data = await fetchJson(
    `/api/runs/${encodeURIComponent(state.runId)}/rounds/${state.round}/games/${encodeURIComponent(gameId)}`
  );
  return (data.lines || []).map((line) => JSON.stringify(line)).join("\n");
}

async function copyGameLog(gameId) {
  if (!gameId) return;
  try {
    const text = await fetchGameLogText(gameId);
    await copyText(text, `game:${gameId}`);
  } catch (err) {
    console.error(err);
  }
}

async function copyAllGameLogs() {
  if (!state.games.length) return;
  try {
    const parts = await Promise.all(
      state.games.map(async (game) => {
        const text = await fetchGameLogText(game.id);
        return `### ${game.id}\n${text}`;
      })
    );
    await copyText(parts.join("\n\n"), "all-logs");
  } catch (err) {
    console.error(err);
  }
}

async function copyText(text, flashKey) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  flashCopy(flashKey);
}

let copyFlashTimer = null;
function flashCopy(key) {
  state.copyFlash = key;
  render();
  if (copyFlashTimer) clearTimeout(copyFlashTimer);
  copyFlashTimer = setTimeout(() => {
    if (state.copyFlash === key) {
      state.copyFlash = null;
      render();
    }
  }, 1400);
}

function hydrateSetupAgentsFromRun() {
  if (state.setup.agents.length >= 2) return;
  const fromSession =
    state.session?.run_id === state.runId && Array.isArray(state.session?.agents)
      ? state.session.agents.filter((id) => typeof id === "string" && id)
      : [];
  if (fromSession.length >= 2) {
    state.setup.agents = [...fromSession];
    return;
  }
  const fromStandings = (state.standings?.agents || [])
    .map((row) => row?.name)
    .filter((id) => typeof id === "string" && id);
  if (fromStandings.length >= 2) {
    state.setup.agents = [...fromStandings];
  }
}

function openTournamentSetup() {
  state.setupMode = "tournament";
  state.setupOpen = true;
  state.setupMenuOpen = false;
  state.setupError = null;
}

async function openRoundSetup() {
  await loadSession({ quiet: true });
  syncLivePolling();
  hydrateSetupAgentsFromRun();
  if (state.setup.agents.length < 2) {
    openTournamentSetup();
    state.setupError = "Pick agents for a new tournament first.";
    return;
  }
  state.setupMode = "round";
  state.setupOpen = true;
  state.setupMenuOpen = false;
  state.setupError = null;
}

function startNewTournament() {
  const id = timestampRunId();
  ensureRunInList(id);
  state.runId = id;
  state.round = null;
  state.standings = null;
  state.roundSummaries = {};
  state.runRounds = [];
  state.setup.agents = [];
  openTournamentSetup();
  const hash = `#/run/${encodeURIComponent(id)}/standings`;
  if (location.hash === hash) {
    loadScoreboard().then(() => render());
  } else {
    location.hash = hash;
  }
}

function bindSessionControls() {
  document.getElementById("toggle-setup")?.addEventListener("click", () => {
    if (state.setupOpen && state.setupMode === "round") {
      state.setupOpen = false;
      state.setupMenuOpen = false;
      state.setupError = null;
      render();
      return;
    }
    openRoundSetup().then(() => render());
  });
}

function nextRoundNumber() {
  const fromRun = currentRun()?.rounds || [];
  const fromBoard = state.runRounds || [];
  // Only count the live session when it belongs to this tournament run.
  // Otherwise a finished prior tournament (e.g. round 5) leaks into the next run.
  const fromSession =
    state.session?.run_id && state.session.run_id === state.runId
      ? (state.session.rounds || [])
          .map((row) => row?.number)
          .filter((n) => Number.isFinite(n))
      : [];
  const existing = [...fromRun, ...fromBoard, ...fromSession];
  if (!existing.length) return 1;
  return Math.max(...existing) + 1;
}

function readSetupFieldsFromDom() {
  const seedEl = document.getElementById("setup-seed");
  const timeoutEl = document.getElementById("setup-timeout");
  const gamesEl = document.getElementById("setup-games");
  if (seedEl) {
    const raw = String(seedEl.value ?? "").trim();
    state.setup.seed = raw === "" ? null : Number(raw);
  }
  if (timeoutEl) state.setup.timeout = Number(timeoutEl.value) || 1;
  if (gamesEl) state.setup.games = Math.max(1, Number(gamesEl.value) || 1);
}

function bindSetup() {
  if (!state.setupOpen) return;
  const picking = state.setupMode === "tournament";
  document.getElementById("close-setup")?.addEventListener("click", () => {
    state.setupOpen = false;
    render();
  });
  document.getElementById("setup-seed")?.addEventListener("change", (event) => {
    const raw = String(event.target.value ?? "").trim();
    state.setup.seed = raw === "" ? null : Number(raw);
  });
  document.getElementById("setup-timeout")?.addEventListener("change", (event) => {
    state.setup.timeout = Number(event.target.value) || 1;
  });
  document.getElementById("setup-games")?.addEventListener("change", (event) => {
    state.setup.games = Math.max(1, Number(event.target.value) || 1);
    render();
  });
  document.querySelectorAll("[data-prefer-size]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.setup.tableSize = Number(btn.getAttribute("data-prefer-size")) || 5;
      state.setupError = null;
      render();
    });
  });
  if (picking) {
    document.querySelectorAll("[data-add-agent]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-add-agent");
        if (!id) return;
        state.setup.agents.push(id);
        state.setupError = null;
        render();
      });
    });
    document.querySelectorAll("[data-remove-index]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const index = Number(btn.getAttribute("data-remove-index"));
        if (!Number.isInteger(index) || index < 0) return;
        state.setup.agents = state.setup.agents.filter((_, i) => i !== index);
        state.setupError = null;
        render();
      });
    });
    document.getElementById("add-all-standard")?.addEventListener("click", () => {
      const standardIds = availableAgents().filter(isStandardAgent).map((agent) => agent.id);
      state.setup.agents.push(...standardIds);
      state.setupError = null;
      render();
    });
    document.getElementById("add-all-local")?.addEventListener("click", () => {
      const localIds = availableAgents()
        .filter((agent) => agent.kind === "local")
        .map((agent) => agent.id);
      if (!localIds.length) return;
      state.setup.agents.push(...localIds);
      state.setupError = null;
      render();
    });
  }
  document.getElementById("start-session")?.addEventListener("click", () => startSession());
}

async function startSession() {
  state.setupError = null;
  readSetupFieldsFromDom();
  if (state.setup.agents.length < 2) {
    state.setupError = "Pick at least 2 agents.";
    render();
    return;
  }
  const prefer = Math.min(6, Math.max(2, Number(state.setup.tableSize) || 5));
  if (!chooseSizes(state.setup.agents.length, prefer)) {
    state.setupError = "Cannot seat that many agents into tables of 2–6.";
    render();
    return;
  }
  // New tournament agent-pick always starts at round 1; Play Games continues the run.
  const roundNumber = state.setupMode === "tournament" ? 1 : nextRoundNumber();
  const seed =
    state.setup.seed == null || state.setup.seed === ""
      ? randomSeed()
      : Number(state.setup.seed);
  if (!Number.isFinite(seed)) {
    state.setupError = "Seed must be a number, or leave blank for random.";
    render();
    return;
  }
  const payload = {
    run_id: state.runId || undefined,
    agents: [...state.setup.agents],
    rounds: [{ number: roundNumber, games_per_agent: Math.max(1, Number(state.setup.games) || 1) }],
    seed,
    timeout: Number(state.setup.timeout) || 1,
    table_size: prefer,
    sandbox: false,
    force: true,
  };
  try {
    state.session = await fetchJson("/api/session/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    // Start returns a "running" snapshot; fast rounds may already be done.
    await loadSession({ quiet: true });
    state.setupOpen = false;
    state.setupMenuOpen = false;
    state.runId = state.session?.run_id || state.runId;
    state.round = state.session?.current_round || roundNumber;
    ensureRunInList(state.runId);
    const gamesHash = `#/games/${encodeURIComponent(state.runId)}/${state.round}`;
    if (location.hash === gamesHash) {
      state.view = "games";
      await loadRuns({ quiet: true });
      await loadGames({ quiet: true });
      render();
    } else {
      location.hash = gamesHash;
    }
    syncLivePolling();
    if (!sessionIsLive()) {
      await loadRuns({ quiet: true });
      await loadGames({ quiet: true });
      render();
    }
  } catch (err) {
    await loadSession({ quiet: true });
    syncLivePolling();
    state.setupError = err.message;
    render();
  }
}

function bindPlayback() {
  const pb = state.playback;
  bindSessionControls();
  document.querySelectorAll("[data-act]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const act = btn.getAttribute("data-act");
      if (act === "toggle") {
        pb.playing = !pb.playing;
        if (pb.playing) startPlaybackTimer();
        else stopPlaybackTimer();
        render();
        return;
      }
      pb.playing = false;
      stopPlaybackTimer();
      if (act === "start") pb.index = 0;
      if (act === "prev") pb.index = Math.max(0, pb.index - 1);
      if (act === "next") pb.index = Math.min(pb.events.length - 1, pb.index + 1);
      if (act === "end") pb.index = Math.max(0, pb.events.length - 1);
      render();
    });
  });
  const speed = document.getElementById("speed");
  if (speed) {
    speed.addEventListener("change", () => {
      pb.speedMs = Number(speed.value);
      if (pb.playing) {
        stopPlaybackTimer();
        startPlaybackTimer();
      }
    });
  }
  const reveal = document.getElementById("reveal");
  if (reveal) {
    reveal.addEventListener("change", () => {
      pb.reveal = reveal.checked;
      render();
    });
  }
  const scrub = document.getElementById("scrub");
  if (scrub) {
    scrub.addEventListener("input", () => {
      pb.playing = false;
      stopPlaybackTimer();
      pb.index = Number(scrub.value);
      render();
    });
  }
  document.querySelectorAll(".event-item[data-index]").forEach((item) => {
    item.addEventListener("click", () => {
      pb.playing = false;
      stopPlaybackTimer();
      pb.index = Number(item.getAttribute("data-index"));
      render();
    });
  });
  const list = document.getElementById("event-list");
  const current = list?.querySelector(".event-item.current");
  if (current) current.scrollIntoView({ block: "nearest" });
}

function startPlaybackTimer() {
  stopPlaybackTimer();
  const pb = state.playback;
  if (!pb) return;
  playTimer = setInterval(() => {
    if (!state.playback?.playing) return;
    if (state.playback.index >= state.playback.events.length - 1) {
      state.playback.playing = false;
      stopPlaybackTimer();
      render();
      return;
    }
    state.playback.index += 1;
    render();
  }, pb.speedMs);
}

function stopPlaybackTimer() {
  if (playTimer) {
    clearInterval(playTimer);
    playTimer = null;
  }
}

function avg(points, games) {
  if (!games) return "0.00";
  return (points / games).toFixed(2);
}

function pct(wins, games) {
  if (!games) return "0%";
  return `${Math.round((100 * wins) / games)}%`;
}

function avgMs(row) {
  const decisions = row.decisions || 0;
  if (!decisions) return "0";
  return ((1000 * row.decision_time) / decisions).toFixed(2);
}

function formatEventMessage(event) {
  let html = escapeHtml(event?.message || "");
  const roles = [
    ["Ambassador", "ambassador"],
    ["Assassin", "assassin"],
    ["Contessa", "contessa"],
    ["Captain", "captain"],
    ["Duke", "duke"],
  ];
  for (const [label, slug] of roles) {
    html = html.replaceAll(label, `<span class="msg-role role-${slug}">${label}</span>`);
  }
  html = html.replace(
    /\b(gains|steals|paying|pays)\s+(\d+)\b/g,
    (_m, verb, amount) => `${verb} <span class="msg-coins">${amount}¢</span>`
  );
  html = html.replace(
    /\b(\d+)\s+coins?\b/g,
    (_m, amount) => `<span class="msg-coins">${amount}¢</span>`
  );
  return html;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

init();
