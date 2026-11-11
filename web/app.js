// Three pages in one file, no build step: Ask, Monitor, Evals.
const $ = (sel) => document.querySelector(sel);
const view = $("#view");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (path, body) => {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};
const pct = (x) => (x == null ? "–" : Math.round(x * 100) + "%");
const num = (x, d = 3) => (x == null ? "–" : Number(x).toFixed(d));
const ms = (x) => (x == null ? "–" : x >= 1000 ? (x / 1000).toFixed(2) + " s" : Number(x).toFixed(x < 10 ? 1 : 0) + " ms");
const ago = (ts) => { const s = Date.now() / 1000 - ts; return s < 60 ? "now" : s < 3600 ? Math.floor(s / 60) + "m" : s < 86400 ? Math.floor(s / 3600) + "h" : Math.floor(s / 86400) + "d"; };
const badge = (text, tone) => `<span class="badge ${tone}">${esc(text)}</span>`;
const statusBadge = (status, reason) => badge(status === "answered" ? "answered" : `${status}: ${reason}`, status === "answered" ? "good" : status === "error" ? "bad" : "warn");
const REASONS = {
  grounded: "Every claim in the answer is supported by its cited source.",
  below_score_floor: "The best retrieved chunk scored under the floor, so the model was never called.",
  model_declined: "The model said the sources do not answer the question.",
  no_grounded_claims: "The model answered, but no claim survived the ground check.",
  invalid_json: "The model's output was not valid JSON, so nothing could be checked.",
};

let chat = [];          // Ask page conversation
let golden = [];

async function boot() {
  try {
    const o = await api("/api/overview");
    $("#env").textContent = `${o.provider} · ${o.models.generation} · ${o.models.embedding} · ${o.corpus.chunks} chunks`;
    golden = await api("/api/golden");
  } catch (e) { $("#env").textContent = "not ready: " + e.message; }
  window.addEventListener("hashchange", route);
  route();
}

function route() {
  const [, tab = "ask", arg] = location.hash.split("/");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.tab === tab));
  clearInterval(window._poll);
  ({ ask: renderAsk, monitor: renderMonitor, evals: renderEvals }[tab] || renderAsk)(arg);
}

// ------------------------------------------------------------------ Ask
function renderAsk() {
  const samples = golden.filter((g) => g.type !== "follow_up").filter((_, i) => i % 5 === 0).slice(0, 6);
  view.innerHTML = `
    <h1>Ask the policy library</h1>
    <p class="lead">What an employee sees. Answers come only from the bank's policy documents, each sentence carries its source, and anything the documents do not cover is refused. Follow-up questions use the conversation so far.</p>
    <div id="chat"></div>
    <div class="panel">
      <form class="row" id="askform"><input type="text" id="q" placeholder="e.g. How many days of annual leave do I get?" autocomplete="off"><button>Ask</button>
      <button type="button" class="ghost" id="clear">New conversation</button></form>
      <div class="chips">${samples.map((g) => `<button type="button" class="chip">${esc(g.q)}</button>`).join("")}</div>
    </div>`;
  drawChat();
  const send = async (q) => {
    if (!q.trim()) return;
    const history = chat.flatMap((c) => [{ role: "user", text: c.q }, { role: "assistant", text: c.r ? c.r.answer : "" }]).slice(-6);
    const turn = { q, r: null };
    chat.push(turn); drawChat(); $("#q").value = "";
    try { turn.r = await api("/api/ask", { question: q, history }); } catch (e) { turn.err = e.message; }
    drawChat();
  };
  $("#askform").onsubmit = (e) => { e.preventDefault(); send($("#q").value); };
  $("#clear").onclick = () => { chat = []; drawChat(); };
  view.querySelectorAll(".chip").forEach((c) => (c.onclick = () => send(c.textContent)));
  $("#q").focus();
}

