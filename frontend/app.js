// This is the frontend for the platform. It has two views, a live browse and
// filter screen and a detail view for one company. The detail view shows its work,
// every figure ties back to and links to its real source.
//
// Where the backend lives depends on where this page is being served from, and
// hardcoding it to localhost meant the page could never be deployed anywhere:
// a browser fetching 127.0.0.1 asks the machine it is running on, not the server
// the page came from.
//
//   1. window.API_BASE, if config.js sets it. That is how a split deployment
//      points the page at an API on another host.
//   2. the local backend, when opened from the dev server or from a file://
//      URL, which is how this is developed.
//   3. same origin, meaning whatever is in front of both the page and the API
//      routes to each of them. That is the deployment this wants by default.
const API = (typeof window.API_BASE === "string")
  ? window.API_BASE
  : ((location.protocol === "file:" || location.port === "5501")
      ? "http://127.0.0.1:8000"
      : "");

const el = (id) => document.getElementById(id);
const browseView = el("browse-view");
const detailView = el("detail-view");
const browseCount = el("browse-count");
const browseResults = el("browse-results");
const detailStatus = el("detail-status");
const detailResults = el("detail-results");

// how many companies there are in total, used for the "N of TOTAL" count
let TOTAL = null;
// ticker -> name, filled when the universe loads. The chat returns tickers as
// its sources and a bare ticker is a poor receipt: ABBV means nothing to a
// reader who does not already know the answer.
let NAME_BY_TICKER = {};

