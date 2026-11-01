const app = document.getElementById("app");

async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data.detail || data.message || res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function imgSrc(path) {
  return path ? `/catalog/${path}` : "";
}

function choreMedia(c) {
  if (c.demo_video) {
    const poster = c.cover_image ? ` poster="${imgSrc(c.cover_image)}"` : "";
    return `<video class="cover" src="${imgSrc(c.demo_video)}"${poster} controls playsinline></video>`;
  }
  if (c.cover_image) {
    return `<img class="cover" src="${imgSrc(c.cover_image)}" alt="">`;
  }
  return "";
}

function render(node) {
  app.replaceChildren(node);
}

async function boot() {
  const session = await api("/api/session");
  if (session.role === "child") {
    await showHome();
    return;
  }
  await showPicker();
}

async function showPicker() {
  const kids = await api("/api/children");
  const root = document.createElement("div");
  root.append(el(`<div class="top"><div class="brand">Chore Helper</div></div>`));
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `<h1>Who are you?</h1>`;
  if (!kids.length) {
    card.innerHTML += `<p class="muted">Ask a grown-up to add you on the parent page.</p>
      <p><a href="/parent">Parent login</a></p>`;
  }
  kids.forEach((k) => {
    const b = document.createElement("button");
    b.className = "name-btn";
    b.style.marginBottom = "12px";
    b.textContent = k.display_name;
    b.onclick = () => showPin(k);
    card.append(b);
  });
  root.append(card);
  render(root);
}

function showPin(kid) {
  let pin = "";
  const root = document.createElement("div");
  root.innerHTML = `
    <div class="top"><div class="brand">Chore Helper</div></div>
    <div class="card">
      <h1>Hi ${escapeHtml(kid.display_name)}</h1>
      <p class="muted">Type your PIN</p>
      <div class="pin-dots" id="dots"></div>
      <div class="error" id="err"></div>
      <div class="pin-pad" id="pad"></div>
      <button class="secondary" id="back">Back</button>
    </div>`;
  const dots = root.querySelector("#dots");
  const err = root.querySelector("#err");
  const keys = ["1","2","3","4","5","6","7","8","9","OK","0","⌫"];
  async function submit() {
    if (pin.length < 4) {
      err.textContent = "PIN is at least 4 digits";
      return;
    }
    try {
      await api("/api/kids/login", { method: "POST", body: JSON.stringify({ child_id: kid.id, pin }) });
      await showHome();
    } catch (e) {
      err.textContent = e.message;
      pin = "";
      dots.textContent = "";
    }
  }
  keys.forEach((k) => {
    const b = document.createElement("button");
    b.textContent = k;
    b.onclick = async () => {
      err.textContent = "";
      if (k === "⌫") pin = pin.slice(0, -1);
      else if (k === "OK") { await submit(); return; }
      else if (pin.length < 8) pin += k;
      dots.textContent = "•".repeat(pin.length);
    };
    root.querySelector("#pad").append(b);
  });
  root.querySelector("#back").onclick = showPicker;
  render(root);
}

