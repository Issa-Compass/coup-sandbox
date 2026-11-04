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

const ACTION_BLOCK = {
  foreign_aid: ["duke"],
  assassinate: ["contessa"],
  steal: ["captain", "ambassador"],
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
  { id: "guard", name: "guard_bot", kind: "example" },
  { id: "turtle", name: "turtle_bot", kind: "example" },
  { id: "greedy", name: "greedy_bot", kind: "example" },
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
  runAgents: [], // catalog tokens from results/<run>/roster.json
  games: [],
  playback: null,
  agents: [],
  session: null,
  setupOpen: false,
  setupMode: "round", // "tournament" | "round" | "manual"
  setupMenuOpen: false,
  setup: defaultSetup(),
  setupError: null,
  setupStarting: false, // Run/Play request in flight — blocks remount races
  sessionErrorHidden: false, // user dismissed a failed-session banner
  rulesOpen: false,
  rulesText: null,
  copyFlash: null,
  submitOpen: false,
  manual: null, // live human-vs-agents snapshot from /api/manual
  manualBusy: false,
  manualError: null,
  manualSpeedMs: 1000,
  manualPumpTimer: null,
  manualExchangeKeep: [], // selected cards during exchange prompt
  followPlay: false, // after Run, open the table and play games through
  hub: null, // { configured, master_url } | null while loading
  hubPing: null, // { status: checking|ready|offline, error?, version? } | null
  submit: defaultSubmit(),
};

function defaultSubmit() {
  return {
    agent: null,
    name: "",
    fullName: "",
    busy: null, // "test" | "submit" | null
    report: null,
    error: null,
    success: null,
    /** Hub names uploaded this browser session (lowercase). */
    uploadedNames: [],
    /** Last successful upload — used to lock the Submit button. */
    lastUpload: null, // { agent, name } | null
  };
}

/** Hub / arena Coup AI names already on the master (lowercase). */
function hubNameSet() {
  const names = new Set();
  for (const agent of availableAgents()) {
    if (agent.kind !== "submission") continue;
    const raw = String(agent.name || "").trim();
    if (raw) names.add(raw.toLowerCase());
  }
  for (const name of state.submit.uploadedNames || []) {
    if (name) names.add(String(name).toLowerCase());
  }
  return names;
}

/**
 * Why Submit should stay off after a successful upload of this same id.
 * Intentional hub replaces of an older entry are still allowed; only block
 * double-submit of a name we just uploaded this session.
 * @returns {string|null}
 */
function duplicateSubmitReason(name, agentId) {
  const trimmed = String(name || "").trim();
  if (!trimmed) return null;
  const key = trimmed.toLowerCase();
  const uploaded = state.submit.uploadedNames || [];
  if (!uploaded.includes(key)) return null;
  const last = state.submit.lastUpload;
  if (last && String(last.name || "").toLowerCase() === key) {
    if (!agentId || last.agent === agentId) {
      return `"${trimmed}" was just submitted — pick a new Coup AI name (or another agent) to upload again`;
    }
    // Same hub id, different local file — still a duplicate id this session.
    return `"${trimmed}" was just submitted under that Coup AI name — choose a new name`;
  }
  return `"${trimmed}" was already submitted this session — choose a new Coup AI name`;
}

const FULL_NAME_RE = /^[A-Za-z][A-Za-z'-]*(?: [A-Za-z][A-Za-z'-]*)+$/;

