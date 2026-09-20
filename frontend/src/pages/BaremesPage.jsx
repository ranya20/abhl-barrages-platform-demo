import { useEffect, useMemo, useState } from "react";
import {
  archiveBaremeVersion,
  cloneBaremeVersion,
  createBaremeDraft,
  deleteBaremeDraft,
  downloadBaremeTemplate,
  getBaremeAudit,
  getBaremeManagementBarrages,
  getBaremeVersion,
  getBaremeVersions,
  importBaremeDraft,
  previewBaremeImport,
  previewBaremePeriod,
  publishBaremeVersion,
  resolveBareme,
  updateBaremeDraft,
  updateBaremePeriod,
} from "../api";
import { useAuth } from "../auth/AuthContext";
import "./BaremesPage.css";

const EMPTY_POINT = { cote_ngm: "", volume_mm3: "", surface_km2: "" };

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function emptyDraft(code = "") {
  return {
    barrage_code: code,
    nom: "",
    annee_bareme: "",
    date_debut_validite: "",
    date_fin_validite: "",
    cote_normale_ngm: "",
    volume_normal_mm3: "",
    surface_normale_km2: "",
    observation: "",
    points: [{ ...EMPTY_POINT }],
  };
}

function decimalOrNull(value) {
  if (value === "" || value === null || value === undefined) return null;
  const normalized = String(value).trim().replace(/\s+/g, "").replace(",", ".");
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(normalized)) return null;
  return normalized;
}

function canonicalDecimal(value) {
  if (value === "" || value === null || value === undefined) return null;
  let raw = String(value).trim().replace(/\s+/g, "").replace(",", ".");
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw)) return null;

  let sign = "";
  if (raw.startsWith("-")) {
    sign = "-";
    raw = raw.slice(1);
  } else if (raw.startsWith("+")) {
    raw = raw.slice(1);
  }

  let [integer = "0", fraction = ""] = raw.split(".");
  integer = integer.replace(/^0+(?=\d)/, "") || "0";
  fraction = fraction.replace(/0+$/, "");

  if (integer === "0" && !fraction) sign = "";
  return `${sign}${integer}${fraction ? `.${fraction}` : ""}`;
}

function deriveNormalReference(points, coteNormale) {
  const key = canonicalDecimal(coteNormale);
  if (!key) return null;

  const matches = (points || []).filter(
    (point) => canonicalDecimal(point?.cote_ngm) === key
  );
  if (matches.length !== 1) return null;

  return {
    volume_mm3: matches[0]?.volume_mm3 ?? "",
    surface_km2: matches[0]?.surface_km2 ?? "",
  };
}

function formatNumber(value, digits = 6) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString("fr-FR", { maximumFractionDigits: digits });
}

function statusLabel(status) {
  if (status === "PUBLIE") return "Publié";
  if (status === "BROUILLON") return "Brouillon";
  if (status === "ARCHIVE") return "Archivé";
  return status || "—";
}

function cleanPointPayload(points) {
  const cleaned = [];
  for (const point of points || []) {
    const values = [point.cote_ngm, point.volume_mm3, point.surface_km2];
    if (values.every((v) => v === "" || v === null || v === undefined)) continue;
    if (values.some((v) => v === "" || v === null || v === undefined)) {
      throw new Error("Chaque ligne du barème doit contenir cote, volume et surface.");
    }
    const cote = decimalOrNull(point.cote_ngm);
    const volume = decimalOrNull(point.volume_mm3);
    const surface = decimalOrNull(point.surface_km2);
    if ([cote, volume, surface].some((v) => v === null)) {
      throw new Error("Une valeur de barème n'est pas numérique.");
    }
    cleaned.push({ cote_ngm: cote, volume_mm3: volume, surface_km2: surface });
  }
  if (cleaned.length < 2) {
    throw new Error("Le barème doit contenir au moins deux points.");
  }
  return cleaned;
}