async function showHome() {
  const state = await api("/api/kid/state");
  if (state.current) {
    showWalkthrough(state);
    return;
  }
  const root = document.createElement("div");
  root.append(kidTop(state.child, "chores"));
  (state.pending || []).forEach((asg) => {
    const banner = document.createElement("div");
    banner.className = "banner waiting";
    const title = asg.chore ? asg.chore.title : "that chore";
    banner.innerHTML = `<strong>Waiting for a grown-up</strong> to check ${escapeHtml(title)}.`;
    const cancel = document.createElement("button");
    cancel.className = "secondary";
    cancel.style.marginTop = "10px";
    cancel.textContent = "Pick a different chore";
    cancel.onclick = () => cancelChore(asg.id);
    banner.append(cancel);
    root.append(banner);
  });
  const dailySec = document.createElement("section");
  dailySec.className = "section";
  dailySec.append(el(`<h2>Today's chore</h2>
    <p class="muted">Pick one regular chore for today.</p>`));
  if (state.daily.assignment) {
    const a = state.daily.assignment;
    const title = a.chore ? a.chore.title : a.chore_id;
    let status = "in progress";
    if (a.state === "pending_approval") status = "waiting for a grown-up";
    if (a.state === "approved") status = "done";
    dailySec.append(el(`<div class="card"><h3>${escapeHtml(title)}</h3>
      <p class="muted">${escapeHtml(status)}</p></div>`));
  } else if (state.daily.pickable.length) {
    dailySec.append(choreGrid(state.daily.pickable, pick));
  } else {
    dailySec.append(el(`<div class="card"><p>No regular chores for you today.</p></div>`));
  }
  root.append(dailySec);

  const extraSec = document.createElement("section");
  extraSec.className = "section";
  extraSec.append(el(`<h2>Optional chores</h2>
    <p class="muted">Extra Stars after today's chore is finished.</p>`));
  const extraList = state.extra.listed || state.extra.pickable || [];
  if (!extraList.length) {
    extraSec.append(el(`<div class="card"><p>No optional chores for you today.</p></div>`));
  } else if (!state.extra.unlocked) {
    extraSec.append(choreGrid(extraList, null, true));
  } else {
    const pickable = state.extra.pickable || [];
    const shown = [...pickable];
    extraList.forEach((c) => {
      if (c.taken_by && !shown.some((s) => s.id === c.id)) shown.push(c);
    });
    if (!shown.length) {
      extraSec.append(el(`<div class="card"><p>You already picked the optional chores for today.</p></div>`));
    } else {
      extraSec.append(choreGrid(shown, pick));
    }
  }
  root.append(extraSec);
  const logout = document.createElement("p");
  logout.style.marginTop = "24px";
  const b = document.createElement("button");
  b.className = "secondary";
  b.textContent = "Switch kid";
  b.onclick = async () => { await api("/api/logout", { method: "POST" }); showPicker(); };
  logout.append(b);
  root.append(logout);
  render(root);
}

function kidTop(child, page) {
  const wrap = document.createElement("div");
  wrap.className = "top";
  const avail = child.available ?? child.stars;
  wrap.innerHTML = `
    <div class="brand">Hi ${escapeHtml(child.display_name)}</div>
    <div class="top-actions">
      <button class="secondary" data-go="chores">Chores</button>
      <button class="secondary" data-go="rewards">Rewards</button>
      <button class="secondary" data-go="history">History</button>
      <div class="stars">★ ${avail}</div>
    </div>`;
  wrap.querySelectorAll("button").forEach((b) => {
    if (b.dataset.go === page) b.setAttribute("aria-current", "true");
    b.onclick = () => {
      if (b.dataset.go === "rewards") showShop();
      else if (b.dataset.go === "history") showHistory();
      else showHome();
    };
  });
  return wrap;
}

async function showHistory() {
  const [state, data] = await Promise.all([
    api("/api/kid/state"),
    api("/api/kid/history"),
  ]);
  const root = document.createElement("div");
  root.append(kidTop(state.child, "history"));
  renderHistory(root, data, {
    heading: "Your history",
    blurb: "See the Stars you earned, the rewards you cashed in, and your chores.",
    kidVoice: true,
  });
  render(root);
}

async function showShop() {
  const shop = await api("/api/kid/rewards");
  const root = document.createElement("div");
  root.append(kidTop(shop.child, "rewards"));
  root.append(el(`<h2>Cash in Stars</h2>
    <p class="muted">Ask for a reward. A grown-up has to say yes. Stars come off when they approve.</p>`));
  if (shop.child.held) {
    root.append(el(`<div class="banner waiting">${shop.child.held} Stars are waiting on a grown-up for a reward.</div>`));
  }
  (shop.pending || []).forEach((row) => {
    const banner = document.createElement("div");
    banner.className = "banner waiting";
    const title = row.reward ? row.reward.title : row.reward_id;
    banner.innerHTML = `<strong>Waiting:</strong> ${escapeHtml(title)} · ★ ${row.stars}`;
    const cancel = document.createElement("button");
    cancel.className = "secondary";
    cancel.style.marginTop = "10px";
    cancel.textContent = "Cancel this reward";
    cancel.onclick = async () => {
      await api("/api/kid/redeem/cancel", {
        method: "POST",
        body: JSON.stringify({ redemption_id: row.id }),
      });
      await showShop();
    };
    banner.append(cancel);
    root.append(banner);
  });
  const grid = document.createElement("div");
  grid.className = "grid";
  const avail = shop.child.available ?? 0;
  shop.rewards.forEach((r) => {
    const can = avail >= r.stars;
    const btn = document.createElement("button");
    btn.className = "chore-card" + (can ? "" : " locked");
    btn.disabled = !can;
    const season = r.season ? ` · ${r.season}` : "";
    btn.innerHTML = `
      <div class="emoji">${escapeHtml(r.emoji || "★")}</div>
      <div class="meta">
        <h3>${escapeHtml(r.title)}</h3>
        <p class="muted">${escapeHtml(r.description || "")}</p>
        <p class="muted">★ ${r.stars}${season}</p>
      </div>`;
    if (can) {
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          await api("/api/kid/redeem", { method: "POST", body: JSON.stringify({ reward_id: r.id }) });
          await showShop();
        } catch (e) {
          alert(e.message);
          btn.disabled = false;
        }
      };
    }
    grid.append(btn);
  });
  root.append(grid);
  const hist = await api("/api/kid/history");
  const past = document.createElement("section");
  past.className = "section";
  past.innerHTML = `<h2>Rewards history</h2>`;
  const box = document.createElement("div");
  box.className = "card";
  fillRewardHistory(box, hist.rewards || []);
  past.append(box);
  root.append(past);
  render(root);
}