function normalizeFullName(value) {
  return String(value || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

/** @returns {string|null} error message, or null when ok */
function fullNameError(value) {
  const text = normalizeFullName(value);
  if (!text) return "Enter your first and last name (e.g. Ada Lovelace)";
  if (text.length < 3 || text.length > 128) {
    return "Use 3–128 characters for your full name";
  }
  const parts = text.split(" ");
  if (parts.length < 2) {
    if (!/^[A-Za-z][A-Za-z'-]*$/.test(parts[0])) {
      return "Letters, spaces, apostrophes, and hyphens only";
    }
    return "Add your last name too (e.g. Ada Lovelace)";
  }
  if (!FULL_NAME_RE.test(text)) {
    return "Letters, spaces, apostrophes, and hyphens only";
  }
  return null;
}

const RESERVED_COUP_AI_NAMES = new Set([
  "template",
  "random",
  "honest",
  "bluffer",
  "challenger",
  "guard",
  "turtle",
  "greedy",
  "master",
  "sandbox",
  "admin",
  "api",
  "health",
]);

/** @returns {string|null} error message, or null when ok */
function coupAiNameError(value) {
  const text = String(value || "").trim();
  if (!text) return "Pick a name for your Coup AI";
  if (text.length < 1 || text.length > 64) {
    return "Coup AI name must be 1–64 characters";
  }
  if (!/^[A-Za-z0-9_-]+$/.test(text)) {
    return "Letters, numbers, underscore, and hyphen only — no spaces";
  }
  if (/^[-_]|[-_]$/.test(text)) {
    return "Don't start or end the Coup AI name with _ or -";
  }
  if (RESERVED_COUP_AI_NAMES.has(text.toLowerCase())) {
    return `"${text}" is reserved — pick another Coup AI name`;
  }
  return null;
}

let playTimer = null;
let followTimer = null;
let liveTimer = null;
let liveInFlight = false;

const app = document.getElementById("app");

async function init() {
  window.addEventListener("hashchange", () => route());
  // Survive innerHTML remounts (loadAgents / boot / live poll) so Run clicks are not dropped.
  bindAppDelegates();
  const hasDeepLink = Boolean(location.hash.replace(/^#\/?/, "").trim());

  // Cold start with no hash: open an empty tournament draft immediately.
  // Old runs still load into the Run menu in the background.
  if (!hasDeepLink) startNewTournament();

  const boot = Promise.all([loadRuns(), loadAgents(), loadSession(), loadHub()]);
  if (hasDeepLink) {
    await boot;
    syncLivePolling();
    await route();
    return;
  }

  boot.then(() => {
    ensureRunInList(state.runId);
    syncLivePolling();
    // Avoid wiping the setup DOM mid-click / mid-start.
    if (!state.setupStarting) render();
  });
}

/** One-shot delegated handlers on #app — remount-safe. */
function bindAppDelegates() {
  if (app.dataset.delegatesBound === "1") return;
  app.dataset.delegatesBound = "1";
  app.addEventListener("click", (event) => {
    const start = event.target.closest("#start-session");
    if (start) {
      event.preventDefault();
      if (start.disabled || state.setupStarting) return;
      if (state.setupMode === "manual") startManualGame();
      else startSession();
      return;
    }
    const dismiss = event.target.closest("#dismiss-session-error");
    if (dismiss) {
      event.preventDefault();
      state.sessionErrorHidden = true;
      render();
      return;
    }
    const stop = event.target.closest("#stop-session");
    if (stop) {
      event.preventDefault();
      stopSession();
    }
  });
}

async function loadHub() {
  try {
    state.hub = await fetchJson("/api/hub");
  } catch {
    state.hub = { configured: false, master_url: null };
  }
}

async function pingHub() {
  state.hubPing = { status: "checking", error: null, version: null };
  try {
    const data = await fetchJson("/api/hub/ping");
    if (data.configured === false) {
      state.hubPing = {
        status: "unset",
        error: "Add a coup-master .env to submit (see .env.example)",
        version: null,
      };
      if (state.hub) state.hub.configured = false;
      return;
    }
    if (state.hub) state.hub.configured = true;
    state.hubPing = {
      status: data.status === "ready" ? "ready" : "offline",
      error: data.error || null,
      version: data.version || null,
    };
  } catch (err) {
    state.hubPing = {
      status: "offline",
      error: err?.message || String(err),
      version: null,
    };
  }
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
    const prevStatus = state.session?.status;
    const prevGame = state.session?.current_game;
    const prevMessage = state.session?.message;
    const prevGamesLen = state.games.length;
    await loadSession({ quiet: true });
    const live = sessionIsLive();
    if (state.session?.status === "running") state.sessionErrorHidden = false;
    if (state.session?.status === "error" && prevStatus === "running") {
      state.sessionErrorHidden = false;
    }
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
        if (armFollowPlay()) {
          syncLivePolling();
          return;
        }
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
  if (parts[0] === "manual") {
    return { view: "manual", runId: state.runId, round: state.round };
  }
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
  stopFollowTimer();
  stopManualPump();
  const next = parseHash();
  // Leaving the table (scoreboard, games list, manual) stops the auto play-through.
  // Moving from the waiting games list onto a game does not.
  if (state.view === "play" && next.view !== "play") state.followPlay = false;
  state.view = next.view;
  if (next.runId) state.runId = next.runId;
  if (!state.runId && state.runs.length) state.runId = state.runs[0].id;
  if (next.view === "scoreboard") {
    state.round = Number.isFinite(next.round) ? next.round : null;
    await loadScoreboard();
  } else if (next.view === "games") {
    state.round = next.round;
    await loadGames();
    // A fast round is already on disk by the time this list opens. Go to the
    // table instead of leaving the finished games sitting under the scoreboard.
    if (armFollowPlay()) return;
  } else if (next.view === "play") {
    state.round = next.round;
    await loadPlayback(next.gameId);
  } else if (next.view === "manual") {
    await loadManual({ quiet: true });
  }
  render();
}

async function loadRuns({ quiet = false } = {}) {
  try {
    const data = await fetchJson("/api/runs");
    state.runs = data.runs || [];
    // Keep a client-only draft id in the menu after history replaces the list.
    ensureRunInList(state.runId);
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
    // Local that reuses a base alias arrives as local:<name> — distinct from example id.
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
    state.runAgents = [];
    return;
  }
  // Fresh empty draft is not on disk yet — skip 404 round-trips.
  if (tournamentDraftPending()) {
    state.standings = null;
    state.roundSummaries = {};
    state.runRounds = [];
    state.runAgents = [];
    return;
  }
  try {
    let rounds = [];
    let roster = [];
    try {
      const meta = await fetchJson(`/api/runs/${encodeURIComponent(state.runId)}`);
      rounds = meta.rounds || [];
      roster = Array.isArray(meta.agents) ? meta.agents.filter((id) => typeof id === "string" && id) : [];
    } catch {
      rounds = [];
      roster = [];
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
    state.runAgents = roster;
    const run = currentRun();
    if (run) run.agents = [...roster];

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
    state.runAgents = [];
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
  const previousSpeed = state.playback?.speedMs;
  const followThrough = Boolean(state.followPlay);
  // The log endpoint returns the file as stored. A listed game can be a header
  // with no events, or a single frame. Stepping needs a later event; shorter
  // logs still have to hand follow-play to the next game.
  const canStep = events.length > 1;
  state.playback = {
    header,
    result,
    events,
    index: 0,
    playing: followThrough && canStep,
    speedMs: previousSpeed || (state.followPlay ? 500 : 1000),
    reveal: false,
    hasHands,
  };
  if (followThrough && !canStep) scheduleFollowNext();
}

function playHash(gameId) {
  return `#/play/${encodeURIComponent(state.runId)}/${state.round}/${encodeURIComponent(gameId)}`;
}

/** Jump onto the first table and play it. Stay put if this round is already on screen. */
function armFollowPlay() {
  if (!state.followPlay) return false;
  if (!state.runId || !state.round || !state.games.length) return false;
  const watching = state.playback?.header?.id;
  if (state.view === "play" && watching && state.games.some((game) => game.id === watching)) {
    return false;
  }
  const hash = playHash(state.games[0].id);
  if (location.hash === hash) return false;
  location.hash = hash;
  return true;
}

function stopFollowTimer() {
  if (followTimer == null) return;
  clearTimeout(followTimer);
  followTimer = null;
}

function scheduleFollowNext() {
  stopFollowTimer();
  if (!state.followPlay || state.view !== "play") return;
  followTimer = setTimeout(() => {
    followTimer = null;
    followNextGame();
  }, 700);
}

async function followNextGame() {
  if (!state.followPlay || state.view !== "play") return;
  const runId = state.runId;
  const round = state.round;
  const gameId = state.playback?.header?.id ?? null;
  if (!runId || round == null || !gameId) return;
  await loadGames({ quiet: true });
  const samePlayback =
    state.followPlay &&
    state.view === "play" &&
    state.runId === runId &&
    state.round === round &&
    (state.playback?.header?.id ?? null) === gameId;
  if (!samePlayback) return;
  const ids = state.games.map((game) => game.id);
  const at = ids.indexOf(gameId);
  const next = at >= 0 ? ids[at + 1] : null;
  if (next) {
    const hash = playHash(next);
    if (location.hash !== hash) location.hash = hash;
    return;
  }
  if (sessionIsLive() && state.session?.run_id === state.runId) {
    followTimer = setTimeout(() => {
      followTimer = null;
      followNextGame();
    }, 400);
  }
}

async function fetchJson(url, options) {
  const res = await fetch(url, { cache: "no-store", ...options });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const issues = Array.isArray(body.issues) && body.issues.length
      ? `: ${body.issues.join("; ")}`
      : "";
    throw new Error(`${body.error || `${res.status} ${url}`}${issues}`);
  }
  return res.json();
}

function render() {
  // Flush open form fields before wiping the DOM so remounts keep drafts.
  readSetupFieldsFromDom();
  const submitName = document.getElementById("submit-name");
  if (submitName) state.submit.name = submitName.value;
  const submitFullName = document.getElementById("submit-full-name");
  if (submitFullName) state.submit.fullName = submitFullName.value;
  if (state.view === "play" && state.playback) {
    app.innerHTML = renderPlayback();
    bindPlayback();
    return;
  }
  if (state.view === "manual") {
    app.innerHTML = renderManualPlay();
    bindManualPlay();
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
            }>${escapeHtml(displayId(run.id))}</option>`
          )
          .join("")
    : state.runId
      ? `<option value="${escapeAttr(state.runId)}" selected>${escapeHtml(displayId(state.runId))}</option>`
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
              <button class="btn primary ${state.setupOpen && state.setupMode === "tournament" ? "active" : ""}" id="toggle-setup" type="button">New Tournament</button>
              <div class="menu ${state.setupMenuOpen ? "open" : ""}">
                <button class="btn icon-btn ${
                  state.submitOpen ||
                  (state.setupOpen && (state.setupMode === "round" || state.setupMode === "manual")) ||
                  (state.view === "manual" && state.manual?.status === "waiting")
                    ? "active"
                    : ""
                }" id="setup-menu-btn" type="button" aria-label="More play options" aria-expanded="${state.setupMenuOpen ? "true" : "false"}" title="Settings">
                  ${settingsIcon()}
                </button>
                <div class="menu-panel" role="menu">
                  <button class="menu-item" type="button" id="another-round" role="menuitem">Another round</button>
                  <button class="menu-item ${state.setupOpen && state.setupMode === "manual" ? "active" : ""}" type="button" id="play-manually" role="menuitem">Play manually</button>
                  <button class="menu-item ${state.submitOpen ? "active" : ""}" type="button" id="submit-agent" role="menuitem">Submit agent</button>
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
      ${state.submitOpen ? renderSubmitModal() : ""}
    </div>
  `;
}

function renderSessionBanner() {
  const session = state.session;
  if (!session) return "";
  if (session.status === "error" && !state.sessionErrorHidden) {
    const detail = session.error || session.message || "Tournament failed";
    return `<div class="session-live-banner is-error">
      <div class="session-live-text">
        <strong>Tournament failed</strong>
        <span class="muted">${escapeHtml(detail)}</span>
      </div>
      <button class="btn" type="button" id="dismiss-session-error">Dismiss</button>
    </div>`;
  }
  if (session.status !== "running") return "";
  if (session.run_id && state.runId && session.run_id !== state.runId) {
    return `<div class="session-live-banner">
      <div class="session-live-dot" aria-hidden="true"></div>
      <div class="session-live-text">
        <strong>Live on another run</strong>
        <span class="muted">${escapeHtml(session.message || session.run_id)}</span>
      </div>
      <a class="btn" href="#/games/${encodeURIComponent(session.run_id)}/${session.current_round || 1}">Watch</a>
      <button class="btn" type="button" id="stop-session">Stop</button>
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
    <button class="btn" type="button" id="stop-session">Stop</button>
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

function refreshIcon() {
  return `<svg class="icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path d="M21 12a9 9 0 1 1-2.6-6.3"></path>
    <path d="M21 3v6h-6"></path>
  </svg>`;
}

function baseSetIcon() {
  return `<svg class="icon catalog-section-icon" viewBox="0 0 24 24" width="13" height="13" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 2 2 7l10 5 10-5-10-5z"></path>
    <path d="M2 12l10 5 10-5"></path>
    <path d="M2 17l10 5 10-5"></path>
  </svg>`;
}

function localAgentsIcon() {
  return `<svg class="icon catalog-section-icon" viewBox="0 0 24 24" width="13" height="13" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
  </svg>`;
}

function arenaIcon() {
  return `<svg class="icon catalog-section-icon" viewBox="0 0 24 24" width="13" height="13" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path d="M8 21h8"></path>
    <path d="M12 17v4"></path>
    <path d="M7 4h10v5a5 5 0 0 1-10 0V4z"></path>
    <path d="M17 8h1a3 3 0 0 0 0-6h-1"></path>
    <path d="M7 8H6a3 3 0 0 1 0-6h1"></path>
  </svg>`;
}

function renderGameWinner(winnerName) {
  if (!winnerName) return "";
  return `<span class="game-winner" title="Winner">
    ${crownIcon()}
    <span class="game-winner-label">Winner</span>
    <span class="game-winner-name">${escapeHtml(displayId(winnerName))}</span>
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
        <span class="player-name">${escapeHtml(displayId(name))}</span>
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

function displayId(value) {
  return String(value || "").toLowerCase();
}

function stripCatalogPrefix(value) {
  const raw = String(value || "");
  if (raw.startsWith("arena:")) return raw.slice("arena:".length);
  if (raw.startsWith("local:")) return raw.slice("local:".length);
  return raw;
}

function agentDisplayName(agent) {
  if (!agent) return "";
  // Base set: short id (challenger), not the *_bot file stem.
  if (isStandardAgent(agent)) {
    return displayId(agent.id || String(agent.name || "").replace(/_bot$/i, ""));
  }
  // Local / arena: bare folder or hub name — never the local:/arena: catalog id.
  return displayId(stripCatalogPrefix(agent.name || agent.id || ""));
}

function agentFolderName(agent) {
  if (!agent) return "";
  if (agent.name) return String(agent.name);
  return stripCatalogPrefix(agent.id || "");
}

function agentKindLabel(agent) {
  if (agent.kind === "local") return "local";
  return "";
}

function agentKindHtml(agent) {
  const kindLabel = agentKindLabel(agent);
  return kindLabel ? `<span class="agent-kind">${escapeHtml(kindLabel)}</span>` : "";
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
  const label = agentDisplayName(agent);
  const count = selected.filter((id) => id === agent.id).length;
  const title =
    count > 0
      ? `Add another ${label} (${count} in roster)`
      : `Add ${label}`;
  return `
    <button
      class="agent-pick"
      type="button"
      data-add-agent="${escapeAttr(agent.id)}"
      title="${escapeAttr(title)}"
    >
      <span class="agent-pick-plus" aria-hidden="true">+</span>
      <span class="agent-id">${escapeHtml(label)}</span>
      ${agentKindHtml(agent)}
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
      const label = agentDisplayName(agent) || id;
      const remove = editable
        ? `<button class="agent-remove" type="button" data-remove-index="${index}" aria-label="Remove ${escapeAttr(label)}">×</button>`
        : "";
      return `
        <div class="agent-seat ${agentSeatClass(agent)}">
          <span class="agent-id">${escapeHtml(label)}</span>
          ${agentKindHtml(agent)}
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
  const submittedEmpty = state.hub?.configured
    ? "No approved agents on coup-master yet."
    : "Arena needs a coup-master .env. Local play works without it.";
  const submittedPicks = submitted.length
    ? submitted.map((agent) => renderAgentPickerChip(agent, selected)).join("")
    : `<div class="muted agent-catalog-empty">${submittedEmpty}</div>`;
  return `
    <div class="agent-catalog">
      <div class="agent-catalog-group">
        <div class="agent-catalog-label">
          <span class="agent-catalog-title">${baseSetIcon()}Base set</span>
          <button class="btn ghost tiny" type="button" id="add-all-standard">Add all</button>
        </div>
        <div class="agent-grid">${standardPicks}</div>
      </div>
      <div class="agent-catalog-group">
        <div class="agent-catalog-label">
          <span class="agent-catalog-title">${localAgentsIcon()}Your local agents</span>
          <button class="btn ghost tiny" type="button" id="add-all-local" ${local.length ? "" : "disabled"}>Add all</button>
        </div>
        <div class="agent-grid">${localPicks}</div>
      </div>
      <div class="agent-catalog-group">
        <div class="agent-catalog-label">
          <span class="agent-catalog-title">${arenaIcon()}The Arena</span>
          <button class="btn ghost tiny" type="button" id="add-all-submitted" ${submitted.length ? "" : "disabled"}>Add all</button>
        </div>
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
  const manual = state.setupMode === "manual";
  const count = s.agents.length;
  const seedValue = s.seed == null || s.seed === "" ? "" : s.seed;
  const title = picking ? "New Tournament" : manual ? "Play Manually" : "Play Games";
  const blurb = picking
    ? "Pick the field for this tournament. Large fields split into equal-play tables of 2–6."
    : manual
      ? "You sit as You against 1–5 agents. One live game — pick moves yourself."
      : "Same agents, next round. Set games, hit Run.";
  const agentCountLabel = manual
    ? `${count} opponent${count === 1 ? "" : "s"}<span class="muted"> · need 1–5</span>`
    : `${count} selected${picking ? `<span class="muted"> · need 2+</span>` : ""}`;
  const agentSection = `
    <div class="agent-setup">
      <div class="agent-setup-head">
        <div class="setup-label">${picking ? "Agents" : manual ? "Opponents" : "Field"}</div>
        <div class="agent-count">${agentCountLabel}</div>
      </div>
      ${manual ? renderManualRoster() : renderSetupRoster(picking)}
      ${picking || manual ? renderAgentCatalog() : ""}
    </div>`;

  const gamesField = manual
    ? ""
    : `<div class="field">
          <label for="setup-games">Games / agent</label>
          <input id="setup-games" type="number" min="1" value="${s.games}">
        </div>`;

  return `
    <section class="panel setup-panel">
      <div class="panel-head">
        <h2>${title}</h2>
        <p class="muted">${escapeHtml(blurb)}</p>
      </div>
      <div class="setup-body">
        ${agentSection}
        ${manual ? "" : renderSeatingBlock()}
        <div class="setup-grid setup-grid-simple">
          <div class="field">
            <label for="setup-seed">Seed <span class="muted">(blank = random)</span></label>
            <input id="setup-seed" type="number" placeholder="random" value="${seedValue}">
          </div>
          <div class="field">
            <label for="setup-timeout">Timeout (s)</label>
            <input id="setup-timeout" type="number" min="0.1" step="0.1" value="${s.timeout}">
          </div>
          ${gamesField}
        </div>
        ${
          !manual && sessionIsLive()
            ? `<div class="session-error">A tournament is already running — Stop it in the banner, or wait for it to finish.</div>`
            : ""
        }
        ${state.setupError ? `<div class="session-error">${escapeHtml(state.setupError)}</div>` : ""}
        <div class="controls">
          <button class="btn primary" type="button" id="start-session" ${
            state.setupStarting || (!manual && sessionIsLive()) ? "disabled" : ""
          }>${state.setupStarting ? "Starting…" : manual ? "Play" : "Run"}</button>
          <button class="btn" type="button" id="close-setup">Close</button>
        </div>
      </div>
    </section>
  `;
}

function renderManualRoster() {
  const selected = state.setup.agents;
  const you = `
    <div class="agent-seat human-seat">
      <span class="agent-id">You</span>
      <span class="agent-kind human">Human</span>
    </div>`;
  const opponents = selected.length
    ? selected
        .map((id, index) => {
          const agent = agentById(id);
          const label = agentDisplayName(agent) || displayId(id);
          return `
            <div class="agent-seat ${agentSeatClass(agent)}">
              <span class="agent-id">${escapeHtml(label)}</span>
              ${agentKindHtml(agent)}
              <button class="agent-remove" type="button" data-remove-index="${index}" aria-label="Remove ${escapeAttr(label)}">×</button>
            </div>`;
        })
        .join("")
    : `<div class="agent-roster-empty muted">Add 1–5 agent opponents from the catalog.</div>`;
  return `<div class="agent-roster">${you}${opponents}</div>`;
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
        <div class="empty">No tournament results yet. New Tournament to pick agents, then Another round to play.</div>
      </section>`,
      "Tournament scoreboard"
    );
  }

  const standingsBody = standingsRows.length
    ? renderBoardTable(standingsRows)
    : `<div class="empty">${
        rounds.length
          ? "Standings appear after a round finishes."
          : "No rounds yet. Another round from settings to play more games."
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
    "Tournament scoreboard"
  );
}

function renderBoardTable(rows) {
  return `<div class="table-wrap"><table class="board">
    <thead>
      <tr>
        <th>Rank</th><th>Agent</th><th>Games</th><th>Points</th><th>Avg</th>
        <th>Wins</th><th>Win%</th><th>Errors</th><th>Avg ms</th>
      </tr>
    </thead>
    <tbody>${rows.map((row, index) => scoreRow(row, index + 1)).join("")}</tbody>
  </table></div>`;
}

function scoreRow(row, rank) {
  const games = row.games || 0;
  const errors = (row.errors || 0) + (row.timeouts || 0);
  return `<tr>
    <td>${rank}</td>
    <td class="agent-name">${escapeHtml(displayId(row.name))}</td>
    <td>${games}</td>
    <td>${row.points}</td>
    <td>${avg(row.points, games)}</td>
    <td>${row.wins}</td>
    <td>${pct(row.wins, games)}</td>
    <td>${errors}</td>
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
          <div class="game-id">${escapeHtml(displayId(game.id))}</div>
          <div>
            <div>${escapeHtml((game.players || []).map(displayId).join(" · "))}</div>
            <div class="muted" style="margin-top:0.25rem">Winner: ${escapeHtml(game.winner ? displayId(game.winner) : "—")} · ${game.turns ?? "?"} turns${game.capped ? " (capped)" : ""}</div>
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
            <div class="seat-name">${escapeHtml(displayId(player.name))}</div>
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
            <h1 class="game-id">${escapeHtml(displayId(pb.header.id || "Game"))}</h1>
            ${renderGameWinner(
              pb.events.length && pb.index >= pb.events.length - 1 ? pb.result?.winner : null
            )}
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

function renderManualPlay() {
  const m = state.manual;
  if (!m || m.status === "idle") {
    return renderChrome(
      `<section class="panel">
        <div class="panel-head"><h2>Play Manually</h2></div>
        <div class="empty">Pick opponents from Settings → Play manually, then hit Play.</div>
      </section>`,
      "You vs agents"
    );
  }

  const players = m.board?.players || [];
  const n = players.length || 2;
  const lastEvent = m.history?.length ? m.history[m.history.length - 1] : null;
  const roles = actionRoles(lastEvent, m.board);
  const actionTone = actionToneClass(lastEvent);
  const humanSeat = m.human_seat ?? 0;
  const claimsBySeat = claimsThrough(
    (m.history || []).map((item) => ({ ...item, type: "event" })),
    (m.history || []).length - 1
  );

  const seats = players
    .map((player, i) => {
      const pos = seatPosition(i, n);
      const out = (player.influence || 0) === 0;
      const isTurn = roles.turn === player.seat;
      const isActor = roles.actor === player.seat;
      const isTarget = roles.target === player.seat;
      const isChallenger = roles.challenger === player.seat;
      const isYou = player.seat === humanSeat;
      const role =
        (isActor && "actor") ||
        (isTarget && "target") ||
        (isChallenger && "challenger") ||
        "";
      const tags = [];
      if (isYou) tags.push(`<span class="seat-badge you">You</span>`);
      if (isActor) tags.push(`<span class="seat-badge">Act</span>`);
      if (isTarget) tags.push(`<span class="seat-badge target">Target</span>`);
      if (isChallenger) tags.push(`<span class="seat-badge challenger">Challenge</span>`);
      if (isTurn) tags.push(`<span class="seat-turn" title="This player's turn">Turn</span>`);
      const claims = claimsBySeat.get(player.seat) || [];
      return `
        <div class="seat ${out ? "out" : ""} ${role} ${isTurn ? "turn" : ""} ${isYou ? "you" : ""}" style="left:${pos.x}%;top:${pos.y}%" data-seat="${player.seat}">
          <div class="seat-card">
            ${tags.length ? `<div class="seat-tags">${tags.join("")}</div>` : ""}
            <div class="seat-name">${escapeHtml(isYou ? player.name : displayId(player.name))}</div>
            <div class="seat-meta">
              <span class="coins">${player.coins ?? "?"}¢</span>
              <span>${player.influence ?? "?"} inf</span>
            </div>
            ${renderCards(player, isYou)}
            ${renderClaims(claims)}
          </div>
        </div>`;
    })
    .join("");

  const winner =
    m.status === "finished" && m.result
      ? renderGameWinner(m.result.winner_name)
      : "";
  const promptPanel = renderManualPrompt(m);
  const backHref = state.runId
    ? `#/run/${encodeURIComponent(state.runId)}/standings`
    : "#/";

  return `
    <div class="shell play-shell">
      <header class="play-topbar">
        <a class="back-link" href="${backHref}">← Scoreboard</a>
        <div class="play-title">
          <div class="play-title-row">
            <h1>You vs agents</h1>
            ${winner}
          </div>
          ${renderPlayerRoster(players, { turnSeat: roles.turn })}
        </div>
        <div class="play-progress muted">seed ${m.seed ?? "—"}</div>
      </header>
      <div class="playback manual-playback">
        <div class="table-stage ${actionTone}">
          <div class="action-hud">${
            m.status === "finished"
              ? escapeHtml(m.message || "Game over")
              : m.status === "thinking"
                ? `<div class="eyebrow">Agents</div><div class="headline">${escapeHtml(m.message || "Thinking…")}</div>`
                : actionHud(lastEvent, players, roles) || escapeHtml(m.message || "")
          }</div>
          <div class="table-arena">
            ${actionArcs(roles, n)}
            <div class="table-ring" aria-hidden="true"></div>
            ${seats}
          </div>
        </div>
        <aside class="side-rail">
          <div class="manual-controls panel">
            <div class="panel-head">
              <h3>${escapeHtml(m.message || "Your move")}</h3>
              <label class="meta-chip manual-speed" for="manual-speed">
                <span class="meta-label">Speed</span>
                <select id="manual-speed">
                  ${SPEEDS.map(
                    (item) =>
                      `<option value="${item.ms}" ${item.ms === state.manualSpeedMs ? "selected" : ""}>${item.label}/move</option>`
                  ).join("")}
                </select>
              </label>
            </div>
            ${state.manualError ? `<div class="session-error">${escapeHtml(state.manualError)}</div>` : ""}
            ${promptPanel}
            <div class="controls manual-actions">
              <button class="btn" type="button" id="manual-leave">${
                m.status === "finished" ? "Close" : "Leave game"
              }</button>
              ${
                m.status === "finished"
                  ? `<button class="btn primary" type="button" id="manual-again">Play again</button>`
                  : ""
              }
            </div>
          </div>
          <div class="event-rail">
            <h3>Event log</h3>
            <div class="event-list" id="event-list">
              ${(m.history || [])
                .map((item, index, arr) => {
                  const kind = escapeAttr(item.event || "event");
                  const current = index === arr.length - 1;
                  return `
                <div class="event-item ${current ? "current" : ""}">
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

function renderManualPrompt(m) {
  if (m.status === "finished") {
    const rows = (m.result?.placements || [])
      .map(
        (row) =>
          `<div class="manual-place">${row.place}. ${escapeHtml(row.name)} · ${row.points} pts · ${row.influence} inf · ${row.coins}¢</div>`
      )
      .join("");
    return `<div class="manual-prompt">${rows || `<p class="muted">${escapeHtml(m.message || "Finished")}</p>`}</div>`;
  }
  if (m.status === "thinking") {
    const name = m.prompt?.name || "Agent";
    return `<div class="manual-prompt"><p class="muted">${escapeHtml(name)} is taking a turn…</p></div>`;
  }
  if (m.status !== "waiting" || !m.prompt || !m.view) {
    return `<div class="manual-prompt"><p class="muted">Waiting…</p></div>`;
  }
  const kind = m.prompt.kind;
  const busy = state.manualBusy ? "disabled" : "";
  if (kind === "choose_action") {
    const buttons = (m.view.legal_actions || [])
      .map((action) => {
        const label = actionLabel(action, m.board?.players || []);
        return `<button class="btn ${action.type === "coup" || action.type === "assassinate" ? "primary" : ""}" type="button" data-manual-action="${escapeAttr(
          action.type
        )}" data-manual-target="${action.target == null ? "" : action.target}" ${busy}>${escapeHtml(label)}</button>`;
      })
      .join("");
    return `<div class="manual-prompt"><div class="manual-choice-grid">${buttons}</div></div>`;
  }
  if (kind === "respond_to_action" || kind === "respond_to_block") {
    const phase = m.view.phase || m.prompt?.phase;
    const actionType = m.view.action?.type;
    const blockers = ACTION_BLOCK[actionType] || [];
    const isTarget = m.view.action?.target === m.view.you;
    let hint = "";
    if (phase === "challenge" && blockers.length) {
      const names = blockers.map((card) => CARD_SHORT[card] || card).join(" / ");
      const who =
        actionType === "foreign_aid"
          ? "Anyone can block after challenges"
          : isTarget
            ? `You can block with ${names} after challenges`
            : `The target can block with ${names} after challenges`;
      hint = `<p class="muted manual-phase-hint">${escapeHtml(who)}. Pass here first if you are not challenging.</p>`;
    } else if (phase === "block" && blockers.length) {
      const names = blockers.map((card) => CARD_SHORT[card] || card).join(" / ");
      hint = `<p class="muted manual-phase-hint">Claim ${escapeHtml(names)} to block (truthful or bluff).</p>`;
    }
    const buttons = (m.view.legal_responses || [])
      .map((response) => {
        if (response.type === "pass") {
          return `<button class="btn" type="button" data-manual-response="pass" ${busy}>Pass</button>`;
        }
        if (response.type === "challenge") {
          return `<button class="btn primary" type="button" data-manual-response="challenge" ${busy}>Challenge</button>`;
        }
        if (response.type === "block") {
          return `<button class="btn" type="button" data-manual-response="block" data-manual-card="${escapeAttr(
            response.card
          )}" ${busy}>Block (${escapeHtml(CARD_SHORT[response.card] || response.card)})</button>`;
        }
        return "";
      })
      .join("");
    return `<div class="manual-prompt">${hint}<div class="manual-choice-grid">${buttons}</div></div>`;
  }
  if (kind === "choose_card_to_lose") {
    const buttons = (m.view.your_cards || [])
      .map(
        (card) =>
          `<button class="btn primary" type="button" data-manual-lose="${escapeAttr(card)}" ${busy}>Lose ${escapeHtml(
            CARD_SHORT[card] || card
          )}</button>`
      )
      .join("");
    return `<div class="manual-prompt"><div class="manual-choice-grid">${buttons}</div></div>`;
  }
  if (kind === "choose_exchange") {
    const pool = [...(m.view.your_cards || []), ...(m.view.drawn || [])];
    const need = (m.view.your_cards || []).length;
    const selected = new Set(state.manualExchangeKeep);
    const chips = pool
      .map((card, index) => {
        const key = `${card}:${index}`;
        const on = state.manualExchangeKeep.includes(key);
        return `<button class="card-chip held ${escapeAttr(card)} ${on ? "picked" : ""}" type="button" data-exchange-toggle="${escapeAttr(
          key
        )}" ${busy}>${shortLabel(card)}</button>`;
      })
      .join("");
    const canConfirm = state.manualExchangeKeep.length === need;
    return `
      <div class="manual-prompt">
        <p class="muted">Pick ${need} card${need === 1 ? "" : "s"} to keep (${selected.size}/${need}).</p>
        <div class="manual-exchange-pool">${chips}</div>
        <button class="btn primary" type="button" id="manual-exchange-confirm" ${
          canConfirm && !state.manualBusy ? "" : "disabled"
        }>Keep selected</button>
      </div>`;
  }
  return `<div class="manual-prompt"><p class="muted">Unknown prompt</p></div>`;
}

function actionLabel(action, players) {
  const base = ACTION_LABEL[action.type] || action.type;
  if (action.target == null) return base;
  const name = players.find((p) => p.seat === action.target)?.name || `seat ${action.target}`;
  return `${base} → ${name}`;
}

function bindManualPlay() {
  bindChrome();
  document.getElementById("manual-speed")?.addEventListener("change", (event) => {
    state.manualSpeedMs = Number(event.target.value) || 1000;
  });
  document.getElementById("manual-leave")?.addEventListener("click", () => leaveManualGame());
  document.getElementById("manual-again")?.addEventListener("click", () => leaveManualGame({ reopenSetup: true }));
  document.querySelectorAll("[data-manual-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const type = btn.getAttribute("data-manual-action");
      const rawTarget = btn.getAttribute("data-manual-target");
      const decision = { type };
      if (rawTarget !== "" && rawTarget != null) decision.target = Number(rawTarget);
      submitManualMove(decision);
    });
  });
  document.querySelectorAll("[data-manual-response]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const type = btn.getAttribute("data-manual-response");
      const decision = { type };
      if (type === "block") decision.card = btn.getAttribute("data-manual-card");
      submitManualMove(decision);
    });
  });
  document.querySelectorAll("[data-manual-lose]").forEach((btn) => {
    btn.addEventListener("click", () => {
      submitManualMove({ card: btn.getAttribute("data-manual-lose") });
    });
  });
  document.querySelectorAll("[data-exchange-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-exchange-toggle");
      if (!key) return;
      const need = (state.manual?.view?.your_cards || []).length;
      let next = [...state.manualExchangeKeep];
      if (next.includes(key)) next = next.filter((item) => item !== key);
      else if (next.length < need) next.push(key);
      state.manualExchangeKeep = next;
      render();
    });
  });
  document.getElementById("manual-exchange-confirm")?.addEventListener("click", () => {
    const keep = state.manualExchangeKeep.map((key) => key.split(":")[0]);
    submitManualMove({ keep });
  });
  const list = document.getElementById("event-list");
  if (list) list.scrollTop = list.scrollHeight;
  if (state.manual?.status === "thinking" && state.manualPumpTimer == null && !state.manualBusy) {
    scheduleManualPump();
  }
}

