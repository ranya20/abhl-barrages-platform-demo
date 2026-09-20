
import { useEffect, useMemo, useState } from "react";
import {
  askAssistant,
  getAssistantMetadata,
  getGuidedBarrageProfile,
  runGuidedAssistantQuery,
} from "../api";

function formatValue(value, digits = 2, unit = "") {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") {
    return `${value.toLocaleString("fr-FR", { maximumFractionDigits: digits })}${unit ? ` ${unit}` : ""}`;
  }
  return value;
}

function SearchSelect({ label, value, onChange, options, getLabel, getValue, placeholder }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const selected = options.find((item) => getValue(item) === value);
  const filtered = options.filter((item) => getLabel(item).toLowerCase().includes(query.toLowerCase())).slice(0, 50);

  return (
    <label className="assistant-field">
      <span>{label}</span>
      <div className="assistant-search-select">
        <input
          value={open ? query : selected ? getLabel(selected) : ""}
          placeholder={placeholder}
          onFocus={() => { setOpen(true); setQuery(""); }}
          onChange={(event) => { setOpen(true); setQuery(event.target.value); }}
        />
        {value && <button type="button" className="assistant-clear" onClick={() => { onChange(""); setQuery(""); setOpen(false); }}>×</button>}
        {open && (
          <div className="assistant-options">
            <button type="button" onClick={() => { onChange(""); setOpen(false); }}>Tous</button>
            {filtered.map((item) => (
              <button type="button" key={getValue(item)} onClick={() => { onChange(getValue(item)); setQuery(""); setOpen(false); }}>
                {getLabel(item)}
              </button>
            ))}
          </div>
        )}
      </div>
    </label>
  );
}

