import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import {
  applyDataImport,
  downloadDataImportTemplate,
  getDataImportDetails,
  getDataImportHistory,
  previewDataImport,
  rejectDataImport,
  rollbackDataImport,
  submitDataImport,
} from "../api";

const MODES = [
  {
    value: "ADD_ONLY",
    label: "Ajouter uniquement les nouvelles lignes",
    help: "Toute ligne déjà présente dans PostgreSQL est ignorée.",
  },
  {
    value: "FILL_EMPTY",
    label: "Ajouter et compléter les champs vides",
    help: "Mode recommandé : aucune valeur existante n’est remplacée.",
  },
  {
    value: "REPLACE_SELECTED",
    label: "Remplacer les conflits sélectionnés",
    help: "Réservé aux validateurs et administrateurs. Les cellules vides du fichier n’effacent jamais la base.",
  },
];

const STATUS_LABELS = {
  PREVIEW: "Prévisualisation",
  PENDING_VALIDATION: "En attente de validation",
  APPLIED: "Validé et appliqué",
  ROLLED_BACK: "Annulé — état antérieur restauré",
  REJECTED: "Rejeté",
  FAILED: "Échec",
  NEW: "Nouvelle ligne",
  COMPLEMENT: "Champs à compléter",
  IDENTICAL: "Identique",
  CONFLICT: "Conflit",
  INVALID: "Invalide",
  APPLIED_ROW: "Appliquée",
};

function fmtDate(value) {
  if (!value) return "—";
  try {
    return new Intl.DateTimeFormat("fr-FR", {
      dateStyle: "short",
      timeStyle: value.includes?.("T") ? "short" : undefined,
    }).format(new Date(value.includes?.("T") ? value : `${value}T12:00:00`));
  } catch {
    return value;
  }
}

function fmtNumber(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (Number.isFinite(Number(value))) {
    return Number(value).toLocaleString("fr-FR", { maximumFractionDigits: 6 });
  }
  return String(value);
}