function stopManualPump() {
  if (state.manualPumpTimer != null) {
    clearTimeout(state.manualPumpTimer);
    state.manualPumpTimer = null;
  }
}

function scheduleManualPump() {
  stopManualPump();
  if (state.view !== "manual" || state.manual?.status !== "thinking") return;
  const delay = Math.max(100, Number(state.manualSpeedMs) || 1000);
  state.manualPumpTimer = setTimeout(() => {
    state.manualPumpTimer = null;
    stepManualAgent();
  }, delay);
}

async function stepManualAgent() {
  if (state.view !== "manual") return;
  if (state.manual?.status !== "thinking") return;
  if (state.manualBusy) return;
  state.manualBusy = true;
  state.manualError = null;
  try {
    state.manual = await fetchJson("/api/manual/step", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (err) {
    state.manualError = err.message || String(err);
  } finally {
    state.manualBusy = false;
    render();
    if (state.manual?.status === "thinking") scheduleManualPump();
  }
}

async function submitManualMove(decision) {
  if (state.manualBusy || state.manual?.status === "thinking") return;
  stopManualPump();
  state.manualBusy = true;
  state.manualError = null;
  render();
  try {
    state.manual = await fetchJson("/api/manual/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(decision),
    });
    state.manualExchangeKeep = [];
  } catch (err) {
    state.manualError = err.message || String(err);
  } finally {
    state.manualBusy = false;
    render();
    if (state.manual?.status === "thinking") scheduleManualPump();
  }
}

async function leaveManualGame({ reopenSetup = false } = {}) {
  stopManualPump();
  try {
    await fetchJson("/api/manual/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (err) {
    console.error(err);
  }
  state.manual = null;
  state.manualError = null;
  state.manualExchangeKeep = [];
  if (reopenSetup) {
    state.setupMode = "manual";
    state.setupOpen = true;
    state.setupError = null;
    state.submitOpen = false;
    if (state.setup.agents.length > 5) state.setup.agents = state.setup.agents.slice(0, 5);
  }
  const target = state.runId ? `#/run/${encodeURIComponent(state.runId)}/standings` : "#/";
  if (location.hash === "#/manual" || state.view === "manual") {
    if (location.hash === target) {
      state.view = "scoreboard";
      await loadScoreboard({ quiet: true });
      render();
    } else {
      location.hash = target;
    }
  } else {
    render();
  }
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
    if (!state.setupMenuOpen) unbindMenuCloser();
    render();
  });
  document.getElementById("another-round")?.addEventListener("click", () => {
    closeSetupMenu();
    openRoundSetup().then(() => render());
  });
  document.getElementById("play-manually")?.addEventListener("click", () => {
    closeSetupMenu();
    openManualSetup().then(() => render());
  });
  document.getElementById("submit-agent")?.addEventListener("click", () => {
    closeSetupMenu();
    openSubmitModal();
  });
  bindSubmitModal();
  bindMenuCloser();
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

function localAgents() {
  return availableAgents().filter((agent) => agent.kind === "local");
}

function renderHubStatus() {
  const ping = state.hubPing;
  const status = ping?.status || "checking";
  let badge = "CHECKING";
  let badgeClass = "checking";
  let title = "Pinging hub…";
  if (status === "ready") {
    badge = "READY";
    badgeClass = "ready";
    title = ping.version ? `Hub v${ping.version}` : "Hub ready";
  } else if (status === "unset") {
    badge = "NO .ENV";
    badgeClass = "not-ready";
    title = ping?.error || "Add a coup-master .env to submit (see .env.example)";
  } else if (status === "offline") {
    badge = "OFFLINE";
    badgeClass = "not-ready";
    title = ping?.error || "Hub unreachable";
  }
  return `
    <div class="submit-hub" title="${escapeAttr(title)}">
      <span class="muted">Hub</span>
      <span class="submit-badge ${badgeClass}">${badge}</span>
      <button type="button" class="btn icon-btn hub-ping-btn" id="ping-hub"
        title="Check hub" aria-label="Check hub"
        ${status === "checking" ? "disabled" : ""}>${refreshIcon()}</button>
    </div>`;
}

function renderSubmitModal() {
  const local = localAgents();
  const s = state.submit;
  const selected = s.agent;
  const hubStatus = state.hubPing?.status;
  const hubReady = hubStatus === "ready";
  const hubUnset =
    hubStatus === "unset" ||
    (state.hub?.configured === false && hubStatus !== "checking");
  const report = s.report;
  const taken = hubNameSet();
  const picks = local.length
    ? local
        .map((agent) => {
          const active = agent.id === selected ? "active" : "";
          const label = agentDisplayName(agent);
          const folder = agentFolderName(agent);
          const onHub = taken.has(folder.toLowerCase());
          const kind = onHub ? "on hub" : "local";
          const kindClass = onHub ? "agent-kind on-hub" : "agent-kind";
          return `<button class="agent-pick submit-pick ${active}${
            onHub ? " on-hub" : ""
          }" type="button" data-submit-agent="${escapeAttr(agent.id)}" ${
            onHub ? `title="${escapeAttr(`${label} is already on the hub`)}"` : ""
          }>
            <span class="agent-id">${escapeHtml(label)}</span>
            <span class="${kindClass}">${escapeHtml(kind)}</span>
          </button>`;
        })
        .join("")
    : `<div class="muted agent-catalog-empty">No agents in agents/local yet. Copy the template into agents/local/&lt;name&gt;/agent.py first.</div>`;

  const busy = Boolean(s.busy);
  const fullNameIssue = fullNameError(s.fullName);
  const fullNameOk = !fullNameIssue;
  const nameTrimmed = (s.name || "").trim();
  const coupAiIssue = coupAiNameError(s.name);
  const coupAiOk = !coupAiIssue;
  const dupReason = duplicateSubmitReason(nameTrimmed, selected);
  const onHubAlready =
    Boolean(nameTrimmed) &&
    !dupReason &&
    taken.has(nameTrimmed.toLowerCase());
  const showCoupAiError = Boolean(nameTrimmed) && Boolean(coupAiIssue);
  const canAct = Boolean(selected) && coupAiOk && !busy;
  const localReady =
    Boolean(report) &&
    report.ready === true &&
    report.name_ok !== false &&
    report.safe !== false;
  // Submit stays disabled without coup-master .env (hub unset) or when hub is down.
  const canSubmit =
    canAct && hubReady && localReady && fullNameOk && !dupReason;
  const submitTitle = dupReason
    ? dupReason
    : hubStatus === "checking"
      ? "Checking hub…"
      : hubUnset
        ? "Add a coup-master .env first — local play still works"
        : !hubReady
          ? "Hub is offline — check hub status first"
          : !fullNameOk
            ? fullNameIssue || "Enter your full name"
            : !coupAiOk
              ? coupAiIssue || "Name your Coup AI"
              : localReady
                ? onHubAlready
                  ? `Replace existing hub agent "${nameTrimmed}"`
                  : "Upload to coup-master"
                : "Run Test locally and get READY first";
  const submitLabel = s.busy === "submit"
    ? "Submitting…"
    : dupReason
      ? "Already submitted"
      : onHubAlready && localReady
        ? "Replace on hub"
        : "Submit to hub";
  const fullNameHint = fullNameIssue
    ? `<p class="field-error">${escapeHtml(fullNameIssue)}</p>`
    : `<p class="muted field-hint">First and last name, as you'd write it on a form</p>`;
  let coupAiHint;
  if (showCoupAiError) {
    coupAiHint = `<p class="field-error">${escapeHtml(coupAiIssue)}</p>`;
  } else if (dupReason && !s.success) {
    coupAiHint = `<p class="field-error">${escapeHtml(dupReason)}</p>`;
  } else if (onHubAlready) {
    coupAiHint = `<p class="muted field-hint">"${escapeHtml(
      nameTrimmed
    )}" is already on the hub — submit will replace it</p>`;
  } else {
    coupAiHint = `<p class="muted field-hint">Public handle on the hub — letters, numbers, _ and - only</p>`;
  }

  let statusHtml = "";
  if (s.error) {
    statusHtml = `<div class="session-error">${escapeHtml(s.error)}</div>`;
  } else if (s.success) {
    statusHtml = `<div class="submit-success">
      <div>${escapeHtml(s.success)}</div>
      <p class="muted field-hint submit-success-hint">Submit is locked for this Coup AI name. Pick another local agent or a new name to upload again.</p>
    </div>`;
  }
  if (report && !s.success) {
    const ready = report.ready && report.name_ok !== false;
    const badge = ready ? "READY" : "NOT READY";
    const badgeClass = ready ? "ready" : "not-ready";
    const issueList = report.issues || [];
    const issues = issueList.length
      ? `<ul class="submit-issues">${issueList
          .map((issue) => `<li>${escapeHtml(issue)}</li>`)
          .join("")}</ul>`
      : "";
    const failNote =
      !ready && !s.error
        ? `<p class="field-error">Fix the issues below, then run Test locally again.</p>`
        : "";
    statusHtml += `
      <div class="submit-report">
        ${failNote}
        <div class="submit-badge ${badgeClass}">${badge}</div>
        <pre class="submit-report-text">${escapeHtml(report.text || "")}</pre>
        ${issues}
      </div>`;
  }

  return `
    <div class="modal-backdrop" id="submit-backdrop" role="presentation">
      <div class="modal rules-modal submit-modal" role="dialog" aria-modal="true" aria-labelledby="submit-title">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Settings</p>
            <h2 id="submit-title">Submit agent</h2>
          </div>
          <div class="submit-head-actions">
            ${renderHubStatus()}
            <button type="button" class="btn" id="close-submit">Close</button>
          </div>
        </div>
        <div class="rules-scroll submit-body">
          <div class="agent-catalog-group">
            <div class="agent-catalog-label"><span class="agent-catalog-title">${localAgentsIcon()}Your local agents</span></div>
            <div class="agent-grid">${picks}</div>
          </div>
          <div class="field">
            <label for="submit-full-name">Your full name</label>
            <input id="submit-full-name" type="text" autocomplete="name" spellcheck="false"
              placeholder="Ada Lovelace" value="${escapeAttr(s.fullName || "")}" ${busy ? "disabled" : ""}
              aria-invalid="${fullNameIssue && (s.fullName || "").trim() ? "true" : "false"}">
            ${fullNameHint}
          </div>
          <div class="field">
            <label for="submit-name">Name of your Coup AI</label>
            <input id="submit-name" type="text" autocomplete="off" spellcheck="false"
              placeholder="milo_bot" value="${escapeAttr(s.name || "")}" ${busy ? "disabled" : ""}
              aria-invalid="${showCoupAiError || (dupReason && !s.success) ? "true" : "false"}">
            ${coupAiHint}
          </div>
          ${statusHtml}
          <div class="controls submit-actions">
            <button class="btn" type="button" id="test-submit-agent" ${canAct ? "" : "disabled"}>
              ${s.busy === "test" ? "Testing…" : "Test locally"}
            </button>
            <button class="btn primary" type="button" id="confirm-submit-agent" ${
              canSubmit ? "" : "disabled"
            } title="${escapeAttr(submitTitle)}" aria-disabled="${canSubmit ? "false" : "true"}">
              ${escapeHtml(submitLabel)}
            </button>
          </div>
        </div>
      </div>
    </div>`;
}

let menuCloser = null;

function unbindMenuCloser() {
  if (!menuCloser) return;
  document.removeEventListener("click", menuCloser);
  menuCloser = null;
}

function closeSetupMenu() {
  state.setupMenuOpen = false;
  unbindMenuCloser();
}

function bindMenuCloser() {
  unbindMenuCloser();
  if (!state.setupMenuOpen) return;
  menuCloser = (event) => {
    const menu = document.querySelector(".menu");
    if (menu && menu.contains(event.target)) return;
    closeSetupMenu();
    render();
  };
  setTimeout(() => {
    if (menuCloser) document.addEventListener("click", menuCloser);
  }, 0);
}

async function openSubmitModal() {
  closeSetupMenu();
  state.submitOpen = true;
  // Keep agent / name / last READY report across open/close.
  const local = localAgents();
  if (!state.submit.agent && local.length) {
    state.submit.agent = local[0].id;
    if (!state.submit.name) state.submit.name = agentFolderName(local[0]);
  }
  state.hubPing = { status: "checking", error: null, version: null };
  render();
  if (!state.hub) {
    await loadHub();
  }
  await pingHub();
  if (state.submitOpen) render();
}

function closeSubmitModal() {
  const submitName = document.getElementById("submit-name");
  if (submitName) state.submit.name = submitName.value;
  const submitFullName = document.getElementById("submit-full-name");
  if (submitFullName) state.submit.fullName = submitFullName.value;
  state.submitOpen = false;
  state.submit.busy = null;
  if (submitKeyHandler) {
    document.removeEventListener("keydown", submitKeyHandler);
    submitKeyHandler = null;
  }
  render();
}

let submitKeyHandler = null;

function bindSubmitEscape() {
  if (submitKeyHandler) {
    document.removeEventListener("keydown", submitKeyHandler);
    submitKeyHandler = null;
  }
  if (!state.submitOpen) return;
  submitKeyHandler = (event) => {
    if (event.key === "Escape" && !state.submit.busy) closeSubmitModal();
  };
  document.addEventListener("keydown", submitKeyHandler);
}

function bindSubmitModal() {
  if (!state.submitOpen) return;
  bindSubmitEscape();
  document.getElementById("close-submit")?.addEventListener("click", () => {
    if (!state.submit.busy) closeSubmitModal();
  });
  document.getElementById("submit-backdrop")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget && !state.submit.busy) closeSubmitModal();
  });
  document.querySelectorAll("[data-submit-agent]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (state.submit.busy) return;
      const id = btn.getAttribute("data-submit-agent");
      const prev = state.submit.agent;
      const prevFolder = agentFolderName(agentById(prev));
      const next = agentById(id);
      state.submit.agent = id;
      // Coup AI hub name is the bare folder name, not local:/arena: catalog ids.
      if (!state.submit.name || state.submit.name === prev || state.submit.name === prevFolder) {
        state.submit.name = agentFolderName(next) || id;
      }
      state.submit.report = null;
      state.submit.error = null;
      state.submit.success = null;
      render();
    });
  });
  const nameInput = document.getElementById("submit-name");
  nameInput?.addEventListener("input", () => {
    const pos = nameInput.selectionStart;
    state.submit.name = nameInput.value;
    state.submit.success = null;
    state.submit.error = null;
    if (state.submit.report) state.submit.report = null;
    render();
    const again = document.getElementById("submit-name");
    if (again) {
      again.focus();
      if (typeof pos === "number") again.setSelectionRange(pos, pos);
    }
  });
  const fullNameInput = document.getElementById("submit-full-name");
  fullNameInput?.addEventListener("input", () => {
    const pos = fullNameInput.selectionStart;
    state.submit.fullName = fullNameInput.value;
    state.submit.success = null;
    state.submit.error = null;
    render();
    const again = document.getElementById("submit-full-name");
    if (again) {
      again.focus();
      if (typeof pos === "number") again.setSelectionRange(pos, pos);
    }
  });
  document.getElementById("ping-hub")?.addEventListener("click", async () => {
    if (state.hubPing?.status === "checking") return;
    state.hubPing = { status: "checking", error: null, version: null };
    render();
    await pingHub();
    if (state.submitOpen) render();
  });
  document.getElementById("test-submit-agent")?.addEventListener("click", () => runSubmitTest());
  document.getElementById("confirm-submit-agent")?.addEventListener("click", () => runSubmitUpload());
}