// setup on page load
window.addEventListener("DOMContentLoaded", () => {
  loadSectors();
  // honor a #/c/TICKER deep link if there is one, otherwise show the browse view
  route();
  // ?ask=... runs a question on load, so a question is shareable the same way a
  // company page is. It is also the only way to drive the chat from outside the
  // browser, which is how this surface gets checked.
  const params = new URLSearchParams(location.search);
  const asked = params.get("ask");
  // ?ws=1 lands the answer in the dense register rather than the conversational
  // one, so a workspace view is as shareable as a company page
  if (asked) askQuestion(asked, params.get("ws") === "1");
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
["f-minrd", "f-mincash", "f-minactive", "f-minrunway"].forEach((id) =>
  el(id).addEventListener("input", debouncedFilter));
el("f-sector").addEventListener("change", runFilters);
el("f-phase3").addEventListener("change", runFilters);
el("f-sort").addEventListener("change", runFilters);
el("clear").addEventListener("click", clearFilters);
el("back").addEventListener("click", () => showBrowse());

// fold or unfold the company list, the count stays visible either way
// the last result set, held so the table can be built when it is actually shown
let LAST_ROWS = [];

// Closed is the landing state. 787 rows is a wall rather than an answer, and
// scrolling one is not how anyone finds a company — a filter or a question is.
function setListOpen(open) {
  const results = el("browse-results");
  const btn = el("toggle-list");
  results.classList.toggle("hidden", !open);
  btn.textContent = open ? "Hide list" : `Show all`;
  btn.setAttribute("aria-expanded", String(open));
  results.innerHTML = "";
  if (open) renderBrowse(LAST_ROWS);
}

el("toggle-list").addEventListener("click", () => {
  const open = el("browse-results").classList.contains("hidden");
  setListOpen(open);
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

// what each tool actually reached for, in words rather than function names
const TOOL_LABEL = {
  filter_companies: "filtered the universe",
  company_report: "read one company's figures",
  search_trials: "searched trial descriptions",
  search_filings: "searched annual report text",
  patent_protection: "checked patents and exclusivity",
  upcoming_readouts: "looked up expected readouts",
  decline: "declined",
  greeting: "greeting",
};

// follow-ups the data can actually answer, so a suggestion is never a dead end
const FOLLOW_UPS = [
  "Which companies have a Phase 3 and over 3 years of runway?",
  "What Phase 3 readouts are expected soonest?",
  "Which company has the nearest patent cliff?",
];

async function askQuestion(preset, openWorkspace) {
  const input = el("chat-q");
  if (preset) input.value = preset;
  const q = input.value.trim();
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
    box.innerHTML = "";
    const empty = el("ask-empty");
    if (empty) empty.hidden = true;
    const thread = el("ask-thread");
    if (thread) thread.textContent = q.length > 46 ? q.slice(0, 46) + "…" : q;
    const openBar = el("ask-open");
    if (openBar) {
      openBar.hidden = false;
      openBar.onclick = () => showWorkspace({ ...data, question: q });
    }

    // the retrieval trace. The chat picks its own tools now, so which ones it
    // called is the honest account of how the answer was reached — and it is
    // what makes a wrong answer diagnosable rather than merely wrong.
    const tools = (data.tools_used || []).filter((t) => t !== "greeting");
    if (tools.length) {
      const seen = [];
      tools.forEach((t) => {
        const last = seen[seen.length - 1];
        if (last && last.name === t) last.n += 1;
        else seen.push({ name: t, n: 1 });
      });
      const steps = seen.map((x) =>
        `<span class="tool">${escapeHtml(TOOL_LABEL[x.name] || x.name)}${x.n > 1 ? ` ×${x.n}` : ""}</span>`
      ).join('<span class="sep"> → </span>');
      const trace = document.createElement("div");
      trace.className = "ask-trace";
      trace.innerHTML = steps;
      box.appendChild(trace);
    }

    // an unsourced answer must not render like a sourced one
    const grounded = (data.retrieved || "").trim().length > 0;
    const p = document.createElement("p");
    p.className = grounded ? "answer-prose" : "answer-miss";
    p.textContent = data.answer || "";
    box.appendChild(p);

    // the companies the answer was allowed to use, as receipts you can open
    const sources = data.sources || [];
    if (sources.length) {
      const wrap = document.createElement("div");
      wrap.className = "ask-cards";
      sources.slice(0, 8).forEach((t) => {
        const name = (NAME_BY_TICKER && NAME_BY_TICKER[t]) || "";
        const b = document.createElement("button");
        b.type = "button";
        b.className = "ask-card";
        b.innerHTML = `<div class="kind">company</div>
          <div class="t">${escapeHtml(t)}</div>
          <div class="d">${escapeHtml(name.slice(0, 30))}</div>`;
        b.addEventListener("click", () => showDetail(t));
        wrap.appendChild(b);
      });
      box.appendChild(wrap);
      if (sources.length > 8) {
        const more = document.createElement("p");
        more.className = "muted-cell";
        more.textContent = `+${sources.length - 8} more companies behind this answer.`;
        box.appendChild(more);
      }
    }

    // The provenance is the point of this project, and it used to stop at the
    // edge of the page: copy an answer into a memo and every figure became an
    // assertion with nothing behind it. This carries the trace, the companies
    // and the sources out with the text.
    const actions = document.createElement("div");
    actions.className = "ask-actions";
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "ask-copy";
    copy.textContent = "Copy with citations";
    copy.addEventListener("click", async () => {
      const steps = (data.tools_used || [])
        .filter((t) => t !== "greeting" && t !== "decline")
        .map((t) => TOOL_LABEL[t] || t);
      const uniqueSteps = steps.filter((v, i) => v !== steps[i - 1]);
      const lines = [
        data.answer || "",
        "",
        `Question: ${q}`,
        `Retrieved: ${new Date().toISOString().slice(0, 10)}` +
          (uniqueSteps.length ? ` — ${uniqueSteps.join(" → ")}` : ""),
      ];
      if (sources.length) {
        lines.push(`Companies behind this answer: ${sources.join(", ")}`);
      }
      // stated rather than implied: an answer with nothing behind it must not
      // travel as though it had sources
      if (!grounded) {
        lines.push("No matching data was found; this answer reports an absence.");
      }
      lines.push("Primary sources: ClinicalTrials.gov, SEC EDGAR, FDA Orange Book and Purple Book.");
      lines.push(`${location.origin}${location.pathname}?ask=${encodeURIComponent(q)}`);
      try {
        await navigator.clipboard.writeText(lines.join("\n"));
        copy.textContent = "Copied";
        setTimeout(() => { copy.textContent = "Copy with citations"; }, 1800);
      } catch (err) {
        copy.textContent = "Press ⌘C to copy";
      }
    });
    actions.appendChild(copy);
    box.appendChild(actions);

    if (openWorkspace) showWorkspace({ ...data, question: q });

    const next = document.createElement("div");
    next.className = "ask-next";
    FOLLOW_UPS.filter((f) => f !== q).slice(0, 3).forEach((f) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = f;
      b.addEventListener("click", () => askQuestion(f));
      next.appendChild(b);
    });
    box.appendChild(next);
  } catch (e) {
    box.className = "chat-answer";
    box.textContent = "Couldn't reach the backend at " + API + ".";
  }
}

// the cover's own line, kept separate from the one inside the tool because it
// says a different thing: the cover states what stands behind the tool, the
// tool states what is currently in scope
function fillCover(stats) {
  const meta = el("cover-meta");
  if (!meta || !stats) return;
  const n = (v) => (v || 0).toLocaleString();
  meta.textContent =
    `${n(stats.companies)} companies · ${n(stats.trials)} trials · ` +
    `${n(stats.filings)} annual reports · ${n(stats.registry_trials)} registry studies`;
}

const coverGo = el("cover-go");
if (coverGo) {
  coverGo.addEventListener("click", () =>
    el("tool").scrollIntoView({ behavior: "smooth", block: "start" }));
}


// Dark mode. Remembered, because a reader who chose it once did not choose it
// for one page. The neutrals stay warm in both and the phase ramp keeps its
// order, so a chart means the same thing either way.
(function () {
  const KEY = "bii-mode";
  const apply = (mode) => document.documentElement.setAttribute("data-mode", mode);
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { /* private window */ }
  apply(saved || (window.matchMedia &&
        window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  const btn = el("mode-toggle");
  if (btn) {
    btn.addEventListener("click", () => {
      const next = document.documentElement.getAttribute("data-mode") === "dark"
        ? "light" : "dark";
      apply(next);
      try { localStorage.setItem(KEY, next); } catch (e) { /* nothing to remember with */ }
    });
  }
})();


// - WORKSPACE (the dense register)
//
// The same answer as the chat, laid out for reading rather than conversing:
// scope stated above it, evidence beside it, and the rows each lookup returned
// kept apart. The handoff carries the whole result over — nothing is re-asked,
// because re-running would risk a different answer and the point is to inspect
// THIS one.
let LAST_ANSWER = null;

function showWorkspace(data) {
  LAST_ANSWER = data;
  browseView.classList.add("hidden");
  detailView.classList.add("hidden");
  el("workspace-view").classList.remove("hidden");
  window.scrollTo(0, 0);

  el("ws-question").textContent = data.question || "Answer";
  el("ws-date").textContent = new Date().toISOString().slice(0, 10);

  const ev = data.evidence || [];
  const sources = data.sources || [];
  // what was searched, before what was found
  const kinds = [...new Set(ev.map((e) => e.source))];
  el("ws-envelope").textContent =
    `${ev.length} lookup${ev.length === 1 ? "" : "s"} · ` +
    (kinds.join(" · ") || "no source reached") +
    ` · ${sources.length} compan${sources.length === 1 ? "y" : "ies"}`;

  const grounded = (data.retrieved || "").trim().length > 0;
  const ans = el("ws-answer");
  ans.className = grounded ? "ws-answer" : "ws-answer miss";
  // citation markers, rendered as chips that scroll the evidence pane to the
  // block they name. The backend has already removed any pointing at a block
  // that does not exist, because a marker that leads nowhere looks like
  // provenance and is worse than none.
  ans.innerHTML = escapeHtml(data.answer || "").replace(
    /\[(\d+)\]/g,
    (_, n) => `<button type="button" class="cite" data-cite="${n}">${n}</button>`);
  ans.querySelectorAll(".cite").forEach((c) =>
    c.addEventListener("click", () => {
      const block = document.querySelector(`.ws-ev[data-n="${c.dataset.cite}"]`);
      if (!block) return;
      block.scrollIntoView({ block: "nearest", behavior: "smooth" });
      block.classList.add("lit");
      setTimeout(() => block.classList.remove("lit"), 1400);
    }));

  const acts = el("ws-acts");
  acts.innerHTML = "";
  const back = document.createElement("button");
  back.type = "button";
  back.innerHTML = '<i class="ti ti-messages" aria-hidden="true"></i>Back to the conversational view';
  back.addEventListener("click", () => { showBrowse(); });
  acts.appendChild(back);

  const scope = el("ws-scope");
  scope.innerHTML = "";
  sources.slice(0, 10).forEach((t) => {
    const chip = document.createElement("span");
    chip.className = "ws-chip";
    chip.textContent = t;
    chip.style.cursor = "pointer";
    chip.addEventListener("click", () => showDetail(t));
    scope.appendChild(chip);
  });
  const right = document.createElement("span");
  right.className = "right";
  right.textContent = sources.length > 10
    ? `+${sources.length - 10} more` : `${sources.length} in scope`;
  scope.appendChild(right);

  // a new answer resets the rail, or the selection from the last one would sit
  // highlighted over evidence it did not filter
  document.querySelectorAll(".ws-rail div").forEach((d) =>
    d.classList.toggle("on", d.dataset.wsNav === "all"));
  renderEvidence("all");
}


// The rail filters the evidence pane by the source behind each block, which is
// the only thing it can honestly do: a lookup either read the registry or it
// read a filing, and that is recorded on the block. It was inert before —
// attributes and no handler, so the two middle items rendered and did nothing,
// which is worse than the disabled one because that at least says why.
// One entry per source we actually hold. Trials and Filings alone left the FDA
// blocks reachable only from Answer, which made the rail look like it covered
// the evidence when it covered two thirds of it.
const WS_FILTERS = {
  all: () => true,
  trials: (e) => (e.source || "").includes("CT.gov"),
  filings: (e) => (e.source || "").includes("SEC EDGAR"),
  approvals: (e) => (e.source || "").includes("FDA"),
};

const WS_WANTED = {
  trials: "the trial registry",
  filings: "an annual report",
  approvals: "the FDA approval and patent files",
};

function renderEvidence(which) {
  const data = LAST_ANSWER || {};
  const all = data.evidence || [];
  const keep = all.filter(WS_FILTERS[which] || WS_FILTERS.all);
  const pane = el("ws-evidence");
  pane.innerHTML = "";

  if (!all.length) {
    pane.innerHTML = `<div class="ws-ev"><div class="b">Nothing was retrieved, so there is no evidence to show. The answer reports that absence rather than filling it.</div></div>`;
    return;
  }
  if (!keep.length) {
    // an empty section states which of the sources it wanted and that this
    // answer did not reach it, rather than showing a blank pane
    const what = WS_WANTED[which] || "that source";
    pane.innerHTML = `<div class="ws-ev"><div class="b">This answer did not read ${what}. ${all.length} other lookup${all.length === 1 ? "" : "s"} stand behind it — see Answer.</div></div>`;
    return;
  }
  keep.forEach((e) => {
    const block = document.createElement("div");
    block.className = "ws-ev";
    block.dataset.n = e.n;
    block.innerHTML =
      `<div class="m"><span class="n">${e.n}</span>` +
      `<span>${escapeHtml(e.label)}</span>` +
      `<span style="margin-left:auto">${escapeHtml(e.source)}</span></div>` +
      `<div class="b">${escapeHtml(e.text)}</div>`;
    pane.appendChild(block);
  });
}

document.querySelectorAll(".ws-rail div").forEach((item) => {
  if (item.classList.contains("off")) return;
  item.addEventListener("click", () => {
    document.querySelectorAll(".ws-rail div").forEach((d) => d.classList.remove("on"));
    item.classList.add("on");
    renderEvidence(item.dataset.wsNav || "all");
  });
});

el("ws-back").addEventListener("click", () => showBrowse());


// - BROWSE / FILTER

// The sector labels this project curates. Everything else in the column is a
// description EDGAR supplied for a filing code we do not label ourselves, which
// is how a biotech screener ends up offering "Cigarettes" and "Wholesale-Beer,
// Wine & Distilled Alcoholic Beverages" as sectors. Those companies belong in
// the universe — they run real clinical trials — but they do not belong at the
// same level as Biologics in a dropdown of 34.
const CURATED_SECTORS = [
  "Pharma preparations", "Biologics", "Medical devices", "Diagnostics",
  "Medicinal chemicals", "Bio research", "Lab instruments", "Medical labs",
  "Health services", "Medical distribution",
];

// the three worked examples on the landing screen
document.querySelectorAll(".starter").forEach((b) =>
  b.addEventListener("click", () => showDetail(b.dataset.ticker)));

// and the question starters inside the ask surface. Each demonstrates a
// different lookup — a cross-company ranking, a date query, a sector filter,
// a composed one — rather than four flavours of the same thing.
document.querySelectorAll(".ask-starters button").forEach((b) =>
  b.addEventListener("click", () => askQuestion(b.dataset.ask)));


async function loadSectors() {
  try {
    const data = await (await fetch(API + "/companies")).json();
    TOTAL = data.count;
    // counted by the API rather than written here: every one of these has moved
    // as the universe widened, and a number typed into the page would quietly
    // become a claim the data no longer supports
    let stats = null;
    try { stats = await (await fetch(API + "/stats")).json(); } catch (e) { /* banner falls back */ }
    fillCover(stats);
    const banner = el("stat-banner");
    if (banner) {
      const n = (v) => (v || 0).toLocaleString();
      banner.innerHTML = stats
        ? `<strong>${n(stats.companies)}</strong> public biotech companies ·
           <strong>${n(stats.trials)}</strong> trials they lead ·
           <strong>${n(stats.upcoming_readouts)}</strong> readouts still expected ·
           <strong>${n(stats.filings)}</strong> annual reports read ·
           <strong>${n(stats.registry_trials)}</strong> studies in the wider registry`
        : `This platform analyzes <strong>${TOTAL}</strong> public biotech companies ` +
          `using real clinical-trial and financial data.`;
    }

    // counts, so the dropdown says how much is behind each label
    const counts = new Map();
    data.companies.forEach((c) => {
      if (c.sector) counts.set(c.sector, (counts.get(c.sector) || 0) + 1);
      if (c.ticker) NAME_BY_TICKER[c.ticker] = c.name || "";
    });

    const sel = el("f-sector");
    sel.innerHTML = '<option value="">Any sector</option>';
    const label = (s) => `${s} (${counts.get(s)})`;

    // curated first, biggest first, because that is what someone is looking for
    CURATED_SECTORS.filter((s) => counts.has(s))
      .sort((a, b) => counts.get(b) - counts.get(a))
      .forEach((s) => sel.add(new Option(label(s), s)));

    // and the rest kept apart rather than mixed in
    const rest = [...counts.keys()].filter((s) => !CURATED_SECTORS.includes(s)).sort();
    if (rest.length) {
      const group = document.createElement("optgroup");
      group.label = `Other filers running trials (${rest.length} codes)`;
      rest.forEach((s) => group.appendChild(new Option(label(s), s)));
      sel.appendChild(group);
    }
  } catch (e) {
    // Never swallow this. The banner is the first thing on the page and it
    // starts on "Loading the universe…", so a failure here leaves that sitting
    // there forever with nothing to say what went wrong — which is exactly how
    // a slow endpoint looked identical to a broken one from the browser.
    const banner = el("stat-banner");
    if (banner) {
      banner.innerHTML = `Couldn't load the universe from <code>${escapeHtml(API || location.origin)}</code>. ` +
        `Is the API running? <code>./run-local.sh</code> starts it.`;
      banner.classList.add("banner-error");
    }
  }
}

function anyFilterSet() {
  return ["f-minrd", "f-mincash", "f-minactive", "f-minrunway"]
           .some((id) => (el(id).value || "").trim() !== "")
         || el("f-sector").value !== "" || el("f-phase3").checked;
}


async function runFilters() {
  showBrowse();
  // the R&D and cash inputs are in $M for convenience, but the API wants raw dollars
  const params = new URLSearchParams();
  const minrd = numVal("f-minrd");
  const mincash = numVal("f-mincash");
  const minactive = numVal("f-minactive");
  const minrunway = numVal("f-minrunway");
  const sector = el("f-sector").value;
  const sortBy = el("f-sort").value;
  if (minrd !== null) params.set("min_rd", minrd * 1e6);
  if (mincash !== null) params.set("min_cash", mincash * 1e6);
  if (minactive !== null) params.set("min_active_trials", minactive);
  if (el("f-phase3").checked) params.set("has_phase3", "true");
  if (sector) params.set("sector", sector);
  // runway is in years, the same unit the backend works in, so it goes straight through
  if (minrunway !== null) params.set("min_runway", minrunway);
  if (sortBy) params.set("sort_by", sortBy);

  try {
    const data = await (await fetch(API + "/companies?" + params.toString())).json();
    const of = TOTAL ? ` <span class="muted-cell">of ${TOTAL}</span>` : "";
    browseCount.innerHTML = `<strong>${data.count}</strong> companies${of}`;
    // Held rather than rendered. Hiding 787 rows still builds 787 rows, which
    // is most of the work for none of the benefit — and it is not really
    // declining to list them, only declining to show the list.
    LAST_ROWS = data.companies;
    const btn = el("toggle-list");
    // a filter is a request to see the result, so the list opens itself once it
    // has been narrowed to something worth reading. Unfiltered it stays closed.
    setListOpen(anyFilterSet());
  } catch (e) {
    browseCount.textContent = "Couldn't reach the backend at " + API + ". Is it running?";
    browseResults.innerHTML = "";
  }
}

function clearFilters() {
  ["f-minrd", "f-mincash", "f-minactive", "f-minrunway"].forEach((id) => (el(id).value = ""));
  el("f-phase3").checked = false;
  el("f-sector").value = "";
  el("f-sort").value = "";
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
      <td class="num">${cell(money(c.rd_expense))}</td>
      <td class="num">${cell(money(c.cash))}</td>
      <td class="num">${runwayCell(c)}</td>
    </tr>`).join("");
  browseResults.innerHTML = `
    <table>
      <thead><tr>
        <th>Ticker</th><th>Name</th><th>Sector</th><th>Stage</th>
        <th class="num">Trials</th><th class="num">Active</th>
        <th class="num">R&amp;D</th><th class="num">Cash</th>
        <th class="num">Runway</th>
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
  const wsv = el("workspace-view");
  if (wsv) wsv.classList.add("hidden");
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
    // what changed is a separate request on purpose: it compares two archived
    // snapshots and is slower, so the page should not wait on it to draw
    loadChanges(ticker);
  } catch (e) {
    detailStatus.className = "status error";
    detailStatus.textContent = "Couldn't reach the backend at " + API + ".";
  }
}

async function loadChanges(ticker) {
  // a company with only one snapshot, or none, is the normal case rather than an
  // error, so a 404 here means there is simply nothing to compare
  let data;
  try {
    const r = await fetch(API + "/company/" + ticker + "/changes");
    if (!r.ok) return;
    data = await r.json();
  } catch (e) { return; }
  if (!data.changes || !data.changes.length) return;
  detailResults.insertBefore(changesCard(data), detailResults.lastChild);
}

// what moved between two archived snapshots. the dates are shown because the
// window is what makes "changed" mean anything.
function changesCard(data) {
  const rows = data.changes.map((c) => {
    const notable = c.notable || c.kind === "phase_changed";
    const what = c.nct_id
      ? `<a href="https://clinicaltrials.gov/study/${encodeURIComponent(c.nct_id)}"
           target="_blank" rel="noopener">${escapeHtml(c.nct_id)}</a>`
      : escapeHtml(c.metric || "");
    return `<li class="${notable ? "change notable" : "change"}">
      <span class="change-kind">${escapeHtml(c.kind.replace(/_/g, " "))}</span>
      <span class="change-what">${what}</span>
      <span class="change-detail">${escapeHtml(c.detail || "")}</span>
      ${c.note ? `<span class="change-note">${escapeHtml(c.note)}</span>` : ""}
    </li>`;
  }).join("");

  return card(`
    <p class="card-title">What changed</p>
    <p class="meta">Comparing the archived snapshots of ${escapeHtml(data.from)}
      and ${escapeHtml(data.to)}. Everything here is a difference between two
      stored responses, not a new lookup.</p>
    <ul class="changes">${rows}</ul>`);
}

function showBrowse(fromRoute) {
  // clear the hash and let route() show it, unless we already came from route()
  if (!fromRoute && location.hash) { location.hash = ""; return; }
  detailView.classList.add("hidden");
  const ws = el("workspace-view");
  if (ws) ws.classList.add("hidden");
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
  detailResults.appendChild(financialsCard(data.financials, a.financial_signal,
                                           data.cik, data.derived));

  // what is expected to report, and when. The dates are forecasts the registry
  // publishes, never dates we worked out
  if (data.readouts && data.readouts.length) {
    detailResults.appendChild(readoutsCard(data.readouts));
  }

  // patents and exclusivity on the approved products, if there are any
  if (data.protection) {
    detailResults.appendChild(protectionCard(data.protection));
  }

  // trials, linked out to ClinicalTrials.gov
  detailResults.appendChild(trialsCard(data.trials, p.total_trials,
                                       p.total_trials_reported, p.truncated,
                                       p.collaborator_trials));

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

function financialsCard(fin, signal, cik, derived) {
  const cls = signalClass(signal.label);
  const evidence = (signal.evidence || []).map((l) => `<li>${escapeHtml(l)}</li>`).join("");

  let body;
  if (!fin || !fin.available) {
    body = `<p class="muted-cell">${escapeHtml((fin && fin.reason) || "Financials unavailable.")}</p>`;
  } else {
    const d = derived || {};
    // every figure here comes from the API. runway in particular is NOT worked
    // out again in the browser: which balance counts toward it, which burn
    // figure it divides by, and whether it applies at all are real rules, and a
    // second copy of them here would drift from the one the evidence describes.
    const figures = [
      figure("Cash", money(fin.cash), period(fin.cash)),
      figure("Securities", money(fin.marketable_securities),
             period(fin.marketable_securities)),
      // what the two above add up to, when their dates allow it
      figure("Liquidity", money(d.liquidity), period(d.liquidity)),
      figure("Annual burn", money(d.burn === null || d.burn === undefined
                                  ? null : { value: d.burn }),
             d.burn_source || ""),
      figure("R&D expense", money(fin.rd_expense), period(fin.rd_expense)),
      figure("Revenue", money(fin.revenue), period(fin.revenue)),
      figure("Debt", money(fin.debt), period(fin.debt)),
      figure("Shares outstanding", count(fin.shares_outstanding),
             period(fin.shares_outstanding)),
    ];

    // a company funding itself out of operations has no runway to run out of,
    // which is a different statement from not being able to work one out
    if (d.cash_generative) {
      figures.push(figure("Runway", "n/a", "operations generate cash"));
    } else if (d.runway !== null && d.runway !== undefined) {
      figures.push(figure("Runway", d.runway.toFixed(1) + " yrs",
                          "liquidity ÷ " + (d.burn_source || "burn")));
    }

    body = `<div class="figures">${figures.join("")}</div>`;
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
  // a figure the company never reported is left out entirely rather than shown
  // as "n/a", so the card says what is known instead of listing what isn't
  if (val === "n/a" && label !== "Runway") return "";
  return `<div class="figure">
    <div class="flabel">${label}</div>
    <div class="fval">${val}</div>
    <div class="fsub">${escapeHtml(sub || "")}</div>
  </div>`;
}

// which period a figure covers. these are not all the same kind of number: a
// balance is true on a date, a total covers a year, so saying "FY2025" for both
// would claim something different from what was filed.
function period(entry) {
  if (!entry) return "";
  if (entry.fiscal_period === "FY") return "FY" + entry.fiscal_year + ", full year";
  if (entry.period_end) return "as of " + entry.period_end;
  return entry.fiscal_year ? "FY" + entry.fiscal_year : "";
}

// runway as the API computed it. the title says which burn figure it divided by,
// because R&D expense is the weaker fallback and the two shouldn't look alike.
//
// A missing runway means two opposite things and used to render as one. 196
// companies have none: 175 because operations generate cash, which is a
// strength, and 21 because no financials could be parsed at all, which is a gap
// in what we hold. AbbVie and Aurora Cannabis both read "n/a", so a profitable
// company with $61B of revenue looked identical to one we know nothing about.
function runwayCell(c) {
  if (c.runway === null || c.runway === undefined) {
    // the burn figure exists and no runway was derived from it, which is what
    // happens when operations throw off cash rather than consume it
    if (c.burn_source) {
      return `<span class="cell-na" title="Operations generated cash over the last full year, so there is no burn to divide into. Not a missing figure.">generates cash</span>`;
    }
    return `<span class="cell-missing" title="No financials could be parsed for this filer.">no data</span>`;
  }
  const src = c.burn_source || "burn";
  const weak = src === "R&D expense" ? " *" : "";
  return `<span title="liquidity ÷ ${escapeHtml(src)}">${c.runway.toFixed(1)}y${weak}</span>`;
}

function count(entry) {
  if (!entry) return "n/a";
  const m = entry.value / 1e6;
  return m >= 1 ? m.toFixed(1) + "M" : Math.round(entry.value).toLocaleString();
}

function readoutsCard(readouts) {
  // an estimated completion is when a readout is EXPECTED. The registry marks a
  // date ACTUAL or ESTIMATED and only the second is a forecast, so calling these
  // "expected" rather than "due" is the honest word for what they are.
  const rows = readouts.map((r) => `
    <tr>
      <td class="nct"><a href="https://clinicaltrials.gov/study/${encodeURIComponent(r.nct_id)}"
        target="_blank" rel="noopener">${escapeHtml(r.nct_id)}</a></td>
      <td class="phase-tag">${escapeHtml(r.phase || "")}</td>
      <td>${escapeHtml((r.conditions || "").split(";")[0] || "—")}</td>
      <td class="num">${r.enrollment == null ? "—" : r.enrollment.toLocaleString()}</td>
      <td class="num">${escapeHtml(r.completion_date || "")}</td>
    </tr>`).join("");
  return card(`
    <p class="card-title">Expected readouts <span class="muted-cell">(${readouts.length} soonest)</span></p>
    <p class="muted-cell">Primary completion dates the sponsor has filed as
      <em>estimated</em>. A forecast the registry publishes, not a prediction made here,
      and only for trials this company leads.</p>
    <div class="table-scroll"><table>
      <thead><tr><th>NCT id</th><th>Phase</th><th>Indication</th>
        <th class="num">Enrolment</th><th class="num">Expected</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`);
}


function protectionCard(pr) {
  // the whole point of this card is that "no approved product" is not the same
  // claim as "no patents", so the state carries its own explanation
  const evidence = (pr.evidence || [])
    .map((e) => `<li>${escapeHtml(e)}</li>`).join("");
  // "no approved product" is a gap in the source, not a weak company, so it must
  // not be coloured like one. Only genuinely open generic entry is a warning.
  const cls = pr.state === "protected" ? "good"
            : (pr.state === "approved, no listed protection" ? "warn" : "");
  const dates = pr.next_expiry
    ? `<div class="protect-dates">
         <div><span class="label">Nearest expiry</span><strong>${escapeHtml(pr.next_expiry)}</strong></div>
         <div><span class="label">Protection runs to</span><strong>${escapeHtml(pr.last_expiry)}</strong></div>
         <div><span class="label">Composition-of-matter</span><strong>${pr.composition_of_matter}</strong></div>
       </div>`
    : "";
  const held = [];
  if (pr.products) held.push(`${pr.products} approved drug${pr.products === 1 ? "" : "s"}`);
  if (pr.biologics) held.push(`${pr.biologics} licensed biologic${pr.biologics === 1 ? "" : "s"}`);
  return card(`
    <p class="card-title">Patents &amp; exclusivity</p>
    ${held.length ? `<p class="stage-legend">${held.join(" and ")}.</p>` : ""}
    ${dates}
    <p class="signal"><span class="signal-label ${cls}">${escapeHtml(pr.state)}</span></p>
    <ul>${evidence}</ul>
    <p class="provenance">From the FDA
      <a href="https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files"
         target="_blank" rel="noopener">Orange Book</a> and
      <a href="https://purplebooksearch.fda.gov/" target="_blank" rel="noopener">Purple Book</a>.
      US approvals only, so protection held outside the United States is not
      shown here at all.</p>`);
}


function trialsCard(trials, total, sponsorTotal, truncated, collaborating) {
  if (!trials || !trials.length) {
    return card(`
      <p class="card-title">Registered trials</p>
      <p class="muted-cell">No registered trials under this sponsor name. Some companies
      (e.g. sequencing/tools firms) simply don't sponsor clinical trials.</p>`);
  }
  // whether the company runs the trial or partners on one somebody else runs.
  // The counts above are the ones it leads, so a partnered study sitting in the
  // same table unlabelled reads as part of a pipeline it is not part of.
  const rows = trials.map((t) => `
    <tr>
      <td class="nct"><a href="https://clinicaltrials.gov/study/${t.nct_id}" target="_blank" rel="noopener">${t.nct_id}</a></td>
      <td class="muted-cell">${escapeHtml((t.conditions || "").split(";")[0] || "—")}</td>
      <td>${escapeHtml(t.title || "")}
        ${t.role === "collaborator"
          ? `<span class="role-tag" title="Led by ${escapeHtml(t.lead_sponsor || "another sponsor")}. Not counted in the pipeline figures above.">collaborator</span>`
          : ""}</td>
      <td class="phase-tag">${escapeHtml(t.phase || "")}</td>
      <td class="muted-cell">${escapeHtml(t.status || "")}</td>
    </tr>`).join("");
  const led = trials.filter((t) => (t.role || "lead") === "lead").length;
  const shown = total > led ? `showing ${led} of ${total} led` : `${total} led`;
  // a few very large sponsors register more studies than one ingest will pull.
  // say so, rather than presenting part of a pipeline as the whole of it.
  const partial = truncated && sponsorTotal
    ? `<p class="muted-cell">This sponsor has ${sponsorTotal.toLocaleString()} registered
       studies in total. Ingestion stops short of fetching them all, so the counts and
       phase breakdown above cover the ${total.toLocaleString()} stored here, not the
       full set.</p>`
    : "";
  // reported next to the led count, never added to it
  const alsoOn = collaborating
    ? `, plus ${collaborating.toLocaleString()} it collaborates on`
    : "";
  return card(`
    <p class="card-title">Registered trials <span class="muted-cell">(${shown}${alsoOn})</span></p>
    ${partial}
    <div class="table-scroll"><table>
      <thead><tr><th>NCT id</th><th>Indication</th><th>Title</th><th>Phase</th><th>Status</th></tr></thead>
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

// A table has to put something in every cell, where the detail card can leave a
// figure out entirely. So absence is decorated here rather than inside money(),
// and it is decorated as a gap in what we hold rather than as a small number.
function cell(v) {
  return v === "n/a"
    ? '<span class="cell-missing" title="Not reported in the filings we hold.">no data</span>'
    : v;
}


function money(entry) {
  // the plain sentinel matters: figure() drops a figure that reads "n/a"
  // instead of listing what the company never reported, so this must stay a
  // value that can be compared and not markup
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