function choreGrid(chores, onPick, locked) {
  const wrap = document.createElement("div");
  wrap.className = "grid";
  chores.forEach((c) => {
    const taken = c.taken_by;
    const cardLocked = Boolean(locked) || Boolean(taken);
    const btn = document.createElement("button");
    btn.className = "chore-card" + (cardLocked ? " locked" : "");
    btn.disabled = cardLocked;
    let note = "";
    if (taken) note = ` · ${escapeHtml(taken)} already picked this`;
    else if (locked) note = " · finish today's chore first";
    btn.innerHTML = `
      ${c.cover_image ? `<img src="${imgSrc(c.cover_image)}" alt="">` : (c.demo_video ? `<video src="${imgSrc(c.demo_video)}" muted playsinline></video>` : "")}
      <div class="meta">
        <h3>${escapeHtml(c.title)}</h3>
        <p class="muted">${c.minutes} min · ★ ${c.stars}${note}</p>
      </div>`;
    if (!cardLocked && onPick) btn.onclick = () => onPick(c.id);
    wrap.append(btn);
  });
  return wrap;
}

async function pick(choreId) {
  await api("/api/kid/pick", { method: "POST", body: JSON.stringify({ chore_id: choreId }) });
  await showHome();
}

async function cancelChore(assignmentId) {
  await api("/api/kid/cancel", { method: "POST", body: JSON.stringify({ assignment_id: assignmentId }) });
  await showHome();
}

function showWalkthrough(state) {
  const asg = state.current;
  const c = asg.chore;
  const root = document.createElement("div");
  root.append(kidTop(state.child, "chores"));
  root.append(el(`<h2>${escapeHtml(c.title)}</h2>`));
  if (asg.state === "returned") {
    root.append(el(`<div class="banner back"><strong>Please try again.</strong> ${escapeHtml(asg.return_note || "")}</div>`));
  }
  if (c.grown_up_required) {
    root.append(el(`<div class="banner grownup"><strong>Ask a grown-up</strong> before you start this one.</div>`));
  }
  const card = document.createElement("div");
  card.className = "card";
  const media = choreMedia(c);
  if (media) card.append(el(media));
  if (c.materials && c.materials.length) {
    card.append(el(`<p><strong>Get:</strong> ${escapeHtml(c.materials.join(", "))}</p>`));
  }
  c.steps.forEach((step, i) => {
    const row = document.createElement("label");
    row.className = "step";
    row.innerHTML = `<input type="checkbox"> <span><strong>${i + 1}.</strong> ${escapeHtml(step.text)}${step.tip ? `<div class="muted">${escapeHtml(step.tip)}</div>` : ""}</span>`;
    card.append(row);
  });
  if (c.done_when && c.done_when.length) {
    card.append(el(`<p><strong>Done when:</strong> ${escapeHtml(c.done_when.join(" · "))}</p>`));
  }
  const row = document.createElement("div");
  row.className = "primary-row";
  const finish = document.createElement("button");
  finish.className = "good";
  finish.textContent = "I finished";
  finish.onclick = async () => {
    finish.disabled = true;
    try {
      await api("/api/kid/finish", { method: "POST", body: JSON.stringify({ assignment_id: asg.id }) });
      await showHome();
    } catch (e) {
      finish.disabled = false;
      alert(e.message);
    }
  };
  const cancel = document.createElement("button");
  cancel.className = "secondary";
  cancel.textContent = "Pick a different chore";
  cancel.onclick = () => cancelChore(asg.id);
  row.append(finish, cancel);
  card.append(row);
  root.append(card);
  render(root);
}

boot().catch((e) => {
  app.innerHTML = `<div class="card error">${escapeHtml(e.message)}</div>`;
});
