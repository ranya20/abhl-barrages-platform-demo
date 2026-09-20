import { useEffect, useState } from "react";
import {
  checkSituation,
  exportSituation,
  getHealth,
  getSituationPdfOptions,
  previewSituation,
} from "./api";
import DashboardPage from "./pages/DashboardPage";
import AssistantDataPage from "./pages/AssistantDataPage";
import CalculsPage from "./pages/CalculsPage";
import BilanPage from "./pages/BilanPage";
import BarragesPage from "./pages/BarragesPage";
import BaremesPage from "./pages/BaremesPage";
import AdminUsersPage from "./pages/AdminUsersPage";
import ProfilePage from "./pages/ProfilePage";
import AuthUserMenu from "./components/AuthUserMenu";
import { useAuth } from "./auth/AuthContext";

const NAV_ITEMS = [
  { id: "dashboard", label: "Tableau de bord", icon: "dashboard", roles: ["ADMIN", "SAISIE", "VALIDATEUR", "CONSULTATION"] },
  { id: "assistant", label: "Assistant données", icon: "assistant", roles: ["ADMIN", "SAISIE", "VALIDATEUR", "CONSULTATION"] },
  { id: "situation", label: "Situation quotidienne", icon: "situation", roles: ["ADMIN", "SAISIE", "VALIDATEUR", "CONSULTATION"] },
  { id: "calculs", label: "Annonce / Calculs", icon: "annonce", roles: ["ADMIN", "SAISIE", "VALIDATEUR"] },
  { id: "bilan", label: "BILAN mensuel", icon: "bilan", roles: ["ADMIN", "SAISIE", "VALIDATEUR", "CONSULTATION"] },
  { id: "barrages", label: "Barrages", icon: "barrages", roles: ["ADMIN"] },
  { id: "baremes", label: "Barèmes", icon: "baremes", roles: ["ADMIN", "SAISIE", "VALIDATEUR", "CONSULTATION"] },
  { id: "users", label: "Utilisateurs", icon: "users", roles: ["ADMIN"] },
];

function App() {
  const { user } = useAuth();
  const [activePage, setActivePage] = useState("dashboard");
  const [sharedDate, setSharedDate] = useState("2026-06-09");
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState("");

  const roleCode = user?.role_code || "CONSULTATION";
  const visibleNavItems = NAV_ITEMS.filter((item) => item.roles.includes(roleCode));

  useEffect(() => {
    const selected = NAV_ITEMS.find((item) => item.id === activePage);
    if (selected && !selected.roles.includes(roleCode)) {
      setActivePage("dashboard");
    }
  }, [activePage, roleCode]);

  useEffect(() => {
    getHealth()
      .then((result) => {
        setHealth(result);
        setHealthError("");
      })
      .catch((error) => {
        setHealth(null);
        setHealthError(error.message);
      });
  }, []);

  return (
    <div className="app">
      <header className="top-nav-premium">
        <div className="top-brand-premium">
          <div className="brand-logo-premium">ABHL</div>
          <div>
            <h1>Plateforme Barrages</h1>
            <p>Agence du Bassin Hydraulique du Loukkos</p>
          </div>
        </div>

        <nav className="top-menu-premium" aria-label="Navigation principale">
          {visibleNavItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={activePage === item.id ? "active" : ""}
              onClick={() => setActivePage(item.id)}
            >
              <TopIcon name={item.icon} />
              {item.label}
            </button>
          ))}
        </nav>

        <div className="backend-status-premium" title={healthError || ""}>
          <span className={health ? "status-dot-premium ok" : "status-dot-premium"} />
          <span>{health ? "" : healthError || "Connexion..."}</span>
        </div>

        <AuthUserMenu
          onOpenProfile={() => setActivePage("profile")}
          onOpenUsers={() => setActivePage("users")}
        />
      </header>

      <main className="main">
        {activePage === "dashboard" && (
          <DashboardPage
            initialDate={sharedDate}
            onDateChange={setSharedDate}
          />
        )}

        {activePage === "assistant" && (
          <AssistantDataPage initialDate={sharedDate} />
        )}

        {activePage === "situation" && (
          <SituationPage initialDate={sharedDate} onDateChange={setSharedDate} />
        )}

        {activePage === "calculs" && (
          <CalculsPage
            initialDate={sharedDate}
            onDateChange={setSharedDate}
            onOpenSituation={(date) => {
              setSharedDate(date);
              setActivePage("situation");
            }}
          />
        )}

        {activePage === "bilan" && <BilanPage initialDate={sharedDate} />}

        {activePage === "barrages" && roleCode === "ADMIN" && <BarragesPage />}
        {activePage === "baremes" && <BaremesPage />}
        {activePage === "users" && roleCode === "ADMIN" && <AdminUsersPage />}
        {activePage === "profile" && <ProfilePage />}
      </main>
    </div>
  );
}