async function runSubmitTest() {
  const agent = state.submit.agent;
  const name = (state.submit.name || "").trim();
  const nameIssue = coupAiNameError(name);
  if (!agent || state.submit.busy) return;
  if (nameIssue) {
    state.submit.error = nameIssue;
    render();
    return;
  }
  state.submit.busy = "test";
  state.submit.error = null;
  state.submit.success = null;
  state.submit.report = null;
  render();
  try {
    const report = await fetchJson("/api/agents/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent, name, games: 40, sandbox_games: 2 }),
    });
    // Keep the detailed NOT READY report visible — don’t cover it with a generic banner.
    state.submit.report = report;
    state.submit.error = null;
  } catch (err) {
    state.submit.error = err.message;
  } finally {
    state.submit.busy = null;
    render();
  }
}

async function runSubmitUpload() {
  const agent = state.submit.agent;
  const name = (state.submit.name || "").trim();
  const fullName = normalizeFullName(state.submit.fullName);
  if (!agent || state.submit.busy) return;
  const nameIssue = coupAiNameError(name);
  if (nameIssue) {
    state.submit.error = nameIssue;
    render();
    return;
  }
  const dupReason = duplicateSubmitReason(name, agent);
  if (dupReason) {
    state.submit.error = dupReason;
    render();
    return;
  }
  const personIssue = fullNameError(fullName);
  if (personIssue) {
    state.submit.error = personIssue;
    render();
    return;
  }
  if (!state.hub?.configured || state.hubPing?.status === "unset") {
    state.submit.error =
      "Add a coup-master .env first (see .env.example). The dashboard works without it — only submit needs the hub.";
    render();
    return;
  }
  const report = state.submit.report;
  const localReady =
    Boolean(report) &&
    report.ready === true &&
    report.name_ok !== false &&
    report.safe !== false;
  if (!localReady) {
    state.submit.error = "Run Test locally and get READY before submitting.";
    render();
    return;
  }
  state.submit.busy = "submit";
  state.submit.error = null;
  state.submit.success = null;
  render();
  try {
    const meta = await fetchJson("/api/hub/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent,
        name,
        full_name: fullName,
        require_ready: true,
        games: 40,
        sandbox_games: 2,
      }),
    });
    const who = meta.full_name || meta.uploader || fullName;
    const uploaded = String(meta.name || name).trim();
    state.submit.success = `Uploaded ${uploaded} as ${who} (${meta.size_bytes} bytes).`;
    state.submit.lastUpload = { agent, name: uploaded };
    const key = uploaded.toLowerCase();
    if (!state.submit.uploadedNames.includes(key)) {
      state.submit.uploadedNames = [...state.submit.uploadedNames, key];
    }
    state.submit.report = {
      ready: true,
      name_ok: true,
      safe: true,
      issues: [],
      text: `READY\nuploaded ${uploaded}\nfull name ${who}\nsha256 ${meta.sha256}`,
    };
    // Refresh arena catalog so the name shows as taken immediately.
    await loadAgents({ quiet: true });
  } catch (err) {
    state.submit.error = err.message;
  } finally {
    state.submit.busy = null;
    render();
  }
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

