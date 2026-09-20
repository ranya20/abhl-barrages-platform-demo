import { useEffect, useMemo, useState } from "react";
import {
  getDashboardCustomValues,
  getDashboardFilters,
  getDashboardOverview,
  getDashboardTimeseries,
} from "../api";

const DEFAULT_VARIABLES = ["volume", "taux", "apports", "restitutions"];

function addDays(value, days) {
  const date = new Date(`${value}T12:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("fr-FR", { maximumFractionDigits: digits });
}

function formatDate(value) {
  if (!value) return "-";
  const [, month, day] = value.split("-");
  return `${day}/${month}`;
}

function formatFullDate(value) {
  if (!value) return "-";
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function safePercent(value) {
  const n = Number(value || 0);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

function safeNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function statusClass(value) {
  if (value === "danger") return "danger";
  if (value === "warning") return "warning";
  if (value === "info") return "info";
  return "success";
}

export default function DashboardPage({ initialDate = "2026-06-09", onDateChange }) {
  const [dateSituation, setDateSituation] = useState(initialDate || "2026-06-09");
  const [startDate, setStartDate] = useState(addDays(initialDate || "2026-06-09", -30));
  const [endDate, setEndDate] = useState(initialDate || "2026-06-09");
  const [agenceCode, setAgenceCode] = useState("");
  const [barrageCode, setBarrageCode] = useState("");
  const [filters, setFilters] = useState(null);
  const [overview, setOverview] = useState(null);
  const [timeseries, setTimeseries] = useState(null);
  const [customData, setCustomData] = useState(null);
  const [selectedVariables, setSelectedVariables] = useState(DEFAULT_VARIABLES);
  const [selectedBarrages, setSelectedBarrages] = useState([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [loading, setLoading] = useState(false);
  const [customLoading, setCustomLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setDateSituation(initialDate || "2026-06-09");
    setEndDate(initialDate || "2026-06-09");
  }, [initialDate]);

  useEffect(() => {
    getDashboardFilters()
      .then(setFilters)
      .catch((err) => setError(`Erreur filtres dashboard : ${err.message}`));
  }, []);

  async function loadDashboard() {
    if (!dateSituation || !startDate || !endDate) return;

    setLoading(true);
    setError("");

    try {
      const [overviewData, timeseriesData] = await Promise.all([
        getDashboardOverview({
          date_situation: dateSituation,
          agence_code: agenceCode || null,
          barrage_code: barrageCode || null,
        }),
        getDashboardTimeseries({
          start_date: startDate,
          end_date: endDate,
          agence_code: agenceCode || null,
          barrage_code: barrageCode || null,
        }),
      ]);

      setOverview(overviewData);
      setTimeseries(timeseriesData);
      setLastRefresh(new Date());
      onDateChange?.(dateSituation);
    } catch (err) {
      setError(err.message);
      setOverview(null);
      setTimeseries(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateSituation, startDate, endDate, agenceCode, barrageCode]);

  useEffect(() => {
    if (!autoRefresh) return;

    const timer = window.setInterval(() => {
      loadDashboard();
    }, 30000);

    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh, dateSituation, startDate, endDate, agenceCode, barrageCode]);

  async function loadCustomValues() {
    setCustomLoading(true);
    setError("");

    try {
      const result = await getDashboardCustomValues({
        start_date: startDate,
        end_date: endDate,
        agence_code: agenceCode || null,
        barrage_codes: selectedBarrages,
        variables: selectedVariables,
      });
      setCustomData(result);
    } catch (err) {
      setError(err.message);
      setCustomData(null);
    } finally {
      setCustomLoading(false);
    }
  }

  function toggleVariable(code) {
    setSelectedVariables((current) =>
      current.includes(code) ? current.filter((item) => item !== code) : [...current, code]
    );
  }

  function toggleBarrage(code) {
    setSelectedBarrages((current) =>
      current.includes(code) ? current.filter((item) => item !== code) : [...current, code]
    );
  }

  const summary = overview?.summary || {};
  const points = timeseries?.points || [];
  const barrages = overview?.barrages || [];
  const agencies = overview?.agency_summary || [];
  const variables = filters?.variables || {};
  const filteredBarrages = (filters?.barrages || []).filter((item) => !agenceCode || item.agence_code === agenceCode);

  const topBarrages = useMemo(
    () => [...barrages].sort((a, b) => safeNumber(b.taux_remplissage) - safeNumber(a.taux_remplissage)).slice(0, 5),
    [barrages]
  );

  const watchBarrages = useMemo(
    () => [...barrages].sort((a, b) => safeNumber(a.taux_remplissage, 999) - safeNumber(b.taux_remplissage, 999)).slice(0, 4),
    [barrages]
  );

  const totalN1Volume = useMemo(
    () => barrages.reduce((sum, row) => sum + safeNumber(row.volume_n1_mm3), 0),
    [barrages]
  );

  const quality = summary.barrages_count
    ? Math.round(((safeNumber(summary.barrages_count) - safeNumber(summary.missing_count)) / safeNumber(summary.barrages_count)) * 100)
    : 0;

  const lastPoint = points.length ? points[points.length - 1] : null;
  const firstPoint = points.length ? points[0] : null;

  const comparison = {
    volumeCurrent: safeNumber(summary.volume_mm3),
    volumeN1: totalN1Volume,
    tauxCurrent: safeNumber(summary.taux_remplissage),
    tauxN1: safeNumber(summary.taux_n1),
    volumePeriodDelta: safeNumber(lastPoint?.volume_mm3) - safeNumber(firstPoint?.volume_mm3),
    tauxPeriodDelta: safeNumber(lastPoint?.taux_remplissage) - safeNumber(firstPoint?.taux_remplissage),
  };

  return (
    <section className="abhlDashV12">
      <DashboardV12Styles />
      <div className="dashv12-filters">
        <Field label="Date">
          <input
            type="date"
            value={dateSituation}
            onChange={(event) => {
              const nextDate = event.target.value;
              setDateSituation(nextDate);
              setEndDate(nextDate);
              setStartDate(addDays(nextDate, -30));
            }}
          />
        </Field>

        <Field label="Début">
          <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
        </Field>

        <Field label="Fin">
          <input
            type="date"
            value={endDate}
            onChange={(event) => {
              const nextEnd = event.target.value;
              setEndDate(nextEnd);
              setDateSituation(nextEnd);
            }}
          />
        </Field>

        <Field label="Agence">
          <select
            value={agenceCode}
            onChange={(event) => {
              setAgenceCode(event.target.value);
              setBarrageCode("");
            }}
          >
            <option value="">Toutes les agences</option>
            {(filters?.agences || []).map((agence) => (
              <option key={agence.code} value={agence.code}>
                {agence.nom || agence.code}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Barrage">
          <select value={barrageCode} onChange={(event) => setBarrageCode(event.target.value)}>
            <option value="">Tous les barrages</option>
            {filteredBarrages.map((barrage) => (
              <option key={barrage.code} value={barrage.code}>
                {barrage.nom_court || barrage.code}
              </option>
            ))}
          </select>
        </Field>
        <div className="dashv12-filter-actions">
          <button type="button" onClick={loadDashboard} disabled={loading}>
            <Icon name="refresh" />
            {loading ? "..." : "Actualiser"}
          </button>

          <label>
            <input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
            <i />
            Temps réel 30s
          </label>

          <small>{lastRefresh ? `MAJ ${lastRefresh.toLocaleTimeString("fr-FR")}` : "En attente"}</small>
        </div>
      </div>

      {error && <div className="dashv12-error">{error}</div>}

      <div className="dashv12-kpis">
        <Kpi icon="dam" label="Barrages" value={summary.barrages_count ?? "-"} note={`${summary.bilans_count ?? 0} bilans`} />
        <Kpi icon="drop" label="Volume" value={`${formatNumber(summary.volume_mm3, 1)} Mm³`} note={`Cap. ${formatNumber(summary.capacite_normale_mm3, 1)} Mm³`} />
        <Kpi icon="percent" label="Taux" value={`${formatNumber(summary.taux_remplissage, 0)}%`} note={`N-1 ${formatNumber(summary.taux_n1, 0)}%`} />
        <Kpi icon="rain" label="Apports" value={`${formatNumber(summary.apports_m3, 0)} m³`} note="Journalier" />
        <Kpi icon="arrow" label="Restitutions" value={`${formatNumber(summary.total_restitutions_m3, 0)} m³`} note="Journalier" />
        <Kpi icon="sun" label="Évaporation" value={`${formatNumber(summary.evaporation_m3, 0)} m³`} note="Journalier" />
      </div>

      <div className="dashv12-grid">
        <Card className="card-volume" title="Volume total" subtitle="Évolution sur la période" badge={`${formatNumber(lastPoint?.volume_mm3, 1)} Mm³`}>
          <AreaChart data={points} yKey="volume_mm3" unit="Mm³" />
        </Card>

        <Card className="card-agency" title="Répartition par agence" subtitle="Volume stocké" badge={`${agencies.length} agences`}>
          <Donut data={agencies.map((item) => ({ label: item.agence_nom || item.agence_code, value: item.volume_mm3 }))} />
        </Card>

        <Card className="card-compare" title="Comparaison" subtitle="Actuel vs N-1 et période" badge={comparison.volumeN1 ? `${formatSigned(comparison.volumeCurrent - comparison.volumeN1, 1)} Mm³` : "N-1"}>
          <ComparisonCard comparison={comparison} />
        </Card>

        <Card className="card-rate" title="Taux de remplissage" subtitle="Tendance globale" badge={`${formatNumber(summary.taux_remplissage, 0)}%`}>
          <LineChart data={points} yKey="taux_remplissage" unit="%" />
        </Card>

        <Card className="card-water" title="Bilan hydrique" subtitle="Entrées / sorties" badge="m³">
          <WaterBars summary={summary} />
        </Card>

        <Card className="card-rank" title="Classement & surveillance" subtitle="Meilleurs taux et barrages à suivre" badge="Priorité">
          <RankAndWatch topBarrages={topBarrages} watchBarrages={watchBarrages} />
        </Card>
      </div>

      <div className="dashv12-table-card">
        <div className="dashv12-section-head">
          <div>
            <h3>Suivi détaillé par barrage</h3>
            <p>Date : {formatFullDate(overview?.date_situation)} • Données PostgreSQL</p>
          </div>
          <span>{barrages.length} barrages</span>
        </div>

        <div className="dashv12-table-wrap">
          <table>
            <thead>
              <tr>
                <th>Barrage</th>
                <th>Agence</th>
                <th>Cote</th>
                <th>Volume</th>
                <th>Taux</th>
                <th>N-1</th>
                <th>Pluie</th>
                <th>Apports</th>
                <th>Restitutions</th>
                <th>Évap.</th>
                <th>Statut</th>
              </tr>
            </thead>
            <tbody>
              {barrages.map((row) => (
                <tr key={row.barrage_code}>
                  <td>
                    <strong>{row.barrage_nom_court || row.barrage_code}</strong>
                    <small>{row.barrage_code}</small>
                  </td>
                  <td>{row.agence_nom || row.agence_code || "-"}</td>
                  <td>{formatNumber(row.cote_7h_ngm, 2)}</td>
                  <td>{formatNumber(row.volume_mm3, 3)}</td>
                  <td><MiniBar value={row.taux_remplissage} /></td>
                  <td>{formatNumber(row.volume_n1_mm3, 3)}</td>
                  <td>{formatNumber(row.pluie_mm, 2)}</td>
                  <td>{formatNumber(row.apports_m3, 0)}</td>
                  <td>{formatNumber(row.total_restitutions_m3, 0)}</td>
                  <td>{formatNumber(row.evaporation_m3, 0)}</td>
                  <td><span className={`dashv12-status ${statusClass(row.severity)}`}>{row.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <details className="dashv12-analysis">
        <summary>
          <div>
            <h3>Analyse personnalisée</h3>
            <p>Section repliable pour éviter d’alourdir le tableau de bord principal.</p>
          </div>
          <span>Ouvrir</span>
        </summary>

        <div className="dashv12-analysis-body">
          <div>
            <h4>Variables</h4>
            <div className="dashv12-chips">
              {Object.entries(variables).map(([code, item]) => (
                <label key={code} className={selectedVariables.includes(code) ? "active" : ""}>
                  <input type="checkbox" checked={selectedVariables.includes(code)} onChange={() => toggleVariable(code)} />
                  {item.label}
                </label>
              ))}
            </div>
          </div>

          <div>
            <h4>Barrages</h4>
            <div className="dashv12-chips barrages">
              {filteredBarrages.map((barrage) => (
                <label key={barrage.code} className={selectedBarrages.includes(barrage.code) ? "active" : ""}>
                  <input type="checkbox" checked={selectedBarrages.includes(barrage.code)} onChange={() => toggleBarrage(barrage.code)} />
                  {barrage.nom_court || barrage.code}
                </label>
              ))}
            </div>
          </div>

          <button type="button" onClick={loadCustomValues} disabled={customLoading || !selectedVariables.length}>
            <Icon name="chart" />
            {customLoading ? "Chargement..." : "Afficher"}
          </button>
        </div>

        {customData?.rows?.length > 0 && (
          <div className="dashv12-analysis-result">
            <CompactComparisonBars rows={customData.rows.slice(-24)} variable={selectedVariables[0]} />
            <div className="dashv12-table-wrap custom">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Barrage</th>
                    {Object.entries(customData.variables || {}).map(([code, item]) => (
                      <th key={code}>{item.label} {item.unit ? `(${item.unit})` : ""}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {customData.rows.slice(0, 120).map((row, index) => (
                    <tr key={`${row.date}-${row.barrage_code}-${index}`}>
                      <td>{formatFullDate(row.date)}</td>
                      <td>{row.barrage_nom_court || row.barrage_code}</td>
                      {Object.keys(customData.variables || {}).map((code) => (
                        <td key={code}>{formatNumber(row.values?.[code], customData.variables?.[code]?.digits ?? 2)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </details>
    </section>
  );
}

function Field({ label, children }) {
  return (
    <label>
      <span>{label}</span>
      {children}
    </label>
  );
}

function formatSigned(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}${formatNumber(n, digits)}`;
}

function Icon({ name }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
  };

  if (name === "drop") return <svg {...common}><path d="M12 3s6 6.4 6 11a6 6 0 0 1-12 0c0-4.6 6-11 6-11z" /></svg>;
  if (name === "dam") return <svg {...common}><path d="M4 20V8l8-4 8 4v12" /><path d="M4 13h16" /><path d="M8 20v-7" /><path d="M16 20v-7" /></svg>;
  if (name === "percent") return <svg {...common}><path d="M19 5 5 19" /><circle cx="7" cy="7" r="2" /><circle cx="17" cy="17" r="2" /></svg>;
  if (name === "rain") return <svg {...common}><path d="M7 17v2" /><path d="M12 17v3" /><path d="M17 17v2" /><path d="M20 16.6A4.6 4.6 0 0 0 17 8h-1.2A6 6 0 0 0 4 10a4 4 0 0 0 0 8h16" /></svg>;
  if (name === "arrow") return <svg {...common}><path d="M7 17 17 7" /><path d="M8 7h9v9" /></svg>;
  if (name === "sun") return <svg {...common}><circle cx="12" cy="12" r="4" /><path d="M12 2v2" /><path d="M12 20v2" /><path d="M2 12h2" /><path d="M20 12h2" /><path d="m4.9 4.9 1.4 1.4" /><path d="m17.7 17.7 1.4 1.4" /></svg>;
  if (name === "refresh") return <svg {...common}><path d="M20 12a8 8 0 1 1-2.3-5.7" /><path d="M20 4v6h-6" /></svg>;
  return <svg {...common}><path d="M4 19V5" /><path d="M4 19h16" /><path d="M8 15l3-3 3 2 5-7" /></svg>;
}