function TopIcon({ name }) {
  const common = {
    width: 17,
    height: 17,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
  };

  if (name === "dashboard") return <svg {...common}><path d="M4 13h6V4H4v9Z" /><path d="M14 20h6V4h-6v16Z" /><path d="M4 20h6v-3H4v3Z" /></svg>;
  if (name === "situation") return <svg {...common}><path d="M4 19V5" /><path d="M4 19h16" /><path d="M8 15l3-4 3 2 5-7" /></svg>;
  if (name === "assistant") return <svg {...common}><path d="M12 3a8 8 0 0 0-8 8v4a4 4 0 0 0 4 4h1l3 3 3-3h1a4 4 0 0 0 4-4v-4a8 8 0 0 0-8-8Z" /><path d="M8 11h.01" /><path d="M12 11h.01" /><path d="M16 11h.01" /></svg>;
  if (name === "annonce") return <svg {...common}><path d="M4 5h16v14H4z" /><path d="M8 9h8" /><path d="M8 13h5" /></svg>;
  if (name === "bilan") return <svg {...common}><path d="M4 20V4" /><path d="M8 20v-8" /><path d="M13 20V8" /><path d="M18 20v-5" /></svg>;
  if (name === "baremes") return <svg {...common}><path d="M4 5h16" /><path d="M4 10h16" /><path d="M4 15h16" /><path d="M7 3v14" /><path d="M12 3v14" /><path d="M17 3v14" /></svg>;
  if (name === "barrages") return <svg {...common}><path d="M4 20V8l8-4 8 4v12" /><path d="M4 13h16" /><path d="M8 20v-7" /><path d="M16 20v-7" /></svg>;
  if (name === "users") return <svg {...common}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>;

  return <svg {...common}><path d="M4 4h16v16H4z" /><path d="M8 8h8" /><path d="M8 12h8" /><path d="M8 16h5" /></svg>;
}

