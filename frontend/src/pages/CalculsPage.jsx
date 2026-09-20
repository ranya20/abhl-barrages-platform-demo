// === ABHL V26 ANNONCE NULL INPUTS ===
import { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import DataImportPanel from "../components/DataImportPanel";
import {
  computeBilan,
  exportAnnonce,
  getBilanMonth,
  getCalculsForm,
  saveBilan,
} from "../api";
import "../annonce-sheet.css";

function toInputValue(value) {
  return value === null || value === undefined ? "" : String(value);
}

function toNumber(value) {
  if (value === "" || value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatNumber(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }
  return Number(value).toLocaleString("fr-FR", {
    maximumFractionDigits: digits,
  });
}

function formatDateFr(value) {
  if (!value) return "—";
  const [year, month, day] = String(value).split("-");
  return `${day}/${month}/${year}`;
}

function monthLabel(year, month) {
  return new Intl.DateTimeFormat("fr-FR", {
    month: "long",
    year: "numeric",
  }).format(new Date(Number(year), Number(month) - 1, 1));
}

function initialPeriod(initialDate) {
  const match = String(initialDate || "").match(/^(\d{4})-(\d{2})/);
  if (match) return { year: Number(match[1]), month: Number(match[2]) };
  const today = new Date();
  return { year: today.getFullYear(), month: today.getMonth() + 1 };
}

function nextMonthFirstDate(year, month) {
  const date = new Date(Number(year), Number(month), 1, 12, 0, 0);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}-01`;
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

function periodKey(year, month) {
  return `${Number(year)}-${String(Number(month)).padStart(2, "0")}`;
}

function createSheet(form, sheetPeriodKey) {
  return {
    form,
    periodKey: sheetPeriodKey,
    rows: normalizeRows(form),
    nextDayCote: toInputValue(form?.next_day_cote_7h_ngm),
    resultsByDate: {},
    dirtyIndexes: [],
    calculatingDates: [],
  };
}

function uniqueIndexes(indexes, rowCount) {
  return [...new Set(indexes)]
    .filter((index) => Number.isInteger(index) && index >= 0 && index < rowCount)
    .sort((a, b) => a - b);
}

function mergeRowsKeepingLocal(refreshedRows, localRows, indexesToKeep) {
  const keepDates = new Set(
    indexesToKeep.map((index) => localRows[index]?.date_bilan).filter(Boolean)
  );
  const localByDate = new Map(localRows.map((row) => [row.date_bilan, row]));
  return refreshedRows.map((row) =>
    keepDates.has(row.date_bilan) ? localByDate.get(row.date_bilan) || row : row
  );
}

export default function CalculsPage({
  initialDate = "2026-06-09",
  onDateChange,
}) {
  const { canWrite } = useAuth();
  const initial = initialPeriod(initialDate);
  const [year, setYear] = useState(initial.year);
  const [month, setMonth] = useState(initial.month);
  const [catalog, setCatalog] = useState([]);
  const [selectedCode, setSelectedCode] = useState("");
  const [sheets, setSheets] = useState({});
  const [activeSection, setActiveSection] = useState("SAISIE");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const sheetsRef = useRef(sheets);
  const gridRef = useRef(null);
  const requestGenerationRef = useRef(0);

  useEffect(() => {
    sheetsRef.current = sheets;
  }, [sheets]);

  useEffect(() => {
    const next = initialPeriod(initialDate);
    setYear(next.year);
    setMonth(next.month);
  }, [initialDate]);

  const currentPeriodKey = periodKey(year, month);
  const selectedSheet = selectedCode ? sheets[selectedCode] : null;
  const currentSheet =
    selectedSheet?.periodKey === currentPeriodKey ? selectedSheet : null;
  const selectedBarrage = useMemo(
    () => catalog.find((item) => item.barrage_code === selectedCode) || null,
    [catalog, selectedCode]
  );
  const inputFields = currentSheet?.form?.input_fields || [];

  // === ABHL V21 BOEM SPECIAL COLUMNS ORDER ===
  // Les mesures BGE sont des mesures spéciales, pas des restitutions :
  // elles doivent apparaître après Total rest. et Apports comme dans annonce.xlsx.
  const restitutionInputFields = inputFields.filter(
    (field) => field?.role !== "special_measure"
  );
  const specialMeasureInputFields = inputFields.filter(
    (field) => field?.role === "special_measure"
  );
  const totalDirty = Object.values(sheets).reduce(
    (total, sheet) => total + (sheet?.dirtyIndexes?.length || 0),
    0
  );

  function resetWorkbook() {
    requestGenerationRef.current += 1;
    setCatalog([]);
    setSelectedCode("");
    sheetsRef.current = {};
    setSheets({});
    setMessage("");
    setError("");
  }

  function updateSheet(code, updater) {
    setSheets((current) => {
      const existing = current[code];
      if (!existing) return current;
      const next = { ...current, [code]: updater(existing) };
      sheetsRef.current = next;
      return next;
    });
  }

  async function loadSheet(
    code,
    force = false,
    targetYear = year,
    targetMonth = month,
    requestGeneration = requestGenerationRef.current
  ) {
    if (!code) return;

    const targetPeriodKey = periodKey(targetYear, targetMonth);
    const existing = sheetsRef.current[code];
    if (!force && existing?.periodKey === targetPeriodKey) return;

    setLoading(true);
    setError("");
    try {
      const result = await getBilanMonth(code, targetYear, targetMonth);

      // Ignore une ancienne réponse arrivée après un changement de mois/année.
      if (requestGeneration !== requestGenerationRef.current) return;

      const expectedPrefix = `${Number(targetYear)}-${String(
        Number(targetMonth)
      ).padStart(2, "0")}-`;
      const wrongDate = (result?.rows || []).find(
        (row) => !String(row?.date_bilan || "").startsWith(expectedPrefix)
      );
      if (wrongDate) {
        throw new Error(
          `La feuille ${code} a renvoyé une période incorrecte (${wrongDate.date_bilan}) au lieu de ${targetPeriodKey}.`
        );
      }

      setSheets((current) => {
        if (requestGeneration !== requestGenerationRef.current) return current;
        const next = {
          ...current,
          [code]: createSheet(result, targetPeriodKey),
        };
        sheetsRef.current = next;
        return next;
      });
    } catch (err) {
      if (requestGeneration === requestGenerationRef.current) {
        setError(err.message);
      }
    } finally {
      if (requestGeneration === requestGenerationRef.current) {
        setLoading(false);
      }
    }
  }

  async function loadWorkbook() {
    const targetYear = Number(year);
    const targetMonth = Number(month);
    const requestGeneration = requestGenerationRef.current + 1;
    requestGenerationRef.current = requestGeneration;

    setLoading(true);
    setError("");
    setMessage("");
    setCatalog([]);
    setSelectedCode("");
    setSheets({});
    sheetsRef.current = {};

    try {
      const exportDate = nextMonthFirstDate(targetYear, targetMonth);
      const form = await getCalculsForm(exportDate);
      const items = (form?.barrages || []).filter(
        (item) => item.inclure_annonce !== false
      );

      if (!items.length) {
        throw new Error("Aucun barrage actif n’est configuré pour l’annonce.");
      }

      const firstCode = items[0].barrage_code;
      if (requestGeneration !== requestGenerationRef.current) return;

      setCatalog(items);
      setSelectedCode(firstCode);
      onDateChange?.(exportDate);
      await loadSheet(
        firstCode,
        true,
        targetYear,
        targetMonth,
        requestGeneration
      );
      if (requestGeneration !== requestGenerationRef.current) return;
      setMessage(
        `${items.length} barrage(s) chargé(s) pour ${monthLabel(
          targetYear,
          targetMonth
        )}. ` +
          "Choisissez un onglet puis saisissez directement dans le tableau."
      );
    } catch (err) {
      setError(err.message);
      setCatalog([]);
      setSelectedCode("");
      setSheets({});
    } finally {
      setLoading(false);
    }
  }

  async function selectBarrage(code) {
    setSelectedCode(code);
    setError("");
    setMessage("");
    await loadSheet(
      code,
      false,
      Number(year),
      Number(month),
      requestGenerationRef.current
    );
  }

  function markDirty(sheet, indexes) {
    return uniqueIndexes(
      [...(sheet.dirtyIndexes || []), ...indexes],
      sheet.rows.length
    );
  }

  function clearResultsForIndexes(sheet, indexes) {
    const nextResults = { ...sheet.resultsByDate };
    for (const index of indexes) {
      const date = sheet.rows[index]?.date_bilan;
      if (date) delete nextResults[date];
    }
    return nextResults;
  }

  function updateRow(index, key, value) {
    const affected = key === "cote_7h_ngm" ? [index - 1, index] : [index];
    updateSheet(selectedCode, (sheet) => {
      const indexes = uniqueIndexes(affected, sheet.rows.length);
      return {
        ...sheet,
        rows: sheet.rows.map((row, rowIndex) =>
          rowIndex === index ? { ...row, [key]: value } : row
        ),
        dirtyIndexes: markDirty(sheet, indexes),
        resultsByDate: clearResultsForIndexes(sheet, indexes),
      };
    });
  }

  function updateRestitution(index, typeCode, value) {
    updateSheet(selectedCode, (sheet) => ({
      ...sheet,
      rows: sheet.rows.map((row, rowIndex) =>
        rowIndex === index
          ? {
              ...row,
              restitutions: { ...row.restitutions, [typeCode]: value },
            }
          : row
      ),
      dirtyIndexes: markDirty(sheet, [index]),
      resultsByDate: clearResultsForIndexes(sheet, [index]),
    }));
  }

  function updateNextDayCote(value) {
    updateSheet(selectedCode, (sheet) => {
      const lastIndex = sheet.rows.length - 1;
      return {
        ...sheet,
        nextDayCote: value,
        dirtyIndexes: markDirty(sheet, [lastIndex]),
        resultsByDate: clearResultsForIndexes(sheet, [lastIndex]),
      };
    });
  }

  function payloadRow(sheet, index) {
    const row = sheet.rows[index];
    const nextCote =
      index < sheet.rows.length - 1
        ? sheet.rows[index + 1]?.cote_7h_ngm
        : sheet.nextDayCote;

    return {
      date_bilan: row.date_bilan,
      cote_7h_ngm: toNumber(row.cote_7h_ngm),
      cote_suivante_ngm: toNumber(nextCote),
      hauteur_bac_mm: toNumber(row.hauteur_bac_mm),
      pluie_mm: toNumber(row.pluie_mm),
      restitutions: (sheet.form?.input_fields || []).map((field) => ({
        type_code: field.code,
        valeur_m3: toNumber(row.restitutions?.[field.code]) ?? null,
      })),
      observation: row.observation || null,
    };
  }

  function rowIsReady(sheet, index) {
    const row = sheet.rows[index];
    if (!row) return false;
    const nextCote =
      index < sheet.rows.length - 1
        ? sheet.rows[index + 1]?.cote_7h_ngm
        : sheet.nextDayCote;

    return (
      toNumber(row.cote_7h_ngm) !== null &&
      toNumber(nextCote) !== null &&
      toNumber(row.hauteur_bac_mm) !== null &&
      toNumber(row.pluie_mm) !== null
    );
  }

  function buildPayload(code, sheet, indexes, save = false) {
    return {
      barrage_code: code,
      year: Number(year),
      month: Number(month),
      rows: indexes.map((index) => payloadRow(sheet, index)),
      ...(save ? { statut: "CALCULE", overwrite: true } : {}),
    };
  }

  async function computeIndexes(code, requestedIndexes, options = {}) {
    const sheet = sheetsRef.current[code];
    if (!sheet) return null;

    const indexes = uniqueIndexes(requestedIndexes, sheet.rows.length).filter(
      (index) => rowIsReady(sheet, index)
    );
    if (!indexes.length) return null;

    const dates = indexes.map((index) => sheet.rows[index].date_bilan);
    updateSheet(code, (current) => ({
      ...current,
      calculatingDates: [...new Set([...(current.calculatingDates || []), ...dates])],
    }));

    try {
      const freshSheet = sheetsRef.current[code];
      const result = await computeBilan(buildPayload(code, freshSheet, indexes));
      const mapped = {};
      for (const item of result?.results || []) mapped[item.date_bilan] = item;

      updateSheet(code, (current) => ({
        ...current,
        resultsByDate: { ...current.resultsByDate, ...mapped },
        calculatingDates: (current.calculatingDates || []).filter(
          (date) => !dates.includes(date)
        ),
      }));

      if (!options.silent) {
        setMessage(`${result.ready_count}/${result.count} ligne(s) calculée(s).`);
      }
      return result;
    } catch (err) {
      updateSheet(code, (current) => ({
        ...current,
        calculatingDates: (current.calculatingDates || []).filter(
          (date) => !dates.includes(date)
        ),
      }));
      setError(err.message);
      return null;
    }
  }

  function handleCellBlur(index, key) {
    const affected = key === "cote_7h_ngm" ? [index - 1, index] : [index];
    window.setTimeout(() => {
      computeIndexes(selectedCode, affected, { silent: true });
    }, 0);
  }

  function focusGridCell(rowIndex, columnKey) {
    const selector = `[data-row-index="${rowIndex}"][data-column-key="${columnKey}"]`;
    gridRef.current?.querySelector(selector)?.focus();
  }

  function handleGridKeyDown(event, rowIndex, columnKey) {
    if (event.key === "Enter" || event.key === "ArrowDown") {
      event.preventDefault();
      focusGridCell(rowIndex + 1, columnKey);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusGridCell(rowIndex - 1, columnKey);
    }
  }

  async function saveCurrentSheet() {
    const code = selectedCode;
    const sheet = sheetsRef.current[code];
    if (!sheet) return;

    const dirty = uniqueIndexes(sheet.dirtyIndexes || [], sheet.rows.length);
    const ready = dirty.filter((index) => rowIsReady(sheet, index));
    const incomplete = dirty.filter((index) => !rowIsReady(sheet, index));

    if (!ready.length) {
      setError(
        incomplete.length
          ? "Les lignes modifiées sont encore incomplètes. Elles restent dans le tableau mais ne peuvent pas être calculées ni enregistrées."
          : "Aucune modification à enregistrer."
      );
      return;
    }

    const confirmed = window.confirm(
      `Enregistrer ${ready.length} ligne(s) calculable(s) pour ${
        selectedBarrage?.barrage_nom || code
      } ?${incomplete.length ? `\n\n${incomplete.length} ligne(s) incomplète(s) resteront non enregistrées.` : ""}`
    );
    if (!confirmed) return;

    setLoading(true);
    setError("");
    setMessage("");
    try {
      const freshSheet = sheetsRef.current[code];
      const result = await saveBilan(buildPayload(code, freshSheet, ready, true));
      if (result?.status !== "ok") {
        throw new Error(result?.message || "L’enregistrement a échoué.");
      }

      const refreshedForm = await getBilanMonth(code, year, month);
      const refreshedRows = normalizeRows(refreshedForm);
      const localSheet = sheetsRef.current[code];
      const mergedRows = mergeRowsKeepingLocal(
        refreshedRows,
        localSheet.rows,
        incomplete
      );

      setSheets((current) => {
        const next = {
          ...current,
          [code]: {
            ...createSheet(refreshedForm, periodKey(year, month)),
            rows: mergedRows,
            nextDayCote: localSheet.nextDayCote,
            dirtyIndexes: incomplete,
          },
        };
        sheetsRef.current = next;
        return next;
      });
      setMessage(
        `${result.saved_count} ligne(s) enregistrée(s) pour ${
          selectedBarrage?.barrage_nom || code
        }.${incomplete.length ? ` ${incomplete.length} ligne(s) restent à compléter.` : ""}`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function exportFullAnnonce() {
    if (totalDirty > 0) {
      setError(
        `Il reste ${totalDirty} ligne(s) modifiée(s) non enregistrée(s). Enregistrez-les avant l’export.`
      );
      return;
    }

    setLoading(true);
    setError("");
    setMessage("");
    try {
      const filename = await exportAnnonce(nextMonthFirstDate(year, month));
      setMessage(`Fichier téléchargé : ${filename}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function statusForRow(sheet, row, index) {
    const result = sheet.resultsByDate?.[row.date_bilan];
    const calculating = sheet.calculatingDates?.includes(row.date_bilan);
    const dirty = sheet.dirtyIndexes?.includes(index);

    if (calculating) return { label: "Calcul…", className: "calculating" };
    if (!rowIsReady(sheet, index)) {
      return { label: dirty ? "À compléter" : row.storedStatus || "Incomplète", className: "incomplete" };
    }
    if (result?.can_save === false) {
      return { label: "À corriger", className: "error", checks: result.checks || [] };
    }
    if (result?.can_save === true) {
      return { label: dirty ? "Calculée" : "Prête", className: dirty ? "calculated" : "ready", checks: result.checks || [] };
    }
    if (dirty) return { label: "À calculer", className: "pending" };
    return { label: row.storedStatus || "Enregistrée", className: "saved" };
  }

  return (
    <section className="page abhl-module-page calculations-page annonce-workbook-page">
      <div className="module-page-heading">
        <div>
          <span className="module-kicker">Gestion métier</span>
          <h2>Annonce mensuelle des barrages</h2>
          <p>
            Travaillez comme dans le classeur Excel : un onglet par barrage, une
            ligne par journée et des calculs déclenchés automatiquement après la saisie.
          </p>
        </div>

        <div className="module-tabs" role="tablist" aria-label="Sections Annonce">
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

      {activeSection === "IMPORT" ? (
        <DataImportPanel
          moduleCode="ANNONCE"
          context={{}}
          onClose={() => setActiveSection("SAISIE")}
        />
      ) : (
        <>
          <div className="panel annonce-workbook-toolbar">
            <div className="annonce-period-controls">
              <label>
                Mois
                <select
                  value={month}
                  onChange={(event) => {
                    setMonth(Number(event.target.value));
                    resetWorkbook();
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
                    resetWorkbook();
                  }}
                />
              </label>

              <button className="primary" onClick={loadWorkbook} disabled={loading}>
                Charger le classeur
              </button>
            </div>

            <div className="annonce-workbook-actions">
              {currentSheet && canWrite && (
                <button
                  className="save-button"
                  onClick={saveCurrentSheet}
                  disabled={loading || !currentSheet.dirtyIndexes?.length}
                >
                  Enregistrer ce barrage
                </button>
              )}
              {catalog.length > 0 && (
                <button className="primary" onClick={exportFullAnnonce} disabled={loading}>
                  Exporter annonce Excel
                </button>
              )}
            </div>

            <div className="annonce-workbook-context">
              <span>Période</span>
              <strong>{monthLabel(year, month)}</strong>
              <small>
                {catalog.length
                  ? `${catalog.length} barrage(s) dynamique(s)`
                  : "Chargez le classeur pour commencer"}
              </small>
            </div>
          </div>

          {loading && <div className="alert info">Traitement en cours…</div>}
          {message && <div className="alert success">{message}</div>}
          {error && <div className="alert error">{error}</div>}

          {!catalog.length && !loading && (
            <div className="panel module-empty-guide">
              <div className="module-empty-icon">A</div>
              <div>
                <h3>Chargez le classeur mensuel</h3>
                <p>
                  La plateforme récupère automatiquement tous les barrages actifs
                  configurés avec « inclure dans Annonce ».
                </p>
              </div>
            </div>
          )}

          {catalog.length > 0 && (
            <div className="panel annonce-barrage-tabs-panel">
              <div className="annonce-barrage-tabs" role="tablist" aria-label="Barrages">
                {catalog.map((item) => {
                  const dirtyCount = sheets[item.barrage_code]?.dirtyIndexes?.length || 0;
                  return (
                    <button
                      type="button"
                      role="tab"
                      key={item.barrage_code}
                      className={selectedCode === item.barrage_code ? "active" : ""}
                      onClick={() => selectBarrage(item.barrage_code)}
                    >
                      <span>{item.barrage_nom || item.barrage_code}</span>
                      {dirtyCount > 0 && <em>{dirtyCount}</em>}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {catalog.length > 0 && !currentSheet && !loading && (
            <div className="panel module-empty-guide">
              <div className="module-empty-icon">B</div>
              <div>
                <h3>Chargement du barrage</h3>
                <p>Sélectionnez un onglet pour ouvrir sa feuille mensuelle.</p>
              </div>
            </div>
          )}

          {currentSheet && (
            <>
              <div className="panel annonce-sheet-summary">
                <div>
                  <span>Barrage</span>
                  <strong>
                    {currentSheet.form?.barrage?.barrage_nom ||
                      selectedBarrage?.barrage_nom ||
                      selectedCode}
                  </strong>
                </div>
                <div>
                  <span>Période</span>
                  <strong>{monthLabel(year, month)}</strong>
                </div>
                <label>
                  Cote à 7h du {formatDateFr(currentSheet.form?.next_date)}
                  <input
                    type="number"
                    step="0.01"
                    value={currentSheet.nextDayCote}
                    onChange={(event) => updateNextDayCote(event.target.value)}
                    onBlur={() =>
                      computeIndexes(selectedCode, [currentSheet.rows.length - 1], {
                        silent: true,
                      })
                    }
                    placeholder="Nécessaire pour calculer le dernier jour"
                  />
                </label>
                <div className="annonce-auto-info">
                  <strong>Calcul automatique</strong>
                  <span>
                    Quittez une cellule ou appuyez sur Entrée : la ligne se recalcule
                    dès que la cote du lendemain, la hauteur du bac et la pluie sont disponibles.
                  </span>
                </div>
              </div>

              <div className="panel annonce-sheet-panel" ref={gridRef}>
                <div className="annonce-sheet-scroll">
                  <table className="annonce-sheet-table">
                    <thead>
                      <tr>
                        <th className="sticky-date">Date</th>
                        <th className="editable-heading">Cote à 7h<br />(NGM)</th>
                        <th className="calculated-heading">Volume<br />(Mm³)</th>
                        <th className="editable-heading">Hauteur bac<br />(mm)</th>
                        <th className="editable-heading">Pluie<br />(mm)</th>
                        <th className="calculated-heading">Évaporation<br />(m³)</th>
                        {restitutionInputFields.map((field) => (
                          <th className="editable-heading" key={field.code}>
                            {field.label}<br />({field.unit || "m³"})
                          </th>
                        ))}
                        <th className="calculated-heading">Total rest.<br />(m³)</th>
                        <th className="calculated-heading">Apports<br />(m³)</th>

                        {specialMeasureInputFields.map((field) => (
                          <th className="editable-heading" key={field.code}>
                            {field.label}<br />({field.unit || "m³"})
                          </th>
                        ))}
                        <th className="status-heading">État</th>
                      </tr>
                    </thead>
                    <tbody>
                      {currentSheet.rows.map((row, index) => {
                        const result = currentSheet.resultsByDate?.[row.date_bilan];
                        const computed = result?.computed || row.storedComputed || {};
                        const rowStatus = statusForRow(currentSheet, row, index);
                        const dirty = currentSheet.dirtyIndexes?.includes(index);
                        const classNames = [
                          dirty ? "row-dirty" : "",
                          rowStatus.className === "incomplete" ? "row-incomplete" : "",
                          rowStatus.className === "error" ? "row-error" : "",
                        ]
                          .filter(Boolean)
                          .join(" ");

                        return (
                          <tr key={row.date_bilan} className={classNames}>
                            <td className="sticky-date">
                              <strong>{formatDateFr(row.date_bilan)}</strong>
                            </td>
                            <GridNumberInput
                              rowIndex={index}
                              columnKey="cote"
                              value={row.cote_7h_ngm}
                              step="0.01"
                              onChange={(value) => updateRow(index, "cote_7h_ngm", value)}
                              onBlur={() => handleCellBlur(index, "cote_7h_ngm")}
                              onKeyDown={handleGridKeyDown}
                            />
                            <td className="calculated-cell">
                              {formatNumber(
                                computed.volume_interval_mm3 ?? computed.volume_mm3,
                                6
                              )}
                            </td>
                            <GridNumberInput
                              rowIndex={index}
                              columnKey="hauteur"
                              value={row.hauteur_bac_mm}
                              step="0.01"
                              onChange={(value) => updateRow(index, "hauteur_bac_mm", value)}
                              onBlur={() => handleCellBlur(index, "hauteur_bac_mm")}
                              onKeyDown={handleGridKeyDown}
                            />
                            <GridNumberInput
                              rowIndex={index}
                              columnKey="pluie"
                              value={row.pluie_mm}
                              step="0.01"
                              min="0"
                              onChange={(value) => updateRow(index, "pluie_mm", value)}
                              onBlur={() => handleCellBlur(index, "pluie_mm")}
                              onKeyDown={handleGridKeyDown}
                            />
                            <td className="calculated-cell">
                              {formatNumber(computed.evaporation_m3, 2)}
                            </td>
                            {restitutionInputFields.map((field) => (
                              <GridNumberInput
                                key={field.code}
                                rowIndex={index}
                                columnKey={`rest-${field.code}`}
                                value={row.restitutions?.[field.code] ?? ""}
                                step="0.01"
                                min="0"
                                title={`${field.label} (${field.unit || "m³"})`}
                                onChange={(value) =>
                                  updateRestitution(index, field.code, value)
                                }
                                onBlur={() => handleCellBlur(index, field.code)}
                                onKeyDown={handleGridKeyDown}
                              />
                            ))}
                            <td className="calculated-cell">
                              {formatNumber(computed.total_restitutions_m3, 2)}
                            </td>
                            <td className="calculated-cell">
                              {formatNumber(
                                computed.apports_raw_m3 ?? computed.apports_m3,
                                2
                              )}
                            </td>

                            {specialMeasureInputFields.map((field) => (
                              <GridNumberInput
                                key={field.code}
                                rowIndex={index}
                                columnKey={`rest-${field.code}`}
                                value={row.restitutions?.[field.code] ?? ""}
                                step="0.01"
                                min="0"
                                title={`${field.label} (${field.unit || "m³"})`}
                                onChange={(value) =>
                                  updateRestitution(index, field.code, value)
                                }
                                onBlur={() => handleCellBlur(index, field.code)}
                                onKeyDown={handleGridKeyDown}
                              />
                            ))}
                            <td className="status-cell">
                              <span
                                className={`annonce-row-status ${rowStatus.className}`}
                                title={(rowStatus.checks || [])
                                  .map((item) => item.message)
                                  .join("\n")}
                              >
                                {rowStatus.label}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="annonce-sheet-legend">
                <span><i className="editable" /> Cellules blanches : saisie</span>
                <span><i className="calculated" /> Cellules bleutées : calcul automatique</span>
                <span><i className="dirty" /> Point bleu : modification non enregistrée</span>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}

function GridNumberInput({
  rowIndex,
  columnKey,
  value,
  onChange,
  onBlur,
  onKeyDown,
  step = "any",
  min,
  title,
}) {
  return (
    <td className="editable-cell">
      <input
        type="number"
        step={step}
        min={min}
        value={value}
        title={title}
        data-row-index={rowIndex}
        data-column-key={columnKey}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        onKeyDown={(event) => onKeyDown(event, rowIndex, columnKey)}
      />
    </td>
  );
}