function drawChat() {
  const el = $("#chat"); if (!el) return;
  el.innerHTML = chat.map((c, i) => `
    <div class="bubble user">${esc(c.q)}</div>
    <div class="bubble bot">${c.err ? badge("error", "bad") + " " + esc(c.err) : !c.r ? '<span class="muted">Thinking…</span>' : `
      <div class="answer">${esc(c.r.answer)}</div>
      ${c.r.citations.length ? `<div class="cite">${c.r.citations.map((s) => `[${s.n}] ${esc(s.title)} › ${esc(s.section)} (v${esc(s.version)})`).join("<br>")}</div>` : ""}
      <div class="foot">${statusBadge(c.r.status, c.r.reason)} <span>${ms(c.r.ms)}</span>
        <a href="#/monitor/${c.r.trace_id}">See how this answer was made →</a>
        <span style="margin-left:auto">${c.fb != null ? "Thanks for the feedback" : `Helpful? <button class="small ghost" data-fb="${i}:1">Yes</button> <button class="small ghost" data-fb="${i}:0">No</button>`}</span>
      </div>`}
    </div>`).join("");
  el.querySelectorAll("[data-fb]").forEach((b) => (b.onclick = async () => {
    const [i, v] = b.dataset.fb.split(":").map(Number);
    await api("/api/feedback", { trace_id: chat[i].r.trace_id, helpful: !!v });
    chat[i].fb = v; drawChat();
  }));
}

// ------------------------------------------------------------------ Monitor
async function renderMonitor(traceId) {
  view.innerHTML = `
    <h1>Monitor</h1>
    <p class="lead">Type a question and watch every step: which chunks each search found, how they were scored, what the model was sent and what it wrote, which claims passed the ground check, and how long each stage took.</p>
    <div class="panel"><form class="row" id="mform"><input type="text" id="mq" placeholder="Run a question through the pipeline" autocomplete="off"><button>Run and trace</button></form>
      <div class="chips">${golden.filter((g) => g.type !== "follow_up").filter((_, i) => i % 4 === 1).slice(0, 7).map((g) => `<button type="button" class="chip">${esc(g.q)}</button>`).join("")}</div></div>
    <div id="tiles" class="tiles"></div>
    <div class="split">
      <div class="panel"><h2>Recent traces</h2>
        <div class="row" style="margin-bottom:10px"><label><input type="radio" name="kind" value="live" checked> live</label><label><input type="radio" name="kind" value="eval"> eval</label><label><input type="radio" name="kind" value=""> all</label></div>
        <div class="list" id="tlist"></div></div>
      <div id="detail"><div class="panel empty">Run a question or pick a trace on the left.</div></div>
    </div>`;
  const run = async (q) => {
    if (!q.trim()) return;
    $("#detail").innerHTML = `<div class="panel empty">Running “${esc(q)}”…</div>`;
    try { const r = await api("/api/ask", { question: q }); location.hash = "#/monitor/" + r.trace_id; }
    catch (e) { $("#detail").innerHTML = `<div class="panel">${badge("error", "bad")} ${esc(e.message)}</div>`; }
  };
  $("#mform").onsubmit = (e) => { e.preventDefault(); run($("#mq").value); };
  view.querySelectorAll(".chips .chip").forEach((c) => (c.onclick = () => run(c.textContent)));
  view.querySelectorAll("[name=kind]").forEach((r) => (r.onchange = () => drawTraceList(traceId)));
  drawOverview(); drawTraceList(traceId);
  if (traceId) drawTrace(traceId);
}