function catalogIdForSeatName(name) {
  if (typeof name !== "string" || !name) return null;
  const agents = availableAgents();
  const arenaId = `arena:${name}`;
  if (agents.some((agent) => agent.id === arenaId)) return arenaId;
  if (agents.some((agent) => agent.id === name)) return name;
  return null;
}

function hydrateSetupAgentsFromRun() {
  // Always rebuild for the current run — never keep a sticky draft from another tournament.
  const run = currentRun();
  const fromRoster = (
    (Array.isArray(state.runAgents) && state.runAgents.length ? state.runAgents : null) ||
    (Array.isArray(run?.agents) ? run.agents : [])
  ).filter((id) => typeof id === "string" && id);
  if (fromRoster.length >= 2) {
    state.setup.agents = [...fromRoster];
    return;
  }
  const fromSession =
    state.session?.run_id === state.runId && Array.isArray(state.session?.agents)
      ? state.session.agents.filter((id) => typeof id === "string" && id)
      : [];
  if (fromSession.length >= 2) {
    state.setup.agents = [...fromSession];
    return;
  }
  const fromStandings = (state.standings?.agents || [])
    .map((row) => catalogIdForSeatName(row?.name))
    .filter((id) => typeof id === "string" && id);
  if (fromStandings.length >= 2) {
    state.setup.agents = [...fromStandings];
  } else {
    state.setup.agents = [];
  }
}