function Kpi({ icon, label, value, note }) {
  return (
    <div className="dashv12-kpi">
      <i><Icon name={icon} /></i>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{note}</small>
      </div>
    </div>
  );
}

function Card({ title, subtitle, badge, children, className = "" }) {
  return (
    <div className={`dashv12-card ${className}`}>
      <div className="dashv12-card-head">
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
        {badge && <span>{badge}</span>}
      </div>
      {children}
    </div>
  );
}

function Gauge({ value }) {
  const p = safePercent(value);
  const radius = 29;
  const circumference = 2 * Math.PI * radius;
  const dash = (p / 100) * circumference;

  return (
    <svg className="dashv12-gauge" viewBox="0 0 78 78">
      <circle cx="39" cy="39" r={radius} className="track" />
      <circle cx="39" cy="39" r={radius} className="value" strokeDasharray={`${dash} ${circumference - dash}`} transform="rotate(-90 39 39)" />
    </svg>
  );
}

function MiniBar({ value }) {
  return (
    <div className="dashv12-mini-bar">
      <span style={{ width: `${safePercent(value)}%` }} />
      <b>{formatNumber(value, 0)}%</b>
    </div>
  );
}

function LineChart({ data, yKey, unit }) {
  return <SvgChart data={data} yKey={yKey} unit={unit} area={false} />;
}