async function drawOverview() {
  const o = await api("/api/overview");
  const fb = o.feedback.total ? pct(o.feedback.helpful / o.feedback.total) : "–";
  const reasons = Object.entries(o.refusal_reasons).map(([k, v]) => `${k} ${v}`).join(" · ") || "none yet";
  $("#tiles").innerHTML = [
    ["Live questions", o.queries, `${o.answered} answered · ${o.refused} refused · ${o.errors} errors`, ""],
    ["Refusal reasons", o.refused + o.errors, reasons, ""],
    ["Latency p50 / p95", `${ms(o.p50_ms)} / ${ms(o.p95_ms)}`, "end to end, live questions", ""],
    ["Groundedness", pct(o.groundedness), "claims kept ÷ claims made", o.groundedness == null ? "" : o.groundedness >= .95 ? "good" : "warn"],
    ["Helpful votes", fb, `${o.feedback.helpful} of ${o.feedback.total} votes`, ""],
    ["Audit chain", o.audit.ok ? "intact" : "BROKEN", `${o.audit.rows} rows${o.audit.ok ? "" : ", first bad row " + o.audit.broken_at}`, o.audit.ok ? "good" : "bad"],
    ["Score floor", num(o.score_floor), "from " + o.score_floor_source, ""],
  ].map(([k, v, s, tone]) => `<div class="tile ${tone}"><div class="k">${k}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");
}

async function drawTraceList(selected) {
  const kind = (document.querySelector("[name=kind]:checked") || {}).value || "";
  const rows = await api(`/api/traces?limit=100${kind ? "&kind=" + kind : ""}`);
  $("#tlist").innerHTML = rows.length ? rows.map((t) => `
    <div class="item ${t.id === selected ? "on" : ""}" data-id="${t.id}" title="${esc(t.status)}: ${esc(t.reason)}">
      <span class="dot ${t.status}"></span><span class="q">${esc(t.question)}</span>
      <span class="m">${t.golden_pass == null ? "" : t.golden_pass ? "✓ " : "✗ "}${ms(t.total_ms)} · ${ago(t.ts)}</span></div>`).join("")
    : `<div class="empty">No traces yet.</div>`;
  $("#tlist").querySelectorAll(".item").forEach((el) => (el.onclick = () => (location.hash = "#/monitor/" + el.dataset.id)));
}

async function drawTrace(id) {
  let t;
  try { t = await api("/api/traces/" + id); } catch (e) { $("#detail").innerHTML = `<div class="panel empty">${esc(e.message)}</div>`; return; }
  const o = t.outcome, sc = t.scores, g = t.generation, cfg = t.config, gold = t.golden;
  const total = Math.max(t.total_ms, 0.01);
  let offset = 0;
  const water = t.stages.map((s) => { const left = (offset / total) * 100; offset += s.ms; return `
    <div class="mono">${s.name}</div><div class="track"><div class="fill" style="left:${left}%;width:${Math.max((s.ms / total) * 100, .4)}%"></div></div><div class="num mono" style="text-align:right">${ms(s.ms)}</div>
    <div class="note">${esc(s.note)}</div>`; }).join("");
  const maxScore = Math.max(1, sc.top_score || 0);
  const tiles = [
    ["Outcome", o.status, o.reason.startsWith("provider_error") ? "provider error" : o.reason, o.status === "answered" ? "good" : o.status === "error" ? "bad" : "warn"],
    ["Top retrieval score", num(sc.top_score), `floor ${num(cfg.score_floor)} · margin ${sc.score_margin >= 0 ? "+" : ""}${num(sc.score_margin)}`, sc.score_margin >= 0 ? "good" : "warn"],
    ["Groundedness", pct(sc.groundedness), t.claims.length ? `${t.claims.filter((c) => c.kept).length} of ${t.claims.length} claims supported` : "no claims made", sc.groundedness == null ? "" : sc.groundedness === 1 ? "good" : "warn"],
    ["Context used", pct(sc.context_used), "retrieved chunks the answer cites", ""],
    ["Answer ↔ question", num(sc.answer_similarity, 2), "embedding similarity", ""],
    ["Golden check", gold ? (gold.passed ? "pass" : "fail") : "–", gold ? `case ${gold.case_id} expects ${gold.expected}` : "not a golden-set question", gold ? (gold.passed ? "good" : "bad") : ""],
    ["Total time", ms(t.total_ms), t.over_budget ? "over the budget" : `budget ${ms(cfg.budget_ms)}`, t.over_budget ? "bad" : ""],
    ["Generation speed", g ? g.tokens_per_s + " tok/s" : "–", g ? `${g.prompt_tokens} in · ${g.output_tokens} out` : "model not called", ""],
  ].map(([k, v, s, tone]) => `<div class="tile ${tone}"><div class="k">${k}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");

  $("#detail").innerHTML = `
    <div class="panel">
      <div class="muted mono">trace ${t.id} · ${new Date(t.ts * 1000).toLocaleString()} · ${t.kind}${t.run_id ? " · " + t.run_id : ""}</div>
      <h1 style="margin-top:6px">${esc(t.question)}</h1>
      <div class="answer" style="margin-top:8px">${esc(o.answer)}</div>
      ${o.citations.length ? `<div class="cite">${o.citations.map((s) => `[${s.n}] ${esc(s.title)} › ${esc(s.section)} · v${esc(s.version)} · <span class="mono">${s.chunk_id}</span>`).join("<br>")}</div>` : ""}
      <div class="foot" style="margin-top:10px">${statusBadge(o.status, o.reason)} <span class="muted">${esc(REASONS[o.reason] || o.reason)}</span></div>
      ${t.feedback ? `<div class="muted" style="margin-top:6px">Employee feedback: ${t.feedback.helpful ? "helpful" : "not helpful"}</div>` : ""}
    </div>
    <div class="tiles">${tiles}</div>

    <div class="panel"><h2>Time per stage</h2><div class="water">${water}</div>
      <div class="muted mono" style="margin-top:8px">path: ${t.trajectory.join(" → ")}</div></div>

    <div class="panel"><h2><span class="n">1</span>Question understanding</h2>
      ${t.history.length ? `<div class="muted">History: ${t.history.map((h) => `<b>${h.role}</b> ${esc(h.text)}`).join(" · ")}</div>` : ""}
      <dl class="kv" style="margin-top:6px">${t.queries.map((q, i) => `<dt>${i === 0 ? "original" : "rewritten"}</dt><dd>${esc(q)}</dd>`).join("")}</dl>
      ${t.queries.length === 1 ? `<div class="muted" style="margin-top:6px">${t.history.length ? "The rewrite returned the same question." : "No chat history, so the rewrite step was skipped."}</div>` : ""}</div>

    <div class="panel"><h2><span class="n">2</span>Retrieval: which chunks were fetched</h2>
      <p class="lead">Keyword search (BM25) and vector search each rank the chunks. RRF fuses the two lists into candidates, the reranker scores them, and the top ${cfg.top_k} go to the model.</p>
      <div class="scroll"><table><thead><tr><th></th><th>Chunk</th><th>Document › section</th><th class="num">BM25 rank</th><th class="num">BM25</th><th class="num">Vector rank</th><th class="num">Cosine</th><th class="num">RRF</th><th class="num">Rerank</th></tr></thead><tbody>
      ${t.candidates.map((c) => `<tr class="${c.selected ? "sel" : "dim"}"><td>${c.selected ? "●" : ""}${gold && gold.expected_docs && gold.expected_docs.includes(c.doc) && (!gold.expected_section || gold.expected_section === c.section) ? " ★" : ""}</td>
        <td class="mono">${c.chunk_id}</td><td><details><summary style="color:inherit;font-size:13px">${esc(c.title)} › ${esc(c.section)}</summary><pre>${esc(c.text)}</pre></details></td>
        <td class="num">${c.bm25_rank ?? "–"}</td><td class="num">${num(c.bm25_score, 2)}</td><td class="num">${c.vector_rank ?? "–"}</td><td class="num">${num(c.vector_score)}</td><td class="num">${num(c.rrf_score, 4)}</td><td class="num"><b>${num(c.rerank_score)}</b></td></tr>`).join("")}
      </tbody></table></div>
      <div class="muted" style="margin-top:8px">● sent to the model${gold && gold.expected_docs ? " · ★ the section the golden set expects" + (gold.retrieved_rank ? ` (found at rank ${gold.retrieved_rank})` : gold.candidate_rank ? ` (only in the candidate pool, rank ${gold.candidate_rank})` : " (not retrieved)") : ""}</div></div>

    <div class="panel"><h2><span class="n">3</span>Gate: answer or refuse early</h2>
      <div class="gate"><div class="fill" style="width:${((sc.top_score || 0) / maxScore) * 100}%;background:var(--${sc.score_margin >= 0 ? "good" : "warn"}-soft)"></div>
        <div class="floor" style="left:${(cfg.score_floor / maxScore) * 100}%"><span>floor ${num(cfg.score_floor)}</span></div></div>
      <div>Top score <b>${num(sc.top_score)}</b> is ${sc.score_margin >= 0 ? "above" : "below"} the floor of ${num(cfg.score_floor)} <span class="muted">(floor set by ${esc(cfg.score_floor_source)})</span>. ${sc.score_margin >= 0 ? "The model is called." : "Refused without calling the model: no tokens spent."}</div></div>

    <div class="panel"><h2><span class="n">4</span>Model generation</h2>
      ${g ? `<dl class="kv"><dt>model</dt><dd class="mono">${esc(g.model)}</dd><dt>tokens</dt><dd>${g.prompt_tokens} prompt · ${g.output_tokens} output</dd>
        <dt>speed</dt><dd>${g.tokens_per_s} tokens/s · ${ms(g.gen_ms)} generating${g.load_ms > 50 ? ` · ${ms(g.load_ms)} loading the model` : ""}</dd>
        <dt>output format</dt><dd>${g.json_ok ? badge("valid JSON", "good") : badge("invalid JSON", "bad")} ${g.model_status ? `model status: <span class="mono">${esc(g.model_status)}</span>` : ""}</dd></dl>
        <details style="margin-top:10px" open><summary>Raw model output</summary><pre>${esc(g.raw)}</pre></details>
        <details style="margin-top:8px"><summary>Full prompt sent to the model</summary><pre>${esc(g.prompt)}</pre></details>`
      : `<div class="muted">The model was not called for this question.</div>`}</div>

    <div class="panel"><h2><span class="n">5</span>Ground check: is each claim in its source?</h2>
      ${t.claims.length ? `<div class="scroll"><table><thead><tr><th>Claim</th><th>Cites</th><th>Numbers</th><th class="num">Word support</th><th>Verdict</th></tr></thead><tbody>
        ${t.claims.map((c) => `<tr><td>${esc(c.text)}</td><td class="mono">${esc(c.source_id)}${c.chunk_id ? " → " + c.chunk_id : ""}</td>
          <td>${c.numbers_ok ? badge("all in source", "good") : badge("not in source: " + c.bad_numbers.join(", "), "bad")}</td>
          <td class="num">${pct(c.support)}</td><td>${c.kept ? badge("kept", "good") : badge("dropped: " + c.reason, "bad")}</td></tr>`).join("")}
        </tbody></table></div><div class="muted" style="margin-top:8px">A claim is kept when every number in it appears in the cited chunk and at least ${pct(cfg.support_floor)} of its content words do.</div>`
      : `<div class="muted">No claims to check.</div>`}</div>

    <div class="panel"><h2><span class="n">6</span>Accuracy against the golden set</h2>
      ${gold ? `<dl class="kv"><dt>case</dt><dd class="mono">${gold.case_id} (${gold.type})</dd><dt>expected</dt><dd>${gold.type === "out_of_scope" ? "a refusal" : "answer contains “" + esc(gold.expected) + "”"}</dd>
        ${gold.expected_docs ? `<dt>expected source</dt><dd>${esc(gold.expected_docs.join(", "))} › ${esc(gold.expected_section || "any section")}</dd>
        <dt>retrieval</dt><dd>${gold.retrieved_rank ? badge("found at rank " + gold.retrieved_rank, "good") : badge("expected section not in top " + cfg.top_k, "bad")}</dd>
        <dt>citation</dt><dd>${gold.cited_expected ? badge("cites the expected document", "good") : badge("does not cite it", "warn")}</dd>` : ""}
        <dt>result</dt><dd>${gold.passed ? badge("pass", "good") : badge("fail", "bad")}</dd></dl>`
      : `<div class="muted">This question is not in the golden set, so there is no known right answer to compare with. Add it to <span class="mono">evals/golden.json</span> to track it.</div>`}</div>

    <div class="panel"><h2><span class="n">7</span>Audit log</h2>
      <dl class="kv"><dt>hash</dt><dd class="mono">${t.audit.hash}</dd><dt>previous</dt><dd class="mono">${t.audit.prev_hash}</dd>
      <dt>settings</dt><dd class="mono">top_k=${cfg.top_k} candidates=${cfg.candidates} rewrite=${cfg.rewrite} embedding=${esc(t.models.embedding)}</dd></dl></div>`;
}

// ------------------------------------------------------------------ Evals
const METRICS = [
  ["recall_at_k", "Recall@k", "expected section is in the chunks sent to the model"],
  ["answer_accuracy", "Answer accuracy", "answer contains the expected value"],
  ["groundedness", "Groundedness", "claims supported by their source"],
  ["refusal_rate", "Refusal rate", "out-of-scope questions refused"],
  ["false_refusal_rate", "False refusals", "in-scope questions not answered"],
  ["trajectory_match", "Path match", "pipeline took the expected steps"],
  ["candidate_recall", "Candidate recall", "expected section reached the candidate pool"],
  ["mrr", "MRR", "how high the expected section ranks"],
  ["citation_accuracy", "Citation accuracy", "answers citing the expected document"],
  ["refused_at_gate", "Refused at gate", "refusals that cost no tokens"],
];

async function renderEvals(runId) {
  const runs = await api("/api/evals");
  const status = await api("/api/evals/status");
  const id = runId || (runs[0] && runs[0].id);
  const run = id ? await api("/api/evals/" + id).catch(() => null) : null;
  view.innerHTML = `
    <div class="row" style="justify-content:space-between"><div><h1>Evals</h1>
      <p class="lead">The golden set runs through the same pipeline as live questions: ${golden.filter((g) => g.type === "in_scope").length} in-scope, ${golden.filter((g) => g.type === "follow_up").length} follow-up and ${golden.filter((g) => g.type === "out_of_scope").length} out-of-scope questions. Each case leaves a trace you can open.</p></div>
      <div class="row"><button class="ghost" id="cal">Recalibrate score floor</button><button id="runbtn" ${status.running ? "disabled" : ""}>Run golden set</button></div></div>
    <div id="prog"></div>
    ${run ? evalBody(run) : `<div class="panel empty">No evaluation run yet. Press “Run golden set”.</div>`}
    ${runs.length ? `<div class="panel"><h2>Run history</h2><div class="scroll"><table><thead><tr><th>Run</th><th>When</th><th>Models</th><th>Gates</th><th class="num">Recall@k</th><th class="num">Accuracy</th><th class="num">Grounded</th><th class="num">Refusal</th><th class="num">p95 total</th></tr></thead><tbody>
      ${runs.map((r) => `<tr class="click ${r.id === id ? "sel" : ""}" data-run="${r.id}"><td class="mono">${r.id}</td><td>${new Date(r.ts * 1000).toLocaleString()}</td><td class="mono">${esc(r.models.generation)} · ${esc(r.models.embedding)}</td>
        <td>${r.passed ? badge("pass", "good") : badge("fail", "bad")}</td><td class="num">${pct(r.metrics.recall_at_k)}</td><td class="num">${pct(r.metrics.answer_accuracy)}</td><td class="num">${pct(r.metrics.groundedness)}</td><td class="num">${pct(r.metrics.refusal_rate)}</td><td class="num">${ms(r.latency_ms.total.p95)}</td></tr>`).join("")}
      </tbody></table></div></div>` : ""}`;
  view.querySelectorAll("[data-run]").forEach((el) => (el.onclick = () => (location.hash = "#/evals/" + el.dataset.run)));
  view.querySelectorAll("[data-trace]").forEach((el) => (el.onclick = () => (location.hash = "#/monitor/" + el.dataset.trace)));
  const only = $("#onlyfail"); if (only) only.onchange = () => view.querySelectorAll("tr[data-pass='1']").forEach((tr) => (tr.style.display = only.checked ? "none" : ""));
  $("#cal").onclick = async () => { const c = await api("/api/calibrate", {}); alert(`Score floor set to ${c.floor}\nweakest in-scope ${c.in_scope_min} · strongest out-of-scope ${c.out_of_scope_max}`); };
  const poll = () => { window._poll = setInterval(async () => {
    const s = await api("/api/evals/status");
    $("#prog").innerHTML = s.running ? `<div class="panel">Running case ${s.done} of ${s.total}…<div class="bar"><i style="width:${(s.done / Math.max(s.total, 1)) * 100}%"></i></div></div>` : s.error ? `<div class="panel">${badge("error", "bad")} ${esc(s.error)}</div>` : "";
    if (!s.running) { clearInterval(window._poll); if (!s.error) { if (location.hash === "#/evals") renderEvals(); else location.hash = "#/evals"; } }
  }, 400); };
  $("#runbtn").onclick = async () => { $("#runbtn").disabled = true; await api("/api/evals/run", {}); poll(); };
  if (status.running) poll();
}

function evalBody(run) {
  const m = run.metrics, gates = run.gates;
  const tile = ([key, label, help]) => {
    const g = gates[key] || gates[key + "_max"];
    const lower = (key + "_max") in gates;
    return `<div class="tile ${g ? (g.passed ? "good" : "bad") : ""}"><div class="k">${label}</div><div class="v">${["mrr"].includes(key) ? num(m[key], 2) : pct(m[key])}</div>
      <div class="s">${help}${g ? `<br>gate ${lower ? "≤" : "≥"} ${pct(g.limit)} · ${g.passed ? "pass" : "FAIL"}` : ""}</div></div>`;
  };
  const stages = Object.entries(run.latency_ms);
  const worst = Math.max(...stages.map(([, v]) => v.p95), 0.01);
  return `
    <div class="panel"><div class="row"><b class="mono">${run.id}</b> ${run.passed ? badge("all gates pass", "good") : badge("a gate failed", "bad")}
      <span class="muted">${new Date(run.ts * 1000).toLocaleString()} · ${esc(run.provider)} · ${esc(run.models.generation)} · ${esc(run.models.embedding)} · top_k ${run.config.top_k} · floor ${num(run.config.score_floor)}</span></div></div>
    <div class="tiles">${METRICS.map(tile).join("")}</div>
    <div class="panel"><h2>Latency per stage</h2><div class="water" style="grid-template-columns:90px 1fr 170px">
      ${stages.map(([name, v]) => `<div class="mono">${name}</div><div class="track"><div class="fill" style="left:0;width:${(v.p95 / worst) * 100}%;opacity:.45"></div><div class="fill" style="left:0;width:${(v.p50 / worst) * 100}%"></div></div><div class="mono" style="text-align:right">p50 ${ms(v.p50)} · p95 ${ms(v.p95)}</div>`).join("")}</div>
      <div class="muted" style="margin-top:8px">Solid bar is the median, the lighter bar reaches the 95th percentile.</div></div>
    <div class="panel"><div class="row" style="justify-content:space-between"><h2>Cases</h2><label class="muted"><input type="checkbox" id="onlyfail"> failures only</label></div>
      <div class="scroll"><table><thead><tr><th>Case</th><th>Question</th><th>Result</th><th>Expected</th><th>Answer</th><th class="num">Found at</th><th class="num">Top score</th><th class="num">Time</th></tr></thead><tbody>
      ${run.cases.map((c) => `<tr class="click" data-trace="${c.trace_id}" data-pass="${c.passed ? 1 : 0}"><td class="mono">${c.id}</td><td>${esc(c.q)}</td>
        <td>${c.passed ? badge("pass", "good") : badge("fail", "bad")}${c.trajectory_ok ? "" : " " + badge("path", "warn")}</td><td>${esc(c.expected)}</td>
        <td>${c.status === "answered" ? esc(c.answer) : `<span class="muted">${esc(c.status)}: ${esc(c.reason)}</span>`}</td>
        <td class="num">${c.type === "out_of_scope" ? "" : c.retrieved_rank ? "#" + c.retrieved_rank : "miss"}</td><td class="num">${num(c.top_score)}</td><td class="num">${ms(c.ms)}</td></tr>`).join("")}
      </tbody></table></div><div class="muted" style="margin-top:8px">Click a row to open its trace in the monitor.</div></div>`;
}

boot();
