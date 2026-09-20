import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import DataImportPanel from "../components/DataImportPanel";
import {
  checkBilan,
  computeBilan,
  exportBilan,
  getBilanCatalog,
  getBilanMonth,
  saveBilan,
} from "../api";


function toInputValue(value) {
  return value === null || value === undefined ? "" : String(value);
}

function toNumber(value) {
  if (value === "" || value === null || value === undefined) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatNumber(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toLocaleString("fr-FR", {
    maximumFractionDigits: digits,
  });
}

function formatDateFr(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("fr-FR").format(new Date(`${value}T12:00:00`));
}

function monthLabel(year, month) {
  return new Intl.DateTimeFormat("fr-FR", {
    month: "long",
    year: "numeric",
  }).format(new Date(year, month - 1, 1));
}

function initialPeriod(initialDate) {
  const match = String(initialDate || "").match(/^(\d{4})-(\d{2})/);
  if (match) {
    return { year: Number(match[1]), month: Number(match[2]) };
  }
  const today = new Date();
  return { year: today.getFullYear(), month: today.getMonth() + 1 };
}

function normalizeRows(form) {
  return (form?.rows || []).map((row) => ({
    date_bilan: row.date_bilan,
    cote_7h_ngm: toInputValue(row.inputs?.cote_7h_ngm),
    hauteur_bac_mm: toInputValue(row.inputs?.hauteur_bac_mm),
    pluie_mm: toInputValue(row.inputs?.pluie_mm),
    observation: row.inputs?.observation || "",
    restitutions: Object.fromEntries(
      Object.entries(row.inputs?.restitutions || {}).map(([code, value]) => [
        code,
        toInputValue(value),
      ])
    ),
    storedComputed: row.computed || null,
    storedStatus: row.statut || "NON_SAISI",
  }));
}

export default function BilanPage({ initialDate }) {
  const { canWrite } = useAuth();
  const period = initialPeriod(initialDate);
  const [catalog, setCatalog] = useState([]);
  const [barrageCode, setBarrageCode] = useState("");
  const [year, setYear] = useState(period.year);
  const [month, setMonth] = useState(period.month);
  const [form, setForm] = useState(null);
  const [rows, setRows] = useState([]);
  const [nextDayCote, setNextDayCote] = useState("");
  const [resultsByDate, setResultsByDate] = useState({});
  const [checkResult, setCheckResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [activeSection, setActiveSection] = useState("SAISIE");

  useEffect(() => {
    let mounted = true;
    getBilanCatalog()
      .then((result) => {
        if (!mounted) return;
        const items = result?.barrages || [];
        setCatalog(items);
        setBarrageCode((current) => current || items[0]?.barrage_code || "");
      })
      .catch((err) => setError(err.message));
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    const nextPeriod = initialPeriod(initialDate);
    setYear(nextPeriod.year);
    setMonth(nextPeriod.month);
  }, [initialDate]);

  const inputFields = form?.input_fields || [];
  const selectedBarrage = useMemo(
    () => catalog.find((item) => item.barrage_code === barrageCode),
    [catalog, barrageCode]
  );

  function resetResults() {
    setResultsByDate({});
    setCheckResult(null);
    setMessage("");
    setError("");
  }

  async function loadMonth() {
    if (!barrageCode) return;
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await getBilanMonth(barrageCode, year, month);
      setForm(result);
      setRows(normalizeRows(result));
      setNextDayCote(toInputValue(result.next_day_cote_7h_ngm));
      setResultsByDate({});
      setCheckResult(null);
      setMessage(
        `${result.barrage?.barrage_nom || barrageCode} — ${monthLabel(year, month)} chargé.`
      );
    } catch (err) {
      setError(err.message);
      setForm(null);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  function updateRow(index, key, value) {
    setRows((current) =>
      current.map((row, rowIndex) =>
        rowIndex === index ? { ...row, [key]: value } : row
      )
    );
    setResultsByDate((current) => {
      const next = { ...current };
      delete next[rows[index]?.date_bilan];
      return next;
    });
  }

  function updateRestitution(index, typeCode, value) {
    setRows((current) =>
      current.map((row, rowIndex) =>
        rowIndex === index
          ? {
              ...row,
              restitutions: { ...row.restitutions, [typeCode]: value },
            }
          : row
      )
    );
    setResultsByDate((current) => {
      const next = { ...current };
      delete next[rows[index]?.date_bilan];
      return next;
    });
  }

  function payloadRow(row, index) {
    const nextCote =
      index < rows.length - 1
        ? rows[index + 1]?.cote_7h_ngm
        : nextDayCote;

    return {
      date_bilan: row.date_bilan,
      cote_7h_ngm: toNumber(row.cote_7h_ngm),
      cote_suivante_ngm: toNumber(nextCote),
      hauteur_bac_mm: toNumber(row.hauteur_bac_mm),
      pluie_mm: toNumber(row.pluie_mm),
      restitutions: inputFields.map((field) => ({
        type_code: field.code,
        valeur_m3: toNumber(row.restitutions?.[field.code]) ?? 0,
      })),
      observation: row.observation || null,
    };
  }

  function buildPayload(indexes = null, save = false) {
    const selectedIndexes = indexes || rows.map((_, index) => index);
    return {
      barrage_code: barrageCode,
      year: Number(year),
      month: Number(month),
      rows: selectedIndexes.map((index) => payloadRow(rows[index], index)),
      ...(save ? { statut: "CALCULE", overwrite: true } : {}),
    };
  }

  function storeResults(result) {
    const mapped = {};
    for (const item of result?.results || []) {
      mapped[item.date_bilan] = item;
    }
    setResultsByDate((current) => ({ ...current, ...mapped }));
  }

  async function computeIndexes(indexes, successMessage) {
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await computeBilan(buildPayload(indexes));
      storeResults(result);
      setMessage(successMessage || `${result.ready_count}/${result.count} lignes calculables.`);
      return result;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setLoading(false);
    }
  }

  async function saveIndexes(indexes, successMessage) {
    const count = indexes?.length || rows.length;
    const confirmed = window.confirm(
      `Enregistrer ${count} ligne(s) BILAN pour ${selectedBarrage?.barrage_nom || barrageCode} ?\n\nLes valeurs déjà présentes pour les mêmes dates seront remplacées.`
    );
    if (!confirmed) return;

    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await saveBilan(buildPayload(indexes, true));
      storeResults(result.computed);
      setMessage(successMessage || `${result.saved_count} ligne(s) enregistrée(s) dans PostgreSQL.`);
      const refreshed = await getBilanMonth(barrageCode, year, month);
      setForm(refreshed);
      setRows(normalizeRows(refreshed));
      setNextDayCote(toInputValue(refreshed.next_day_cote_7h_ngm));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCheck() {
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await checkBilan(barrageCode, year, month);
      setCheckResult(result);
      setMessage(
        result.can_export_complete_month
          ? "Le mois est complet et peut être exporté."
          : `${result.ready_count}/${result.expected_count} lignes sont complètes.`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleExport() {
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const filename = await exportBilan(barrageCode, year, month);
      setMessage(`Fichier téléchargé : ${filename}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="page abhl-module-page bilan-page">
      <div className="module-page-heading">
        <div>
          <span className="module-kicker">Gestion métier</span>
          <h2>BILAN mensuel des barrages</h2>
          <p>
            Consultez un barrage, saisissez son mois, importez les données et
            générez le classeur officiel depuis deux espaces clairement séparés.
          </p>
        </div>

        <div className="module-tabs" role="tablist" aria-label="Sections BILAN">
          <button
            type="button"
            className={activeSection === "SAISIE" ? "active" : ""}
            onClick={() => setActiveSection("SAISIE")}
          >
            Saisie mensuelle
          </button>
          {canWrite && (
            <button
              type="button"
              className={activeSection === "IMPORT" ? "active" : ""}
              onClick={() => setActiveSection("IMPORT")}
            >
              Import et historique
            </button>
          )}
        </div>
      </div>

      <div className="panel module-filter-bar">
        <div className="module-filter-grid bilan-filter-grid">
          <label>
            Barrage
            <select
              value={barrageCode}
              onChange={(event) => {
                setBarrageCode(event.target.value);
                setForm(null);
                setRows([]);
                resetResults();
              }}
            >
              {catalog.map((item) => (
                <option key={item.barrage_code} value={item.barrage_code}>
                  {item.barrage_nom || item.barrage_code}
                  {item.is_dynamic ? " · dynamique" : ""}
                </option>
              ))}
            </select>
          </label>

          <label>
            Mois
            <select
              value={month}
              onChange={(event) => {
                setMonth(Number(event.target.value));
                setForm(null);
                resetResults();
              }}
            >
              {Array.from({ length: 12 }, (_, index) => index + 1).map((value) => (
                <option key={value} value={value}>
                  {new Intl.DateTimeFormat("fr-FR", { month: "long" }).format(
                    new Date(2026, value - 1, 1)
                  )}
                </option>
              ))}
            </select>
          </label>

          <label>
            Année
            <input
              type="number"
              min="1900"
              max="2200"
              value={year}
              onChange={(event) => {
                setYear(Number(event.target.value));
                setForm(null);
                resetResults();
              }}
            />
          </label>

          <button className="primary" onClick={loadMonth} disabled={loading || !barrageCode}>
            Charger le mois
          </button>

          {form && activeSection === "SAISIE" && (
            <button type="button" onClick={handleExport} disabled={loading}>
              Exporter BILAN Excel
            </button>
          )}
        </div>

        <div className="module-inline-note">
          Le catalogue vient de PostgreSQL : un nouveau barrage actif avec « inclure dans BILAN »,
          un barème et ses restitutions apparaît automatiquement dans cette liste.
        </div>

        {loading && <div className="alert info">Traitement en cours...</div>}
        {message && <div className="alert success">{message}</div>}
        {error && <div className="alert error">{error}</div>}
      </div>

      {activeSection === "IMPORT" ? (
        barrageCode ? (
          <DataImportPanel
            moduleCode="BILAN"
            context={{ barrage_code: barrageCode, year, month }}
            onClose={() => setActiveSection("SAISIE")}
            onChanged={loadMonth}
          />
        ) : (
          <div className="panel module-empty-guide">
            <div className="module-empty-icon">B</div>
            <div>
              <h3>Sélectionnez un barrage</h3>
              <p>Le fichier importé sera contrôlé avec la configuration actuelle de ce barrage.</p>
            </div>
          </div>
        )
      ) : (
        <>
          {!form && (
            <div className="panel module-empty-guide">
              <div className="module-empty-icon">B</div>
              <div>
                <h3>Chargez une période mensuelle</h3>
                <p>
                  Choisissez le barrage, le mois et l’année. Les champs de restitution
                  sont générés selon la configuration réelle du barrage sélectionné.
                </p>
              </div>
            </div>
          )}

      {form && (
        <>
          <div className="panel bilan-summary-panel refined-bilan-summary">
            <div className="bilan-summary-grid">
              <div>
                <span>Barrage</span>
                <strong>{form.barrage?.barrage_nom}</strong>
              </div>
              <div>
                <span>Période</span>
                <strong>{monthLabel(year, month)}</strong>
              </div>
              <label>
                Cote du {formatDateFr(form.next_date)}
                <input
                  type="number"
                  step="0.01"
                  value={nextDayCote}
                  onChange={(event) => {
                    setNextDayCote(event.target.value);
                    setResultsByDate((current) => {
                      const next = { ...current };
                      delete next[form.date_end];
                      return next;
                    });
                  }}
                  placeholder="Nécessaire pour le dernier jour"
                />
              </label>
              <div className="bilan-global-actions">
                <button onClick={() => computeIndexes(null)} disabled={loading}>
                  Calculer tout le mois
                </button>
                {canWrite && (
                  <button className="save-button" onClick={() => saveIndexes(null)} disabled={loading}>
                    Enregistrer tout le mois
                  </button>
                )}
                <button onClick={handleCheck} disabled={loading}>
                  Vérifier
                </button>
                <button className="primary" onClick={handleExport} disabled={loading}>
                  Télécharger BILAN
                </button>
              </div>
            </div>

            <div className="announcement-note">
              Les champs blancs sont saisis. Volume, surfaces, évaporation,
              variation de réserve, total, apports et débit sont calculés par le
              backend. Pour une même date, un nouvel enregistrement remplace la
              ligne précédente.
            </div>

            {checkResult && (
              <div className={checkResult.can_export_complete_month ? "bilan-check success" : "bilan-check warning"}>
                <strong>
                  {checkResult.ready_count}/{checkResult.expected_count} lignes complètes
                </strong>
                {!checkResult.can_export_complete_month && (
                  <span>
                    Le fichier peut être téléchargé, mais les journées incomplètes
                    resteront vides.
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="panel bilan-table-panel refined-bilan-table">
            <div className="bilan-table-scroll">
              <table className="bilan-table">
                <thead>
                  <tr>
                    <th className="sticky-col date-col">Date</th>
                    <th>Cote 7h</th>
                    <th>H. bac</th>
                    <th>Pluie</th>
                    {inputFields.map((field) => (
                      <th key={field.code}>{field.label}</th>
                    ))}
                    <th>Volume</th>
                    <th>Surface moy.</th>
                    <th>Évaporation</th>
                    <th>Variation</th>
                    <th>Total rest.</th>
                    <th>Apports</th>
                    <th>Débit</th>
                    <th>État</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => {
                    const result = resultsByDate[row.date_bilan];
                    const computed = result?.computed || row.storedComputed || {};
                    const status = result?.status || row.storedStatus || "NON_SAISI";
                    const checks = result?.checks || [];
                    return (
                      <tr key={row.date_bilan} className={result?.can_save === false ? "row-error" : ""}>
                        <td className="sticky-col date-col">
                          <strong>{formatDateFr(row.date_bilan)}</strong>
                        </td>
                        <td>
                          <input
                            type="number"
                            step="0.01"
                            value={row.cote_7h_ngm}
                            onChange={(event) => updateRow(index, "cote_7h_ngm", event.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            step="0.01"
                            value={row.hauteur_bac_mm}
                            onChange={(event) => updateRow(index, "hauteur_bac_mm", event.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            step="0.01"
                            min="0"
                            value={row.pluie_mm}
                            onChange={(event) => updateRow(index, "pluie_mm", event.target.value)}
                          />
                        </td>
                        {inputFields.map((field) => (
                          <td key={field.code}>
                            <input
                              type="number"
                              step="0.01"
                              min="0"
                              value={row.restitutions?.[field.code] ?? ""}
                              onChange={(event) => updateRestitution(index, field.code, event.target.value)}
                              title={`${field.label} (${field.unit || "m3"})`}
                            />
                          </td>
                        ))}
                        <td className="calculated-cell">{formatNumber(computed.volume_interval_mm3 ?? computed.volume_mm3, 6)}</td>
                        <td className="calculated-cell">{formatNumber(computed.surface_moyenne_km2, 6)}</td>
                        <td className="calculated-cell">{formatNumber(computed.evaporation_m3, 2)}</td>
                        <td className="calculated-cell">{formatNumber(computed.variation_reserve_mm3, 6)}</td>
                        <td className="calculated-cell">{formatNumber(computed.total_restitutions_m3, 2)}</td>
                        <td className="calculated-cell">{formatNumber(computed.apports_m3, 2)}</td>
                        <td className="calculated-cell">{formatNumber(computed.debit_m3s, 6)}</td>
                        <td>
                          <span className={`bilan-status ${String(status).toLowerCase()}`} title={checks.map((item) => item.message).join("\n")}>
                            {status}
                          </span>
                        </td>
                        <td>
                          <div className="bilan-row-actions">
                            <button onClick={() => computeIndexes([index], `Ligne du ${formatDateFr(row.date_bilan)} calculée.`)} disabled={loading}>
                              Calculer
                            </button>
                            {canWrite && (
                              <button className="save-button" onClick={() => saveIndexes([index], `Ligne du ${formatDateFr(row.date_bilan)} enregistrée.`)} disabled={loading}>
                                Enregistrer
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
        </>
      )}
    </section>
  );
}
