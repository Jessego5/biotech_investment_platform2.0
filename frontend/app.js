// This is the frontend for the Biotech Agent. It has two views, a live browse and
// filter screen and a detail view for one company. The detail view shows its work,
// every figure ties back to and links to its real source. The backend runs on port 8000.
const API = "http://127.0.0.1:8000";

const el = (id) => document.getElementById(id);
const browseView = el("browse-view");
const detailView = el("detail-view");
const browseCount = el("browse-count");
const browseResults = el("browse-results");
const detailStatus = el("detail-status");
const detailResults = el("detail-results");

// how many companies there are in total, used for the "N of TOTAL" count
let TOTAL = null;

// setup on page load
window.addEventListener("DOMContentLoaded", () => {
  loadSectors();
  // honor a #/c/TICKER deep link if there is one, otherwise show the browse view
  route();
});
// listen for hash changes so company pages stay shareable and back/forward work
window.addEventListener("hashchange", route);

function route() {
  const m = location.hash.match(/^#\/c\/([A-Za-z.]+)/);
  if (m) showDetail(m[1].toUpperCase(), true);
  else { showBrowse(true); runFilters(); }
}

// live filtering. debounce the number inputs so it feels like an instrument,
// and update right away on the selects and checkbox
const debouncedFilter = debounce(runFilters, 250);
["f-minrd", "f-mincash", "f-minactive"].forEach((id) =>
  el(id).addEventListener("input", debouncedFilter));
el("f-sector").addEventListener("change", runFilters);
el("f-phase3").addEventListener("change", runFilters);
el("clear").addEventListener("click", clearFilters);
el("back").addEventListener("click", () => showBrowse());

// fold or unfold the company list, the count stays visible either way
el("toggle-list").addEventListener("click", () => {
  const hidden = el("browse-results").classList.toggle("hidden");
  const btn = el("toggle-list");
  btn.textContent = hidden ? "Show list" : "Hide list";
  btn.setAttribute("aria-expanded", String(!hidden));
});
el("lookup-btn").addEventListener("click", doLookup);
el("ticker-box").addEventListener("keydown", (e) => { if (e.key === "Enter") doLookup(); });

function doLookup() {
  const t = el("ticker-box").value.trim().toUpperCase();
  if (t) showDetail(t);
}

// nav bar: scroll to the relevant section and focus it
document.querySelectorAll(".nav-links a[data-nav]").forEach((a) => {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    navTo(a.dataset.nav);
  });
});