function versionToDraft(version) {
  return {
    barrage_code: version.barrage_code,
    nom: version.nom || "",
    annee_bareme: version.annee_bareme || "",
    date_debut_validite: version.date_debut_validite || "",
    date_fin_validite: version.date_fin_validite || "",
    cote_normale_ngm: version.cote_normale_ngm ?? "",
    volume_normal_mm3: version.volume_normal_mm3 ?? "",
    surface_normale_km2: version.surface_normale_km2 ?? "",
    observation: version.observation || "",
    points: (version.points || []).map((p) => ({
      cote_ngm: p.cote_ngm ?? "",
      volume_mm3: p.volume_mm3 ?? "",
      surface_km2: p.surface_km2 ?? "",
    })),
  };
}

export default function BaremesPage() {
  const { user } = useAuth();
  const roleCode = user?.role_code || "CONSULTATION";
  const canDraft = ["ADMIN", "SAISIE", "VALIDATEUR"].includes(roleCode);
  const canPublish = ["ADMIN", "VALIDATEUR"].includes(roleCode);
  const canArchive = roleCode === "ADMIN";

  const [barrages, setBarrages] = useState([]);
  const [selectedCode, setSelectedCode] = useState("");
  const [versions, setVersions] = useState([]);
  const [selectedVersionId, setSelectedVersionId] = useState(null);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [draft, setDraft] = useState(emptyDraft());
  const [editingDraft, setEditingDraft] = useState(false);
  const [periodForm, setPeriodForm] = useState({
    date_debut_validite: "",
    date_fin_validite: "",
    commentaire: "",
  });
  const [periodPreview, setPeriodPreview] = useState(null);
  const [resolveDate, setResolveDate] = useState(todayIso());
  const [resolved, setResolved] = useState(null);
  const [audit, setAudit] = useState([]);
  const [file, setFile] = useState(null);
  const [filePreview, setFilePreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const selectedBarrage = useMemo(
    () => barrages.find((b) => b.code === selectedCode) || null,
    [barrages, selectedCode]
  );

  const normalReferencePoints = useMemo(() => {
    if (!selectedVersion && filePreview?.points?.length) return filePreview.points;
    return draft.points || [];
  }, [selectedVersion, filePreview, draft.points]);

  const derivedNormalReference = useMemo(
    () => deriveNormalReference(normalReferencePoints, draft.cote_normale_ngm),
    [normalReferencePoints, draft.cote_normale_ngm]
  );

  const hasNormalCote = canonicalDecimal(draft.cote_normale_ngm) !== null;

  function clearFeedback() {
    setMessage("");
    setError("");
  }

  async function loadBarrages() {
    const response = await getBaremeManagementBarrages();
    const data = response?.data || [];
    setBarrages(data);
    if (!selectedCode && data.length) {
      setSelectedCode(data[0].code);
    }
  }

  async function loadVersions(code = selectedCode) {
    if (!code) return;
    const response = await getBaremeVersions(code);
    setVersions(response?.data || []);
  }

  async function loadAudit(versionId = selectedVersionId) {
    const response = await getBaremeAudit(versionId || null, 100);
    setAudit(response?.data || []);
  }

  async function refresh(code = selectedCode, keepVersion = selectedVersionId) {
    await loadBarrages();
    await loadVersions(code);
    if (keepVersion) {
      try {
        const detail = await getBaremeVersion(keepVersion);
        setSelectedVersion(detail?.data || null);
      } catch {
        setSelectedVersion(null);
        setSelectedVersionId(null);
      }
    }
    await loadAudit(keepVersion);
  }

  useEffect(() => {
    setLoading(true);
    Promise.all([loadBarrages(), loadAudit(null)])
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedCode) return;
    setLoading(true);
    clearFeedback();
    setSelectedVersionId(null);
    setSelectedVersion(null);
    setEditingDraft(false);
    setDraft(emptyDraft(selectedCode));
    setFilePreview(null);
    setResolved(null);
    loadVersions(selectedCode)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCode]);

  async function selectVersion(versionId) {
    setLoading(true);
    clearFeedback();
    try {
      const response = await getBaremeVersion(versionId);
      const detail = response?.data;
      setSelectedVersionId(versionId);
      setSelectedVersion(detail);
      setEditingDraft(detail?.status === "BROUILLON");
      if (detail?.status === "BROUILLON") {
        setDraft(versionToDraft(detail));
      }
      setPeriodForm({
        date_debut_validite: detail?.date_debut_validite || "",
        date_fin_validite: detail?.date_fin_validite || "",
        commentaire: "",
      });
      setPeriodPreview(null);
      await loadAudit(versionId);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function startNewManual() {
    clearFeedback();
    setSelectedVersionId(null);
    setSelectedVersion(null);
    setEditingDraft(true);
    setFile(null);
    setFilePreview(null);
    setDraft({
      ...emptyDraft(selectedCode),
      nom: selectedCode ? `Nouveau barème ${selectedCode}` : "Nouveau barème",
    });
  }

  function updateDraft(field, value) {
    setDraft((prev) => ({ ...prev, [field]: value }));
  }

  function updatePoint(index, field, value) {
    setDraft((prev) => ({
      ...prev,
      points: prev.points.map((p, i) => (i === index ? { ...p, [field]: value } : p)),
    }));
  }

  function addPoint() {
    setDraft((prev) => ({ ...prev, points: [...prev.points, { ...EMPTY_POINT }] }));
  }

  function removePoint(index) {
    setDraft((prev) => {
      const next = prev.points.filter((_, i) => i !== index);
      return { ...prev, points: next.length ? next : [{ ...EMPTY_POINT }] };
    });
  }

  function buildDraftPayload() {
    return {
      barrage_code: selectedCode,
      nom: draft.nom.trim(),
      annee_bareme: draft.annee_bareme === "" ? null : Number(draft.annee_bareme),
      date_debut_validite: draft.date_debut_validite || null,
      date_fin_validite: draft.date_fin_validite || null,
      cote_normale_ngm: decimalOrNull(draft.cote_normale_ngm),
      // V28.2 : volume normal calculé côté serveur depuis la cote normale.
      // V28.2 : surface normale calculée côté serveur depuis la cote normale.
      observation: draft.observation || null,
      source_type: "MANUEL",
      source_fichier: "Saisie plateforme",
      source_feuille: "BAREME",
      points: cleanPointPayload(draft.points),
    };
  }

  async function saveManualDraft() {
    setLoading(true);
    clearFeedback();
    try {
      const payload = buildDraftPayload();
      let response;
      if (selectedVersion?.status === "BROUILLON" && selectedVersionId) {
        const { barrage_code, source_type, source_fichier, source_feuille, ...updatePayload } = payload;
        response = await updateBaremeDraft(selectedVersionId, updatePayload);
      } else {
        response = await createBaremeDraft(payload);
      }
      const detail = response?.data;
      setMessage(response?.message || "Brouillon enregistré.");
      setSelectedVersionId(detail?.id || selectedVersionId);
      setSelectedVersion(detail || null);
      if (detail) setDraft(versionToDraft(detail));
      await refresh(selectedCode, detail?.id || selectedVersionId);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handlePreviewFile() {
    if (!file) {
      setError("Choisissez un fichier .xlsx.");
      return;
    }
    setLoading(true);
    clearFeedback();
    try {
      const response = await previewBaremeImport(file);
      setFilePreview(response?.data || null);
      setMessage("Fichier contrôlé. Vérifiez l'aperçu avant de créer le brouillon.");
    } catch (err) {
      setFilePreview(null);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function createDraftFromFile() {
    if (!file || !filePreview) {
      setError("Analysez d'abord le fichier.");
      return;
    }
    if (!draft.nom.trim()) {
      setError("Donnez un nom à la version.");
      return;
    }
    setLoading(true);
    clearFeedback();
    try {
      const response = await importBaremeDraft(file, {
        barrage_code: selectedCode,
        nom: draft.nom,
        annee_bareme: draft.annee_bareme,
        date_debut_validite: draft.date_debut_validite,
        date_fin_validite: draft.date_fin_validite,
        cote_normale_ngm: draft.cote_normale_ngm,
        // V28.2 : valeur dérivée automatiquement.
        // V28.2 : valeur dérivée automatiquement.
        observation: draft.observation,
      });
      const detail = response?.data;
      setMessage("Fichier importé en BROUILLON. Il n'est pas encore utilisé dans les calculs.");
      setSelectedVersionId(detail?.id || null);
      setSelectedVersion(detail || null);
      setEditingDraft(true);
      if (detail) setDraft(versionToDraft(detail));
      setFile(null);
      setFilePreview(null);
      await refresh(selectedCode, detail?.id || null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function publishSelected() {
    if (!selectedVersionId) return;
    const ok = window.confirm(
      "Publier cette version ? Ses points seront verrouillés. " +
      "Si elle remplace une version ouverte antérieure, celle-ci sera fermée la veille."
    );
    if (!ok) return;

    setLoading(true);
    clearFeedback();
    try {
      const response = await publishBaremeVersion(selectedVersionId, {
        close_previous: true,
        commentaire: "Publication depuis l'interface Barèmes",
      });
      setMessage(response?.message || "Version publiée.");
      setEditingDraft(false);
      await refresh(selectedCode, selectedVersionId);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function cloneSelected() {
    if (!selectedVersionId) return;
    setLoading(true);
    clearFeedback();
    try {
      const response = await cloneBaremeVersion(selectedVersionId, {});
      const detail = response?.data;
      setMessage("Copie créée en brouillon. Modifiez ses points ou ses dates avant publication.");
      setSelectedVersionId(detail?.id || null);
      setSelectedVersion(detail || null);
      setEditingDraft(true);
      if (detail) setDraft(versionToDraft(detail));
      await refresh(selectedCode, detail?.id || null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function deleteDraftSelected() {
    if (!selectedVersionId || selectedVersion?.status !== "BROUILLON") return;
    if (!window.confirm("Supprimer définitivement ce brouillon ?")) return;
    setLoading(true);
    clearFeedback();
    try {
      await deleteBaremeDraft(selectedVersionId);
      setMessage("Brouillon supprimé.");
      setSelectedVersionId(null);
      setSelectedVersion(null);
      setEditingDraft(false);
      await refresh(selectedCode, null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function previewPeriod() {
    if (!selectedVersionId || !periodForm.date_debut_validite) {
      setError("La date de début est obligatoire.");
      return;
    }
    setLoading(true);
    clearFeedback();
    try {
      const response = await previewBaremePeriod(selectedVersionId, {
        date_debut_validite: periodForm.date_debut_validite,
        date_fin_validite: periodForm.date_fin_validite || null,
        commentaire: periodForm.commentaire || null,
      });
      setPeriodPreview(response?.data || null);
      if (response?.data?.can_apply) {
        setMessage("La nouvelle période ne chevauche aucune autre version publiée.");
      } else {
        setError("La nouvelle période chevauche une autre version publiée.");
      }
    } catch (err) {
      setPeriodPreview(null);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function applyPeriod() {
    if (!periodPreview?.can_apply) {
      setError("Analysez d'abord la période et corrigez les conflits.");
      return;
    }
    if (
      periodPreview.existing_bilans_in_impacted_window > 0 &&
      !window.confirm(
        `${periodPreview.existing_bilans_in_impacted_window} bilan(s) existent dans la fenêtre impactée. ` +
        "Ils ne seront PAS recalculés automatiquement. Continuer ?"
      )
    ) {
      return;
    }
    setLoading(true);
    clearFeedback();
    try {
      const response = await updateBaremePeriod(selectedVersionId, {
        date_debut_validite: periodForm.date_debut_validite,
        date_fin_validite: periodForm.date_fin_validite || null,
        commentaire: periodForm.commentaire || null,
      });
      setMessage(response?.message || "Période mise à jour.");
      setPeriodPreview(null);
      await refresh(selectedCode, selectedVersionId);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function archiveSelected() {
    if (!selectedVersionId || !canArchive) return;
    if (
      !window.confirm(
        "Archiver cette version clôturée ? Sa période historique restera résoluble. " +
        "Une version sans date de fin ne peut pas être archivée."
      )
    ) {
      return;
    }
    setLoading(true);
    clearFeedback();
    try {
      const response = await archiveBaremeVersion(selectedVersionId, {
        confirm: true,
        commentaire: "Archivage depuis l'interface Barèmes",
      });
      setMessage(response?.message || "Version archivée.");
      await refresh(selectedCode, selectedVersionId);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function testResolution() {
    if (!selectedCode || !resolveDate) return;
    setLoading(true);
    clearFeedback();
    try {
      const response = await resolveBareme(selectedCode, resolveDate);
      setResolved(response?.data || null);
      setMessage("Version applicable trouvée.");
    } catch (err) {
      setResolved(null);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="page baremes-v27-page">
      <div className="page-header baremes-v27-header">
        <div>
          <h1>Barèmes</h1>
          <p>
            Versions cote → volume / surface avec période d'application,
            import Excel contrôlé, saisie manuelle et traçabilité.
          </p>
        </div>
        <div className="baremes-v27-header-actions">
          <button type="button" onClick={() => downloadBaremeTemplate()} disabled={loading}>
            Télécharger le modèle Excel
          </button>
          {canDraft && (
            <button type="button" className="primary" onClick={startNewManual} disabled={!selectedCode || loading}>
              Nouveau barème
            </button>
          )}
        </div>
      </div>

      {loading && <div className="alert info">Traitement en cours...</div>}
      {message && <div className="alert success">{message}</div>}
      {error && <div className="alert error">{error}</div>}

      <div className="baremes-v27-summary">
        <label>
          Barrage
          <select value={selectedCode} onChange={(e) => setSelectedCode(e.target.value)}>
            {barrages.map((b) => (
              <option key={b.code} value={b.code}>
                {b.code} — {b.nom}
              </option>
            ))}
          </select>
        </label>
        {selectedBarrage && (
          <>
            <div className="baremes-v27-kpi">
              <span>Versions</span>
              <strong>{selectedBarrage.versions_count || 0}</strong>
            </div>
            <div className="baremes-v27-kpi">
              <span>Publiées</span>
              <strong>{selectedBarrage.published_count || 0}</strong>
            </div>
            <div className="baremes-v27-kpi">
              <span>Brouillons</span>
              <strong>{selectedBarrage.drafts_count || 0}</strong>
            </div>
            <div className="baremes-v27-kpi">
              <span>Points</span>
              <strong>{selectedBarrage.points_count || 0}</strong>
            </div>
          </>
        )}
      </div>

      <div className="baremes-v27-layout">
        <div className="panel">
          <div className="baremes-v27-section-title">
            <div>
              <h2>Historique des versions</h2>
              <p>Une version publiée est sélectionnée automatiquement selon sa période.</p>
            </div>
          </div>

          <div className="baremes-v27-table-wrap">
            <table className="baremes-v27-table">
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Année</th>
                  <th>Début</th>
                  <th>Fin</th>
                  <th>Points</th>
                  <th>Statut</th>
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr
                    key={v.id}
                    className={selectedVersionId === v.id ? "selected-row" : ""}
                    onClick={() => selectVersion(v.id)}
                  >
                    <td>
                      <strong>{v.nom}</strong>
                      <small>{v.source_type || "—"}</small>
                    </td>
                    <td>{v.annee_bareme || "—"}</td>
                    <td>{v.date_debut_validite || "Non définie"}</td>
                    <td>{v.date_fin_validite || "Sans date de fin"}</td>
                    <td>{v.points_count || 0}</td>
                    <td>
                      <span className={`baremes-v27-status status-${String(v.status || "").toLowerCase()}`}>
                        {statusLabel(v.status)}
                      </span>
                    </td>
                  </tr>
                ))}
                {!versions.length && (
                  <tr>
                    <td colSpan={6} className="muted-text">Aucune version pour ce barrage.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="baremes-v27-resolver">
            <h3>Vérifier le barème applicable à une date</h3>
            <div className="baremes-v27-inline">
              <input type="date" value={resolveDate} onChange={(e) => setResolveDate(e.target.value)} />
              <button type="button" onClick={testResolution} disabled={loading || !selectedCode || !resolveDate}>
                Vérifier
              </button>
            </div>
            {resolved && (
              <div className="baremes-v27-resolved">
                <strong>{resolved.nom}</strong>
                <span>
                  {resolved.date_debut_validite || "legacy"} → {resolved.date_fin_validite || "sans fin"}
                </span>
                {resolved.legacy_fallback && (
                  <em>Compatibilité legacy : aucune chronologie datée n'est encore configurée.</em>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="panel">
          {!editingDraft && !selectedVersion && (
            <div className="baremes-v27-empty">
              <h2>Sélectionnez une version</h2>
              <p>Ou créez un nouveau brouillon pour saisir/importer un barème.</p>
            </div>
          )}

          {selectedVersion && !editingDraft && (
            <div>
              <div className="baremes-v27-section-title">
                <div>
                  <h2>{selectedVersion.nom}</h2>
                  <p>
                    {statusLabel(selectedVersion.status)} · {selectedVersion.points?.length || 0} points
                  </p>
                </div>
                <div className="baremes-v27-actions">
                  {canDraft && (
                    <button type="button" onClick={cloneSelected} disabled={loading}>
                      Dupliquer en brouillon
                    </button>
                  )}
                  {canArchive && selectedVersion.status === "PUBLIE" && (
                    <button type="button" className="danger" onClick={archiveSelected} disabled={loading}>
                      Archiver
                    </button>
                  )}
                </div>
              </div>

              <div className="baremes-v27-meta-grid">
                <div><span>Année barème</span><strong>{selectedVersion.annee_bareme || "—"}</strong></div>
                <div><span>Début application</span><strong>{selectedVersion.date_debut_validite || "Non définie"}</strong></div>
                <div><span>Fin application</span><strong>{selectedVersion.date_fin_validite || "Sans date de fin"}</strong></div>
                <div><span>Source</span><strong>{selectedVersion.source_fichier || selectedVersion.source_type || "—"}</strong></div>
                <div><span>Cote normale</span><strong>{formatNumber(selectedVersion.cote_normale_ngm, 6)}</strong></div>
                <div><span>Volume normal Mm³</span><strong>{formatNumber(selectedVersion.volume_normal_mm3, 9)}</strong></div>
                <div><span>Surface normale km²</span><strong>{formatNumber(selectedVersion.surface_normale_km2, 9)}</strong></div>
              </div>

              {selectedVersion.status === "PUBLIE" && canPublish && (
                <div className="baremes-v27-period-box">
                  <h3>Modifier la période d'application</h3>
                  <p>
                    Les points restent verrouillés. La modification des dates ne recalcule jamais
                    silencieusement les bilans historiques.
                  </p>
                  <div className="baremes-v27-form-grid">
                    <label>
                      Date début *
                      <input
                        type="date"
                        value={periodForm.date_debut_validite}
                        onChange={(e) => setPeriodForm((p) => ({ ...p, date_debut_validite: e.target.value }))}
                      />
                    </label>
                    <label>
                      Date fin
                      <input
                        type="date"
                        value={periodForm.date_fin_validite}
                        onChange={(e) => setPeriodForm((p) => ({ ...p, date_fin_validite: e.target.value }))}
                      />
                      <small>Laisser vide = sans date de fin.</small>
                    </label>
                    <label className="span-2">
                      Commentaire
                      <input
                        value={periodForm.commentaire}
                        onChange={(e) => setPeriodForm((p) => ({ ...p, commentaire: e.target.value }))}
                        placeholder="Motif de la modification"
                      />
                    </label>
                  </div>
                  <div className="baremes-v27-actions">
                    <button type="button" onClick={previewPeriod} disabled={loading}>
                      Analyser l'impact
                    </button>
                    <button
                      type="button"
                      className="primary"
                      onClick={applyPeriod}
                      disabled={loading || !periodPreview?.can_apply}
                    >
                      Appliquer les dates
                    </button>
                  </div>
                  {periodPreview && (
                    <div className={periodPreview.can_apply ? "alert success" : "alert error"}>
                      Bilans dans la fenêtre impactée : {periodPreview.existing_bilans_in_impacted_window}.{" "}
                      Recalcul automatique : non.
                    </div>
                  )}
                </div>
              )}

              <PointsReadOnly points={selectedVersion.points || []} />
            </div>
          )}

          {editingDraft && canDraft && (
            <div>
              <div className="baremes-v27-section-title">
                <div>
                  <h2>{selectedVersion?.status === "BROUILLON" ? "Modifier le brouillon" : "Nouveau barème"}</h2>
                  <p>Le brouillon n'est jamais utilisé par les calculs tant qu'il n'est pas publié.</p>
                </div>
                {selectedVersion?.status === "BROUILLON" && (
                  <button type="button" className="danger" onClick={deleteDraftSelected} disabled={loading}>
                    Supprimer le brouillon
                  </button>
                )}
              </div>

              <div className="baremes-v27-form-grid">
                <label className="span-2">
                  Nom de la version *
                  <input value={draft.nom} onChange={(e) => updateDraft("nom", e.target.value)} />
                </label>
                <label>
                  Année du barème
                  <input
                    type="number"
                    min="1900"
                    max="2200"
                    value={draft.annee_bareme}
                    onChange={(e) => updateDraft("annee_bareme", e.target.value)}
                  />
                </label>
                <label>
                  Date début application
                  <input
                    type="date"
                    value={draft.date_debut_validite}
                    onChange={(e) => updateDraft("date_debut_validite", e.target.value)}
                  />
                </label>
                <label>
                  Date fin application
                  <input
                    type="date"
                    value={draft.date_fin_validite}
                    onChange={(e) => updateDraft("date_fin_validite", e.target.value)}
                  />
                  <small>Laisser vide = sans date de fin.</small>
                </label>
                <label>
                  Cote normale NGM
                  <input
                    inputMode="decimal"
                    value={draft.cote_normale_ngm}
                    onChange={(e) => updateDraft("cote_normale_ngm", e.target.value)}
                    placeholder="Ex. 61,50"
                  />
                  <small>
                    Référence officielle. Elle doit correspondre exactement à une cote du barème.
                  </small>
                </label>
                <label>
                  Volume normal Mm³
                  <input
                    value={derivedNormalReference?.volume_mm3 ?? ""}
                    readOnly
                    aria-readonly="true"
                    placeholder="Calculé automatiquement"
                  />
                  <small>Calculé automatiquement depuis la cote normale. Aucune interpolation.</small>
                </label>
                <label>
                  Surface normale km²
                  <input
                    value={derivedNormalReference?.surface_km2 ?? ""}
                    readOnly
                    aria-readonly="true"
                    placeholder="Calculée automatiquement"
                  />
                  <small>Calculée automatiquement depuis le même point du barème.</small>
                </label>
                {hasNormalCote && !derivedNormalReference && (
                  <div className="span-2 alert warning">
                    La cote normale saisie n'existe pas exactement dans les points actuellement chargés.
                    Vous pouvez enregistrer le brouillon, mais la publication sera refusée tant que ce point n'existe pas.
                  </div>
                )}
                <label className="span-2">
                  Observation
                  <textarea value={draft.observation} onChange={(e) => updateDraft("observation", e.target.value)} />
                </label>
              </div>

              {!selectedVersion && (
                <div className="baremes-v27-import-box">
                  <h3>Importer votre fichier Excel</h3>
                  <p>
                    Il doit respecter la même structure que le modèle :
                    Cote NGM · Volume Mm3 · Surface km2.
                  </p>
                  <div className="baremes-v27-inline">
                    <input
                      type="file"
                      accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                      onChange={(e) => {
                        setFile(e.target.files?.[0] || null);
                        setFilePreview(null);
                      }}
                    />
                    <button type="button" onClick={handlePreviewFile} disabled={!file || loading}>
                      Contrôler le fichier
                    </button>
                  </div>

                  {filePreview && (
                    <div className="baremes-v27-import-preview">
                      <strong>{filePreview.points_count} points valides</strong>
                      <span>
                        Cotes {formatNumber(filePreview.min_cote, 9)} → {formatNumber(filePreview.max_cote, 9)}
                      </span>
                      <span>SHA-256 : {filePreview.source_sha256}</span>
                      {filePreview.warnings?.length > 0 && (
                        <ul>
                          {filePreview.warnings.slice(0, 8).map((warning) => (
                            <li key={warning}>{warning}</li>
                          ))}
                        </ul>
                      )}
                      <button type="button" className="primary" onClick={createDraftFromFile} disabled={loading}>
                        Créer le brouillon depuis cet Excel
                      </button>
                    </div>
                  )}
                </div>
              )}

              <div className="baremes-v27-editor-title">
                <h3>Saisie manuelle des points</h3>
                <button type="button" onClick={addPoint}>Ajouter une ligne</button>
              </div>
              <div className="baremes-v27-points-editor">
                <table className="baremes-v27-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Cote NGM</th>
                      <th>Volume Mm³</th>
                      <th>Surface km²</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {draft.points.map((point, index) => (
                      <tr key={index}>
                        <td>{index + 1}</td>
                        <td>
                          <input
                            inputMode="decimal"
                            value={point.cote_ngm}
                            onChange={(e) => updatePoint(index, "cote_ngm", e.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            inputMode="decimal"
                            value={point.volume_mm3}
                            onChange={(e) => updatePoint(index, "volume_mm3", e.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            inputMode="decimal"
                            value={point.surface_km2}
                            onChange={(e) => updatePoint(index, "surface_km2", e.target.value)}
                          />
                        </td>
                        <td>
                          <button type="button" className="icon-danger" onClick={() => removePoint(index)}>
                            ×
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="baremes-v27-actions sticky-actions">
                <button type="button" className="primary" onClick={saveManualDraft} disabled={loading}>
                  Enregistrer le brouillon
                </button>
                {selectedVersion?.status === "BROUILLON" && canPublish && (
                  <button
                    type="button"
                    className="publish"
                    onClick={publishSelected}
                    disabled={loading || !selectedVersion.date_debut_validite}
                    title={!selectedVersion.date_debut_validite ? "Enregistrez d'abord une date de début." : ""}
                  >
                    Publier la version
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="baremes-v27-section-title">
          <div>
            <h2>Journal de traçabilité</h2>
            <p>Création, import, publication, modification de période, archivage.</p>
          </div>
          <button type="button" onClick={() => loadAudit(selectedVersionId)} disabled={loading}>
            Actualiser
          </button>
        </div>
        <div className="baremes-v27-table-wrap audit-wrap">
          <table className="baremes-v27-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Action</th>
                <th>Version</th>
                <th>Utilisateur</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((item) => (
                <tr key={item.id}>
                  <td>{item.created_at ? new Date(item.created_at).toLocaleString("fr-FR") : "—"}</td>
                  <td>{item.action}</td>
                  <td>{item.bareme_nom || item.bareme_version_id || "—"}</td>
                  <td>{item.full_name || item.username || "Système"}</td>
                </tr>
              ))}
              {!audit.length && (
                <tr><td colSpan={4} className="muted-text">Aucune action enregistrée.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function PointsReadOnly({ points }) {
  return (
    <div className="baremes-v27-points-read">
      <div className="baremes-v27-editor-title">
        <h3>Points du barème</h3>
        <span>{points.length} points</span>
      </div>
      <div className="baremes-v27-table-wrap points-read-wrap">
        <table className="baremes-v27-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Cote NGM</th>
              <th>Volume Mm³</th>
              <th>Surface km²</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point, index) => (
              <tr key={point.id || `${point.cote_ngm}-${index}`}>
                <td>{index + 1}</td>
                <td>{point.cote_ngm}</td>
                <td>{point.volume_mm3}</td>
                <td>{point.surface_km2}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
