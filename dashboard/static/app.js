"use strict";

const $ = id => document.getElementById(id);
const euro = new Intl.NumberFormat("de-DE", {style: "currency", currency: "EUR"});
const signedEuro = new Intl.NumberFormat("de-DE", {style: "currency", currency: "EUR", signDisplay: "exceptZero"});
const percent = new Intl.NumberFormat("de-DE", {style: "percent", maximumFractionDigits: 2});
const number = new Intl.NumberFormat("de-DE", {maximumFractionDigits: 8});
const date = new Intl.DateTimeFormat("de-DE", {timeZone: "UTC", day: "2-digit", month: "2-digit", year: "numeric"});
const shortDate = new Intl.DateTimeFormat("de-DE", {timeZone: "UTC", day: "2-digit", month: "2-digit"});
const dateTime = new Intl.DateTimeFormat("de-DE", {timeZone: "UTC", day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit"});
const variantNames = {original: "Ursprüngliche Variante", net_reward: "Nettoziel-Filter", buy_hold: "Kaufen & Halten", cash: "Nicht handeln"};
variantNames.slow_unfiltered = "Ausbruch · festes Ziel ohne Nettofilter";
variantNames.slow_trailing = "Ausbruch · nachgezogener Stop";
variantNames.slow_breakout = "Langsamer Ausbruch";
variantNames.trend_pullback = "Rücksetzer im Aufwärtstrend";
const groupNames = {before_gap: "Vor der Datenlücke", after_gap: "Nach der Datenlücke", development: "Entwicklung", holdout: "Ehemaliger Holdout"};
const exitNames = {STOP_LOSS: "Stop-Loss", STOP_GAP: "Stop bei Kurslücke", TAKE_PROFIT: "Kursziel erreicht", TAKE_PROFIT_GAP: "Kursziel am Open", STOP_FIRST_AMBIGUOUS_BAR: "Stop vor Kursziel", END_OF_DATA: "Zeitraum beendet"};
const reasonNames = {
  "Maximum position count reached.": "Bereits eine Position offen",
  "Allowed size is below the simulation minimum after rounding.": "Zulässige Position unter Mindestgröße",
  "Net reward at target is below the required stop risk multiple.": "Nettoziel deckt das Stop-Risiko nicht",
  "Take profit must exceed the simulated entry fill.": "Kursziel liegt nicht über dem Einstieg",
  "Only cash-funded LONG entries are supported; HOLD/SHORT cannot open positions.": "Kein Kaufsignal – es wird abgewartet",
  "No following candle available; signal not executed.": "Keine nächste Kerze im Testzeitraum",
  "Drawdown limit reached; entries halted for this session.": "Maximaler Kontorückgang erreicht",
  "Daily loss limit reached; entries halted for this UTC day.": "Tagesverlustgrenze erreicht",
  "No remaining loss budget after existing portfolio risk.": "Kein verbleibendes Risikobudget",
  "Stop-based position size includes entry/exit fees, spread, slippage and rounding.": "Positionsgröße berücksichtigt Stop und sämtliche Kosten",
  "Per-trade, total, daily, drawdown, cash and position limits passed.": "Alle gewöhnlichen Risikogrenzen eingehalten",
  "Net reward/risk filter passed.": "Nettoziel deckt das geplante Stop-Risiko",
  "Stop must be below the current entry reference after rounding.": "Stop liegt nicht unter dem Einstiegskurs",
  "Kill switch is active.": "Handelssperre aktiv"
};
reasonNames["No observed trades in following interval; entry signal expired."] = "Keine belegten Trades im Folgeintervall – Einstiegssignal verfallen";
const state = {studies: [], study: null, group: null, run: null, view: "overview", tradePage: 0, signalPage: 0, runVersion: 0, tradeVersion: 0, signalVersion: 0, catalogVersion: 0};
const text = (id, value) => { $(id).textContent = value; };
const money = value => value === null || value === undefined ? "—" : euro.format(Number(value));
const pct = value => value === null || value === undefined ? "—" : percent.format(Number(value));
function reason(value) {
  if (reasonNames[value]) return reasonNames[value];
  const net = /^Net reward\/unit=([^;]+); stop risk\/unit=([^;]+); required reward\/risk=([^;]+); evaluated at next-open reference=(.+)\.$/.exec(value || "");
  if (net) return `Je BTC: ${money(net[1])} Nettoziel gegenüber ${money(net[2])} geplantem Stop-Verlust. Erforderliches Verhältnis: ${net[3]}:1. Einstiegskurs vor Kosten: ${money(net[4])}.`;
  const warmup = /^Warm-up: (\d+)\/(\d+) closed candles available\./.exec(value || "");
  if (warmup) return `Aufwärmphase: ${warmup[1]} von ${warmup[2]} abgeschlossenen Kerzen vorhanden.`;
  return value || "Keine Begründung gespeichert";
}
const el = (tag, value, className) => { const node = document.createElement(tag); if (value !== undefined) node.textContent = value; if (className) node.className = className; return node; };
function signed(node, value) { node.textContent = signedEuro.format(Number(value)); node.classList.toggle("negative", Number(value) < 0); node.classList.toggle("positive", Number(value) > 0); }
function options(id, values, selected) { $(id).replaceChildren(...values.map(([value, label, disabled]) => { const option = el("option", label); option.value = value; option.disabled = !!disabled; return option; })); if (values.some(v => v[0] === selected && !v[2])) $(id).value = selected; }
async function api(path, query = {}) { const response = await fetch(`/api/${path}?${new URLSearchParams(query)}`, {cache: "no-store"}); const body = await response.json(); if (!response.ok) throw new Error(body.error || "Daten konnten nicht geladen werden."); return body; }

async function loadCatalog() {
  const version = ++state.catalogVersion;
  ++state.runVersion;
  state.run = null;
  $("refresh").disabled = true;
  $("workspace").hidden = true;
  $("global-state").hidden = false;
  $("report-link").hidden = true;
  text("global-state", "Forschungsergebnisse werden geladen …");
  try {
    const {studies} = await api("catalog");
    if (version !== state.catalogVersion) return;
    state.studies = studies;
    const available = studies.filter(s => !s.unavailable);
    if (!available.length) { text("global-state", studies.length ? "Die vorhandenen Auswertungen sind unvollständig oder nicht lesbar. Die Forschungsdateien bleiben unverändert." : "Noch keine abgeschlossenen Forschungsberichte vorhanden. Nach einer Auswertung erscheinen die Ergebnisse hier."); return; }
    const selected = available.some(s => s.id === $("study").value) ? $("study").value : available[0].id;
    options("study", studies.map(s => [s.id, s.unavailable ? `${s.title} · nicht verfügbar` : s.subtitle, s.unavailable]), selected);
    $("workspace").hidden = false;
    $("global-state").hidden = true;
    selectStudy();
  } catch (error) { text("global-state", `${error.message} Mit „Neu laden“ erneut versuchen.`); }
  finally { if (version === state.catalogVersion) $("refresh").disabled = false; }
}

function selectStudy() {
  state.study = state.studies.find(s => s.id === $("study").value);
  text("timeframe-label", `${state.study.timeframe_label} · ${state.study.quote_label || "EUR"} · Zeiten in UTC`);
  $("report-link").href = `/api/report?study=${encodeURIComponent(state.study.id)}`;
  $("report-link").hidden = false;
  for (const id of ["group", "cost", "variant"]) $(id).disabled = !!(state.study.blocked || state.study.report_only);
  if (state.study.blocked || state.study.report_only) {
    ++state.runVersion; ++state.tradeVersion; ++state.signalVersion;
    state.run = null; state.group = null;
    const label = state.study.report_only ? "Abgeschlossener Bericht" : "Noch nicht ausgewertet";
    options("group", [["", label]]);
    options("variant", [["", label]]);
    options("cost", [["", label]]);
    text("period-label", state.study.period_label);
    $("run-content").hidden = true;
    $("run-state").hidden = false;
    text("run-state", state.study.finding_note);
    return;
  }
  options("cost", Object.entries(state.study.cost_names), state.study.default_cost);
  options("group", state.study.groups.map(g => [g.id, `${shortDate.format(new Date(g.start))}–${shortDate.format(new Date(new Date(g.end).getTime() - 1))} · ${groupNames[g.id] || g.id}`]), state.study.groups.at(-1).id);
  selectGroup();
}
function selectGroup() {
  state.group = state.study.groups.find(g => g.id === $("group").value);
  const variants = [...new Set(state.group.runs.map(r => r.variant))];
  options("variant", variants.map(v => [v, variantNames[v] || v]), variants.includes("net_reward") ? "net_reward" : variants[0]);
  loadRun();
}
async function loadRun() {
  const version = ++state.runVersion;
  ++state.tradeVersion; ++state.signalVersion;
  state.run = null;
  state.tradePage = 0; state.signalPage = 0;
  $("run-content").hidden = true;
  $("run-state").hidden = false;
  text("run-state", "Kontoverlauf und Entscheidungen werden geladen …");
  const chosen = state.group.runs.find(r => r.variant === $("variant").value && r.cost_scenario === $("cost").value);
  text("period-label", `${dateTime.format(new Date(state.group.start))} – ${dateTime.format(new Date(state.group.end))} (Ende exklusiv)`);
  try {
    if (!chosen) throw new Error("Diese Kombination wurde nicht ausgewertet.");
    const run = await api("run", {run: chosen.id});
    if (version !== state.runVersion) return;
    state.run = run;
    $("run-state").hidden = true;
    $("run-content").hidden = false;
    renderOverview();
    switchView(state.view);
  } catch (error) { if (version === state.runVersion) text("run-state", error.message); }
}

function renderOverview() {
  const run = state.run, p = run.performance;
  text("capital", money(run.final_equity));
  text("initial", `${money(run.initial_capital)} Startkapital · eigenes Konto`);
  signed($("net"), p.net_profit);
  text("return", `${pct(p.return_fraction)} Rendite im gewählten Zeitraum`);
  text("trade-count", p.trades);
  text("wins", `${p.wins} ${p.wins === 1 ? "Gewinn" : "Gewinne"} · ${p.losses} ${p.losses === 1 ? "Verlust" : "Verluste"} · ${p.breakeven} unverändert`);
  text("drawdown", pct(p.max_drawdown));
  text("fees", money(p.fees)); text("expectancy", money(p.expectancy)); text("win-rate", pct(p.win_rate));
  text("sample-note", p.trades === 0 ? "Keine ausgeführten Trades. Ein unverändertes Konto belegt keinen Handelsvorteil." : "Die Stichprobe ist klein. Das Ergebnis allein belegt keinen verlässlichen Handelsvorteil.");
  text("finding-title", state.study.finding_title || (state.study.segmented ? (state.study.screen_passed ? "Vorab festgelegte Sichtung bestanden" : "Vorab festgelegte Sichtung nicht bestanden") : "Erste Hypothese: keine Bestätigung"));
  text("finding-text", state.study.finding_note);
  renderChart(run);
  const comparison = $("comparison"); comparison.replaceChildren();
  const references = state.group.benchmarks[$("cost").value] || {};
  const rows = state.group.runs.filter(r => r.cost_scenario === $("cost").value).map(r => ({key: r.variant, performance: r.performance, selected: r.id === run.id}));
  for (const key of ["buy_hold", "cash"]) if (references[key]) rows.push({key, performance: references[key].performance});
  for (const row of rows) {
    const line = el("div", undefined, "comparison-row"); const name = el("div", variantNames[row.key] || row.key, "comparison-name");
    if (row.selected) name.append(el("span", "Ausgewählt", "current-label"));
    name.append(el("small", `${row.performance.trades} ${row.performance.trades === 1 ? "Trade" : "Trades"} · ${pct(row.performance.max_drawdown)} max. Rückgang`));
    const value = el("strong"); signed(value, row.performance.net_profit); line.append(name, value); comparison.append(line);
  }
  text("compare-cost", $("cost").selectedOptions[0].textContent);
  text("benchmark-note", Object.keys(references).length ? "Kaufen & Halten: voll investiert, ohne Schutzstops oder Verlustlimits. Die Risiken und die Kapitalbindung unterscheiden sich." : "Für diesen Versuch wurden keine zusätzlichen Benchmarks gespeichert.");
  $("signal-summary").replaceChildren(...[[run.long_signals, "Kaufsignale"], [run.approved_entries, "Freigaben"], [run.signal_counts.HOLD || 0, "Abwarten"]].map(([count, label]) => { const box = el("div"); box.append(el("strong", number.format(count)), el("span", label)); return box; }));
  const reasons = Object.entries(run.rejected_entry_reasons).sort((a, b) => b[1] - a[1]);
  $("rejections").replaceChildren(...reasons.map(([key, count]) => { const line = el("div", undefined, "rejection"); line.append(el("span", reason(key)), el("strong", number.format(count))); return line; }));
  if (!reasons.length) $("rejections").append(el("p", "Keine abgelehnten Kaufsignale in diesem Lauf.", "footnote"));
}

function renderChart(run) {
  const points = run.equity.map(r => ({x: Date.parse(r.timestamp), y: Number(r.value)}));
  const ns = "http://www.w3.org/2000/svg";
  function svgNode(tag, attrs, value) { const node = document.createElementNS(ns, tag); for (const [key, val] of Object.entries(attrs)) node.setAttribute(key, val); if (value !== undefined) node.textContent = value; return node; }
  const width = Math.max(280, $("chart").getBoundingClientRect().width || 650);
  const height = window.matchMedia("(max-width:640px)").matches ? 205 : 240;
  const floor = height - 35, right = width - 10;
  const svg = svgNode("svg", {viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `Virtuelles Kapital von ${money(run.initial_capital)} auf ${money(run.final_equity)}. Maximaler Rückgang ${pct(run.performance.max_drawdown)}.`});
  const lo = Math.min(...points.map(p => p.y)), hi = Math.max(...points.map(p => p.y));
  const pad = Math.max(hi - lo, 15) * .13, bottom = lo - pad, top = hi + pad;
  const first = Date.parse(run.start), last = Date.parse(run.end);
  const x = value => 48 + (value - first) / Math.max(1, last - first) * (right - 48);
  const y = value => 15 + (top - value) / (top - bottom) * (floor - 15);
  for (let i = 0; i < 4; i++) {
    const value = bottom + (top - bottom) * i / 3, pos = y(value);
    svg.append(svgNode("line", {x1: 48, x2: right, y1: pos, y2: pos, class: "chart-grid"}));
    svg.append(svgNode("text", {x: 40, y: pos + 4, "text-anchor": "end", class: "chart-label"}, new Intl.NumberFormat("de-DE", {maximumFractionDigits: 0}).format(value)));
  }
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(p.x).toFixed(2)},${y(p.y).toFixed(2)}`).join(" ");
  svg.append(svgNode("path", {d: `${path} L${x(points.at(-1).x)},${floor} L${x(points[0].x)},${floor} Z`, class: "chart-area"}));
  svg.append(svgNode("line", {x1: 48, x2: right, y1: y(Number(run.initial_capital)), y2: y(Number(run.initial_capital)), class: "chart-baseline"}));
  svg.append(svgNode("path", {d: path, class: "chart-line"}));
  for (const [value, anchor] of [[first, "start"], [(first + last) / 2, "middle"], [last, "end"]]) svg.append(svgNode("text", {x: x(value), y: height - 8, "text-anchor": anchor, class: "chart-label"}, date.format(new Date(value))));
  $("chart").replaceChildren(svg);
  text("chart-caption", `${number.format(run.observation_count)} gespeicherte Kontobewertungen, für die Ansicht verdichtet. Extremwerte bleiben erhalten. Gestrichelt: Startkapital. Keine Tickdaten.`);
}

function switchView(view) {
  state.view = view;
  for (const button of document.querySelectorAll("[data-view]")) { const active = button.dataset.view === view; button.classList.toggle("active", active); if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current"); }
  for (const name of ["overview", "trades", "signals"]) $(`${name}-view`).hidden = name !== view;
  const titles = {overview: ["Forschungsübersicht", "Was die bisherigen Versuche zeigen."], trades: ["Trades im Detail", "Jede Position mit ihrem Ergebnis und ihren Gründen."], signals: ["Entscheidungen verstehen", "Vom beobachteten Signal zur Freigabe oder Ablehnung."]};
  text("page-title", titles[view][0]); text("page-subtitle", titles[view][1]);
  if (state.run && view === "trades") loadTrades();
  if (state.run && view === "signals") loadSignals();
}
function pageState(prefix, result) {
  const {page, page_size: size, total} = result;
  text(`${prefix}-page-label`, total ? `${page * size + 1}–${Math.min((page + 1) * size, total)} von ${number.format(total)}` : "0 Einträge");
  $(`${prefix}-prev`).disabled = page === 0; $(`${prefix}-next`).disabled = (page + 1) * size >= total;
}
function startTable(prefix) { text(`${prefix}-state`, "Einträge werden geladen …"); $(`${prefix}-rows`).replaceChildren(); $(`${prefix}-table`).hidden = true; $(`${prefix}-prev`).disabled = true; $(`${prefix}-next`).disabled = true; text(`${prefix}-page-label`, ""); }
async function loadTrades() {
  const version = ++state.tradeVersion, runVersion = state.runVersion, run = state.run;
  if (!run) return;
  startTable("trade");
  try {
    const result = await api("trades", {run: run.id, page: state.tradePage, outcome: $("outcome").value});
    if (version !== state.tradeVersion || runVersion !== state.runVersion) return;
    text("trade-state", result.items.length ? "" : (Number(run.performance.trades) === 0 ? "In diesem Lauf wurde kein Trade eröffnet. Unter Entscheidungen siehst du die Ablehnungsgründe." : "Keine Trades für diesen Ergebnisfilter."));
    $("trade-table").hidden = !result.items.length;
    for (const item of result.items) {
      const row = el("tr"); const button = el("button", "Details"); button.setAttribute("aria-label", `Trade vom ${dateTime.format(new Date(item.position.opened_at))} ansehen`); button.addEventListener("click", () => showTrade(item));
      const action = el("td"); action.append(button); const net = el("td"); signed(net, item.net_pnl);
      row.append(el("td", dateTime.format(new Date(item.position.opened_at))), el("td", exitNames[item.exit_reason] || item.exit_reason), el("td", number.format(Number(item.position.quantity))), el("td", money(item.fees)), net, action); $("trade-rows").append(row);
    }
    pageState("trade", result);
  } catch (error) { if (version === state.tradeVersion && runVersion === state.runVersion) text("trade-state", error.message); }
}
async function loadSignals() {
  const version = ++state.signalVersion, runVersion = state.runVersion, run = state.run;
  if (!run) return;
  startTable("signal");
  try {
    const result = await api("signals", {run: run.id, page: state.signalPage, decision: $("decision").value, direction: $("direction").value});
    if (version !== state.signalVersion || runVersion !== state.runVersion) return;
    text("signal-state", result.items.length ? "" : "Keine Signale für diese Auswahl."); $("signal-table").hidden = !result.items.length;
    for (const item of result.items) {
      const row = el("tr"), signal = item.signal, decision = item.decision;
      const status = el("td"); status.append(el("span", decision.allowed ? "Freigegeben" : "Nicht freigegeben", `badge${decision.allowed ? " allowed" : ""}`));
      const action = el("td"), button = el("button", "Details"); button.setAttribute("aria-label", `Signal vom ${dateTime.format(new Date(signal.timestamp))} ansehen`); button.addEventListener("click", () => showSignal(item)); action.append(button);
      row.append(el("td", dateTime.format(new Date(signal.timestamp))), el("td", signal.direction === "LONG" ? "Kaufen" : "Abwarten"), status, el("td", reason(decision.reasons[0]), "reason-cell"), action); $("signal-rows").append(row);
    }
    pageState("signal", result);
  } catch (error) { if (version === state.signalVersion && runVersion === state.runVersion) text("signal-state", error.message); }
}

function facts(entries) { const list = el("dl", undefined, "facts"); for (const [label, value] of entries) { const line = el("div"); line.append(el("dt", label), el("dd", value)); list.append(line); } return list; }
function reasonList(title, reasons) { const section = el("section"); section.append(el("h3", title)); const list = el("ul"); list.append(...reasons.map(r => el("li", r))); section.append(list); return section; }
exitNames.TRAILING_STOP = "Nachgezogener Stop erreicht";
exitNames.TRAILING_STOP_GAP = "Kurslücke unter dem nachgezogenen Stop";

function originalDetails(reasons) { const details = el("details"); details.append(el("summary", "Gespeicherte Originalbegründungen"), reasonList("Originalprotokoll", reasons)); return details; }
function signalSummaries(reasons) {
  const names = {Trend: "Trend", Breakout: "Ausbruch", Pullback: "Rücksetzer", Momentum: "Momentum", Volume: "Volumen"};
  return reasons.map(r => { const match = /^(PASS|FAIL) (Trend|Breakout|Pullback|Momentum|Volume):/.exec(r); return match ? `${names[match[2]]}: ${match[1] === "PASS" ? "Bedingung erfüllt" : "Bedingung nicht erfüllt"}` : r.startsWith("Warm-up:") ? reason(r) : reasonNames[r]; }).filter(Boolean);
}
function showTrade(item) {
  const p = item.position; text("detail-title", "Trade nachvollziehen");
  $("detail-content").replaceChildren(facts([["Einstieg · UTC", dateTime.format(new Date(p.opened_at))], ["Ausstieg · UTC", dateTime.format(new Date(item.closed_at))], ["Gekaufte Menge", `${number.format(Number(p.quantity))} BTC`], ["Einstieg / Ausstieg", `${money(p.entry_price)} / ${money(item.exit_price)}`], ["Initialer Stop / Kursziel", `${money(p.stop_price)} / ${money(p.take_profit_price)}`], ["Gebühren gesamt", money(item.fees)], ["Ergebnis nach Kosten", money(item.net_pnl)]]), reasonList("Warum wurde eingestiegen?", signalSummaries(item.entry_reasons)), reasonList("Warum wurde geschlossen?", [exitNames[item.exit_reason] || item.exit_reason]), el("p", item.stop_updates?.length ? `Der Stop wurde ${item.stop_updates.length} Mal nachgezogen, zuletzt auf ${money(item.stop_updates.at(-1).new_stop)}. Jede Änderung galt frühestens ab der folgenden Kerze.` : "Der anfängliche Stop wurde nicht nachgezogen.", "footnote"), el("p", "Ein erreichtes Preisziel kann nach Kosten trotzdem Verlust bedeuten. Intrabar-Zeitpunkte sind Modellkonventionen.", "footnote"), originalDetails(item.entry_reasons));
  $("detail-dialog").showModal();
}
function showSignal(item) {
  const {signal, decision} = item; text("detail-title", "Signalentscheidung");
  $("detail-content").replaceChildren(facts([["Zeitpunkt · UTC", dateTime.format(new Date(signal.timestamp))], ["Strategie", `${signal.strategy} · ${signal.strategy_version}`], ["Signal", signal.direction === "LONG" ? "Kaufen" : "Abwarten"], ["Bedingungs-Score", pct(signal.confidence)], ["Risikoprüfung", decision.allowed ? "Freigegeben" : "Nicht freigegeben"], ["Geplantes Risiko", decision.allowed ? money(decision.estimated_loss) : "Kein Einstieg freigegeben"]]), el("p", "Der Score zeigt erfüllte Bedingungen, keine Gewinnwahrscheinlichkeit.", "footnote"), reasonList("Beobachtete Bedingungen", signalSummaries(signal.reasons)), reasonList("Entscheidung der Risikoprüfung", decision.reasons.map(reason)), originalDetails([...signal.reasons, ...decision.reasons]));
  $("detail-dialog").showModal();
}

$("refresh").addEventListener("click", loadCatalog);
$("study").addEventListener("change", selectStudy); $("group").addEventListener("change", selectGroup);
$("variant").addEventListener("change", loadRun); $("cost").addEventListener("change", loadRun);
for (const button of document.querySelectorAll("[data-view]")) button.addEventListener("click", () => switchView(button.dataset.view));
$("see-signals").addEventListener("click", () => switchView("signals"));
$("outcome").addEventListener("change", () => { state.tradePage = 0; loadTrades(); });
for (const id of ["direction", "decision"]) $(id).addEventListener("change", () => { state.signalPage = 0; loadSignals(); });
for (const [prefix, key, load] of [["trade", "tradePage", loadTrades], ["signal", "signalPage", loadSignals]]) {
  $(`${prefix}-prev`).addEventListener("click", () => { state[key] = Math.max(0, state[key] - 1); load(); });
  $(`${prefix}-next`).addEventListener("click", () => { state[key]++; load(); });
}
$("close-detail").addEventListener("click", () => $("detail-dialog").close());
const chartObserver = new ResizeObserver(() => { if (state.run && !$("overview-view").hidden && !$("run-content").hidden) renderChart(state.run); });
chartObserver.observe($("chart"));
loadCatalog();