function AreaChart({ data, yKey, unit }) {
  return <SvgChart data={data} yKey={yKey} unit={unit} area />;
}

function SvgChart({ data, yKey, unit, area }) {
  if (!data?.length) return <div className="dashv12-empty">Aucune donnée.</div>;

  const values = data.map((item) => Number(item[yKey] || 0));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 620;
  const height = area ? 130 : 120;
  const pad = 14;

  const points = data.map((item, index) => {
    const x = data.length === 1 ? width / 2 : pad + (index / (data.length - 1)) * (width - pad * 2);
    const y = height - pad - ((Number(item[yKey] || 0) - min) / range) * (height - pad * 2);
    return { x, y, item };
  });

  const line = points.map((p, index) => `${index === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  const areaPath = `${line} L ${points[points.length - 1].x} ${height - pad} L ${points[0].x} ${height - pad} Z`;

  return (
    <div className="dashv12-chart">
      <svg viewBox={`0 0 ${width} ${height}`}>
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} />
        {area && <path d={areaPath} className="area" />}
        <path d={line} className="line" />
        {points.map((point, index) => (
          <circle key={index} cx={point.x} cy={point.y} r="2.4">
            <title>{formatFullDate(point.item.date)} : {formatNumber(point.item[yKey], unit === "%" ? 0 : 1)} {unit}</title>
          </circle>
        ))}
      </svg>

      <footer>
        <span>{formatDate(data[0]?.date)}</span>
        <strong>{formatNumber(values[values.length - 1], unit === "%" ? 0 : 1)} {unit}</strong>
        <span>{formatDate(data[data.length - 1]?.date)}</span>
      </footer>
    </div>
  );
}

function Donut({ data }) {
  if (!data?.length) return <div className="dashv12-empty">Aucune agence.</div>;

  const total = data.reduce((sum, item) => sum + Number(item.value || 0), 0) || 1;
  let offset = 25;
  const colors = ["#07567b", "#1685b0", "#45b4d2", "#39a96b", "#82d4c1", "#2b7a5b"];

  return (
    <div className="dashv12-donut">
      <svg viewBox="0 0 116 116">
        <circle cx="58" cy="58" r="36" className="base" />
        {data.map((item, index) => {
          const part = (Number(item.value || 0) / total) * 100;
          const currentOffset = offset;
          offset -= part;

          return (
            <circle
              key={item.label}
              cx="58"
              cy="58"
              r="36"
              className="part"
              stroke={colors[index % colors.length]}
              strokeDasharray={`${part} ${100 - part}`}
              strokeDashoffset={currentOffset}
            />
          );
        })}
        <text x="58" y="56" textAnchor="middle">{formatNumber(total, 0)}</text>
        <text x="58" y="71" textAnchor="middle">Mm³</text>
      </svg>

      <div>
        {data.map((item, index) => (
          <p key={item.label}>
            <i style={{ background: colors[index % colors.length] }} />
            <span>{item.label}</span>
            <b>{formatNumber(item.value, 1)}</b>
          </p>
        ))}
      </div>
    </div>
  );
}

function ComparisonCard({ comparison }) {
  const maxVolume = Math.max(comparison.volumeCurrent, comparison.volumeN1, 1);
  const deltaVolume = comparison.volumeCurrent - comparison.volumeN1;
  const deltaTaux = comparison.tauxCurrent - comparison.tauxN1;

  return (
    <div className="dashv12-compare">
      <CompareRow
        label="Volume actuel"
        main={`${formatNumber(comparison.volumeCurrent, 1)} Mm³`}
        second={`N-1 ${formatNumber(comparison.volumeN1, 1)} Mm³`}
        value={comparison.volumeCurrent}
        max={maxVolume}
      />

      <CompareRow
        label="Volume N-1"
        main={`${formatNumber(comparison.volumeN1, 1)} Mm³`}
        second={`Écart ${formatSigned(deltaVolume, 1)} Mm³`}
        value={comparison.volumeN1}
        max={maxVolume}
        muted
      />

      <div className="dashv12-compare-grid">
        <div>
          <span>Écart taux</span>
          <strong>{formatSigned(deltaTaux, 0)} pts</strong>
        </div>
        <div>
          <span>Variation période</span>
          <strong>{formatSigned(comparison.volumePeriodDelta, 1)} Mm³</strong>
        </div>
      </div>
    </div>
  );
}

function CompareRow({ label, main, second, value, max, muted = false }) {
  const width = Math.max((safeNumber(value) / Math.max(safeNumber(max), 1)) * 100, 2);

  return (
    <div className={muted ? "compare-row muted" : "compare-row"}>
      <div>
        <span>{label}</span>
        <b>{main}</b>
        <small>{second}</small>
      </div>
      <em><i style={{ width: `${width}%` }} /></em>
    </div>
  );
}

function WaterBars({ summary }) {
  const rows = [
    ["Apports", summary.apports_m3],
    ["Restitutions", summary.total_restitutions_m3],
    ["Évaporation", summary.evaporation_m3],
  ];
  const max = Math.max(...rows.map(([, value]) => Number(value || 0)), 1);

  return (
    <div className="dashv12-water">
      {rows.map(([label, value]) => (
        <div key={label}>
          <p><span>{label}</span><b>{formatNumber(value, 0)} m³</b></p>
          <em><i style={{ width: `${(Number(value || 0) / max) * 100}%` }} /></em>
        </div>
      ))}
    </div>
  );
}

function RankAndWatch({ topBarrages, watchBarrages }) {
  return (
    <div className="dashv12-rankwatch">
      <div className="rank-zone">
        {topBarrages.map((item, index) => (
          <div key={item.barrage_code}>
            <span>{index + 1}</span>
            <p><strong>{item.barrage_nom_court || item.barrage_code}</strong><small>{item.agence_nom || item.agence_code}</small></p>
            <em><i style={{ width: `${safePercent(item.taux_remplissage)}%` }} /></em>
            <b>{formatNumber(item.taux_remplissage, 0)}%</b>
          </div>
        ))}
      </div>

      <div className="watch-zone">
        {watchBarrages.map((item) => (
          <div key={item.barrage_code}>
            <p><strong>{item.barrage_nom_court || item.barrage_code}</strong><small>{item.agence_nom || item.agence_code}</small></p>
            <MiniCircle value={item.taux_remplissage} />
          </div>
        ))}
      </div>
    </div>
  );
}

function MiniCircle({ value }) {
  const p = safePercent(value);
  const radius = 12;
  const circumference = 2 * Math.PI * radius;
  const dash = (p / 100) * circumference;

  return (
    <div className="dashv12-mini-circle">
      <svg viewBox="0 0 34 34">
        <circle cx="17" cy="17" r={radius} className="track" />
        <circle cx="17" cy="17" r={radius} className="value" strokeDasharray={`${dash} ${circumference - dash}`} transform="rotate(-90 17 17)" />
      </svg>
      <span>{formatNumber(value, 0)}%</span>
    </div>
  );
}

function CompactComparisonBars({ rows, variable }) {
  if (!rows?.length || !variable) return null;

  const normalizedRows = rows.map((row) => {
    const barrageName = row.barrage_nom_court || row.barrage_code || "Barrage";
    const value = safeNumber(row.values?.[variable]);
    return { ...row, barrageName, value };
  });

  const max = Math.max(...normalizedRows.map((row) => row.value), 1);

  return (
    <div className="dashv12-bars improved">
      {normalizedRows.map((row, index) => (
        <div key={`${row.date}-${row.barrage_code}-${index}`} className="dashv12-bar-item">
          <span
            style={{ height: `${Math.max((row.value / max) * 100, 4)}%` }}
            title={`${row.barrageName} - ${formatFullDate(row.date)} : ${formatNumber(row.value, 2)}`}
          />
          <small title={`${row.barrageName} - ${formatFullDate(row.date)}`}>
            <b>{row.barrageName}</b>
            <em>{formatDate(row.date)}</em>
          </small>
        </div>
      ))}
    </div>
  );
}

function DashboardV12Styles() {
  return (
    <style>{`
      :root {
        --dashv12-deep: #08324c;
        --dashv12-blue: #075f8d;
        --dashv12-sky: #39aeca;
        --dashv12-green: #38a86b;
        --dashv12-bg: #edf7f8;
        --dashv12-text: #12354a;
        --dashv12-muted: #6d8494;
        --dashv12-card: rgba(255, 255, 255, 0.72);
        --dashv12-border: rgba(8, 50, 76, 0.10);
        --dashv12-shadow: 0 9px 24px rgba(8, 50, 76, 0.075);
      }

      .app {
        background:
          radial-gradient(circle at 8% 0%, rgba(57, 174, 202, 0.18), transparent 30%),
          radial-gradient(circle at 92% 10%, rgba(56, 168, 107, 0.13), transparent 28%),
          linear-gradient(145deg, #f8fcfd 0%, #edf7f8 56%, #f7fbf8 100%) !important;
      }

      .main {
        width: min(1540px, calc(100vw - 32px)) !important;
        margin: 0 auto !important;
        padding: 10px 0 24px !important;
      }

      .top-navbar {
        min-height: 76px !important;
        padding: 10px 24px !important;
        display: grid !important;
        grid-template-columns: auto 1fr auto !important;
        align-items: center !important;
        gap: 16px !important;
        background: rgba(255, 255, 255, 0.78) !important;
        backdrop-filter: blur(18px) !important;
        border-bottom: 1px solid rgba(8, 50, 76, 0.08) !important;
        box-shadow: 0 8px 24px rgba(8, 50, 76, 0.055) !important;
      }

      .brand-logo {
        width: 40px !important;
        height: 40px !important;
        border-radius: 14px !important;
        font-size: 12px !important;
      }

      .top-brand h1 {
        font-size: 15px !important;
        margin: 0 !important;
      }

      .top-brand p {
        margin: 2px 0 0 !important;
        font-size: 11px !important;
      }

      .nav {
        display: flex !important;
        flex-wrap: wrap !important;
        justify-content: center !important;
        gap: 7px !important;
      }

      .nav button {
        display: inline-flex !important;
        align-items: center !important;
        gap: 6px !important;
        min-height: 34px !important;
        padding: 7px 11px !important;
        border-radius: 999px !important;
        font-size: 12px !important;
        font-weight: 850 !important;
      }

      .nav button svg {
        width: 15px !important;
        height: 15px !important;
      }

      .backend-status {
        min-height: 34px !important;
        padding: 7px 10px !important;
        font-size: 12px !important;
      }


      /* Dashboard uniquement : enlever la pastille verte de connexion du header global. */
      .backend-status-premium,
      .backend-status,
      .backend-connection,
      .backend-connected,
      .connection-status,
      .status-backend,
      .top-backend-status {
        display: none !important;
      }

      .abhlDashV12 {
        display: grid;
        gap: 10px;
        color: var(--dashv12-text);
      }

      .abhlDashV12 * {
        box-sizing: border-box;
      }

      /* Enlever la case "Backend connecté" affichée par App.jsx pendant le dashboard */
      .backend-status {
        display: none !important;
      }

      .dashv12-compact-head {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto 185px;
        align-items: center;
        gap: 12px;
        padding: 12px 14px;
        border-radius: 18px;
        color: var(--dashv12-text);
        border: 1px solid rgba(255, 255, 255, 0.72);
        background: rgba(255, 255, 255, 0.70);
        backdrop-filter: blur(16px);
        box-shadow: var(--dashv12-shadow);
      }

      .dashv12-compact-head > div:first-child > span {
        display: inline-flex;
        padding: 3px 8px;
        margin-bottom: 5px;
        border-radius: 999px;
        color: var(--dashv12-blue);
        background: rgba(57, 174, 202, 0.13);
        font-size: 9.5px;
        font-weight: 850;
      }

      .dashv12-compact-head h2 {
        margin: 0;
        color: var(--dashv12-deep);
        font-size: clamp(20px, 1.8vw, 27px);
        line-height: 1.05;
        letter-spacing: -0.4px;
      }

      .dashv12-compact-head p {
        margin: 4px 0 0;
        color: var(--dashv12-muted);
        font-size: 11px;
        line-height: 1.3;
      }

      .dashv12-compact-meta {
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        gap: 5px;
      }

      .dashv12-compact-meta b {
        display: inline-flex;
        padding: 4px 7px;
        border-radius: 999px;
        color: var(--dashv12-blue);
        background: rgba(57, 174, 202, 0.13);
        font-size: 9.5px;
        white-space: nowrap;
      }

      .dashv12-compact-actions {
        display: grid;
        gap: 5px;
        justify-self: end;
        width: 185px;
      }

      .dashv12-compact-actions button {
        width: 100%;
        height: 30px;
        border: none;
        border-radius: 10px;
        color: white;
        background: linear-gradient(135deg, var(--dashv12-blue), var(--dashv12-green));
        font-weight: 850;
        font-size: 10.5px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        cursor: pointer;
        box-shadow: 0 8px 18px rgba(8, 50, 76, 0.12);
      }

      .dashv12-compact-actions label {
        display: flex;
        align-items: center;
        gap: 6px;
        color: var(--dashv12-text);
        font-size: 10px;
        font-weight: 850;
      }

      .dashv12-compact-actions label input {
        display: none;
      }

      .dashv12-compact-actions label i {
        position: relative;
        width: 29px;
        height: 16px;
        border-radius: 999px;
        background: rgba(8, 50, 76, 0.16);
      }

      .dashv12-compact-actions label i::after {
        content: "";
        position: absolute;
        top: 3px;
        left: 3px;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: white;
        transition: 0.16s ease;
      }

      .dashv12-compact-actions label input:checked + i {
        background: var(--dashv12-green);
      }

      .dashv12-compact-actions label input:checked + i::after {
        transform: translateX(13px);
      }

      .dashv12-compact-actions small {
        color: var(--dashv12-muted);
        font-size: 9px;
      }

      .dashv12-hero {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 240px 160px;
        align-items: center;
        gap: 12px;
        min-height: 124px;
        padding: 16px 18px;
        border-radius: 21px;
        background:
          radial-gradient(circle at 88% 0%, rgba(255, 255, 255, 0.18), transparent 31%),
          linear-gradient(130deg, rgba(8, 50, 76, 0.97), rgba(7, 95, 141, 0.88) 57%, rgba(56, 168, 107, 0.74));
        box-shadow: var(--dashv12-shadow);
        overflow: hidden;
      }

      .dashv12-title > span {
        display: inline-flex;
        padding: 4px 8px;
        margin-bottom: 6px;
        border-radius: 999px;
        color: rgba(255, 255, 255, 0.86);
        background: rgba(255, 255, 255, 0.14);
        font-size: 10px;
        font-weight: 850;
      }

      .dashv12-title h2 {
        margin: 0;
        color: #ffffff;
        font-size: clamp(23px, 2.3vw, 32px);
        line-height: 1;
        letter-spacing: -0.6px;
      }

      .dashv12-title p {
        margin: 6px 0 0;
        color: rgba(255, 255, 255, 0.80);
        font-size: 12px;
        line-height: 1.35;
      }

      .dashv12-hero-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 8px;
      }

      .dashv12-hero-badges b {
        display: inline-flex;
        padding: 3px 7px;
        border-radius: 999px;
        color: rgba(255, 255, 255, 0.86);
        background: rgba(255, 255, 255, 0.12);
        font-size: 9.5px;
      }

      .dashv12-gauge-card {
        height: 82px;
        display: grid;
        grid-template-columns: 64px 1fr;
        align-items: center;
        gap: 8px;
        padding: 9px;
        border-radius: 15px;
        background: rgba(255, 255, 255, 0.15);
        border: 1px solid rgba(255, 255, 255, 0.22);
      }

      .dashv12-gauge-card strong {
        display: block;
        color: #ffffff;
        font-size: 20px;
        line-height: 1;
      }

      .dashv12-gauge-card span,
      .dashv12-gauge-card small {
        display: block;
        color: rgba(255, 255, 255, 0.78);
        font-size: 9.5px;
        line-height: 1.15;
      }

      .dashv12-actions {
        display: grid;
        gap: 6px;
      }

      .dashv12-actions button,
      .dashv12-analysis-body button {
        height: 31px;
        border: none;
        border-radius: 10px;
        color: white;
        background: linear-gradient(135deg, var(--dashv12-blue), var(--dashv12-green));
        font-weight: 850;
        font-size: 10.5px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        cursor: pointer;
        box-shadow: 0 8px 18px rgba(8, 50, 76, 0.12);
      }

      .dashv12-actions label {
        display: flex;
        align-items: center;
        gap: 6px;
        color: #ffffff;
        font-size: 10.5px;
        font-weight: 800;
      }

      .dashv12-actions label input {
        display: none;
      }

      .dashv12-actions label i {
        position: relative;
        width: 30px;
        height: 17px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.24);
      }

      .dashv12-actions label i::after {
        content: "";
        position: absolute;
        top: 3px;
        left: 3px;
        width: 11px;
        height: 11px;
        border-radius: 50%;
        background: white;
        transition: 0.16s ease;
      }

      .dashv12-actions label input:checked + i {
        background: rgba(56, 168, 107, 0.95);
      }

      .dashv12-actions label input:checked + i::after {
        transform: translateX(13px);
      }

      .dashv12-actions small {
        color: rgba(255, 255, 255, 0.75);
        font-size: 9.5px;
      }

      .dashv12-gauge {
        width: 58px;
        height: 58px;
      }

      .dashv12-gauge .track,
      .dashv12-mini-circle .track {
        fill: none;
        stroke: rgba(255, 255, 255, 0.26);
        stroke-width: 7;
      }

      .dashv12-gauge .value,
      .dashv12-mini-circle .value {
        fill: none;
        stroke: var(--dashv12-sky);
        stroke-width: 7;
        stroke-linecap: round;
      }

      .dashv12-filters,
      .dashv12-kpi,
      .dashv12-card,
      .dashv12-table-card,
      .dashv12-analysis {
        border: 1px solid rgba(255, 255, 255, 0.72);
        background: var(--dashv12-card);
        backdrop-filter: blur(16px);
        box-shadow: var(--dashv12-shadow);
      }

      .dashv12-filters {
        display: grid;
        grid-template-columns: repeat(5, minmax(120px, 1fr));
        gap: 8px;
        padding: 8px;
        border-radius: 15px;
      }

      .dashv12-filters label {
        display: grid;
        gap: 3px;
      }

      .dashv12-filters label span {
        color: var(--dashv12-muted);
        font-size: 9.5px;
        font-weight: 850;
      }

      .dashv12-filters input,
      .dashv12-filters select {
        width: 100%;
        height: 28px;
        border: 1px solid var(--dashv12-border);
        background: rgba(255, 255, 255, 0.70);
        color: var(--dashv12-text);
        border-radius: 9px;
        padding: 0 8px;
        font-size: 10.5px;
        font-weight: 750;
        outline: none;
      }

      .dashv12-error {
        padding: 10px;
        border-radius: 14px;
        color: #9d1d1d;
        background: rgba(255, 240, 240, 0.86);
        border: 1px solid rgba(157, 29, 29, 0.14);
        font-size: 12px;
      }

      .dashv12-kpis {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 8px;
      }

      .dashv12-kpi {
        min-height: 64px;
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 9px;
        border-radius: 14px;
      }

      .dashv12-kpi i {
        display: grid;
        place-items: center;
        width: 27px;
        height: 27px;
        flex: 0 0 27px;
        border-radius: 9px;
        color: var(--dashv12-blue);
        background: rgba(57, 174, 202, 0.14);
      }

      .dashv12-kpi i svg {
        width: 14px;
        height: 14px;
      }

      .dashv12-kpi span {
        display: block;
        color: var(--dashv12-muted);
        font-size: 9.5px;
        font-weight: 850;
      }

      .dashv12-kpi strong {
        display: block;
        margin-top: 1px;
        color: var(--dashv12-deep);
        font-size: 15.5px;
        line-height: 1.05;
      }

      .dashv12-kpi small {
        display: block;
        color: var(--dashv12-muted);
        font-size: 9px;
      }

      .dashv12-grid {
        display: grid;
        grid-template-columns: repeat(12, minmax(0, 1fr));
        gap: 10px;
      }

      .dashv12-card {
        min-height: 168px;
        padding: 11px;
        border-radius: 16px;
        overflow: hidden;
      }

      .dashv12-card.card-volume { grid-column: span 5; }
      .dashv12-card.card-agency { grid-column: span 3; }
      .dashv12-card.card-compare { grid-column: span 4; }
      .dashv12-card.card-rate { grid-column: span 4; }
      .dashv12-card.card-water { grid-column: span 4; }
      .dashv12-card.card-rank { grid-column: span 4; }

      .dashv12-card-head,
      .dashv12-section-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
      }

      .dashv12-card-head h3,
      .dashv12-section-head h3 {
        margin: 0;
        color: var(--dashv12-deep);
        font-size: 13px;
        line-height: 1.1;
      }

      .dashv12-card-head p,
      .dashv12-section-head p {
        margin: 2px 0 0;
        color: var(--dashv12-muted);
        font-size: 9.5px;
      }

      .dashv12-card-head > span,
      .dashv12-section-head > span {
        padding: 3px 6px;
        border-radius: 999px;
        color: var(--dashv12-blue);
        background: rgba(57, 174, 202, 0.14);
        font-size: 9.5px;
        font-weight: 850;
        white-space: nowrap;
      }

      .dashv12-chart svg {
        width: 100%;
        height: 120px;
        display: block;
      }

      .card-volume .dashv12-chart svg {
        height: 130px;
      }

      .dashv12-chart line {
        stroke: rgba(8, 50, 76, 0.12);
      }

      .dashv12-chart circle {
        fill: white;
        stroke: var(--dashv12-blue);
        stroke-width: 1.8;
      }

      .dashv12-chart .line {
        fill: none;
        stroke: var(--dashv12-blue);
        stroke-width: 2.5;
        stroke-linecap: round;
        stroke-linejoin: round;
      }

      .dashv12-chart .area {
        fill: rgba(57, 174, 202, 0.18);
      }

      .dashv12-chart footer {
        display: flex;
        justify-content: space-between;
        color: var(--dashv12-muted);
        font-size: 9.5px;
        font-weight: 800;
      }

      .dashv12-chart footer strong {
        color: var(--dashv12-deep);
      }

      .dashv12-donut {
        display: grid;
        grid-template-columns: 112px 1fr;
        gap: 7px;
        align-items: center;
      }

      .dashv12-donut svg {
        width: 112px;
        height: 112px;
        transform: rotate(-90deg);
      }

      .dashv12-donut .base {
        fill: none;
        stroke: rgba(8, 50, 76, 0.08);
        stroke-width: 16px;
      }

      .dashv12-donut .part {
        fill: none;
        stroke-width: 16px;
        pathLength: 100;
      }

      .dashv12-donut text {
        transform: rotate(90deg);
        transform-origin: 58px 58px;
        fill: var(--dashv12-deep);
        font-weight: 900;
        font-size: 14px;
      }

      .dashv12-donut text:last-child {
        fill: var(--dashv12-muted);
        font-size: 8px;
      }

      .dashv12-donut p {
        display: grid;
        grid-template-columns: 7px 1fr auto;
        align-items: center;
        gap: 5px;
        margin: 0 0 4px;
        font-size: 9px;
      }

      .dashv12-donut p i {
        width: 7px;
        height: 7px;
        border-radius: 50%;
      }

      .dashv12-donut p span {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .dashv12-donut p b {
        color: var(--dashv12-deep);
      }

      .dashv12-compare {
        display: grid;
        gap: 8px;
      }

      .compare-row {
        display: grid;
        grid-template-columns: minmax(110px, 0.8fr) 1fr;
        gap: 8px;
        align-items: center;
      }

      .compare-row span,
      .dashv12-compare-grid span {
        display: block;
        color: var(--dashv12-muted);
        font-size: 9px;
        font-weight: 850;
      }

      .compare-row b,
      .dashv12-compare-grid strong {
        display: block;
        color: var(--dashv12-deep);
        font-size: 12px;
      }

      .compare-row small {
        display: block;
        color: var(--dashv12-muted);
        font-size: 8.5px;
      }

      .compare-row em {
        display: block;
        height: 8px;
        border-radius: 999px;
        overflow: hidden;
        background: rgba(8, 50, 76, 0.08);
      }

      .compare-row em i {
        display: block;
        height: 100%;
        border-radius: inherit;
        background: linear-gradient(90deg, var(--dashv12-green), var(--dashv12-sky), var(--dashv12-blue));
      }

      .compare-row.muted em i {
        background: linear-gradient(90deg, rgba(8, 50, 76, 0.35), rgba(8, 50, 76, 0.20));
      }

      .dashv12-compare-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 7px;
      }

      .dashv12-compare-grid div {
        padding: 7px;
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.46);
        border: 1px solid var(--dashv12-border);
      }

      .dashv12-water {
        display: grid;
        gap: 9px;
        margin-top: 3px;
      }

      .dashv12-water p {
        display: flex;
        justify-content: space-between;
        margin: 0 0 4px;
        font-size: 10.5px;
      }

      .dashv12-water em,
      .rank-zone em {
        display: block;
        height: 7px;
        overflow: hidden;
        border-radius: 999px;
        background: rgba(8, 50, 76, 0.08);
      }

      .dashv12-water i,
      .rank-zone i {
        display: block;
        height: 100%;
        border-radius: inherit;
        background: linear-gradient(90deg, var(--dashv12-green), var(--dashv12-sky), var(--dashv12-blue));
      }

      .dashv12-rankwatch {
        display: grid;
        grid-template-columns: 1.08fr 0.92fr;
        gap: 9px;
      }

      .rank-zone,
      .watch-zone {
        display: grid;
        gap: 5px;
      }

      .rank-zone > div {
        display: grid;
        grid-template-columns: 19px minmax(72px, 1fr) minmax(68px, 1fr) 28px;
        align-items: center;
        gap: 5px;
      }

      .rank-zone > div > span {
        display: grid;
        place-items: center;
        width: 18px;
        height: 18px;
        border-radius: 7px;
        color: white;
        background: var(--dashv12-blue);
        font-size: 8.5px;
        font-weight: 900;
      }

      .rank-zone p,
      .watch-zone p {
        margin: 0;
      }

      .rank-zone strong,
      .watch-zone strong {
        display: block;
        color: var(--dashv12-text);
        font-size: 9.4px;
      }

      .rank-zone small,
      .watch-zone small {
        display: block;
        color: var(--dashv12-muted);
        font-size: 7.8px;
      }

      .rank-zone b {
        color: var(--dashv12-deep);
        font-size: 9.4px;
      }

      .watch-zone > div {
        display: grid;
        grid-template-columns: 1fr 32px;
        align-items: center;
        gap: 6px;
        padding: 5px;
        border-radius: 10px;
        background: rgba(255, 255, 255, 0.50);
        border: 1px solid var(--dashv12-border);
      }

      .dashv12-mini-circle {
        position: relative;
        width: 30px;
        height: 30px;
      }

      .dashv12-mini-circle svg {
        width: 30px;
        height: 30px;
      }

      .dashv12-mini-circle .track {
        stroke: rgba(8, 50, 76, 0.10);
        stroke-width: 4.5px;
      }

      .dashv12-mini-circle .value {
        stroke: var(--dashv12-green);
        stroke-width: 4.5px;
      }

      .dashv12-mini-circle span {
        position: absolute;
        inset: 0;
        display: grid;
        place-items: center;
        color: var(--dashv12-deep);
        font-size: 8px;
        font-weight: 900;
      }

      .dashv12-table-card,
      .dashv12-analysis {
        padding: 9px;
        border-radius: 15px;
        border: 1px solid rgba(255, 255, 255, 0.72);
        background: var(--dashv12-card);
        backdrop-filter: blur(16px);
        box-shadow: var(--dashv12-shadow);
      }

      .dashv12-table-wrap {
        max-height: 215px;
        overflow: auto;
        border: 1px solid var(--dashv12-border);
        border-radius: 12px;
      }

      .dashv12-table-wrap.custom {
        max-height: 250px;
      }

      .dashv12-table-wrap table {
        width: 100%;
        border-collapse: collapse;
        background: rgba(255, 255, 255, 0.54);
      }

      .dashv12-table-wrap th,
      .dashv12-table-wrap td {
        padding: 5px 7px;
        border-bottom: 1px solid rgba(8, 50, 76, 0.06);
        text-align: center;
        white-space: nowrap;
        font-size: 10px;
      }

      .dashv12-table-wrap th {
        position: sticky;
        top: 0;
        z-index: 3;
        color: white;
        background: linear-gradient(135deg, var(--dashv12-deep), var(--dashv12-blue));
        font-size: 9px;
      }

      .dashv12-table-wrap th:first-child,
      .dashv12-table-wrap td:first-child {
        text-align: left;
      }

      .dashv12-table-wrap strong,
      .dashv12-table-wrap small {
        display: block;
      }

      .dashv12-table-wrap small {
        color: var(--dashv12-muted);
        font-size: 8px;
      }

      .dashv12-mini-bar {
        display: grid;
        grid-template-columns: 50px 26px;
        align-items: center;
        gap: 4px;
      }

      .dashv12-mini-bar::before {
        content: "";
        grid-column: 1;
        grid-row: 1;
        height: 5px;
        border-radius: 999px;
        background: rgba(8, 50, 76, 0.08);
      }

      .dashv12-mini-bar span {
        grid-column: 1;
        grid-row: 1;
        display: block;
        height: 5px;
        border-radius: 999px;
        background: linear-gradient(90deg, var(--dashv12-green), var(--dashv12-sky), var(--dashv12-blue));
        z-index: 1;
      }

      .dashv12-mini-bar b {
        color: var(--dashv12-deep);
        font-size: 9.5px;
      }

      .dashv12-status {
        display: inline-flex;
        justify-content: center;
        min-width: 48px;
        padding: 3px 6px;
        border-radius: 999px;
        font-size: 9px;
        font-weight: 850;
      }

      .dashv12-status.success { color: #136f42; background: rgba(56, 168, 107, 0.14); }
      .dashv12-status.warning { color: #8a6500; background: rgba(255, 185, 70, 0.18); }
      .dashv12-status.danger { color: #9d1d1d; background: rgba(255, 110, 110, 0.16); }
      .dashv12-status.info { color: var(--dashv12-blue); background: rgba(57, 174, 202, 0.14); }

      .dashv12-analysis {
        padding: 0;
        overflow: hidden;
      }

      .dashv12-analysis summary {
        list-style: none;
        cursor: pointer;
        display: flex;
        justify-content: space-between;
        gap: 10px;
        padding: 9px;
      }

      .dashv12-analysis summary::-webkit-details-marker {
        display: none;
      }

      .dashv12-analysis h3,
      .dashv12-analysis h4 {
        margin: 0;
        color: var(--dashv12-deep);
      }

      .dashv12-analysis h3 {
        font-size: 13px;
      }

      .dashv12-analysis h4 {
        font-size: 11.5px;
      }

      .dashv12-analysis summary p {
        margin: 2px 0 0;
        color: var(--dashv12-muted);
        font-size: 9.5px;
      }

      .dashv12-analysis summary > span {
        align-self: start;
        padding: 3px 7px;
        border-radius: 999px;
        background: rgba(57, 174, 202, 0.14);
        color: var(--dashv12-blue);
        font-size: 9.5px;
        font-weight: 850;
      }

      .dashv12-analysis-body {
        display: grid;
        grid-template-columns: minmax(210px, 0.75fr) minmax(320px, 1.25fr) 105px;
        gap: 8px;
        align-items: start;
        padding: 0 9px 9px;
      }

      .dashv12-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
        margin-top: 6px;
      }

      .dashv12-chips.barrages {
        max-height: 88px;
        overflow: auto;
        padding: 6px;
        border-radius: 11px;
        border: 1px solid var(--dashv12-border);
        background: rgba(255, 255, 255, 0.42);
      }

      .dashv12-chips label {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 4px 6px;
        border-radius: 999px;
        border: 1px solid var(--dashv12-border);
        background: rgba(255, 255, 255, 0.56);
        color: var(--dashv12-text);
        font-size: 9px;
        font-weight: 800;
        cursor: pointer;
      }

      .dashv12-chips label.active {
        color: var(--dashv12-blue);
        background: rgba(57, 174, 202, 0.14);
      }

      .dashv12-analysis-result {
        display: grid;
        gap: 8px;
        padding: 0 9px 9px;
      }

      .dashv12-bars {
        height: 78px;
        display: flex;
        align-items: end;
        gap: 5px;
        overflow-x: auto;
        padding: 6px;
        border-radius: 11px;
        border: 1px solid var(--dashv12-border);
        background: rgba(255, 255, 255, 0.42);
      }

      .dashv12-bars div {
        min-width: 28px;
        height: 62px;
        display: grid;
        grid-template-rows: 1fr auto;
        align-items: end;
        gap: 3px;
      }

      .dashv12-bars span {
        display: block;
        border-radius: 7px 7px 3px 3px;
        background: linear-gradient(180deg, var(--dashv12-sky), var(--dashv12-blue));
      }

      .dashv12-bars small {
        max-height: 32px;
        justify-self: center;
        color: var(--dashv12-muted);
        font-size: 7px;
      }

      .dashv12-empty {
        min-height: 82px;
        display: grid;
        place-items: center;
        color: var(--dashv12-muted);
        font-size: 10.5px;
        border-radius: 11px;
        border: 1px dashed var(--dashv12-border);
      }

      @media (max-width: 1280px) {

        .dashv12-compact-head {
          grid-template-columns: 1fr;
        }

        .dashv12-compact-meta {
          justify-content: flex-start;
        }

        .dashv12-compact-actions {
          width: 100%;
          max-width: 360px;
          justify-self: start;
        }

        .dashv12-hero {
          grid-template-columns: 1fr;
        }

        .dashv12-grid {
          grid-template-columns: repeat(6, minmax(0, 1fr));
        }

        .dashv12-card.card-volume,
        .dashv12-card.card-agency,
        .dashv12-card.card-compare,
        .dashv12-card.card-rate,
        .dashv12-card.card-water,
        .dashv12-card.card-rank {
          grid-column: span 3;
        }

        .dashv12-filters,
        .dashv12-kpis {
          grid-template-columns: repeat(3, minmax(0, 1fr));
        }

        .dashv12-analysis-body {
          grid-template-columns: 1fr;
        }
      }

      @media (max-width: 760px) {
        .dashv12-filters,
        .dashv12-kpis,
        .dashv12-grid {
          grid-template-columns: 1fr;
        }

        .dashv12-card.card-volume,
        .dashv12-card.card-agency,
        .dashv12-card.card-compare,
        .dashv12-card.card-rate,
        .dashv12-card.card-water,
        .dashv12-card.card-rank {
          grid-column: span 1;
        }

        .top-navbar {
          grid-template-columns: 1fr !important;
        }
      }

/* === ABHL DASHBOARD REMOVE TOP BLOCK KEEP REFRESH START === */
/*
Suppression du grand bloc header dashboard
+ conservation d'un petit bouton Actualiser dans la ligne des filtres.
*/

/* Enlever la pastille Backend connecté affichée par App.jsx */
.backend-status,
.backend-connection,
.backend-connected,
.connection-status,
.status-backend,
.top-backend-status {
  display: none !important;
}

/* Enlever le grand bloc titre/header interne du dashboard */
.abhlDashV9 .dashv9-hero,
.abhlDashV10 .dashv10-hero,
.abhlDashV11 .dashv11-hero,
.abhlDashV12 .dashv12-compact-head,
.abhlDashV12 .dashv12-hero,
.abhlDashV12 .dashv12-hero-side,
.dashboard-hero-pro,
.dashboard-hero,
.premium-dashboard-hero,
.hero.dashboard-hero,
.dashboard-header {
  display: none !important;
  visibility: hidden !important;
  height: 0 !important;
  min-height: 0 !important;
  max-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important;
}

/* Le dashboard commence directement par les filtres */
.abhlDashV9,
.abhlDashV10,
.abhlDashV11,
.abhlDashV12 {
  padding-top: 0 !important;
  margin-top: 0 !important;
  gap: 8px !important;
}

/* La ligne des filtres reçoit une petite zone actions */
.dashv12-filters {
  grid-template-columns: repeat(5, minmax(120px, 1fr)) 165px !important;
  align-items: end !important;
}

.dashv12-filter-actions {
  display: grid !important;
  gap: 4px !important;
  align-self: end !important;
  min-width: 150px !important;
}

.dashv12-filter-actions button {
  width: 100% !important;
  height: 28px !important;
  min-height: 28px !important;
  border: none !important;
  border-radius: 10px !important;
  color: white !important;
  background: linear-gradient(135deg, var(--dashv12-blue, #075f8d), var(--dashv12-green, #38a86b)) !important;
  font-size: 10.5px !important;
  font-weight: 850 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 6px !important;
  cursor: pointer !important;
  box-shadow: 0 7px 16px rgba(8, 50, 76, 0.12) !important;
}

.dashv12-filter-actions label {
  display: flex !important;
  align-items: center !important;
  gap: 5px !important;
  color: var(--dashv12-text, #12354a) !important;
  font-size: 9.5px !important;
  font-weight: 850 !important;
}

.dashv12-filter-actions label input {
  display: none !important;
}

.dashv12-filter-actions label i {
  position: relative !important;
  width: 28px !important;
  height: 16px !important;
  border-radius: 999px !important;
  background: rgba(8, 50, 76, 0.16) !important;
}

.dashv12-filter-actions label i::after {
  content: "" !important;
  position: absolute !important;
  top: 3px !important;
  left: 3px !important;
  width: 10px !important;
  height: 10px !important;
  border-radius: 50% !important;
  background: white !important;
  transition: 0.16s ease !important;
}

.dashv12-filter-actions label input:checked + i {
  background: var(--dashv12-green, #38a86b) !important;
}

.dashv12-filter-actions label input:checked + i::after {
  transform: translateX(12px) !important;
}

.dashv12-filter-actions small {
  color: var(--dashv12-muted, #6d8494) !important;
  font-size: 8.5px !important;
}

@media (max-width: 1280px) {
  .dashv12-filters {
    grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
  }

  .dashv12-filter-actions {
    min-width: 0 !important;
  }
}

@media (max-width: 760px) {
  .dashv12-filters {
    grid-template-columns: 1fr !important;
  }
}
/* === ABHL DASHBOARD REMOVE TOP BLOCK KEEP REFRESH END === */

/* === ABHL DASHBOARD ANALYSIS BARS V13 SAFE START === */
.dashv12-analysis-result {
  gap: 10px !important;
}

.dashv12-bars.improved {
  height: 145px !important;
  display: flex !important;
  align-items: end !important;
  gap: 8px !important;
  overflow-x: auto !important;
  overflow-y: hidden !important;
  padding: 10px 10px 8px !important;
  border-radius: 13px !important;
  border: 1px solid var(--dashv12-border, rgba(8, 50, 76, 0.10)) !important;
  background:
    linear-gradient(180deg, rgba(255,255,255,.58), rgba(255,255,255,.40)),
    repeating-linear-gradient(
      to top,
      rgba(8, 50, 76, 0.05) 0px,
      rgba(8, 50, 76, 0.05) 1px,
      transparent 1px,
      transparent 28px
    ) !important;
}

.dashv12-bars.improved .dashv12-bar-item {
  min-width: 58px !important;
  width: 58px !important;
  height: 122px !important;
  display: grid !important;
  grid-template-rows: 82px 36px !important;
  align-items: end !important;
  justify-items: center !important;
  gap: 5px !important;
}

.dashv12-bars.improved .dashv12-bar-item > span {
  width: 30px !important;
  min-height: 4px !important;
  display: block !important;
  align-self: end !important;
  border-radius: 9px 9px 4px 4px !important;
  background: linear-gradient(180deg, var(--dashv12-sky, #39aeca), var(--dashv12-blue, #075f8d)) !important;
  box-shadow: 0 7px 14px rgba(7, 95, 141, 0.18) !important;
}

.dashv12-bars.improved .dashv12-bar-item > small {
  width: 58px !important;
  max-height: none !important;
  display: grid !important;
  gap: 1px !important;
  text-align: center !important;
  font-size: 8px !important;
  line-height: 1.05 !important;
  writing-mode: horizontal-tb !important;
  transform: none !important;
}

.dashv12-bars.improved .dashv12-bar-item > small b {
  display: block !important;
  max-width: 58px !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  white-space: nowrap !important;
  color: var(--dashv12-text, #12354a) !important;
  font-size: 8px !important;
  font-weight: 900 !important;
}

.dashv12-bars.improved .dashv12-bar-item > small em {
  display: block !important;
  color: var(--dashv12-muted, #6d8494) !important;
  font-size: 7.5px !important;
  font-style: normal !important;
}

.dashv12-analysis-body button {
  max-width: 130px !important;
  justify-self: end !important;
}
/* === ABHL DASHBOARD ANALYSIS BARS V13 SAFE END === */

    `}</style>
  );
}