function MiniChart({ chart, rows, columns }) {
  if (!chart || !rows?.length) return null;
  const xKey = chart.x_key;
  const firstY = (chart.y_keys || [])[0];
  if (!firstY) return null;
  const values = rows.map((row) => Number(row[firstY])).filter((value) => Number.isFinite(value));
  if (!values.length) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const label = columns.find((column) => column.key === firstY)?.label || firstY;

  if (chart.type === "bar") {
    return (
      <div className="assistant-chart-card">
        <div className="assistant-chart-title">{label}</div>
        <div className="assistant-bar-chart">
          {rows.slice(0, 30).map((row, index) => {
            const value = Number(row[firstY] || 0);
            const height = Math.max(((value - min) / range) * 100, 4);
            return (
              <div key={`${row[xKey]}-${index}`} className="assistant-bar-item">
                <span style={{ height: `${height}%` }} title={`${row[xKey]} : ${formatValue(value)}`} />
                <small title={String(row[xKey] || "")}>{row[xKey]}</small>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  const points = rows.slice(0, 80).map((row, index, array) => {
    const value = Number(row[firstY] || 0);
    const x = array.length <= 1 ? 50 : (index / (array.length - 1)) * 100;
    const y = 100 - ((value - min) / range) * 86 - 7;
    return `${x},${y}`;
  });

  return (
    <div className="assistant-chart-card">
      <div className="assistant-chart-title">{label}</div>
      <svg className="assistant-line-chart" viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={points.join(" ")} /></svg>
      <div className="assistant-chart-scale"><span>{formatValue(max)}</span><span>{formatValue(min)}</span></div>
    </div>
  );
}

function AssistantDataPage({ initialDate }) {
  const [metadata, setMetadata] = useState(null);
  const [guidedProfile, setGuidedProfile] = useState(null);
  const [question, setQuestion] = useState("");
  const [barrageCode, setBarrageCode] = useState("");
  const [agenceCode, setAgenceCode] = useState("");
  const [startDate, setStartDate] = useState(initialDate || "2026-06-09");
  const [endDate, setEndDate] = useState(initialDate || "2026-06-09");
  const [guidedMetric, setGuidedMetric] = useState("volume");
  const [useLlm, setUseLlm] = useState(true);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getAssistantMetadata()
      .then((data) => {
        setMetadata(data);
        const maxDate = data?.dates?.max;
        if (maxDate && !initialDate) { setStartDate(maxDate); setEndDate(maxDate); }
      })
      .catch((err) => setError(err.message));
  }, [initialDate]);

  useEffect(() => {
    let active = true;
    getGuidedBarrageProfile(barrageCode || "")
      .then((data) => { if (active) setGuidedProfile(data); })
      .catch((err) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [barrageCode]);

  const barrages = metadata?.barrages || [];
  const agences = metadata?.agences || [];
  const columns = result?.columns || [];
  const rows = result?.rows || [];
  const visibleRows = useMemo(() => rows.slice(0, 120), [rows]);
  const selectedBarrage = barrages.find((item) => item.code === barrageCode);

  const selectedMetricLabel = useMemo(() => {
    for (const group of guidedProfile?.metric_groups || []) {
      const item = group.metrics?.find((metric) => metric.code === guidedMetric);
      if (item) return item.label;
    }
    const restitution = guidedProfile?.restitutions?.find((item) => item.code === guidedMetric);
    if (restitution) return restitution.label;
    const special = guidedProfile?.special_metrics?.find((item) => item.code === guidedMetric);
    return special?.label || guidedMetric;
  }, [guidedMetric, guidedProfile]);

  async function submitQuestion(exampleText) {
    const finalQuestion = exampleText || question;
    if (!finalQuestion.trim()) { setError("Écris une question ou utilise la recherche guidée."); return; }
    setLoading(true); setError("");
    try {
      const data = await askAssistant({ question: finalQuestion, use_llm: useLlm });
      setResult(data);
      if (exampleText) setQuestion(exampleText);
    } catch (err) { setError(err.message); setResult(null); }
    finally { setLoading(false); }
  }

  async function submitGuidedSearch() {
    setLoading(true); setError("");
    try {
      const data = await runGuidedAssistantQuery({
        barrage_code: barrageCode || null,
        agence_code: agenceCode || null,
        start_date: startDate || null,
        end_date: endDate || null,
        metric: guidedMetric,
        restitution_type_code: guidedMetric.startsWith("type::") ? guidedMetric.split("::", 2)[1] : null,
        limit: 500,
      });
      setResult(data);
    } catch (err) { setError(err.message); setResult(null); }
    finally { setLoading(false); }
  }

  function exportCsv() {
    if (!rows.length) return;
    const header = columns.map((column) => column.label).join(";");
    const body = rows.map((row) => columns.map((column) => String(row[column.key] ?? "").replaceAll(";", ",")).join(";")).join("\n");
    const blob = new Blob(["\ufeff" + header + "\n" + body], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = "assistant_donnees_abhl.csv"; link.click(); URL.revokeObjectURL(url);
  }

  const modeLabels = result?.mode === "guided_slicers"
    ? ["Slicers contrôlés", "Sans LLM"]
    : result?.mode === "llm_sql_secure"
      ? ["LLM SQL sécurisé", "LLM utilisé"]
      : ["Moteur contrôlé", result?.llm?.used ? "LLM utilisé" : "LLM non utilisé / fallback"];

  return (
    <section className="assistant-page">
      <div className="assistant-hero">
        <div>
          <span className="assistant-kicker">ABHL Intelligence Métier</span>
          <h2>Assistant données barrages</h2>
          <p>Question libre avec LLM, recherche guidée sans LLM. Les réponses viennent de PostgreSQL, avec SQL sécurisé en lecture seule.</p>
        </div>
        <div className="assistant-safety"><span>Chat LLM séparé</span><span>Slicers sans LLM</span><span>PostgreSQL contrôlé</span></div>
      </div>

      <div className="assistant-layout">
        <div className="assistant-chat-card">
          <div className="assistant-card-title"><h3>Question libre</h3><label className="assistant-toggle"><input type="checkbox" checked={useLlm} onChange={(event) => setUseLlm(event.target.checked)} />LLM SQL sécurisé</label></div>
          <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Exemple : Compare le volume de Dar Khrofa entre juin 2026 et juin 2025" />
          <button className="assistant-primary" disabled={loading} onClick={() => submitQuestion()}>{loading ? "Analyse en cours..." : "Demander au chatbot"}</button>
          <div className="assistant-examples">{(metadata?.examples || []).map((example) => <button type="button" key={example} onClick={() => submitQuestion(example)}>{example}</button>)}</div>
        </div>

        <div className="assistant-filter-card assistant-guided-card">
          <div className="assistant-card-title"><div><h3>Recherche guidée</h3><p className="assistant-muted">Slicers contrôlés par PostgreSQL, sans consommation OpenRouter.</p></div><span className="assistant-badge-green">Sans LLM</span></div>
          <div className="assistant-filter-grid">
            <SearchSelect label="Barrage" value={barrageCode} onChange={(code) => { setBarrageCode(code); setGuidedMetric("volume"); }} options={barrages} getLabel={(item) => `${item.nom_court || item.nom} (${item.code})`} getValue={(item) => item.code} placeholder="Écrire pour chercher..." />
            <SearchSelect label="Agence" value={agenceCode} onChange={setAgenceCode} options={agences} getLabel={(item) => item.nom} getValue={(item) => item.code} placeholder="Agence..." />
            <label className="assistant-field"><span>Début</span><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
            <label className="assistant-field"><span>Fin</span><input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
          </div>

          {selectedBarrage && (
            <div className="assistant-barrage-profile">
              <div><span className="assistant-kicker">Barrage sélectionné</span><h4>{selectedBarrage.nom_court || selectedBarrage.nom}</h4><p>{selectedBarrage.nom}</p></div>
              <div className="assistant-profile-stats">
                <span>Code : <b>{selectedBarrage.code}</b></span>
                <span>Agence : <b>{guidedProfile?.barrage?.agence || selectedBarrage.agence_nom || "-"}</b></span>
                {guidedProfile?.barrage?.capacite_normale_mm3 !== undefined && <span>Capacité : <b>{formatValue(guidedProfile.barrage.capacite_normale_mm3, 3, "Mm³")}</b></span>}
                {guidedProfile?.barrage?.cote_normale_ngm !== undefined && <span>Cote normale : <b>{formatValue(guidedProfile.barrage.cote_normale_ngm, 2, "mNGM")}</b></span>}
              </div>
            </div>
          )}

          <div className="assistant-guided-summary"><span>Variable choisie : <b>{selectedMetricLabel}</b></span></div>

          <div className="assistant-guided-groups">
            {(guidedProfile?.metric_groups || []).map((group) => (
              <div key={group.code} className="assistant-guided-group"><h4>{group.label}</h4><div className="assistant-metrics">{(group.metrics || []).map((metric) => <button type="button" key={metric.code} className={guidedMetric === metric.code ? "active" : ""} onClick={() => setGuidedMetric(metric.code)}>{metric.label}</button>)}</div></div>
            ))}
            <div className="assistant-guided-group"><h4>Restitutions détaillées</h4><div className="assistant-metrics">{(guidedProfile?.restitutions || []).map((metric) => <button type="button" key={metric.code} className={guidedMetric === metric.code ? "active" : ""} onClick={() => setGuidedMetric(metric.code)}>{metric.label}</button>)}</div></div>
            <div className="assistant-guided-group"><h4>Utilisation / transfert</h4><div className="assistant-metrics">{(guidedProfile?.special_metrics || []).map((metric) => <button type="button" key={metric.code} className={guidedMetric === metric.code ? "active" : ""} onClick={() => setGuidedMetric(metric.code)}>{metric.label}</button>)}</div></div>
          </div>

          <button className="assistant-secondary" disabled={loading} onClick={submitGuidedSearch}>{loading ? "Recherche en cours..." : "Afficher avec la recherche guidée"}</button>
        </div>
      </div>

      {error && <div className="assistant-alert error">{error}</div>}

      {result && (
        <div className="assistant-results">
          <div className="assistant-answer"><div><span className="assistant-kicker">Réponse contrôlée</span><h3>{result.answer}</h3><p>{result.explanation}</p></div><div className="assistant-mode"><span>{modeLabels[0]}</span><span>{modeLabels[1]}</span></div></div>
          <MiniChart chart={result.chart} rows={rows} columns={columns} />
          <div className="assistant-table-card"><div className="assistant-table-head"><h3>Données vérifiables</h3><div><span>{rows.length} ligne(s)</span><button type="button" onClick={exportCsv} disabled={!rows.length}>Export CSV</button></div></div><div className="assistant-table-wrap"><table><thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{visibleRows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column.key}>{typeof row[column.key] === "number" ? formatValue(row[column.key], column.digits ?? 2, column.unit || "") : row[column.key] ?? "-"}</td>)}</tr>)}</tbody></table></div>{rows.length > visibleRows.length && <p className="assistant-muted">Affichage limité à {visibleRows.length} lignes dans l’interface.</p>}</div>
          <details className="assistant-sql"><summary>Voir la requête SQL sécurisée</summary><pre>{result.sql_used}</pre></details>
        </div>
      )}

      <AssistantStyles />
    </section>
  );
}

function AssistantStyles() {
  return <style>{`
    .assistant-page { display: grid; gap: 18px; color: #15384d; }
    .assistant-hero, .assistant-chat-card, .assistant-filter-card, .assistant-results > *, .assistant-chart-card { border: 1px solid rgba(8, 50, 76, 0.10); border-radius: 22px; background: linear-gradient(135deg, rgba(255,255,255,.95), rgba(246,251,253,.86)); box-shadow: 0 20px 50px rgba(14, 77, 112, .10); }
    .assistant-hero { display: flex; justify-content: space-between; gap: 20px; padding: 22px; }
    .assistant-kicker { display: inline-flex; margin-bottom: 8px; color: #087ea4; font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: .08em; }
    .assistant-hero h2 { margin: 0 0 8px; font-size: 28px; }
    .assistant-hero p { max-width: 760px; margin: 0; color: #5f7584; }
    .assistant-safety, .assistant-mode { display: flex; flex-wrap: wrap; align-content: start; gap: 7px; }
    .assistant-safety span, .assistant-mode span, .assistant-badge-green { border-radius: 999px; padding: 7px 10px; background: rgba(20, 137, 168, .10); color: #075f8d; font-size: 12px; font-weight: 800; }
    .assistant-badge-green { background: rgba(7,139,97,.12); color: #067454; white-space: nowrap; }
    .assistant-layout { display: grid; grid-template-columns: 1fr 1.28fr; gap: 18px; }
    .assistant-chat-card, .assistant-filter-card, .assistant-answer, .assistant-table-card, .assistant-chart-card, .assistant-sql { padding: 18px; }
    .assistant-card-title, .assistant-table-head, .assistant-answer { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
    .assistant-card-title h3, .assistant-table-head h3, .assistant-answer h3 { margin: 0; }
    .assistant-toggle { display: inline-flex; align-items: center; gap: 8px; color: #607684; font-size: 13px; font-weight: 800; }
    .assistant-chat-card textarea { width: 100%; min-height: 116px; margin: 14px 0; border: 1px solid rgba(8,50,76,.16); border-radius: 16px; padding: 13px 14px; font: inherit; resize: vertical; outline: none; }
    .assistant-primary, .assistant-secondary, .assistant-table-head button { border: 0; border-radius: 14px; padding: 11px 15px; cursor: pointer; font-weight: 900; }
    .assistant-primary { color: white; background: linear-gradient(135deg, #075f8d, #20a6c7); }
    .assistant-secondary { color: white; background: linear-gradient(135deg, #0b6b57, #18a684); margin-top: 14px; }
    .assistant-examples, .assistant-metrics { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .assistant-examples button, .assistant-metrics button { border: 1px solid rgba(8,50,76,.12); border-radius: 999px; background: white; color: #38586a; padding: 8px 10px; cursor: pointer; font-size: 12px; font-weight: 800; }
    .assistant-metrics button.active { border-color: rgba(7,95,141,.28); background: #e6f6fb; color: #075f8d; }
    .assistant-filter-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
    .assistant-field { display: grid; gap: 6px; color: #5e7481; font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: .04em; }
    .assistant-field input { width: 100%; border: 1px solid rgba(8,50,76,.14); border-radius: 14px; padding: 11px 12px; font: inherit; text-transform: none; letter-spacing: 0; outline: none; }
    .assistant-search-select { position: relative; }
    .assistant-clear { position: absolute; right: 8px; top: 7px; border: 0; border-radius: 50%; width: 26px; height: 26px; cursor: pointer; }
    .assistant-options { position: absolute; z-index: 30; left: 0; right: 0; top: calc(100% + 6px); max-height: 240px; overflow: auto; border: 1px solid rgba(8,50,76,.13); border-radius: 14px; background: white; box-shadow: 0 18px 35px rgba(8,50,76,.16); }
    .assistant-options button { display: block; width: 100%; border: 0; padding: 10px 12px; background: white; text-align: left; cursor: pointer; }
    .assistant-options button:hover { background: #eef8fb; }
    .assistant-alert { padding: 13px 15px; border-radius: 16px; font-weight: 800; }
    .assistant-alert.error { color: #9a1b1b; background: #fff0f0; }
    .assistant-results { display: grid; gap: 18px; }
    .assistant-answer p { margin: 8px 0 0; color: #657b88; }
    .assistant-barrage-profile { margin: 14px 0 12px; display: grid; grid-template-columns: 1fr 1.25fr; gap: 12px; border: 1px solid rgba(8,50,76,.08); border-radius: 18px; padding: 14px; background: rgba(230,246,251,.42); }
    .assistant-barrage-profile h4 { margin: 0 0 4px; font-size: 18px; }
    .assistant-barrage-profile p { margin: 0; color: #647b88; }
    .assistant-profile-stats { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .assistant-profile-stats span, .assistant-guided-summary span { border-radius: 12px; padding: 8px 10px; background: white; color: #536e7d; font-size: 12px; }
    .assistant-guided-summary { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
    .assistant-guided-groups { display: grid; gap: 12px; }
    .assistant-guided-group { border-top: 1px solid rgba(8,50,76,.08); padding-top: 10px; }
    .assistant-guided-group h4 { margin: 0 0 7px; color: #0d5877; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; }
    .assistant-chart-title { margin-bottom: 10px; font-weight: 900; }
    .assistant-line-chart { width: 100%; height: 210px; border-radius: 14px; background: repeating-linear-gradient(to top, rgba(8,50,76,.05) 0 1px, transparent 1px 35px); }
    .assistant-line-chart polyline { fill: none; stroke: #087ea4; stroke-width: 2.5; vector-effect: non-scaling-stroke; }
    .assistant-bar-chart { height: 220px; display: flex; align-items: end; gap: 8px; overflow-x: auto; padding: 12px; border-radius: 14px; background: repeating-linear-gradient(to top, rgba(8,50,76,.05) 0 1px, transparent 1px 35px); }
    .assistant-bar-item { min-width: 62px; height: 190px; display: grid; align-items: end; justify-items: center; grid-template-rows: 1fr 34px; gap: 5px; }
    .assistant-bar-item span { width: 30px; border-radius: 10px 10px 4px 4px; background: linear-gradient(180deg, #37b2ce, #075f8d); }
    .assistant-bar-item small { max-width: 62px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #667d89; font-size: 10px; }
    .assistant-chart-scale { display: flex; justify-content: space-between; color: #718894; font-size: 12px; margin-top: 6px; }
    .assistant-table-head div { display: flex; align-items: center; gap: 10px; }
    .assistant-table-head button { color: #075f8d; background: #e6f6fb; }
    .assistant-table-wrap { margin-top: 12px; overflow: auto; max-height: 440px; border-radius: 14px; border: 1px solid rgba(8,50,76,.08); }
    .assistant-table-wrap table { width: 100%; border-collapse: collapse; min-width: 860px; background: white; }
    .assistant-table-wrap th, .assistant-table-wrap td { padding: 10px 11px; border-bottom: 1px solid rgba(8,50,76,.07); text-align: left; font-size: 13px; }
    .assistant-table-wrap th { position: sticky; top: 0; background: #f3fbfd; color: #0d5877; z-index: 1; }
    .assistant-muted { color: #718894; font-size: 12px; }
    .assistant-sql { border-radius: 16px; }
    .assistant-sql pre { overflow: auto; padding: 12px; border-radius: 12px; background: #0c1f2b; color: #d9f5ff; font-size: 12px; }
    @media (max-width: 980px) { .assistant-layout, .assistant-filter-grid, .assistant-hero, .assistant-barrage-profile { grid-template-columns: 1fr; display: grid; } }
  `}</style>;
}

export default AssistantDataPage;
