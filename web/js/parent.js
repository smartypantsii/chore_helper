const app = document.getElementById("app");

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (!(opts.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, {
    credentials: "include",
    ...opts,
    headers,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data.detail || res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function mediaSrc(path) {
  return path ? `/catalog/${path}` : "";
}

async function uploadChoreFile(choreId, kind, file) {
  const body = new FormData();
  body.append("kind", kind);
  body.append("file", file);
  return api(`/api/parent/chores/${choreId}/media`, { method: "POST", body });
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

let tab = "inbox";
let historyChildId = null;
let assignChildId = null;

async function boot() {
  const session = await api("/api/session");
  if (session.role !== "parent") {
    showLogin();
    return;
  }
  await showApp();
}

function showLogin() {
  app.innerHTML = `
    <div class="brand" style="margin-bottom:16px">Chore Helper</div>
    <div class="card" style="max-width:420px">
      <h1>Parent login</h1>
      <form id="login-form">
        <div class="form-row">
          <input id="user" name="username" placeholder="username" value="parent" autocomplete="username">
          <input id="pass" name="password" type="password" placeholder="password" autocomplete="current-password">
        </div>
        <div class="error" id="err"></div>
        <button type="submit" id="go">Log in</button>
      </form>
      <p class="muted">Kids go to the <a href="/">home page</a>.</p>
    </div>`;
  const pass = app.querySelector("#pass");
  pass.focus();
  app.querySelector("#login-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const err = app.querySelector("#err");
    err.textContent = "";
    try {
      await api("/api/parent/login", {
        method: "POST",
        body: JSON.stringify({
          username: app.querySelector("#user").value,
          password: pass.value,
        }),
      });
      await showApp();
    } catch (e) {
      err.textContent = e.message;
      pass.focus();
      pass.select();
    }
  };
}

async function showApp() {
  app.innerHTML = `
    <div class="top">
      <div class="brand">Parent</div>
      <button class="secondary" id="logout">Log out</button>
    </div>
    <div class="tabs">
      <button data-tab="inbox">Inbox</button>
      <button data-tab="assign">Assign</button>
      <button data-tab="chores">Chores</button>
      <button data-tab="kids">Kids</button>
      <button data-tab="rewards">★ Rewards</button>
      <button data-tab="history">History</button>
    </div>
    <div id="main"></div>`;
  app.querySelector("#logout").onclick = async () => {
    await api("/api/logout", { method: "POST" });
    showLogin();
  };
  app.querySelectorAll(".tabs button").forEach((b) => {
    b.onclick = () => { tab = b.dataset.tab; paint(); };
  });
  await paint();
}

async function paint() {
  app.querySelectorAll(".tabs button").forEach((b) => {
    b.setAttribute("aria-current", b.dataset.tab === tab ? "true" : "false");
  });
  const main = app.querySelector("#main");
  main.textContent = "Loading…";
  if (tab === "inbox") await paintInbox(main);
  if (tab === "assign") await paintAssign(main);
  if (tab === "chores") await paintChores(main);
  if (tab === "kids") await paintKids(main);
  if (tab === "history") await paintHistory(main);
  if (tab === "rewards") await paintRewards(main);
}

async function paintInbox(main) {
  const [items, redemptions] = await Promise.all([
    api("/api/parent/inbox"),
    api("/api/parent/redemptions"),
  ]);
  if (!items.length && !redemptions.length) {
    main.innerHTML = `<div class="card"><p>Nothing waiting. Finished chores and reward cash-ins show up here.</p></div>`;
    return;
  }
  main.innerHTML = "";
  redemptions.forEach((item) => {
    const card = document.createElement("div");
    card.className = "card inbox-card";
    const kid = item.child ? item.child.display_name : "?";
    const title = item.reward ? item.reward.title : item.reward_id;
    card.innerHTML = `
      <h2>${escapeHtml(item.reward && item.reward.emoji ? item.reward.emoji + " " : "")}${escapeHtml(kid)} wants ${escapeHtml(title)}</h2>
      <p class="muted">Reward · ★ ${item.stars} (held until you approve)</p>
      ${item.reward && item.reward.parent_notes ? `<p>${escapeHtml(item.reward.parent_notes)}</p>` : ""}
      <div class="form-row"></div>`;
    const row = card.querySelector(".form-row");
    const ok = document.createElement("button");
    ok.className = "good";
    ok.textContent = "Give reward · spend Stars";
    ok.onclick = async () => {
      await api(`/api/parent/redemptions/${item.id}/approve`, { method: "POST" });
      await paint();
    };
    const note = document.createElement("input");
    note.placeholder = "Not this time (optional note)";
    const back = document.createElement("button");
    back.className = "warn";
    back.textContent = "Deny";
    back.onclick = async () => {
      await api(`/api/parent/redemptions/${item.id}/deny`, {
        method: "POST",
        body: JSON.stringify({ note: note.value }),
      });
      await paint();
    };
    row.append(ok, note, back);
    main.append(card);
  });
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "card inbox-card";
    const kid = item.child ? item.child.display_name : "?";
    card.innerHTML = `
      <h2>${escapeHtml(kid)} · ${escapeHtml(item.chore.title)}</h2>
      <p class="muted">${item.state} · ★ ${item.chore.stars} · ${escapeHtml(item.chore.category)}</p>
      ${item.chore.parent_notes ? `<p>${escapeHtml(item.chore.parent_notes)}</p>` : ""}
      ${item.return_note ? `<p>Last note: ${escapeHtml(item.return_note)}</p>` : ""}
      <div class="form-row"></div>`;
    const row = card.querySelector(".form-row");
    if (item.state === "pending_approval") {
      const ok = document.createElement("button");
      ok.className = "good";
      ok.textContent = "Approve ★";
      ok.onclick = async () => {
        await api(`/api/parent/assignments/${item.id}/approve`, { method: "POST" });
        await paint();
      };
      const note = document.createElement("input");
      note.placeholder = "Send back with a note";
      const back = document.createElement("button");
      back.className = "warn";
      back.textContent = "Send back";
      back.onclick = async () => {
        await api(`/api/parent/assignments/${item.id}/return`, {
          method: "POST",
          body: JSON.stringify({ note: note.value }),
        });
        await paint();
      };
      row.append(ok, note, back);
    } else {
      card.append(document.createRange().createContextualFragment(`<p class="muted">Waiting for ${escapeHtml(kid)} to try again.</p>`));
    }
    main.append(card);
  });
}

function stepsToText(steps) {
  return (steps || [])
    .map((s) => (s && s.tip ? `${s.text} | ${s.tip}` : (s && s.text) || s || ""))
    .filter(Boolean)
    .join("\n");
}

async function paintAssign(main) {
  const kids = await api("/api/parent/children");
  if (!kids.length) {
    main.innerHTML = `<div class="card"><p>Add a kid first, then choose which chores they see.</p></div>`;
    return;
  }
  if (!assignChildId || !kids.some((k) => k.id === assignChildId)) {
    assignChildId = kids[0].id;
  }
  const payload = await api(`/api/parent/children/${assignChildId}/chores`);
  const kid = kids.find((k) => k.id === assignChildId);
  main.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <h2>Chores for each child</h2>
      <p class="muted">Turn on the jobs this child can pick. Regular is today's one chore. Optional extras unlock after that. Raise Stars when a job is harder for a younger child.</p>
      <label>Child
        <select id="assign-kid"></select>
      </label>
    </div>
    <div class="card">
      <h2>${escapeHtml(kid.display_name)} · age ${kid.age}</h2>
      <div class="table-wrap">
        <table class="assign-table">
          <thead>
            <tr>
              <th>On</th>
              <th>Chore</th>
              <th>List</th>
              <th>Stars</th>
            </tr>
          </thead>
          <tbody id="assign-body"></tbody>
        </table>
      </div>
      <div class="form-row">
        <button id="assign-save">Save this child's list</button>
      </div>
      <div class="error" id="assign-err"></div>
    </div>`;
  const sel = main.querySelector("#assign-kid");
  kids.forEach((k) => {
    const opt = document.createElement("option");
    opt.value = String(k.id);
    opt.textContent = `${k.display_name} · age ${k.age}`;
    if (k.id === assignChildId) opt.selected = true;
    sel.append(opt);
  });
  sel.onchange = () => { assignChildId = Number(sel.value); paint(); };
  const body = main.querySelector("#assign-body");
  payload.items.forEach((item) => {
    const c = item.chore;
    const tr = document.createElement("tr");
    tr.className = "assign-row" + (item.assigned ? "" : " off");
    tr.dataset.id = c.id;
    const young = c.min_age > kid.age;
    tr.innerHTML = `
      <td><input type="checkbox" class="a-on" ${item.assigned ? "checked" : ""}></td>
      <td>
        <strong>${escapeHtml(c.title)}</strong>
        <div class="muted">default ★ ${c.default_stars} · ${c.minutes} min · age ${c.min_age}+${young ? " · younger than default" : ""}</div>
      </td>
      <td>
        <select class="a-kind">
          <option value="daily" ${item.kind === "daily" ? "selected" : ""}>Regular</option>
          <option value="extra" ${item.kind === "extra" ? "selected" : ""}>Optional</option>
        </select>
      </td>
      <td><input class="a-stars" type="number" min="1" max="999" value="${item.stars}"></td>`;
    const sync = () => { tr.classList.toggle("off", !tr.querySelector(".a-on").checked); };
    tr.querySelector(".a-on").onchange = sync;
    body.append(tr);
  });
  main.querySelector("#assign-save").onclick = async () => {
    const err = main.querySelector("#assign-err");
    err.textContent = "";
    const items = [...main.querySelectorAll(".assign-row")].map((row) => ({
      chore_id: row.dataset.id,
      kind: row.querySelector(".a-kind").value,
      stars: Number(row.querySelector(".a-stars").value),
      enabled: row.querySelector(".a-on").checked,
    }));
    try {
      await api(`/api/parent/children/${assignChildId}/chores`, {
        method: "PUT",
        body: JSON.stringify({ items }),
      });
      err.textContent = "Saved";
      err.classList.remove("error");
      err.className = "muted";
    } catch (e) {
      err.className = "error";
      err.textContent = e.message;
    }
  };
}

async function paintChores(main) {
  const chores = await api("/api/parent/chores");
  main.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <h2>Add a chore</h2>
      <p class="muted">Default Stars and Regular/Optional apply when you first assign the job. Change Stars per child on the Assign tab.</p>
      <div class="form-row">
        <input id="c-title" placeholder="Title">
        <input id="c-stars" type="number" min="1" max="999" placeholder="Stars" style="width:90px">
        <select id="c-kind" style="width:140px">
          <option value="daily">Regular</option>
          <option value="extra">Optional</option>
        </select>
        <input id="c-age" type="number" min="3" max="18" placeholder="Min age" style="width:90px" value="4">
        <input id="c-min" type="number" min="1" max="120" placeholder="Minutes" style="width:90px" value="5">
      </div>
      <div class="form-row">
        <input id="c-cat" placeholder="Category (bedroom, kitchen…)" style="min-width:180px">
        <input id="c-notes" placeholder="Parent notes" style="flex:1; min-width:200px">
      </div>
      <div class="form-row">
        <textarea id="c-steps" class="wide" placeholder="Steps, one per line. Optional tip after | like: Pull the sheet smooth. | Start at the pillows."></textarea>
      </div>
      <div class="form-row">
        <label>Picture <input id="c-cover" type="file" accept="image/jpeg,image/png,image/webp,image/gif"></label>
        <label>Video <input id="c-video" type="file" accept="video/mp4,video/webm"></label>
      </div>
      <div class="form-row">
        <label><input type="checkbox" id="c-grown"> Grown-up nearby</label>
        <button id="c-add">Add chore</button>
      </div>
      <div class="error" id="c-err"></div>
    </div>
    <div id="c-list"></div>`;
  main.querySelector("#c-add").onclick = async () => {
    const err = main.querySelector("#c-err");
    err.textContent = "";
    try {
      const created = await api("/api/parent/chores", {
        method: "POST",
        body: JSON.stringify({
          title: main.querySelector("#c-title").value,
          stars: Number(main.querySelector("#c-stars").value),
          kind: main.querySelector("#c-kind").value,
          min_age: Number(main.querySelector("#c-age").value || 4),
          minutes: Number(main.querySelector("#c-min").value || 5),
          category: main.querySelector("#c-cat").value || "living",
          parent_notes: main.querySelector("#c-notes").value || null,
          steps: main.querySelector("#c-steps").value,
          grown_up_required: main.querySelector("#c-grown").checked,
          enabled: true,
        }),
      });
      const cover = main.querySelector("#c-cover").files[0];
      const video = main.querySelector("#c-video").files[0];
      if (cover) await uploadChoreFile(created.id, "cover", cover);
      if (video) await uploadChoreFile(created.id, "video", video);
      await paint();
    } catch (e) {
      err.textContent = e.message;
    }
  };
  const list = main.querySelector("#c-list");
  chores.forEach((c) => {
    const card = document.createElement("div");
    card.className = "card inbox-card";
    card.innerHTML = `
      <h2><input class="r-title c-title" value="${escapeHtml(c.title)}"></h2>
      <p class="muted">${escapeHtml(c.source)} · ${c.id}</p>
      <div class="media-row">
        ${c.cover_image ? `<img class="media-preview" src="${mediaSrc(c.cover_image)}" alt="">` : `<span class="muted">No picture</span>`}
        ${c.demo_video ? `<video class="media-preview" src="${mediaSrc(c.demo_video)}" controls playsinline></video>` : ""}
      </div>
      <div class="form-row">
        <label>Picture <input type="file" class="c-cover" accept="image/jpeg,image/png,image/webp,image/gif"></label>
        <label>Video <input type="file" class="c-video" accept="video/mp4,video/webm"></label>
        ${c.cover_image && String(c.cover_image).startsWith("media/uploads/") ? `<button type="button" class="secondary c-clear-cover">Remove picture</button>` : ""}
        ${c.demo_video && String(c.demo_video).startsWith("media/uploads/") ? `<button type="button" class="secondary c-clear-video">Remove video</button>` : ""}
      </div>
      <div class="form-row">
        <label>Stars <input class="c-stars" type="number" min="1" max="999" value="${c.stars}" style="width:90px"></label>
        <label>List
          <select class="c-kind">
            <option value="daily" ${c.kind === "daily" ? "selected" : ""}>Regular</option>
            <option value="extra" ${c.kind === "extra" ? "selected" : ""}>Optional</option>
          </select>
        </label>
        <label>Min age <input class="c-age" type="number" min="3" max="18" value="${c.min_age}" style="width:90px"></label>
        <label>Minutes <input class="c-min" type="number" min="1" max="120" value="${c.minutes}" style="width:90px"></label>
        <label>Category <input class="c-cat" value="${escapeHtml(c.category || "")}" style="width:140px"></label>
      </div>
      <div class="form-row">
        <textarea class="wide c-steps">${escapeHtml(stepsToText(c.steps))}</textarea>
      </div>
      <div class="form-row">
        <input class="c-notes" value="${escapeHtml(c.parent_notes || "")}" placeholder="Parent notes" style="flex:1">
      </div>
      <div class="form-row">
        <label><input type="checkbox" class="c-grown" ${c.grown_up_required ? "checked" : ""}> Grown-up nearby</label>
        <label><input type="checkbox" class="c-on" ${c.enabled ? "checked" : ""}> Enabled</label>
        <button class="good c-save">Save</button>
        <button class="warn c-del">${c.source === "catalog" ? "Turn off" : "Delete"}</button>
      </div>
      <div class="error c-msg"></div>`;
    const msg = card.querySelector(".c-msg");
    card.querySelector(".c-save").onclick = async () => {
      msg.textContent = "";
      try {
        await api(`/api/parent/chores/${c.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            title: card.querySelector(".c-title").value,
            stars: Number(card.querySelector(".c-stars").value),
            kind: card.querySelector(".c-kind").value,
            min_age: Number(card.querySelector(".c-age").value),
            minutes: Number(card.querySelector(".c-min").value),
            category: card.querySelector(".c-cat").value,
            steps: card.querySelector(".c-steps").value,
            parent_notes: card.querySelector(".c-notes").value,
            grown_up_required: card.querySelector(".c-grown").checked,
            enabled: card.querySelector(".c-on").checked,
          }),
        });
        msg.textContent = "Saved";
        msg.className = "muted c-msg";
      } catch (e) {
        msg.className = "error c-msg";
        msg.textContent = e.message;
      }
    };
    card.querySelector(".c-cover").onchange = async (ev) => {
      const file = ev.target.files[0];
      if (!file) return;
      msg.textContent = "";
      try {
        await uploadChoreFile(c.id, "cover", file);
        await paint();
      } catch (e) {
        msg.className = "error c-msg";
        msg.textContent = e.message;
      }
    };
    card.querySelector(".c-video").onchange = async (ev) => {
      const file = ev.target.files[0];
      if (!file) return;
      msg.textContent = "";
      try {
        await uploadChoreFile(c.id, "video", file);
        await paint();
      } catch (e) {
        msg.className = "error c-msg";
        msg.textContent = e.message;
      }
    };
    const clearCover = card.querySelector(".c-clear-cover");
    if (clearCover) {
      clearCover.onclick = async () => {
        msg.textContent = "";
        try {
          await api(`/api/parent/chores/${c.id}/media/cover`, { method: "DELETE" });
          await paint();
        } catch (e) {
          msg.className = "error c-msg";
          msg.textContent = e.message;
        }
      };
    }
    const clearVideo = card.querySelector(".c-clear-video");
    if (clearVideo) {
      clearVideo.onclick = async () => {
        msg.textContent = "";
        try {
          await api(`/api/parent/chores/${c.id}/media/video`, { method: "DELETE" });
          await paint();
        } catch (e) {
          msg.className = "error c-msg";
          msg.textContent = e.message;
        }
      };
    }
    card.querySelector(".c-del").onclick = async () => {
      msg.textContent = "";
      try {
        await api(`/api/parent/chores/${c.id}`, { method: "DELETE" });
        await paint();
      } catch (e) {
        msg.className = "error c-msg";
        msg.textContent = e.message;
      }
    };
    list.append(card);
  });
}

async function paintKids(main) {
  const kids = await api("/api/parent/children");
  main.innerHTML = `<div class="card">
      <h2>Kids</h2>
      <div id="list"></div>
      <h3>Add a kid</h3>
      <div class="form-row">
        <input id="name" placeholder="Name">
        <input id="age" type="number" min="3" max="18" placeholder="Age" style="width:80px">
        <input id="pin" placeholder="PIN (4–8 digits)" inputmode="numeric">
        <button id="add">Add</button>
      </div>
      <div class="error" id="err"></div>
    </div>`;
  const list = main.querySelector("#list");
  kids.forEach((k) => {
    const row = document.createElement("div");
    row.className = "kid-row";
    const ready = k.available ?? k.stars;
    const held = k.held ? ` · ${k.held} waiting on a reward` : "";
    row.innerHTML = `<div><strong>${escapeHtml(k.display_name)}</strong> · age ${k.age}<div class="muted">★ ${ready} ready · ${k.stars} earned${held}</div></div>`;
    const pin = document.createElement("input");
    pin.placeholder = "new PIN";
    pin.style.width = "110px";
    const save = document.createElement("button");
    save.className = "secondary";
    save.textContent = "Set PIN";
    save.onclick = async () => {
      if (!pin.value) return;
      await api(`/api/parent/children/${k.id}`, {
        method: "PATCH",
        body: JSON.stringify({ pin: pin.value }),
      });
      pin.value = "";
      alert("PIN updated");
    };
    const hist = document.createElement("button");
    hist.className = "secondary";
    hist.textContent = "History";
    hist.onclick = () => { historyChildId = k.id; tab = "history"; paint(); };
    const assign = document.createElement("button");
    assign.className = "secondary";
    assign.textContent = "Assign chores";
    assign.onclick = () => { assignChildId = k.id; tab = "assign"; paint(); };
    row.append(pin, save, assign, hist);
    list.append(row);
  });
  main.querySelector("#add").onclick = async () => {
    const err = main.querySelector("#err");
    err.textContent = "";
    try {
      await api("/api/parent/children", {
        method: "POST",
        body: JSON.stringify({
          display_name: main.querySelector("#name").value,
          age: Number(main.querySelector("#age").value),
          pin: main.querySelector("#pin").value,
        }),
      });
      await paint();
    } catch (e) {
      err.textContent = e.message;
    }
  };
}

async function paintRewards(main) {
  const rewards = await api("/api/parent/rewards");
  main.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <h2>Add a reward</h2>
      <p class="muted">Kids see enabled rewards they are old enough for. Catalog rewards can be turned off, not deleted.</p>
      <div class="form-row">
        <input id="r-emoji" placeholder="🍦" style="width:70px">
        <input id="r-title" placeholder="Title">
        <input id="r-stars" type="number" min="1" max="999" placeholder="Stars" style="width:90px">
        <input id="r-age" type="number" min="3" max="18" placeholder="Min age" style="width:90px" value="4">
      </div>
      <div class="form-row">
        <input id="r-desc" placeholder="Description" style="flex:1; min-width:200px">
        <input id="r-season" placeholder="Season (optional, e.g. summer)" style="min-width:180px">
      </div>
      <div class="form-row">
        <input id="r-notes" placeholder="Parent notes" style="flex:1; min-width:200px">
        <button id="r-add">Add reward</button>
      </div>
      <div class="error" id="r-err"></div>
    </div>
    <div id="r-list"></div>`;
  main.querySelector("#r-add").onclick = async () => {
    const err = main.querySelector("#r-err");
    err.textContent = "";
    try {
      await api("/api/parent/rewards", {
        method: "POST",
        body: JSON.stringify({
          emoji: main.querySelector("#r-emoji").value || "★",
          title: main.querySelector("#r-title").value,
          stars: Number(main.querySelector("#r-stars").value),
          min_age: Number(main.querySelector("#r-age").value || 4),
          description: main.querySelector("#r-desc").value,
          season: main.querySelector("#r-season").value || null,
          parent_notes: main.querySelector("#r-notes").value || null,
          enabled: true,
          grown_up_required: true,
        }),
      });
      await paint();
    } catch (e) {
      err.textContent = e.message;
    }
  };
  const list = main.querySelector("#r-list");
  rewards.forEach((r) => {
    const card = document.createElement("div");
    card.className = "card inbox-card";
    card.innerHTML = `
      <h2>${escapeHtml(r.emoji || "★")} <input class="r-title" value="${escapeHtml(r.title)}"></h2>
      <p class="muted">${escapeHtml(r.source)} · ${r.id}</p>
      <div class="form-row">
        <label>Emoji <input class="r-emoji" value="${escapeHtml(r.emoji || "")}" style="width:70px"></label>
        <label>Stars <input class="r-stars" type="number" min="1" max="999" value="${r.stars}" style="width:90px"></label>
        <label>Min age <input class="r-age" type="number" min="3" max="18" value="${r.min_age}" style="width:90px"></label>
        <label>Season <input class="r-season" value="${escapeHtml(r.season || "")}" style="width:120px"></label>
      </div>
      <div class="form-row">
        <input class="r-desc" value="${escapeHtml(r.description || "")}" placeholder="Description" style="flex:1">
      </div>
      <div class="form-row">
        <input class="r-notes" value="${escapeHtml(r.parent_notes || "")}" placeholder="Parent notes" style="flex:1">
      </div>
      <div class="form-row">
        <label><input type="checkbox" class="r-on" ${r.enabled ? "checked" : ""}> Enabled for kids</label>
        <button class="good r-save">Save</button>
        <button class="warn r-del">${r.source === "catalog" ? "Turn off" : "Delete"}</button>
      </div>
      <div class="error r-msg"></div>`;
    const msg = card.querySelector(".r-msg");
    card.querySelector(".r-save").onclick = async () => {
      msg.textContent = "";
      try {
        await api(`/api/parent/rewards/${r.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            title: card.querySelector(".r-title").value,
            emoji: card.querySelector(".r-emoji").value,
            stars: Number(card.querySelector(".r-stars").value),
            min_age: Number(card.querySelector(".r-age").value),
            season: card.querySelector(".r-season").value || null,
            description: card.querySelector(".r-desc").value,
            parent_notes: card.querySelector(".r-notes").value,
            enabled: card.querySelector(".r-on").checked,
          }),
        });
        msg.textContent = "Saved";
      } catch (e) {
        msg.textContent = e.message;
      }
    };
    card.querySelector(".r-del").onclick = async () => {
      msg.textContent = "";
      try {
        await api(`/api/parent/rewards/${r.id}`, { method: "DELETE" });
        await paint();
      } catch (e) {
        msg.textContent = e.message;
      }
    };
    list.append(card);
  });
}

async function paintHistory(main) {
  const kids = await api("/api/parent/children");
  if (!kids.length) {
    main.innerHTML = `<div class="card"><p>Add a kid first, then their charts show up here.</p></div>`;
    return;
  }
  if (!historyChildId || !kids.some((k) => k.id === historyChildId)) {
    historyChildId = kids[0].id;
  }
  main.innerHTML = `<div class="card" style="margin-bottom:16px">
      <label>Child
        <select id="hist-kid"></select>
      </label>
    </div>
    <div id="hist-body"></div>`;
  const sel = main.querySelector("#hist-kid");
  kids.forEach((k) => {
    const opt = document.createElement("option");
    opt.value = String(k.id);
    opt.textContent = `${k.display_name} · ★ ${k.available ?? k.stars}`;
    if (k.id === historyChildId) opt.selected = true;
    sel.append(opt);
  });
  sel.onchange = () => { historyChildId = Number(sel.value); paint(); };
  const data = await api(`/api/parent/children/${historyChildId}/history`);
  const body = main.querySelector("#hist-body");
  const kid = kids.find((k) => k.id === historyChildId);
  renderHistory(body, data, {
    heading: (kid ? kid.display_name : "Child") + " — history",
    blurb: "Chores, Stars earned and spent, and reward cash-ins.",
    kidVoice: false,
  });
}

boot().catch((e) => {
  app.innerHTML = `<div class="card error">${escapeHtml(e.message)}</div>`;
});