function navTo(what) {
  // check if we're on a company detail page, so we can go back to browse first
  const onDetail = !detailView.classList.contains("hidden");
  if (onDetail && (what === "browse" || what === "ask")) location.hash = "";
  // then scroll once the view has settled, and focus the box for the chat
  setTimeout(() => {
    if (what === "ask") {
      const box = el("chat-q");
      if (box) { box.scrollIntoView({ behavior: "smooth", block: "center" }); box.focus(); }
    } else if (what === "about") {
      const d = el("disclaimer-callout");
      if (d) d.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      const r = el("browse-results");
      if (r) r.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, onDetail ? 80 : 0);
}

// grounded chat, the secondary feature
el("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  askQuestion();
});

async function askQuestion() {
  const q = el("chat-q").value.trim();
  if (!q) return;
  const box = el("chat-answer");
  box.classList.remove("hidden");
  box.className = "chat-answer thinking";
  box.textContent = "Reading the database…";
  try {
    const r = await fetch(API + "/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    const data = await r.json();
    box.className = "chat-answer";
    box.innerHTML = `<p class="answer-text">${escapeHtml(data.answer || "")}</p>`;
    // show the companies the answer was grounded in, as clickable receipts
    const sources = data.sources || [];
    if (sources.length) {
      const shown = sources.slice(0, 15);
      const chips = shown.map((t) => `<span class="source-chip" data-ticker="${t}">${t}</span>`).join("");
      const more = sources.length > shown.length ? ` <span class="label">+${sources.length - shown.length} more</span>` : "";
      const div = document.createElement("div");
      div.className = "chat-sources";
      div.innerHTML = `<span class="label">Based on</span>${chips}${more}`;
      box.appendChild(div);
      div.querySelectorAll(".source-chip").forEach((chip) =>
        chip.addEventListener("click", () => showDetail(chip.dataset.ticker)));
    }
  } catch (e) {
    box.className = "chat-answer";
    box.textContent = "Couldn't reach the backend at " + API + ".";
  }
}

// - BROWSE / FILTER

async function loadSectors() {
  // the common sectors are already hardcoded in the HTML so the dropdown always
  // works even if this fetch fails, like when the page opens before the backend is up.
  // this just records the total count and adds any sector the HTML doesn't already list.
  try {
    const data = await (await fetch(API + "/companies")).json();
    TOTAL = data.count;
    const banner = el("stat-banner");
    if (banner) {
      banner.innerHTML = `This platform analyzes <strong>${TOTAL}</strong> public biotech companies ` +
        `using real clinical-trial and financial data.`;
    }
    const sel = el("f-sector");
    const existing = new Set([...sel.options].map((o) => o.value));
    [...new Set(data.companies.map((c) => c.sector).filter(Boolean))]
      .sort()
      .forEach((s) => {
        if (!existing.has(s)) {
          const opt = document.createElement("option");
          opt.value = s; opt.textContent = s;
          sel.appendChild(opt);
        }
      });
  } catch (e) { /* the dropdown still works from the static options, so just ignore this */ }
}

async function runFilters() {
  showBrowse();
  // the R&D and cash inputs are in $M for convenience, but the API wants raw dollars
  const params = new URLSearchParams();
  const minrd = numVal("f-minrd");
  const mincash = numVal("f-mincash");
  const minactive = numVal("f-minactive");
  const sector = el("f-sector").value;
  if (minrd !== null) params.set("min_rd", minrd * 1e6);
  if (mincash !== null) params.set("min_cash", mincash * 1e6);
  if (minactive !== null) params.set("min_active_trials", minactive);
  if (el("f-phase3").checked) params.set("has_phase3", "true");
  if (sector) params.set("sector", sector);

  try {
    const data = await (await fetch(API + "/companies?" + params.toString())).json();
    const of = TOTAL ? ` <span class="muted-cell">of ${TOTAL}</span>` : "";
    browseCount.innerHTML = `<strong>${data.count}</strong> companies${of}`;
    renderBrowse(data.companies);
  } catch (e) {
    browseCount.textContent = "Couldn't reach the backend at " + API + ". Is it running?";
    browseResults.innerHTML = "";
  }
}

function clearFilters() {
  ["f-minrd", "f-mincash", "f-minactive"].forEach((id) => (el(id).value = ""));
  el("f-phase3").checked = false;
  el("f-sector").value = "";
  runFilters();
}

function renderBrowse(companies) {
  if (!companies.length) {
    browseResults.innerHTML = "<p class='muted-cell' style='padding:14px 2px'>No companies match these filters.</p>";
    return;
  }
  const rows = companies.map((c) => `
    <tr data-ticker="${c.ticker}" tabindex="0" role="button">
      <td class="tk">${c.ticker}</td>
      <td class="name">${escapeHtml(c.name)}</td>
      <td class="muted-cell">${escapeHtml(c.sector || "")}</td>
      <td>${c.has_phase3 ? '<span class="pill">Phase 3+</span>' : '<span class="pill none">early/mid</span>'}</td>
      <td class="num">${c.total_trials}</td>
      <td class="num">${c.active_trials}</td>
      <td class="num">${money(c.rd_expense)}</td>
      <td class="num">${money(c.cash)}</td>
    </tr>`).join("");
  browseResults.innerHTML = `
    <table>
      <thead><tr>
        <th>Ticker</th><th>Name</th><th>Sector</th><th>Stage</th>
        <th class="num">Trials</th><th class="num">Active</th>
        <th class="num">R&amp;D</th><th class="num">Cash</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  browseResults.querySelectorAll("tr[data-ticker]").forEach((tr) => {
    const open = () => showDetail(tr.dataset.ticker);
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  });
}

// - COMPANY DETAIL

async function showDetail(ticker, fromRoute) {
  // set the hash and let route() render it, unless we already came from route()
  if (!fromRoute) { location.hash = "#/c/" + ticker; return; }
  browseView.classList.add("hidden");
  detailView.classList.remove("hidden");
  window.scrollTo(0, 0);
  detailResults.innerHTML = "";
  detailStatus.textContent = "Fetching " + ticker + "…";
  try {
    const r = await fetch(API + "/company/" + ticker);
    const data = await r.json();
    if (!r.ok) { detailStatus.className = "status error"; detailStatus.textContent = data.detail || ("Error " + r.status); return; }
    detailStatus.textContent = ""; detailStatus.className = "status";
    renderDetail(data);
  } catch (e) {
    detailStatus.className = "status error";
    detailStatus.textContent = "Couldn't reach the backend at " + API + ".";
  }
}

function showBrowse(fromRoute) {
  // clear the hash and let route() show it, unless we already came from route()
  if (!fromRoute && location.hash) { location.hash = ""; return; }
  detailView.classList.add("hidden");
  browseView.classList.remove("hidden");
}

function renderDetail(data) {
  const a = data.assessment;
  const p = data.pipeline;
  detailResults.innerHTML = "";

  // build the header card
  detailResults.appendChild(card(`
    <div class="detail-header">
      <h2>${escapeHtml(data.name)} <span class="ticker">${data.ticker}</span></h2>
    </div>
    <p class="meta">Grounded analysis · served from ${escapeHtml(data.source)}</p>
  `));

  // AI narrative, framed as a summary of the verified data and not an oracle
  if (data.narrative && data.narrative.text) {
    const c = card(`
      <p class="card-title">AI summary</p>
      <p class="narrative-text">${escapeHtml(data.narrative.text)}</p>
      <p class="narrative-frame">
        <span class="tag">AI-written</span>
        <span>Plain-language recap of the verified figures below. The model only rephrases them, it does not supply any numbers.</span>
        <span>· generated via ${escapeHtml(data.narrative.source)}</span>
      </p>`);
    c.classList.add("narrative-card");
    detailResults.appendChild(c);
  }

  // pipeline stage visualization, the signature element
  detailResults.appendChild(pipelineCard(p, a.pipeline_signal));

  // financials, with the sources linked back to EDGAR
  detailResults.appendChild(financialsCard(data.financials, a.financial_signal, data.cik));

  // trials, linked out to ClinicalTrials.gov
  detailResults.appendChild(trialsCard(data.trials, p.total_trials));

  const d = document.createElement("p");
  d.className = "disclaimer";
  d.textContent = a.disclaimer;
  detailResults.appendChild(d);
}

// pipeline stage viz: bucket trials by their highest phase, then draw a stage track
function pipelineCard(pipeline, signal) {
  const b = bucketPhases(pipeline.by_phase || {});
  const stages = [
    { key: "s1", label: "Phase 1", n: b.p1 },
    { key: "s2", label: "Phase 2", n: b.p2 },
    { key: "s3", label: "Phase 3", n: b.p3 },
    { key: "s4", label: "Phase 4", n: b.p4 },
  ];
  const max = Math.max(1, ...stages.map((s) => s.n));
  const cols = stages.map((s) => {
    const h = s.n === 0 ? 3 : Math.round((s.n / max) * 120) + 6;
    const cls = s.n === 0 ? "bar empty" : "bar " + s.key;
    return `
      <div class="stage">
        <span class="count">${s.n}</span>
        <div class="${cls}" style="height:${h}px"></div>
        <span class="stage-label">${s.label}</span>
      </div>`;
  }).join("");

  const naNote = b.na > 0
    ? `<p class="stage-note">+ ${b.na} trial(s) with no phase specified (often observational or device studies).</p>`
    : "";
  const cls = signalClass(signal.label);
  const evidence = (signal.evidence || []).map((l) => `<li>${escapeHtml(l)}</li>`).join("");

  return card(`
    <p class="card-title">Clinical pipeline: where the science is</p>
    <p class="stage-legend">Trials counted at their most advanced phase. Darker = later stage.</p>
    <div class="stage-track">${cols}</div>
    <div class="stage-baseline"></div>
    ${naNote}
    <p class="signal"><span class="signal-label ${cls}">${escapeHtml(signal.label)}</span></p>
    <ul>${evidence}</ul>
    <p class="provenance">Source: every trial above is a real registration on
      <a href="https://clinicaltrials.gov/" target="_blank" rel="noopener">ClinicalTrials.gov</a>
      (see the linked NCT ids below).</p>
  `);
}

function bucketPhases(byPhase) {
  const b = { p1: 0, p2: 0, p3: 0, p4: 0, na: 0 };
  for (const [key, count] of Object.entries(byPhase)) {
    const k = key.toUpperCase();
    if (k.includes("PHASE4")) b.p4 += count;
    else if (k.includes("PHASE3")) b.p3 += count;
    else if (k.includes("PHASE2")) b.p2 += count;
    // count phase 1 here too, including EARLY_PHASE1
    else if (k.includes("PHASE1")) b.p1 += count;
    else b.na += count;
  }
  return b;
}

function financialsCard(fin, signal, cik) {
  const cls = signalClass(signal.label);
  const evidence = (signal.evidence || []).map((l) => `<li>${escapeHtml(l)}</li>`).join("");

  let body;
  if (!fin || !fin.available) {
    body = `<p class="muted-cell">${escapeHtml((fin && fin.reason) || "Financials unavailable.")}</p>`;
  } else {
    const rd = fin.rd_expense, cash = fin.cash;
    let runway = "";
    if (rd && cash && rd.value > 0) runway = (cash.value / rd.value).toFixed(1) + "×";
    body = `
      <div class="figures">
        ${figure("R&D expense", money(rd), rd ? "FY" + rd.fiscal_year : "")}
        ${figure("Cash", money(cash), cash ? "FY" + cash.fiscal_year : "")}
        ${runway ? figure("Runway proxy", runway, "cash ÷ annual R&D") : ""}
      </div>`;
  }

  const src = cik
    ? `Source: <a href="${edgarUrl(cik)}" target="_blank" rel="noopener">SEC EDGAR annual filing (CIK ${escapeHtml(cik)})</a>.`
    : "Source: SEC EDGAR annual filings.";

  return card(`
    <p class="card-title">Financials</p>
    ${body}
    <p class="signal"><span class="signal-label ${cls}">${escapeHtml(signal.label)}</span></p>
    <ul>${evidence}</ul>
    <p class="provenance">${src}</p>
  `);
}

function figure(label, val, sub) {
  return `<div class="figure">
    <div class="flabel">${label}</div>
    <div class="fval">${val}</div>
    <div class="fsub">${escapeHtml(sub || "")}</div>
  </div>`;
}

function trialsCard(trials, total) {
  if (!trials || !trials.length) {
    return card(`
      <p class="card-title">Registered trials</p>
      <p class="muted-cell">No registered trials under this sponsor name. Some companies
      (e.g. sequencing/tools firms) simply don't sponsor clinical trials.</p>`);
  }
  const rows = trials.map((t) => `
    <tr>
      <td class="nct"><a href="https://clinicaltrials.gov/study/${t.nct_id}" target="_blank" rel="noopener">${t.nct_id}</a></td>
      <td>${escapeHtml(t.title || "")}</td>
      <td class="phase-tag">${escapeHtml(t.phase || "")}</td>
      <td class="muted-cell">${escapeHtml(t.status || "")}</td>
    </tr>`).join("");
  const shown = total > trials.length ? `showing ${trials.length} of ${total}` : `${total} total`;
  return card(`
    <p class="card-title">Registered trials <span class="muted-cell">(${shown})</span></p>
    <div class="table-scroll"><table>
      <thead><tr><th>NCT id</th><th>Title</th><th>Phase</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <p class="provenance">Each NCT id links to its registration on
      <a href="https://clinicaltrials.gov/" target="_blank" rel="noopener">ClinicalTrials.gov</a>.</p>
  `);
}

// - helpers

function edgarUrl(cik) {
  return "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=" +
         encodeURIComponent(cik) + "&type=10-K&dateb=&owner=include&count=40";
}

function numVal(id) {
  const v = el(id).value.trim();
  return v === "" ? null : Number(v);
}

function money(entry) {
  if (!entry) return "n/a";
  const m = entry.value / 1e6;
  if (m >= 1000) return "$" + (m / 1000).toFixed(1) + "B";
  return "$" + Math.round(m) + "M";
}

function signalClass(label) {
  const l = (label || "").toLowerCase();
  if (l.includes("tight") || l.includes("unavailable") || l.includes("limited") || l.includes("no registered")) return "warn";
  if (l.includes("comfortable") || l.includes("advancing")) return "good";
  return "";
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function card(html) {
  const d = document.createElement("div");
  d.className = "card";
  d.innerHTML = html;
  return d;
}

// content comes from external APIs, so escape it before injecting as HTML
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