function SituationPage({ initialDate, onDateChange }) {
  const [dateSituation, setDateSituation] = useState(initialDate || "2026-06-09");
  const [exportFormat, setExportFormat] = useState("xlsx");
  const [pdfSheet, setPdfSheet] = useState("");
  const [pdfSheets, setPdfSheets] = useState([]);
  const [loading, setLoading] = useState(false);
  const [checkResult, setCheckResult] = useState(null);
  const [previewResult, setPreviewResult] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (initialDate) {
      setDateSituation(initialDate);
    }
  }, [initialDate]);

  useEffect(() => {
    if (exportFormat !== "pdf" || pdfSheets.length) return;

    getSituationPdfOptions()
      .then((result) => {
        setPdfSheets(result?.data?.sheets || []);
      })
      .catch((err) => {
        setError(err.message);
      });
  }, [exportFormat, pdfSheets.length]);

  function resetResults() {
    setCheckResult(null);
    setPreviewResult(null);
    setMessage("");
    setError("");
  }

  async function handleCheck() {
    setLoading(true);
    setError("");
    setMessage("");
    setPreviewResult(null);

    try {
      const result = await checkSituation(dateSituation);
      setCheckResult(result);

      if (result?.data?.can_generate) {
        setMessage("Données disponibles. Le fichier peut être généré.");
      } else {
        setMessage("Données insuffisantes pour générer le fichier.");
      }
    } catch (err) {
      setError(err.message);
      setCheckResult(null);
    } finally {
      setLoading(false);
    }
  }

  async function handlePreview() {
    setLoading(true);
    setError("");
    setMessage("");

    try {
      const result = await previewSituation(dateSituation);
      setPreviewResult(result);
      setMessage("Aperçu chargé avec succès.");
    } catch (err) {
      setError(err.message);
      setPreviewResult(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleExport() {
    setLoading(true);
    setError("");
    setMessage("");

    try {
      const filename = await exportSituation(
        dateSituation,
        exportFormat,
        exportFormat === "pdf" ? (pdfSheet || null) : null
      );
      setMessage(`Fichier téléchargé : ${filename}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const canGenerate = checkResult?.data?.can_generate === true;

  return (
    <section className="page">
      <div className="page-header">
        <h2>Situation quotidienne des barrages</h2>
        <p>Génération du fichier Excel officiel à partir de PostgreSQL.</p>
      </div>

      <div className="panel">
        <div className="form-row">
          <label>
            Date de situation
            <input
              type="date"
              value={dateSituation}
              onChange={(event) => {
                const value = event.target.value;
                setDateSituation(value);
                onDateChange?.(value);
                resetResults();
              }}
            />
          </label>

          <label>
            Format d'export
            <select
              value={exportFormat}
              onChange={(event) => {
                const next = event.target.value;
                setExportFormat(next);
                if (next !== "pdf") setPdfSheet("");
              }}
            >
              <option value="xlsx">Excel (.xlsx)</option>
              <option value="pdf">PDF (.pdf)</option>
            </select>
          </label>

          {exportFormat === "pdf" && (
            <label>
              Contenu du PDF
              <select
                value={pdfSheet}
                onChange={(event) => setPdfSheet(event.target.value)}
              >
                <option value="">PDF complet - toutes les feuilles</option>
                {pdfSheets.map((sheetName) => (
                  <option key={sheetName} value={sheetName}>
                    {sheetName}
                  </option>
                ))}
              </select>

            </label>
          )}

          <div className="actions">
            <button onClick={handleCheck} disabled={loading || !dateSituation}>
              Vérifier
            </button>

            <button onClick={handlePreview} disabled={loading || !dateSituation}>
              Aperçu
            </button>

            <button
              className="primary"
              onClick={handleExport}
              disabled={loading || !dateSituation}
            >
              {exportFormat === "pdf"
                ? (pdfSheet ? `Télécharger PDF - ${pdfSheet}` : "Télécharger PDF complet")
                : "Télécharger Excel"}
            </button>
          </div>
        </div>

        {loading && <div className="alert info">Traitement en cours...</div>}
        {message && <div className="alert success">{message}</div>}
        {error && <div className="alert error">{error}</div>}

        {checkResult && (
          <div className="result-block">
            <h3>Résultat de vérification</h3>

            <div className="check-line">
              <span>Statut :</span>
              <strong className={canGenerate ? "text-success" : "text-error"}>
                {canGenerate ? "Génération possible" : "Données manquantes"}
              </strong>
            </div>

            <div className="mini-grid">
              <InfoCard
                title="Date situation"
                value={checkResult.data.date_situation}
              />
              <InfoCard title="Date veille" value={checkResult.data.date_veille} />
              <InfoCard
                title="Année précédente"
                value={checkResult.data.date_annee_precedente}
              />
            </div>

            {!canGenerate && <MissingData data={checkResult.data} />}
          </div>
        )}

        {previewResult && (
          <div className="result-block">
            <h3>Aperçu des totaux</h3>

            <div className="preview-grid">
              <TotalsTable
                title="Situation Détaillée"
                totals={previewResult.normal_totals}
                columns={[
                  ["B", "Volume normal"],
                  ["C", "Volume veille"],
                  ["D", "Volume jour"],
                  ["E", "Variation"],
                  ["K", "Total lâchers"],
                  ["N", "Taux jour"],
                  ["O", "Volume N-1"],
                  ["P", "Taux N-1"],
                ]}
              />

              <TotalsTable
                title="Situation Détaillée (T)"
                totals={previewResult.transfer_totals}
                columns={[
                  ["B", "Volume normal"],
                  ["C", "Volume veille"],
                  ["D", "Volume jour"],
                  ["E", "Variation"],
                  ["L", "Total lâchers"],
                  ["O", "Taux jour"],
                  ["P", "Volume N-1"],
                  ["Q", "Taux N-1"],
                ]}
              />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function MissingData({ data }) {
  return (
    <div className="missing-box">
      {data.missing_barrages?.length > 0 && (
        <>
          <h4>Barrages manquants</h4>
          <ul>
            {data.missing_barrages.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      )}

      {data.missing_bilans?.length > 0 && (
        <>
          <h4>Bilans manquants</h4>
          <ul>
            {data.missing_bilans.map((item, index) => (
              <li key={index}>
                {item.barrage_code} — {item.date_type} — {item.date}
              </li>
            ))}
          </ul>
        </>
      )}

      {data.missing_required_values?.length > 0 && (
        <>
          <h4>Valeurs obligatoires manquantes</h4>
          <ul>
            {data.missing_required_values.map((item, index) => (
              <li key={index}>
                {item.barrage_code} — {item.date} — {item.field}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function TotalsTable({ title, totals, columns }) {
  return (
    <div className="totals-card">
      <h4>{title}</h4>

      <table>
        <tbody>
          {columns.map(([key, label]) => (
            <tr key={key}>
              <td>{label}</td>
              <td>{formatValue(totals?.[key])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InfoCard({ title, value }) {
  return (
    <div className="info-card">
      <span>{title}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ComingSoonPage({ title }) {
  return (
    <section className="page">
      <div className="page-header">
        <h2>{title}</h2>
        <p>Cette partie sera développée dans une étape suivante.</p>
      </div>

      <div className="panel">
        <h3>Module en préparation</h3>
        <p>
          Cette page sera connectée aux services backend correspondants après la
          validation du workflow de calcul journalier.
        </p>
      </div>
    </section>
  );
}

function formatValue(value) {
  if (value === null || value === undefined) {
    return "-";
  }

  if (typeof value === "number") {
    return value.toLocaleString("fr-FR", {
      maximumFractionDigits: 3,
    });
  }

  return value;
}

export default App;
