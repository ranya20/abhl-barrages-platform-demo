import { useEffect, useMemo, useState } from "react";
import {
  createBarrageFull,
  getBarrageAdminList,
  getBarrageReferenceData,
  importBarrageBaremePoints,
  initializeBarrageBilan,
} from "../api";

function emptyForm() {
  return {
    code: "",
    nom: "",
    nom_court: "",
    agence_id: "",
    bassin_id: "",
    province_id: "",
    capacite_normale_mm3: "",
    cote_normale_ngm: "",
    cote_min_ngm: "",
    cote_max_ngm: "",
    feuille_annonce: "",
    feuille_djbarrage: "",
    fichier_bm: "",
    ordre_affichage: "",
    date_mise_service: "",
    actif: true,
    inclure_calculs: true,
    inclure_annonce: true,
    inclure_bilan: true,
    inclure_situation: true,
    observation: "",
  };
}

function toNumberOrNull(value) {
  if (value === "" || value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

function toIntOrNull(value) {
  if (value === "" || value === null || value === undefined) return null;
  const n = Number.parseInt(value, 10);
  return Number.isNaN(n) ? null : n;
}

function formatValue(value, digits = 6) {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString("fr-FR", { maximumFractionDigits: digits });
}

function parseBaremeText(text) {
  const points = [];
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);

  for (const line of lines) {
    const parts = line.split(/[;\t,]/).map((p) => p.trim()).filter((p) => p !== "");
    if (parts.length < 3) {
      throw new Error(`Ligne barème invalide : ${line}`);
    }
    const cote = Number(parts[0].replace(",", "."));
    const volume = Number(parts[1].replace(",", "."));
    const surface = Number(parts[2].replace(",", "."));
    if ([cote, volume, surface].some((v) => Number.isNaN(v))) {
      throw new Error(`Valeur numérique invalide dans : ${line}`);
    }
    points.push({ cote_ngm: cote, volume_mm3: volume, surface_km2: surface });
  }

  return points;
}

export default function BarragesPage() {
  const [reference, setReference] = useState(null);
  const [barrages, setBarrages] = useState([]);
  const [selectedCode, setSelectedCode] = useState("");
  const [form, setForm] = useState(emptyForm());
  const [selectedRestitutionIds, setSelectedRestitutionIds] = useState([]);
  const [baremeText, setBaremeText] = useState("100.00;0.000;0.000\n100.10;0.025;0.015");
  const [baremeName, setBaremeName] = useState("Barème plateforme");
  const [initialForm, setInitialForm] = useState({
    barrage_code: "",
    date_bilan: "",
    cote_7h_ngm: "",
    observation: "Initialisation du premier bilan journalier",
  });
  const [lastInitialResult, setLastInitialResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const selectedBarrage = useMemo(
    () => barrages.find((b) => b.code === selectedCode),
    [barrages, selectedCode]
  );

  async function loadData() {
    setLoading(true);
    setError("");
    try {
      const [refData, list] = await Promise.all([
        getBarrageReferenceData(),
        getBarrageAdminList(),
      ]);
      setReference(refData);
      setBarrages(list.data || []);

      if (!selectedCode && list.data?.length) {
        setSelectedCode(list.data[0].code);
        setInitialForm((prev) => ({ ...prev, barrage_code: list.data[0].code }));
      }

      setForm((prev) => ({
        ...prev,
        ordre_affichage: prev.ordre_affichage || refData.suggested_next_order || "",
      }));
    } catch (err) {
      setError(err.message || "Erreur lors du chargement des barrages.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function updateForm(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function toggleRestitution(id) {
    setSelectedRestitutionIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  async function handleCreateBarrage(event) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    setError("");

    try {
      const payload = {
        code: form.code,
        nom: form.nom,
        nom_court: form.nom_court || null,
        agence_id: toIntOrNull(form.agence_id),
        bassin_id: toIntOrNull(form.bassin_id),
        province_id: toIntOrNull(form.province_id),
        capacite_normale_mm3: toNumberOrNull(form.capacite_normale_mm3),
        cote_normale_ngm: toNumberOrNull(form.cote_normale_ngm),
        cote_min_ngm: toNumberOrNull(form.cote_min_ngm),
        cote_max_ngm: toNumberOrNull(form.cote_max_ngm),
        feuille_annonce: form.feuille_annonce || null,
        feuille_djbarrage: form.feuille_djbarrage || null,
        fichier_bm: form.fichier_bm || null,
        ordre_affichage: toIntOrNull(form.ordre_affichage),
        ordre_annonce: toIntOrNull(form.ordre_affichage),
        ordre_bilan: toIntOrNull(form.ordre_affichage),
        ordre_situation: toIntOrNull(form.ordre_affichage),
        date_mise_service: form.date_mise_service || null,
        actif: form.actif,
        inclure_calculs: form.inclure_calculs,
        inclure_annonce: form.inclure_annonce,
        inclure_bilan: form.inclure_bilan,
        inclure_situation: form.inclure_situation,
        restitution_type_ids: selectedRestitutionIds,
        observation: form.observation || null,
      };

      const response = await createBarrageFull(payload);
      const newCode = response?.barrage?.code || form.code.toUpperCase();
      setMessage(`Barrage ${newCode} créé avec succès.`);
      setForm(emptyForm());
      setSelectedRestitutionIds([]);
      setSelectedCode(newCode);
      setInitialForm((prev) => ({ ...prev, barrage_code: newCode }));
      await loadData();
    } catch (err) {
      setError(err.message || "Erreur lors de la création du barrage.");
    } finally {
      setLoading(false);
    }
  }

  async function handleImportBareme(event) {
    event.preventDefault();
    if (!selectedCode) {
      setError("Choisissez d'abord un barrage.");
      return;
    }

    setLoading(true);
    setMessage("");
    setError("");

    try {
      const points = parseBaremeText(baremeText);
      const response = await importBarrageBaremePoints(selectedCode, {
        nom: baremeName || "Barème plateforme",
        points,
        source_fichier: "Saisie plateforme",
        source_feuille: "Barème manuel",
      });
      setMessage(`${response.points_count} points de barème importés pour ${selectedCode}.`);
      await loadData();
    } catch (err) {
      setError(err.message || "Erreur lors de l'import du barème.");
    } finally {
      setLoading(false);
    }
  }

  async function handleInitialBilan(event) {
    event.preventDefault();
    const code = initialForm.barrage_code || selectedCode;

    if (!code) {
      setError("Choisissez un barrage à initialiser.");
      return;
    }
    if (!initialForm.date_bilan) {
      setError("Choisissez la date initiale.");
      return;
    }
    if (initialForm.cote_7h_ngm === "") {
      setError("Saisissez la cote initiale.");
      return;
    }

    setLoading(true);
    setMessage("");
    setError("");
    setLastInitialResult(null);

    try {
      const response = await initializeBarrageBilan(code, {
        date_bilan: initialForm.date_bilan,
        cote_7h_ngm: Number(initialForm.cote_7h_ngm),
        observation: initialForm.observation || "Initialisation du premier bilan journalier",
        statut: "BROUILLON",
      });

      setLastInitialResult(response);
      setMessage(
        `Premier bilan ${response.action === "updated" ? "mis à jour" : "créé"} pour ${code} : ` +
          `cote ${formatValue(response.cote_7h_ngm)}, volume ${formatValue(response.volume_mm3)}, surface ${formatValue(response.surface_km2)}.`
      );
      await loadData();
    } catch (err) {
      setError(err.message || "Erreur lors de l'initialisation du premier bilan.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="page barrage-admin-page">
      <div className="page-header">
        <div>
          <h1>Gestion dynamique des barrages</h1>
          <p>Ajouter un nouveau barrage, choisir son agence, ses restitutions, importer son barème et initialiser son premier bilan.</p>
        </div>
      </div>

      {loading && <div className="alert info">Traitement en cours...</div>}
      {message && <div className="alert success">{message}</div>}
      {error && <div className="alert error">{error}</div>}

      <div className="panel barrage-admin-grid">
        <div>
          <h2>Barrages existants</h2>
          <div className="barrage-list-table">
            <table>
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Nom</th>
                  <th>Agence</th>
                  <th>Rest.</th>
                  <th>Barème</th>
                  <th>Dernier bilan</th>
                  <th>Actif</th>
                </tr>
              </thead>
              <tbody>
                {barrages.map((barrage) => (
                  <tr
                    key={barrage.code}
                    className={selectedCode === barrage.code ? "selected-row" : ""}
                    onClick={() => {
                      setSelectedCode(barrage.code);
                      setInitialForm((prev) => ({ ...prev, barrage_code: barrage.code }));
                    }}
                  >
                    <td>{barrage.code}</td>
                    <td>{barrage.nom}</td>
                    <td>{barrage.agence_code || "-"}</td>
                    <td>{barrage.nb_restitutions}</td>
                    <td>{barrage.nb_points_bareme}</td>
                    <td>{barrage.dernier_bilan || "-"}</td>
                    <td>{barrage.actif ? "Oui" : "Non"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selectedBarrage && (
            <div className="selected-barrage-box">
              <strong>{selectedBarrage.nom}</strong>
              <p>Code : {selectedBarrage.code}</p>
              <p>Agence : {selectedBarrage.agence_nom || "-"}</p>
              <p>Restitutions : {selectedBarrage.nb_restitutions}</p>
              <p>Points barème : {selectedBarrage.nb_points_bareme}</p>
              <p>Dernier bilan : {selectedBarrage.dernier_bilan || "aucun"}</p>
            </div>
          )}
        </div>

        <form onSubmit={handleCreateBarrage}>
          <h2>Ajouter un barrage</h2>

          <div className="input-grid">
            <label>
              Code barrage *
              <input value={form.code} onChange={(e) => updateForm("code", e.target.value)} placeholder="EX: NOUVEAU_BARRAGE" required />
            </label>
            <label>
              Nom officiel *
              <input value={form.nom} onChange={(e) => updateForm("nom", e.target.value)} required />
            </label>
            <label>
              Nom court
              <input value={form.nom_court} onChange={(e) => updateForm("nom_court", e.target.value)} />
            </label>
            <label>
              Agence / secteur
              <select value={form.agence_id} onChange={(e) => updateForm("agence_id", e.target.value)}>
                <option value="">-- Choisir --</option>
                {reference?.agences?.map((a) => <option key={a.id} value={a.id}>{a.nom}</option>)}
              </select>
            </label>
            <label>
              Bassin
              <select value={form.bassin_id} onChange={(e) => updateForm("bassin_id", e.target.value)}>
                <option value="">-- Choisir --</option>
                {reference?.bassins?.map((b) => <option key={b.id} value={b.id}>{b.nom}</option>)}
              </select>
            </label>
            <label>
              Province
              <select value={form.province_id} onChange={(e) => updateForm("province_id", e.target.value)}>
                <option value="">-- Choisir --</option>
                {reference?.provinces?.map((p) => <option key={p.id} value={p.id}>{p.nom}</option>)}
              </select>
            </label>
            <label>
              Capacité normale Mm³ *
              <input type="number" step="0.000001" value={form.capacite_normale_mm3} onChange={(e) => updateForm("capacite_normale_mm3", e.target.value)} required />
            </label>
            <label>
              Cote normale NGM *
              <input type="number" step="0.001" value={form.cote_normale_ngm} onChange={(e) => updateForm("cote_normale_ngm", e.target.value)} required />
            </label>
            <label>
              Cote minimale
              <input type="number" step="0.001" value={form.cote_min_ngm} onChange={(e) => updateForm("cote_min_ngm", e.target.value)} />
            </label>
            <label>
              Cote maximale
              <input type="number" step="0.001" value={form.cote_max_ngm} onChange={(e) => updateForm("cote_max_ngm", e.target.value)} />
            </label>
            <label>
              Ordre d'affichage
              <input type="number" value={form.ordre_affichage} onChange={(e) => updateForm("ordre_affichage", e.target.value)} />
            </label>
            <label>
              Date mise en service
              <input type="date" value={form.date_mise_service} onChange={(e) => updateForm("date_mise_service", e.target.value)} />
            </label>
          </div>

          <h3>Activation</h3>
          <div className="checkbox-grid">
            {[
              ["actif", "Barrage actif"],
              ["inclure_calculs", "Calculs"],
              ["inclure_annonce", "Annonce"],
              ["inclure_bilan", "BILAN"],
              ["inclure_situation", "Situation"],
            ].map(([key, label]) => (
              <label key={key} className="checkbox-label">
                <input type="checkbox" checked={form[key]} onChange={(e) => updateForm(key, e.target.checked)} />
                {label}
              </label>
            ))}
          </div>

          <h3>Restitutions associées</h3>
          <div className="restitution-checkboxes">
            {reference?.types_restitution?.map((type) => (
              <label key={type.id} className="checkbox-label">
                <input
                  type="checkbox"
                  checked={selectedRestitutionIds.includes(type.id)}
                  onChange={() => toggleRestitution(type.id)}
                />
                {type.code} — {type.libelle}
              </label>
            ))}
          </div>

          <label className="full-width-field">
            Observation
            <textarea value={form.observation} onChange={(e) => updateForm("observation", e.target.value)} />
          </label>

          <div className="actions">
            <button className="primary" type="submit" disabled={loading}>Créer le barrage</button>
          </div>
        </form>
      </div>

      <div className="panel bareme-import-panel">
        <h2>Importer le barème du barrage sélectionné</h2>
        <p className="muted-text">Format attendu : une ligne par point, séparée par point-virgule, tabulation ou virgule : cote;volume;surface.</p>
        <form onSubmit={handleImportBareme}>
          <div className="input-grid">
            <label>
              Barrage
              <select value={selectedCode} onChange={(e) => setSelectedCode(e.target.value)}>
                {barrages.map((b) => <option key={b.code} value={b.code}>{b.code} — {b.nom}</option>)}
              </select>
            </label>
            <label>
              Nom du barème
              <input value={baremeName} onChange={(e) => setBaremeName(e.target.value)} />
            </label>
          </div>
          <label className="full-width-field">
            Points du barème
            <textarea rows={7} value={baremeText} onChange={(e) => setBaremeText(e.target.value)} />
          </label>
          <div className="actions">
            <button className="primary" type="submit" disabled={loading || !selectedCode || !baremeText.trim()}>
              Importer le barème
            </button>
          </div>
        </form>
      </div>

      <div className="panel bareme-import-panel">
        <h2>Initialiser le premier bilan journalier</h2>
        <p className="muted-text">
          Cette étape crée la première ligne dans bilans_journaliers. Elle est obligatoire pour qu'un nouveau barrage puisse être calculé le jour suivant.
          Le volume et la surface sont calculés automatiquement depuis le barème.
        </p>

        <form onSubmit={handleInitialBilan}>
          <div className="input-grid">
            <label>
              Barrage
              <select
                value={initialForm.barrage_code || selectedCode}
                onChange={(e) => {
                  setInitialForm((prev) => ({ ...prev, barrage_code: e.target.value }));
                  setSelectedCode(e.target.value);
                }}
              >
                {barrages.map((b) => <option key={b.code} value={b.code}>{b.code} — {b.nom}</option>)}
              </select>
            </label>
            <label>
              Date initiale *
              <input
                type="date"
                value={initialForm.date_bilan}
                onChange={(e) => setInitialForm((prev) => ({ ...prev, date_bilan: e.target.value }))}
                required
              />
            </label>
            <label>
              Cote initiale NGM *
              <input
                type="number"
                step="0.001"
                value={initialForm.cote_7h_ngm}
                onChange={(e) => setInitialForm((prev) => ({ ...prev, cote_7h_ngm: e.target.value }))}
                required
              />
            </label>
          </div>

          <label className="full-width-field">
            Observation
            <textarea
              value={initialForm.observation}
              onChange={(e) => setInitialForm((prev) => ({ ...prev, observation: e.target.value }))}
            />
          </label>

          <div className="actions">
            <button className="primary" type="submit" disabled={loading}>Initialiser le premier bilan</button>
          </div>
        </form>

        {lastInitialResult && (
          <div className="selected-barrage-box">
            <strong>Dernière initialisation</strong>
            <p>Barrage : {lastInitialResult.barrage_code}</p>
            <p>Date : {lastInitialResult.date_bilan}</p>
            <p>Cote : {formatValue(lastInitialResult.cote_7h_ngm)} NGM</p>
            <p>Volume : {formatValue(lastInitialResult.volume_mm3)} Mm³</p>
            <p>Surface : {formatValue(lastInitialResult.surface_km2)} km²</p>
            <p>Taux : {formatValue(lastInitialResult.taux_remplissage, 2)} %</p>
            <p>Méthode : {lastInitialResult.lookup_method}</p>
          </div>
        )}
      </div>
    </section>
  );
}