export default function DataImportPanel({
  moduleCode,
  context,
  onClose,
  onChanged,
}) {
  const { user } = useAuth();
  const [file, setFile] = useState(null);
  const [mode, setMode] = useState("FILL_EMPTY");
  const [preview, setPreview] = useState(null);
  const [selectedConflictIds, setSelectedConflictIds] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [filterBarrage, setFilterBarrage] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterDate, setFilterDate] = useState("");

  const role = user?.role_code || "CONSULTATION";
  const canValidate = ["ADMIN", "VALIDATEUR"].includes(role);
  const canPrepare = ["ADMIN", "SAISIE", "VALIDATEUR"].includes(role);
  const summary = preview?.batch?.summary || {};
  const rows = preview?.rows || [];
  const conflictRows = useMemo(
    () => rows.filter((row) => row.row_status === "CONFLICT"),
    [rows]
  );
  const availableBarrages = useMemo(
    () => [...new Set(rows.map((row) => row.barrage_code).filter(Boolean))].sort(),
    [rows]
  );
  const availableDates = useMemo(
    () => [...new Set(rows.map((row) => row.date_bilan || row.normalized_data?.date_situation).filter(Boolean))].sort(),
    [rows]
  );
  const filteredRows = useMemo(
    () => rows.filter((row) => {
      const rowDate = row.date_bilan || row.normalized_data?.date_situation || "";
      return (!filterBarrage || row.barrage_code === filterBarrage)
        && (!filterStatus || row.row_status === filterStatus)
        && (!filterDate || rowDate === filterDate);
    }),
    [rows, filterBarrage, filterStatus, filterDate]
  );

  useEffect(() => {
    refreshHistory();
  }, [moduleCode]);

  async function refreshHistory() {
    try {
      const result = await getDataImportHistory(moduleCode, 25);
      setHistory(result.imports || []);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleTemplate() {
    setError("");
    try {
      await downloadDataImportTemplate(moduleCode, context);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handlePreview() {
    if (!file) {
      setError("Sélectionnez un fichier Excel ou CSV.");
      return;
    }
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await previewDataImport(moduleCode, file, context);
      setPreview(result);
      setSelectedConflictIds([]);
      setFilterBarrage("");
      setFilterStatus("");
      setFilterDate("");
      const incomplete = Number(result.batch.summary.incomplete || 0);
      setMessage(
        incomplete > 0
          ? `${result.batch.summary.total} ligne(s) analysée(s), dont ${incomplete} incomplète(s). Elles pourront être stockées avec avertissement. Aucune donnée n’a encore été modifiée.`
          : `${result.batch.summary.total} ligne(s) analysée(s). Aucune donnée n’a encore été modifiée.`
      );
      await refreshHistory();
    } catch (err) {
      setPreview(null);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit() {
    if (!preview?.batch?.import_uid) return;
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await submitDataImport(preview.batch.import_uid, {
        mode,
        reason: null,
      });
      setMessage(result.message);
      setPreview((current) => ({
        ...current,
        batch: { ...current.batch, status: "PENDING_VALIDATION" },
      }));
      await refreshHistory();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleApply() {
    if (!preview?.batch?.import_uid) return;
    if (mode === "REPLACE_SELECTED" && selectedConflictIds.length === 0) {
      setError("Sélectionnez au moins une ligne conflictuelle à remplacer.");
      return;
    }

    const confirmed = window.confirm(
      "Valider et appliquer cet import ?\n\nUn instantané complet de l’état actuel sera enregistré avant toute modification. L’import pourra ensuite être annulé."
    );
    if (!confirmed) return;

    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await applyDataImport(preview.batch.import_uid, {
        mode,
        replace_row_ids: selectedConflictIds,
        validation_reason: null,
      });
      const incompleteText = result.incomplete_rows
        ? ` ${result.incomplete_rows} ligne(s) stockée(s) avec des champs manquants.`
        : "";
      setMessage(
        `${result.message} ${result.applied_rows} ligne(s) appliquée(s), ${result.skipped_rows} ignorée(s).${incompleteText}`
      );
      setPreview((current) => ({
        ...current,
        batch: { ...current.batch, status: "APPLIED", can_rollback: true },
      }));
      await refreshHistory();
      await onChanged?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function toggleConflict(rowId) {
    setSelectedConflictIds((current) =>
      current.includes(rowId)
        ? current.filter((item) => item !== rowId)
        : [...current, rowId]
    );
  }


  async function openImport(item) {
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await getDataImportDetails(item.import_uid);
      setPreview({
        batch: {
          ...result.batch,
          context: result.batch.import_context || {},
        },
        rows: result.rows || [],
      });
      if (result.batch.selected_mode) {
        setMode(result.batch.selected_mode);
      }
      setSelectedConflictIds([]);
      window.setTimeout(() => {
        document.querySelector(".import-preview")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 50);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleReject(item) {
    const rejectionReason = window.prompt(
      "Motif obligatoire du rejet :",
      "Le fichier doit être corrigé avant un nouvel import."
    );
    if (!rejectionReason || rejectionReason.trim().length < 3) return;
    if (!window.confirm("Rejeter cet import sans modifier les données métier ?")) return;

    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await rejectDataImport(item.import_uid, {
        reason: rejectionReason.trim(),
      });
      setMessage(result.message);
      if (preview?.batch?.import_uid === item.import_uid) {
        setPreview((current) => ({
          ...current,
          batch: { ...current.batch, status: "REJECTED" },
        }));
      }
      await refreshHistory();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function performRollback(item, force = false, presetReason = "") {
    const rollbackReason =
      presetReason ||
      window.prompt(
        "Motif obligatoire du retour arrière :",
        "Correction demandée après validation de l’import."
      );
    if (!rollbackReason || rollbackReason.trim().length < 3) return;

    const confirmed = window.confirm(
      force
        ? "Forcer le retour arrière ? Les modifications réalisées après l’import sur les mêmes données seront écrasées."
        : "Annuler cet import et restaurer exactement les données présentes avant sa validation ?"
    );
    if (!confirmed) return;

    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await rollbackDataImport(item.import_uid, {
        reason: rollbackReason.trim(),
        force,
      });
      setMessage(result.message);
      await refreshHistory();
      await onChanged?.();
    } catch (err) {
      if (
        !force &&
        role === "ADMIN" &&
        err.message.toLowerCase().includes("modifi") &&
        window.confirm(
          `${err.message}\n\nSouhaitez-vous effectuer un retour arrière forcé en tant qu’administrateur ?`
        )
      ) {
        await performRollback(item, true, rollbackReason);
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="import-workflow panel">
      <div className="import-header">
        <div>
          <span className="import-eyebrow">Import contrôlé</span>
          <h3>Importer des données {moduleCode === "ANNONCE" ? "Annonce" : "BILAN"}</h3>
          <p>
            {moduleCode === "ANNONCE"
              ? "Le fichier complet est analysé : toutes les feuilles, toutes les dates remplies et tous les barrages reconnus dans PostgreSQL. Aucune date de saisie n’est imposée."
              : "Les barrages sont lus directement depuis PostgreSQL. Le fichier est analysé avant toute modification et chaque import appliqué peut être annulé."}
          </p>
        </div>
        <button type="button" className="import-close" onClick={onClose} aria-label="Fermer">
          ×
        </button>
      </div>

      {!canPrepare && (
        <div className="alert warning">Votre rôle ne permet pas de préparer un import.</div>
      )}

      {canPrepare && (
        <>
          <div className="import-guidance-bar">
            <div>
              <strong>1. Choisir et analyser</strong>
              <span>{moduleCode === "ANNONCE" ? "Toutes les journées remplies du classeur sont contrôlées." : "Le fichier est contrôlé sans modifier la base."}</span>
            </div>
            <div>
              <strong>2. Vérifier puis appliquer</strong>
              <span>Les doublons sont ignorés et l’état précédent reste restaurable.</span>
            </div>
          </div>

          <div className="import-controls">
            <label className="import-file-field">
              Fichier à analyser
              <input
                type="file"
                accept=".xlsx,.xlsm,.csv"
                onChange={(event) => {
                  setFile(event.target.files?.[0] || null);
                  setPreview(null);
                  setMessage("");
                  setError("");
                }}
              />
              <small>{file ? `${file.name} — ${Math.ceil(file.size / 1024)} Ko` : "Aucun fichier sélectionné"}</small>
            </label>

            <label>
              Politique d’import
              <select value={mode} onChange={(event) => setMode(event.target.value)}>
                {MODES.map((item) => (
                  <option
                    key={item.value}
                    value={item.value}
                    disabled={item.value === "REPLACE_SELECTED" && !canValidate}
                  >
                    {item.label}
                  </option>
                ))}
              </select>
              <small>{MODES.find((item) => item.value === mode)?.help}</small>
            </label>

            <div className="import-control-actions">
              <button type="button" onClick={handleTemplate} disabled={loading}>
                Télécharger un modèle CSV
              </button>
              <button type="button" className="primary" onClick={handlePreview} disabled={loading || !file}>
                {loading ? "Analyse…" : "Analyser le fichier"}
              </button>
            </div>
          </div>
        </>
      )}

      {message && <div className="alert success">{message}</div>}
      {error && <div className="alert error">{error}</div>}

      {preview && (
        <div className="import-preview">
          <div className="import-summary-grid">
            <SummaryCard label="Total" value={summary.total} />
            <SummaryCard label="Nouvelles" value={summary.new} tone="new" />
            <SummaryCard label="À compléter" value={summary.complement} tone="complement" />
            <SummaryCard label="Identiques" value={summary.identical} />
            <SummaryCard label="Conflits" value={summary.conflict} tone="conflict" />
            <SummaryCard label="Incomplètes" value={summary.incomplete} tone="incomplete" />
            <SummaryCard label="Invalides" value={summary.invalid} tone="invalid" />
          </div>

          {moduleCode === "ANNONCE" && (
            <div className="import-analysis-meta">
              <div><span>Période détectée</span><strong>{fmtDate(summary.date_min)} → {fmtDate(summary.date_max)}</strong></div>
              <div><span>Dates</span><strong>{summary.dates_count ?? 0}</strong></div>
              <div><span>Barrages</span><strong>{summary.barrages_count ?? 0}</strong></div>
              <div><span>Feuilles analysées</span><strong>{summary.sheets_count ?? 0}</strong></div>
            </div>
          )}

          <div className="import-result-filters">
            <label>
              Barrage
              <select value={filterBarrage} onChange={(event) => setFilterBarrage(event.target.value)}>
                <option value="">Tous les barrages</option>
                {availableBarrages.map((code) => <option key={code} value={code}>{code}</option>)}
              </select>
            </label>
            <label>
              Date
              <select value={filterDate} onChange={(event) => setFilterDate(event.target.value)}>
                <option value="">Toutes les dates</option>
                {availableDates.map((value) => <option key={value} value={value}>{fmtDate(value)}</option>)}
              </select>
            </label>
            <label>
              État
              <select value={filterStatus} onChange={(event) => setFilterStatus(event.target.value)}>
                <option value="">Tous les états</option>
                {["NEW", "COMPLEMENT", "IDENTICAL", "CONFLICT", "INVALID"].map((value) => (
                  <option key={value} value={value}>{STATUS_LABELS[value]}</option>
                ))}
              </select>
            </label>
            <button type="button" onClick={() => { setFilterBarrage(""); setFilterStatus(""); setFilterDate(""); }}>
              Réinitialiser
            </button>
          </div>

          <div className="import-preview-title">
            <div>
              <h4>Prévisualisation — {preview.batch.original_filename}</h4>
              <p>
                Référence : <strong>{preview.batch.import_uid}</strong> · Format détecté : {preview.batch.source_format}
              </p>
            </div>
            <span className={`import-status ${String(preview.batch.status).toLowerCase()}`}>
              {STATUS_LABELS[preview.batch.status] || preview.batch.status}
            </span>
          </div>

          <div className="import-table-scroll">
            <table className="import-table">
              <thead>
                <tr>
                  {mode === "REPLACE_SELECTED" && <th>Remplacer</th>}
                  <th>Ligne</th>
                  <th>Barrage</th>
                  <th>Date</th>
                  <th>État</th>
                  <th>Données détectées</th>
                  <th>Conflits / erreurs</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.slice(0, 200).map((row) => {
                  const data = row.normalized_data || {};
                  return (
                    <tr key={row.id} className={`import-row ${String(row.row_status).toLowerCase()}`}>
                      {mode === "REPLACE_SELECTED" && (
                        <td>
                          {row.row_status === "CONFLICT" ? (
                            <input
                              type="checkbox"
                              checked={selectedConflictIds.includes(row.id)}
                              onChange={() => toggleConflict(row.id)}
                              aria-label={`Remplacer les conflits de la ligne ${row.row_number}`}
                            />
                          ) : "—"}
                        </td>
                      )}
                      <td>{row.sheet_name ? `${row.sheet_name} / ` : ""}{row.row_number}</td>
                      <td><strong>{row.barrage_code || "—"}</strong></td>
                      <td>{fmtDate(row.date_bilan || data.date_situation)}</td>
                      <td>
                        <span className={`import-row-status ${String(row.row_status).toLowerCase()}`}>
                          {STATUS_LABELS[row.row_status] || row.row_status}
                        </span>
                        {data.incomplete_fields?.length > 0 && (
                          <span className="import-incomplete-badge">Données incomplètes</span>
                        )}
                      </td>
                      <td>
                        <div className="import-data-list">
                          {moduleCode === "ANNONCE" && <span>Cote début : {fmtNumber(data.cote_interval_ngm)}</span>}
                          <span>{moduleCode === "ANNONCE" ? "Cote suivante" : "Cote"} : {fmtNumber(data.cote_7h_ngm)}</span>
                          <span>H. bac : {fmtNumber(data.hauteur_bac_mm)}</span>
                          <span>Pluie : {fmtNumber(data.pluie_mm)}</span>
                          <span>Restitutions : {Object.keys(data.restitutions || {}).length}</span>
                        </div>
                      </td>
                      <td>
                        {row.errors?.length > 0 && (
                          <ul className="import-errors">
                            {row.errors.map((item, index) => <li key={index}>{item}</li>)}
                          </ul>
                        )}
                        {row.errors?.length === 0 && row.comparison?.some((item) => item.kind === "CONFLICT") && (
                          <ul className="import-conflicts">
                            {row.comparison
                              .filter((item) => item.kind === "CONFLICT")
                              .slice(0, 5)
                              .map((item) => (
                                <li key={item.field}>
                                  {item.field} : {fmtNumber(item.old)} → {fmtNumber(item.new)}
                                </li>
                              ))}
                          </ul>
                        )}
                        {row.warnings?.length > 0 && (
                          <ul className="import-warnings">
                            {row.warnings.slice(0, 5).map((item, index) => <li key={index}>{item}</li>)}
                          </ul>
                        )}
                        {!row.errors?.length
                          && !row.warnings?.length
                          && !row.comparison?.some((item) => item.kind === "CONFLICT")
                          && "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <p className="muted-text">
            {Math.min(filteredRows.length, 200)} ligne(s) affichée(s) sur {filteredRows.length} résultat(s) filtré(s), {rows.length} au total.
          </p>

          <div className="import-validation-box compact">
            <div className="import-validation-copy">
              <strong>Prêt pour l’étape suivante</strong>
              <span>
                L’application enregistrera automatiquement l’utilisateur, toutes les dates détectées,
                le fichier, le mode choisi et l’état précédent. Les lignes incomplètes seront stockées
                avec avertissement et sans bloquer les autres lignes.
              </span>
            </div>

            <div className="import-validation-actions">
              {canValidate ? (
                <button
                  type="button"
                  className="save-button"
                  onClick={handleApply}
                  disabled={loading || summary.invalid === summary.total || !["PREVIEW", "PENDING_VALIDATION"].includes(preview.batch.status)}
                >
                  Valider et appliquer
                </button>
              ) : (
                <button
                  type="button"
                  className="primary"
                  onClick={handleSubmit}
                  disabled={loading || preview.batch.status !== "PREVIEW"}
                >
                  Envoyer pour validation
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="import-history">
        <div className="import-history-heading">
          <div>
            <h4>Historique des imports {moduleCode}</h4>
            <p>Les imports validés restent annulables tant que les mêmes données n’ont pas été modifiées ensuite.</p>
          </div>
          <button type="button" onClick={refreshHistory} disabled={loading}>Actualiser</button>
        </div>

        {history.length === 0 ? (
          <div className="empty-state">Aucun import enregistré.</div>
        ) : (
          <div className="import-history-list">
            {history.map((item) => (
              <article className="import-history-item" key={item.import_uid}>
                <div>
                  <strong>{item.original_filename}</strong>
                  <span>{item.import_uid}</span>
                  <small>
                    Créé le {fmtDate(item.created_at)} par {item.created_by_username || "utilisateur supprimé"}
                  </small>
                </div>
                <div className="import-history-meta">
                  <span className={`import-status ${String(item.status).toLowerCase()}`}>
                    {STATUS_LABELS[item.status] || item.status}
                  </span>
                  {item.validated_by_username && <small>Validé par {item.validated_by_username}</small>}
                </div>
                <div className="import-history-actions">
                  <button
                    type="button"
                    onClick={() => openImport(item)}
                    disabled={loading}
                  >
                    Ouvrir le détail
                  </button>
                  {canValidate && ["PREVIEW", "PENDING_VALIDATION"].includes(item.status) && (
                    <button
                      type="button"
                      className="danger-outline-button"
                      onClick={() => handleReject(item)}
                      disabled={loading}
                    >
                      Rejeter
                    </button>
                  )}
                  {canValidate && item.status === "APPLIED" && item.can_rollback && (
                    <button
                      type="button"
                      className="danger-button"
                      onClick={() => performRollback(item)}
                      disabled={loading}
                    >
                      Annuler et restaurer l’état précédent
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function SummaryCard({ label, value, tone = "" }) {
  return (
    <div className={`import-summary-card ${tone}`}>
      <span>{label}</span>
      <strong>{value ?? 0}</strong>
    </div>
  );
}
