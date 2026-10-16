"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const form = $("take-form");
  const cameraLabels = { locked: "Locked off", push: "Slow push", orbit: "Orbit", track: "Tracking" };
  const lightingLabels = { golden: "Golden hour", studio: "Studio light", night: "Night", overcast: "Overcast" };
  const statusLabels = { submitting: "Submitting", queued: "Queued", running: "Rendering", succeeded: "Ready", failed: "Failed", unknown: "Unconfirmed" };
  const activeStatuses = new Set(["submitting", "queued", "running"]);
  const pendingKey = "takelab-pending-submission";
  const state = { takes: [], status: null, activeId: null, compareIds: [], mode: "single", screenKey: "single:empty:empty", sending: false, pending: null, pollTimer: null, refreshing: false, videos: [], comparing: false };
  const rows = new Map();
  let comparisonFrame = null;
  let comparisonAttempt = 0;

  function setText(element, value) {
    const next = String(value ?? "");
    if (element.textContent !== next) element.textContent = next;
  }

  function announce(message) { setText($("announcement"), message); }

  function showMessage(message, kind = "info") {
    $("form-message").hidden = !message;
    $("form-message").dataset.kind = kind;
    setText($("form-message"), message);
  }

  function savePending(pending) {
    state.pending = pending;
    try {
      if (pending) sessionStorage.setItem(pendingKey, JSON.stringify(pending));
      else sessionStorage.removeItem(pendingKey);
    } catch {}
    $("recovery").hidden = !pending || state.sending;
  }

  try {
    const saved = JSON.parse(sessionStorage.getItem(pendingKey) || "null");
    if (saved && typeof saved.request_id === "string" && saved.title && typeof saved.scene === "string") state.pending = saved;
  } catch {}

  function randomSeed() { return crypto.getRandomValues(new Uint32Array(1))[0]; }
  function takeById(id) { return state.takes.find((take) => take.id === id); }
  function mediaPath(take, kind) { return `/api/takes/${encodeURIComponent(take.id)}/${kind}`; }
  function timeLabel(seconds) {
    const value = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
    return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
  }
  function elapsedLabel(seconds) {
    if (!Number.isFinite(seconds)) return "";
    return seconds < 60 ? `${Math.round(seconds)}s render` : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s render`;
  }

  function updateAvailability() {
    const status = state.status;
    const active = state.takes.some((take) => activeStatuses.has(take.status));
    const busy = Boolean(status?.busy || active);
    $("generate").disabled = state.sending || Boolean(state.pending) || !status?.ready || busy;
    $("check-submission").disabled = state.sending;
    $("recovery").hidden = !state.pending || state.sending;
    setText($("generate-label"), state.sending ? "Sending your direction…" : busy ? "A take is in progress" : "Generate a take");
    setText($("generate-hint"), state.pending ? "Resolve the unconfirmed submission before making another take." : !status ? "Waiting for your local studio connection." : !status.ready ? status.message || "Your local studio is not ready." : busy ? "Your local render queue is working. This page will update automatically." : "5-second video with audio · runs on your machine");
  }

  function updateStatus(status) {
    state.status = status;
    $("connection").dataset.state = !status.ready ? "offline" : status.busy ? "busy" : "ready";
    setText($("connection-label"), !status.ready ? "Studio needs attention" : status.busy ? "Local studio · rendering" : "Local studio · ready");
    $("connection").title = status.message || "";
    setText($("format-label"), `${status.model || "LTX-2.5"} · ${status.width || 864} × ${status.height || 480} · ${status.fps || 24} fps`);
    updateAvailability();
  }

  function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function renderHistory() {
    const valid = new Set(state.takes.map((take) => take.id));
    for (const [id, row] of rows) {
      if (!valid.has(id)) { row.element.remove(); rows.delete(id); }
    }
    const list = $("take-list");
    state.takes.forEach((take, index) => {
      let row = rows.get(take.id);
      if (!row) {
        const element = createElement("article", "take-row");
        const number = createElement("span", "take-row-number");
        const open = createElement("button", "take-row-open");
        open.type = "button";
        const title = createElement("span", "take-row-title");
        const info = createElement("span", "take-row-info");
        const status = createElement("span", "take-row-status");
        const detail = createElement("span");
        info.append(status, detail);
        open.append(title, info);
        open.addEventListener("click", () => selectTake(take.id));
        const label = createElement("label", "compare-check");
        const check = document.createElement("input");
        check.type = "checkbox";
        check.addEventListener("change", () => toggleCompare(take.id, check.checked));
        label.append(check, document.createTextNode("Compare"));
        element.append(number, open, label);
        row = { element, number, title, status, detail, check, open };
        rows.set(take.id, row);
      }
      setText(row.number, String(state.takes.length - index).padStart(2, "0"));
      setText(row.title, take.title);
      setText(row.status, statusLabels[take.status] || take.status);
      row.status.dataset.status = take.status;
      setText(row.detail, `${cameraLabels[take.camera] || take.camera} · ${lightingLabels[take.lighting] || take.lighting}`);
      row.open.setAttribute("aria-label", `View ${take.title}, ${statusLabels[take.status] || take.status}`);
      row.element.dataset.active = String(state.activeId === take.id);
      row.check.checked = state.compareIds.includes(take.id);
      row.check.disabled = take.status !== "succeeded" || (!row.check.checked && state.compareIds.length >= 2);
      row.check.setAttribute("aria-label", `Compare ${take.title}`);
      row.check.title = take.status !== "succeeded" ? "Available when this take finishes" : !row.check.checked && state.compareIds.length >= 2 ? "Deselect a take to choose another" : "Select for comparison";
      // Leave existing rows in place during polling so keyboard focus is preserved.
      if (list.children[index] !== row.element) list.insertBefore(row.element, list.children[index] || null);
    });
    setText($("take-count"), String(state.takes.length).padStart(2, "0"));
    $("history-message").hidden = state.takes.length > 0;
    if (!state.takes.length) setText($("history-message"), "No takes yet. Load the starter scene, add your direction, and make the first one.");
    setText($("compare-count"), `${state.compareIds.length}/2`);
  }

  function selectTake(id) {
    state.activeId = id;
    state.mode = "single";
    renderHistory();
    renderScreen();
  }

  function toggleCompare(id, checked) {
    if (checked && state.compareIds.length < 2) state.compareIds.push(id);
    else if (!checked) state.compareIds = state.compareIds.filter((value) => value !== id);
    renderHistory();
    if (state.compareIds.length === 2 && checked) state.mode = "compare";
    renderScreen();
    announce(`${state.compareIds.length} of 2 takes selected for comparison.`);
  }

  function makeVideo(take, controls) {
    const video = document.createElement("video");
    video.controls = controls;
    video.playsInline = true;
    video.preload = "metadata";
    video.src = mediaPath(take, "video");
    video.setAttribute("aria-label", take.title);
    video.addEventListener("error", () => {
      $("playback-message").hidden = false;
      setText($("playback-message"), controls ? "The video could not be played. Try the video download below or refresh your local studio connection." : "A video could not be played. Open that take from Your takes to download it, or refresh your local studio connection.");
      if (!controls) pauseComparison();
    });
    return video;
  }

  function emptyScreen(overline, title, note, rendering = false) {
    const container = createElement("div", "screen-status");
    if (rendering) container.append(createElement("span", "render-indicator"));
    container.append(createElement("span", "screen-overline", overline), createElement("p", "screen-empty-title", title), createElement("p", "screen-empty-note", note));
    return container;
  }

  function renderScreen() {
    $("single-view").setAttribute("aria-pressed", String(state.mode === "single"));
    $("compare-view").setAttribute("aria-pressed", String(state.mode === "compare"));
    const selected = takeById(state.activeId);
    const compared = state.compareIds.map(takeById).filter(Boolean);
    const key = state.mode === "single" ? `single:${selected?.id || "empty"}:${selected?.status || "empty"}` : `compare:${compared.map((take) => `${take.id}:${take.status}`).join(":")}`;
    if (key !== state.screenKey) {
      pauseComparison();
      state.videos.forEach((video) => video.pause());
      state.videos = [];
      $("playback-message").hidden = true;
      state.screenKey = key;
      const screen = $("screen");
      if (state.mode === "compare") {
        const grid = createElement("div", "compare-screen");
        for (let index = 0; index < 2; index += 1) {
          const take = compared[index];
          const pane = createElement("div", "compare-pane");
          const label = createElement("div", "compare-pane-label");
          label.append(createElement("span", "compare-pane-letter", index ? "B" : "A"), createElement("span", "compare-pane-title", take?.title || "Choose a take"));
          pane.append(label);
          if (take?.status === "succeeded") {
            const video = makeVideo(take, false);
            video.addEventListener("loadedmetadata", updateComparisonTime);
            video.addEventListener("ended", pauseComparison);
            pane.append(video);
            state.videos.push(video);
          } else pane.append(createElement("p", "compare-pane-placeholder", "Select a finished take in Your takes below."));
          grid.append(pane);
        }
        screen.replaceChildren(grid);
        setComparisonAudio();
        updateComparisonTime();
      } else if (selected?.status === "succeeded") {
        const video = makeVideo(selected, true);
        state.videos = [video];
        screen.replaceChildren(video);
      } else if (selected) {
        const statusCopy = {
          submitting: ["Sending your scene", "Your direction is being handed to the local studio."],
          queued: ["Your moment is in line.", "The render is queued. You can leave this page open; it will update automatically."],
          running: ["A scene is taking shape.", "Your local studio is rendering video and audio. Good takes take a little time."],
          failed: ["This take didn't finish.", "Read the error below. Your direction and workflow are saved."],
          unknown: ["Let's check this take.", "The render could not be confirmed. Check the local queue before submitting this direction again."]
        };
        const copy = statusCopy[selected.status] || ["Waiting for an update", "Your saved take will update when the local studio responds."];
        screen.replaceChildren(emptyScreen(statusLabels[selected.status] || selected.status, copy[0], copy[1], activeStatuses.has(selected.status)));
      } else {
        screen.replaceChildren(emptyScreen("Your screening room", "Every good film starts with a take.", "Describe a scene or load the starter. Your first render will play here."));
      }
    }
    $("compare-controls").hidden = state.mode !== "compare" || state.videos.length !== 2;
    $("take-details").hidden = !selected || state.mode === "compare";
    setText($("screen-caption"), state.mode === "compare" ? "Two directions. One moment. Playback stays together." : selected ? `${statusLabels[selected.status] || selected.status}${elapsedLabel(selected.elapsed_seconds) ? ` · ${elapsedLabel(selected.elapsed_seconds)}` : ""}` : "A space for your next idea.");
    if (selected && state.mode === "single") renderTakeDetails(selected);
  }

  function renderTakeDetails(take) {
    setText($("selected-title"), take.title);
    setText($("selected-scene"), take.scene);
    const metadata = [cameraLabels[take.camera] || take.camera, lightingLabels[take.lighting] || take.lighting, `Seed ${take.seed}`];
    if (take.sound) metadata.push(`Sound: ${take.sound}`);
    const meta = $("selected-meta");
    const metaKey = JSON.stringify(metadata);
    if (meta.dataset.value !== metaKey) {
      meta.replaceChildren(...metadata.map((value) => createElement("span", "", value)));
      meta.dataset.value = metaKey;
    }
    $("selected-error").hidden = !take.error;
    setText($("selected-error"), take.error || "");
    const links = $("download-links");
    const linksKey = `${take.id}:${take.status}`;
    if (links.dataset.value !== linksKey) {
      const exports = take.status === "succeeded" ? [["video", "Download video"], ["bundle", "Keep the whole take"], ["workflow", "Exact workflow"]] : [["workflow", "Exact workflow"]];
      links.replaceChildren(...exports.map(([kind, label]) => {
        const anchor = createElement("a", "download-link", label);
        anchor.href = mediaPath(take, kind);
        anchor.download = "";
        return anchor;
      }));
      links.dataset.value = linksKey;
    }
  }

  function comparisonDuration() {
    const durations = state.videos.map((video) => video.duration).filter((duration) => Number.isFinite(duration) && duration > 0);
    return durations.length ? Math.min(...durations) : 5;
  }

  function updateComparisonTime() {
    const duration = comparisonDuration();
    const current = state.videos[0]?.currentTime || 0;
    $("compare-seek").max = String(duration);
    if (document.activeElement !== $("compare-seek")) $("compare-seek").value = String(current);
    setText($("compare-time"), `${timeLabel(current)} / ${timeLabel(duration)}`);
  }

  function setComparisonAudio() {
    state.videos.forEach((video, index) => { video.muted = $("compare-audio").value !== (index === 0 ? "a" : "b"); });
  }

  function pauseComparison() {
    comparisonAttempt += 1;
    state.comparing = false;
    if (comparisonFrame !== null) cancelAnimationFrame(comparisonFrame);
    comparisonFrame = null;
    if (state.mode === "compare") state.videos.forEach((video) => video.pause());
    setText($("compare-play"), "Play both");
  }

  function synchronizeComparison() {
    if (!state.comparing || state.videos.length !== 2) return;
    const [first, second] = state.videos;
    if (first.currentTime >= comparisonDuration() - 0.035) { pauseComparison(); updateComparisonTime(); return; }
    if (Math.abs(first.currentTime - second.currentTime) > 0.12) second.currentTime = first.currentTime;
    updateComparisonTime();
    comparisonFrame = requestAnimationFrame(synchronizeComparison);
  }

  async function playComparison() {
    if (state.comparing) { pauseComparison(); return; }
    if (state.videos.length !== 2) return;
    const attempt = ++comparisonAttempt;
    const currentVideos = [...state.videos];
    const duration = comparisonDuration();
    const start = currentVideos[0].currentTime >= duration - 0.1 ? 0 : currentVideos[0].currentTime;
    currentVideos.forEach((video) => { video.currentTime = start; });
    setComparisonAudio();
    state.comparing = true;
    setText($("compare-play"), "Pause both");
    try {
      await Promise.all(currentVideos.map((video) => video.play()));
      if (attempt !== comparisonAttempt) return;
      if (!state.comparing || currentVideos[0] !== state.videos[0]) { currentVideos.forEach((video) => video.pause()); return; }
      $("playback-message").hidden = true;
      synchronizeComparison();
    } catch {
      if (attempt !== comparisonAttempt) return;
      currentVideos.forEach((video) => video.pause());
      pauseComparison();
      $("playback-message").hidden = false;
      setText($("playback-message"), "Both videos must load before playback. Try Play both again when they are ready.");
    }
  }

  async function requestJson(url, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal, cache: "no-store" });
      let body;
      try { body = await response.json(); } catch { throw new Error("The studio returned an unreadable response."); }
      if (!response.ok) {
        const error = new Error(body.error || `The studio returned an error (${response.status}).`);
        error.confirmedRejection = response.status >= 400 && response.status < 500;
        throw error;
      }
      return body;
    } finally { clearTimeout(timeout); }
  }

  async function refresh() {
    if (state.refreshing) return;
    state.refreshing = true;
    const results = await Promise.allSettled([requestJson("/api/status"), requestJson("/api/takes")]);
    if (results[0].status === "fulfilled") updateStatus(results[0].value);
    else {
      state.status = null;
      $("connection").dataset.state = "offline";
      setText($("connection-label"), "Studio connection lost");
      $("connection").title = "Waiting to reconnect to your local studio.";
    }
    if (results[1].status === "fulfilled" && Array.isArray(results[1].value.takes)) {
      const previous = new Map(state.takes.map((take) => [take.id, take.status]));
      state.takes = results[1].value.takes;
      if (state.pending) {
        const confirmed = takeById(state.pending.request_id);
        if (confirmed) {
          savePending(null);
          state.activeId = confirmed.id;
          showMessage(`“${confirmed.title}” is in your take history.`);
        }
      }
      if (!takeById(state.activeId)) state.activeId = state.takes[0]?.id || null;
      state.compareIds = state.compareIds.filter((id) => takeById(id)?.status === "succeeded");
      for (const take of state.takes) {
        if (previous.has(take.id) && previous.get(take.id) !== take.status) announce(`${take.title}: ${statusLabels[take.status] || take.status}.`);
      }
      renderHistory();
      renderScreen();
    } else {
      $("history-message").hidden = false;
      setText($("history-message"), "Take history could not be refreshed. Saved takes will appear when the studio reconnects.");
    }
    updateAvailability();
    state.refreshing = false;
  }

  async function poll() {
    clearTimeout(state.pollTimer);
    if (!document.hidden) await refresh();
    state.pollTimer = setTimeout(poll, 3000);
  }

  function reuseDirection(take) {
    $("title").value = take.title;
    $("scene").value = take.scene;
    const camera = form.querySelector(`input[name="camera"][value="${Object.hasOwn(cameraLabels, take.camera) ? take.camera : "locked"}"]`);
    camera.checked = true;
    $("lighting").value = take.lighting;
    $("sound").value = take.sound || "";
    $("seed").value = String(take.seed);
    showMessage("Direction loaded. Make your changes, then generate a new take.");
    $("scene").focus();
  }

  async function submitTake(payload) {
    if (state.sending) return;
    state.sending = true;
    savePending(payload);
    showMessage("Sending your direction to the local studio…");
    updateAvailability();
    try {
      const result = await requestJson("/api/takes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!result.take || result.take.id !== payload.request_id) throw new Error("The studio did not confirm this submission.");
      savePending(null);
      state.takes = [result.take, ...state.takes.filter((take) => take.id !== result.take.id)];
      state.activeId = result.take.id;
      state.mode = "single";
      renderHistory();
      renderScreen();
      showMessage(`“${result.take.title}” is saved. Follow its progress in the screening room.`);
      announce("Take submitted. Rendering progress appears in the screening room.");
    } catch (error) {
      if (error.confirmedRejection) {
        savePending(null);
        showMessage(error.message, "error");
      } else {
        showMessage("Submission unconfirmed. TakeLab will not automatically send it again.", "error");
        announce("Submission unconfirmed. Check the same submission before generating another take.");
      }
    } finally {
      state.sending = false;
      updateAvailability();
      await refresh();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (state.sending || state.pending || $("generate").disabled || !form.reportValidity()) return;
    const data = new FormData(form);
    const payload = { request_id: crypto.randomUUID(), title: String(data.get("title")).trim(), scene: String(data.get("scene")).trim(), camera: String(data.get("camera")), lighting: String(data.get("lighting")), sound: String(data.get("sound")).trim(), seed: Number(data.get("seed")) };
    if (!payload.title || !payload.scene) { showMessage("Add a take name and a scene before generating.", "error"); return; }
    if (!Number.isInteger(payload.seed) || payload.seed < 0 || payload.seed > 4294967295) { showMessage("Choose a whole-number seed between 0 and 4294967295.", "error"); return; }
    submitTake(payload);
  });

  $("load-starter").addEventListener("click", () => {
    reuseDirection({ title: "Rain at the diner", scene: "A small roadside diner at night, seen through a rain-streaked window. A red neon sign reflects in the wet pavement. Inside, steam rises slowly from a white coffee cup beside the window. A passing car sends a soft sweep of light across the glass. Cinematic realism, subtle movement, no cuts.", camera: "push", lighting: "night", sound: "Steady soft rainfall, a distant passing car, the quiet hum of a diner. No music or speech.", seed: randomSeed() });
    showMessage("Starter scene loaded. Give it your own direction, or generate it as it is.");
  });
  $("randomize-seed").addEventListener("click", () => { $("seed").value = String(randomSeed()); announce("New random seed selected."); });
  $("reuse-selected").addEventListener("click", () => { const take = takeById(state.activeId); if (take) reuseDirection(take); });
  $("single-view").addEventListener("click", () => { state.mode = "single"; renderScreen(); });
  $("compare-view").addEventListener("click", () => { state.mode = "compare"; renderScreen(); });
  $("refresh-takes").addEventListener("click", async () => {
    $("refresh-takes").disabled = true;
    try { await refresh(); } finally { $("refresh-takes").disabled = false; }
  });
  $("check-submission").addEventListener("click", async () => {
    await refresh();
    // Reuse the exact UUID and body only after this explicit action. Never auto-retry a POST.
    if (state.pending && !state.sending) await submitTake(state.pending);
  });
  $("compare-play").addEventListener("click", playComparison);
  $("compare-rewind").addEventListener("click", () => { state.videos.forEach((video) => { video.currentTime = 0; }); updateComparisonTime(); });
  $("compare-audio").addEventListener("change", setComparisonAudio);
  $("compare-seek").addEventListener("input", () => { const time = Number($("compare-seek").value); state.videos.forEach((video) => { video.currentTime = time; }); updateComparisonTime(); });
  document.addEventListener("visibilitychange", () => {
    clearTimeout(state.pollTimer);
    if (document.hidden) pauseComparison();
    else poll();
  });
  $("seed").value = String(randomSeed());
  if (state.pending) showMessage("An earlier submission is unconfirmed. Check it before generating another take.", "error");
  updateAvailability();
  poll();
})();