function agentCatalogFingerprint() {
  return availableAgents()
    .map((agent) => `${agent.id}:${agent.kind}:${agent.full_name || ""}`)
    .join("|");
}

async function openTournamentSetup() {
  state.setupMode = "tournament";
  state.setupOpen = true;
  closeSetupMenu();
  state.setupError = null;
  render();
  // Hub approvals land after upload; refresh so Submitted picks up coup-master.
  const before = agentCatalogFingerprint();
  await loadAgents({ quiet: true });
  // Skip remount when nothing changed or Run is already in flight (click survival).
  if (
    state.setupOpen &&
    state.setupMode === "tournament" &&
    !state.setupStarting &&
    agentCatalogFingerprint() !== before
  ) {
    render();
  }
}

function tournamentDraftPending() {
  if (state.setupMode !== "tournament" || !state.runId) return false;
  const finishedRounds =
    typeof state.standings?.rounds === "number"
      ? state.standings.rounds
      : (state.runRounds || []).filter((r) => state.roundSummaries[r]?.agents?.length).length;
  if (finishedRounds > 0) return false;
  const sessionRounds =
    state.session?.run_id === state.runId ? state.session.rounds || [] : [];
  return sessionRounds.length === 0;
}

async function openRoundSetup() {
  // Set mode before loadScoreboard so a leftover New Tournament draft does not
  // short-circuit roster/standings fetch for this run.
  state.setupMode = "round";
  await Promise.all([
    loadSession({ quiet: true }),
    loadAgents({ quiet: true }),
    loadScoreboard({ quiet: true }),
  ]);
  syncLivePolling();
  hydrateSetupAgentsFromRun();
  if (state.setup.agents.length < 2) {
    await openTournamentSetup();
    state.setupError = "Couldn't restore this run's agents — pick agents for a new tournament.";
    render();
    return;
  }
  state.setupOpen = true;
  closeSetupMenu();
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
  state.runAgents = [];
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
    if (state.setupOpen && state.setupMode === "tournament") {
      readSetupFieldsFromDom();
      state.setupOpen = false;
      closeSetupMenu();
      state.setupError = null;
      render();
      return;
    }
    // Reopen a closed draft instead of wiping agent picks / minting a new run.
    if (!state.setupOpen && tournamentDraftPending()) {
      openTournamentSetup();
      render();
      return;
    }
    startNewTournament();
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
  const picking = state.setupMode === "tournament" || state.setupMode === "manual";
  const manual = state.setupMode === "manual";
  document.getElementById("close-setup")?.addEventListener("click", () => {
    readSetupFieldsFromDom();
    state.setupOpen = false;
    state.setupError = null;
    if (manual) {
      leaveManualGame();
      return;
    }
    render();
  });
  document.getElementById("setup-seed")?.addEventListener("input", (event) => {
    const raw = String(event.target.value ?? "").trim();
    state.setup.seed = raw === "" ? null : Number(raw);
  });
  document.getElementById("setup-timeout")?.addEventListener("input", (event) => {
    state.setup.timeout = Number(event.target.value) || 1;
  });
  document.getElementById("setup-games")?.addEventListener("input", (event) => {
    state.setup.games = Math.max(1, Number(event.target.value) || 1);
  });
  document.getElementById("setup-games")?.addEventListener("change", () => {
    readSetupFieldsFromDom();
    render();
  });
  document.querySelectorAll("[data-prefer-size]").forEach((btn) => {
    btn.addEventListener("click", () => {
      readSetupFieldsFromDom();
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
        if (manual && state.setup.agents.length >= 5) {
          state.setupError = "At most 5 agent opponents.";
          render();
          return;
        }
        if (manual && state.setup.agents.includes(id)) {
          state.setupError = "Each opponent once — pick different agents.";
          render();
          return;
        }
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
      if (manual) {
        addManualOpponents(standardIds);
      } else {
        state.setup.agents.push(...standardIds);
        state.setupError = null;
        render();
      }
    });
    document.getElementById("add-all-local")?.addEventListener("click", () => {
      const localIds = availableAgents()
        .filter((agent) => agent.kind === "local")
        .map((agent) => agent.id);
      if (!localIds.length) return;
      if (manual) {
        addManualOpponents(localIds);
      } else {
        state.setup.agents.push(...localIds);
        state.setupError = null;
        render();
      }
    });
    document.getElementById("add-all-submitted")?.addEventListener("click", () => {
      const submittedIds = availableAgents()
        .filter((agent) => agent.kind === "submission")
        .map((agent) => agent.id);
      if (!submittedIds.length) return;
      if (manual) {
        addManualOpponents(submittedIds);
      } else {
        state.setup.agents.push(...submittedIds);
        state.setupError = null;
        render();
      }
    });
  }
  // #start-session is handled by bindAppDelegates (remount-safe).
}

function addManualOpponents(ids) {
  const next = [...state.setup.agents];
  for (const id of ids) {
    if (next.includes(id)) continue;
    if (next.length >= 5) break;
    next.push(id);
  }
  state.setup.agents = next;
  state.setupError = next.length >= 5 && ids.some((id) => !state.setup.agents.includes(id))
    ? "Filled to 5 opponents."
    : null;
  render();
}

async function openManualSetup() {
  state.setupMode = "manual";
  state.setupOpen = true;
  closeSetupMenu();
  state.setupError = null;
  state.submitOpen = false;
  if (!state.setup.agents.length) {
    state.setup.agents = ["random", "honest", "guard", "turtle", "greedy"].filter((id) =>
      availableAgents().some((agent) => agent.id === id)
    );
  }
  if (state.setup.agents.length > 5) {
    state.setup.agents = state.setup.agents.slice(0, 5);
  }
  await loadAgents({ quiet: true });
  render();
}

async function startManualGame() {
  if (state.setupStarting) return;
  state.setupError = null;
  readSetupFieldsFromDom();
  if (state.setup.agents.length < 1) {
    state.setupError = "Pick at least 1 agent opponent.";
    render();
    return;
  }
  if (state.setup.agents.length > 5) {
    state.setupError = "At most 5 agent opponents.";
    render();
    return;
  }
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
    agents: [...state.setup.agents],
    seed,
    timeout: Number(state.setup.timeout) || 1,
  };
  try {
    state.setupStarting = true;
    state.manualBusy = true;
    state.manualError = null;
    render();
    state.manual = await fetchJson("/api/manual/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.manualExchangeKeep = [];
    state.setupOpen = false;
    state.setupMenuOpen = false;
    state.manualBusy = false;
    state.setupStarting = false;
    if (location.hash === "#/manual") {
      state.view = "manual";
      render();
    } else {
      location.hash = "#/manual";
    }
  } catch (err) {
    state.manualBusy = false;
    state.setupStarting = false;
    state.setupError = err.message || String(err);
    render();
  }
}

async function loadManual({ quiet = false } = {}) {
  try {
    state.manual = await fetchJson("/api/manual");
  } catch (err) {
    if (!quiet) console.error(err);
    state.manualError = err.message || String(err);
  }
}

async function stopSession() {
  try {
    state.session = await fetchJson("/api/session/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (err) {
    console.error(err);
  }
  await loadSession({ quiet: true });
  syncLivePolling();
  render();
}

async function startSession() {
  if (state.setupStarting) return;
  state.setupError = null;
  readSetupFieldsFromDom();
  if (sessionIsLive()) {
    state.setupError = "A tournament is already running — Stop it first, or wait.";
    render();
    return;
  }
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
  // New tournament agent-pick always starts at round 1; Another round continues the run.
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
    state.setupStarting = true;
    state.sessionErrorHidden = false;
    state.followPlay = true;
    render();
    state.session = await fetchJson("/api/session/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    // Start returns a "running" snapshot; fast rounds may already be done or failed.
    await loadSession({ quiet: true });
    if (state.session?.status === "error") {
      state.setupStarting = false;
      state.followPlay = false;
      state.setupOpen = true;
      state.setupError = state.session.error || state.session.message || "Tournament failed";
      syncLivePolling();
      render();
      return;
    }
    state.setupOpen = false;
    state.setupMenuOpen = false;
    state.setupStarting = false;
    state.runId = state.session?.run_id || state.runId;
    state.round = state.session?.current_round || roundNumber;
    state.runAgents = [...payload.agents];
    ensureRunInList(state.runId);
    const run = currentRun();
    if (run) run.agents = [...payload.agents];
    await loadGames({ quiet: true });
    syncLivePolling();
    if (armFollowPlay()) return;
    const gamesHash = `#/games/${encodeURIComponent(state.runId)}/${state.round}`;
    if (location.hash === gamesHash) {
      state.view = "games";
      await loadRuns({ quiet: true });
      render();
    } else {
      location.hash = gamesHash;
    }
    if (!sessionIsLive()) {
      await loadRuns({ quiet: true });
      await loadGames({ quiet: true });
      // Failed after navigate — reopen setup with the error.
      if (state.session?.status === "error") {
        state.followPlay = false;
        state.setupOpen = true;
        state.setupError = state.session.error || state.session.message || "Tournament failed";
        render();
        return;
      }
      if (!armFollowPlay()) render();
    }
  } catch (err) {
    state.setupStarting = false;
    state.followPlay = false;
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
        else {
          state.followPlay = false;
          stopFollowTimer();
          stopPlaybackTimer();
        }
        render();
        return;
      }
      state.followPlay = false;
      stopFollowTimer();
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
      state.followPlay = false;
      stopFollowTimer();
      pb.playing = false;
      stopPlaybackTimer();
      pb.index = Number(scrub.value);
      render();
    });
  }
  document.querySelectorAll(".event-item[data-index]").forEach((item) => {
    item.addEventListener("click", () => {
      state.followPlay = false;
      stopFollowTimer();
      pb.playing = false;
      stopPlaybackTimer();
      pb.index = Number(item.getAttribute("data-index"));
      render();
    });
  });
  if (pb.playing && !playTimer) startPlaybackTimer();
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
      scheduleFollowNext();
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
