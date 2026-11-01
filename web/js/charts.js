function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderHistory(host, data, opts) {
  opts = opts || {};
  const name = data.child ? data.child.display_name : "this kid";
  const s = data.summary || {};
  const days = data.days || [];
  const events = data.events || [];

  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <h2>${opts.heading || "Your history"}</h2>
    <p class="muted">${opts.blurb || "Stars you earned and spent, plus what you did."}</p>
    <div class="stat-row">
      <div class="stat"><strong>★ ${s.stars_earned || 0}</strong><span>earned</span></div>
      <div class="stat"><strong>★ ${s.stars_spent || 0}</strong><span>spent</span></div>
      <div class="stat"><strong>${s.chores_approved || 0}</strong><span>chores done</span></div>
      <div class="stat"><strong>${s.rewards_cashed || 0}</strong><span>rewards</span></div>
      <div class="stat"><strong>★ ${s.available ?? s.stars ?? 0}</strong><span>ready now</span></div>
    </div>
    <div class="card chart-card">
      <h3>Last ${data.range_days || 14} days</h3>
      <div class="chart-bars"></div>
      <p class="legend"><span class="swatch gold"></span> Earned
         <span class="swatch rose"></span> Spent</p>
    </div>
    <div class="card chart-card">
      <h3>All-time Stars</h3>
      <div class="chart-donut"></div>
    </div>
    <div class="card">
      <h3>Rewards history</h3>
      <div class="reward-history"></div>
    </div>
    <div class="card">
      <h3>Activity</h3>
      <div class="event-list"></div>
    </div>`;

  drawBars(wrap.querySelector(".chart-bars"), days);
  drawDonut(wrap.querySelector(".chart-donut"), s.stars_earned || 0, s.stars_spent || 0);
  fillRewardHistory(wrap.querySelector(".reward-history"), data.rewards || []);
  const list = wrap.querySelector(".event-list");
  if (!events.length) {
    list.innerHTML = `<p class="muted">Nothing here yet${opts.kidVoice ? ". Finish a chore to start your chart." : " for " + name + "."}</p>`;
  } else {
    events.forEach((ev) => {
      const row = document.createElement("div");
      row.className = "event " + (ev.kind || "");
      const when = formatWhen(ev.at);
      row.innerHTML = `<div><strong>${escapeHtml(ev.title || "")}</strong>
        <div class="muted">${escapeHtml(ev.detail || "")}</div></div>
        <div class="muted">${escapeHtml(when)}</div>`;
      list.append(row);
    });
  }
  host.append(wrap);
}

function fillRewardHistory(el, rows) {
  if (!rows.length) {
    el.innerHTML = `<p class="muted">No rewards cashed in yet.</p>`;
    return;
  }
  rows.forEach((r) => {
    const row = document.createElement("div");
    row.className = "event reward-" + (r.state || "");
    row.innerHTML = `<div><strong>${escapeHtml(r.emoji || "★")} ${escapeHtml(r.title || "")}</strong>
      <div class="muted">${escapeHtml(r.state_label || r.state || "")} · ★ ${r.stars}${r.note ? " · " + escapeHtml(r.note) : ""}</div></div>
      <div class="muted">${escapeHtml(formatWhen(r.at))}</div>`;
    el.append(row);
  });
}

function formatWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function drawBars(el, days) {
  const w = 640;
  const h = 200;
  const padL = 28;
  const padB = 36;
  const padT = 12;
  const innerW = w - padL - 8;
  const innerH = h - padB - padT;
  const max = Math.max(1, ...days.map((d) => Math.max(d.earned || 0, d.spent || 0)));
  const n = Math.max(1, days.length);
  const group = innerW / n;
  let bars = "";
  days.forEach((d, i) => {
    const x = padL + i * group;
    const ew = Math.max(2, group * 0.32);
    const eh = ((d.earned || 0) / max) * innerH;
    const sh = ((d.spent || 0) / max) * innerH;
    const yE = padT + innerH - eh;
    const yS = padT + innerH - sh;
    bars += `<rect x="${x + group * 0.18}" y="${yE}" width="${ew}" height="${eh}" rx="3" fill="#e9b44c"></rect>`;
    bars += `<rect x="${x + group * 0.52}" y="${yS}" width="${ew}" height="${sh}" rx="3" fill="#c45c5c"></rect>`;
    if (i % 2 === 0 || n <= 10) {
      bars += `<text x="${x + group / 2}" y="${h - 12}" text-anchor="middle" font-size="11" fill="#5c6b86">${escapeHtml(d.label || "")}</text>`;
    }
  });
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Stars earned and spent by day">${bars}
    <line x1="${padL}" y1="${padT + innerH}" x2="${w - 8}" y2="${padT + innerH}" stroke="#d9e4f2"></line>
  </svg>`;
}

function drawDonut(el, earned, spent) {
  const total = earned + spent;
  const r = 54;
  const c = 2 * Math.PI * r;
  if (total <= 0) {
    el.innerHTML = `<p class="muted">No Stars earned or spent yet.</p>`;
    return;
  }
  const earnedLen = (earned / total) * c;
  el.innerHTML = `
    <div class="donut-wrap">
      <svg viewBox="0 0 140 140" width="160" height="160" role="img" aria-label="Earned versus spent">
        <circle cx="70" cy="70" r="${r}" fill="none" stroke="#c45c5c" stroke-width="16"></circle>
        <circle cx="70" cy="70" r="${r}" fill="none" stroke="#e9b44c" stroke-width="16"
          stroke-dasharray="${earnedLen} ${c - earnedLen}"
          transform="rotate(-90 70 70)"></circle>
        <text x="70" y="74" text-anchor="middle" font-size="18" font-weight="700" fill="#1a2744">★ ${earned - spent}</text>
      </svg>
      <div>
        <p><span class="swatch gold"></span> Earned ★ ${earned}</p>
        <p><span class="swatch rose"></span> Spent ★ ${spent}</p>
      </div>
    </div>`;
}
