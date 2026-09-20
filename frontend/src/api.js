const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const ACCESS_TOKEN_KEY = "abhl_access_token";

function getAccessToken() {
  return window.sessionStorage.getItem(ACCESS_TOKEN_KEY) || "";
}

function notifyUnauthorized() {
  window.dispatchEvent(new CustomEvent("abhl:unauthorized"));
}

async function readErrorResponse(response) {
  try {
    const data = await response.json();
    const detail = data?.detail;

    if (typeof detail === "string") return detail;
    if (detail?.message) return detail.message;

    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] || {};
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : "";
      const labels = {
        password: "mot de passe",
        password_confirmation: "confirmation du mot de passe",
        username: "nom d’utilisateur",
        email: "adresse e-mail",
        full_name: "nom complet",
      };
      const label = labels[field] || field;

      if (first.type === "string_too_short") {
        const minimum = first?.ctx?.min_length;
        return `Le champ ${label || "saisi"} doit contenir au moins ${minimum || "le nombre requis de"} caractères.`;
      }
      if (first.type === "missing") {
        return `Le champ ${label || "obligatoire"} doit être renseigné.`;
      }
      return first.msg || "Certaines informations saisies sont invalides.";
    }

    if (data?.message) return data.message;
    return `La demande n’a pas pu être traitée (HTTP ${response.status}).`;
  } catch {
    return `Erreur HTTP ${response.status}`;
  }
}

async function requestJson(path, options = {}) {
  let response;
  const { auth = true, headers: customHeaders = {}, ...fetchOptions } = options;
  const token = auth ? getAccessToken() : "";

  try {
    const isFormData = fetchOptions.body instanceof FormData;
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        Accept: "application/json",
        ...(fetchOptions.body && !isFormData ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...customHeaders,
      },
      ...fetchOptions,
    });
  } catch {
    throw new Error(
      `Backend inaccessible sur ${API_BASE_URL}. Vérifiez que uvicorn est lancé sur le port 8000.`
    );
  }

  if (!response.ok) {
    const message = await readErrorResponse(response);
    if (response.status === 401 && auth) {
      notifyUnauthorized();
    }
    throw new Error(message);
  }

  if (response.status === 204) return null;
  return response.json();
}

async function downloadFile(path, fallbackFilename) {
  let response;

  try {
    const token = getAccessToken();
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    throw new Error(
      `Backend inaccessible sur ${API_BASE_URL}. Vérifiez que uvicorn est lancé sur le port 8000.`
    );
  }

  if (!response.ok) {
    const message = await readErrorResponse(response);
    if (response.status === 401) notifyUnauthorized();
    throw new Error(message);
  }

  const blob = await response.blob();
  let filename = fallbackFilename;
  const disposition = response.headers.get("content-disposition");

  if (disposition) {
    const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const simpleMatch = disposition.match(/filename="?([^";]+)"?/i);
    const rawName = utf8Match?.[1] || simpleMatch?.[1];

    if (rawName) {
      filename = decodeURIComponent(rawName);
    }
  }

  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);

  return filename;
}

export function getHealth() {
  return requestJson("/api/health/db");
}

export function checkSituation(dateSituation) {
  return requestJson(
    `/api/situation/check?date_situation=${encodeURIComponent(dateSituation)}`
  );
}

export function previewSituation(dateSituation) {
  return requestJson(
    `/api/situation/preview?date_situation=${encodeURIComponent(dateSituation)}`
  );
}

export function getSituationPdfOptions() {
  return requestJson("/api/situation/pdf-options");
}

export function exportSituation(dateSituation, format = "xlsx", sheet = null) {
  const exportFormat = String(format || "xlsx").toLowerCase();
  const extension = exportFormat === "pdf" ? "pdf" : "xlsx";
  const query = new URLSearchParams({
    date_situation: dateSituation,
    format: extension,
  });

  if (extension === "pdf" && sheet) {
    query.set("sheet", sheet);
  }

  const suffix = extension === "pdf" && sheet ? ` - ${sheet}` : "";
  return downloadFile(
    `/api/situation/export?${query.toString()}`,
    `Situation quotidienne des barrages - ${dateSituation}${suffix}.${extension}`
  );
}

export function getCalculsForm(dateSituation) {
  return requestJson(
    `/api/calculs/form?date_situation=${encodeURIComponent(dateSituation)}`
  );
}

export function computeCalculs(payload) {
  return requestJson("/api/calculs/compute", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function saveCalculs(payload) {
  return requestJson("/api/calculs/save", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function checkAnnonce(dateSituation) {
  return requestJson(
    `/api/annonce/check?date_situation=${encodeURIComponent(dateSituation)}`
  );
}

export function previewAnnonce(dateSituation) {
  return requestJson(
    `/api/annonce/preview?date_situation=${encodeURIComponent(dateSituation)}`
  );
}

// === ABHL V25 ANNONCE MONTH FILENAME ===
function annonceExportMonthKey(dateSituation) {
  // L'Annonce du mois M est clôturée avec la cote du lendemain.
  // Midi local évite tout décalage UTC lors de la soustraction d'un jour.
  const d = new Date(`${dateSituation}T12:00:00`);
  if (Number.isNaN(d.getTime())) return String(dateSituation).slice(0, 7);
  d.setDate(d.getDate() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function exportAnnonce(dateSituation) {
  return downloadFile(
    `/api/annonce/export?date_situation=${encodeURIComponent(dateSituation)}`,
    `Annonce barrages - ${annonceExportMonthKey(dateSituation)}.xlsx`
  );
}

export function getBilanCatalog() {
  return requestJson("/api/bilan/catalog");
}

export function getBilanMonth(barrageCode, year, month) {
  const query = new URLSearchParams({
    barrage_code: barrageCode,
    year: String(year),
    month: String(month),
  });
  return requestJson(`/api/bilan/month?${query.toString()}`);
}

export function computeBilan(payload) {
  return requestJson("/api/bilan/compute", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function saveBilan(payload) {
  return requestJson("/api/bilan/save", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function checkBilan(barrageCode, year, month) {
  const query = new URLSearchParams({
    barrage_code: barrageCode,
    year: String(year),
    month: String(month),
  });
  return requestJson(`/api/bilan/check?${query.toString()}`);
}

export function previewBilan(barrageCode, year, month) {
  const query = new URLSearchParams({
    barrage_code: barrageCode,
    year: String(year),
    month: String(month),
  });
  return requestJson(`/api/bilan/preview?${query.toString()}`);
}

export function exportBilan(barrageCode, year, month) {
  const query = new URLSearchParams({
    barrage_code: barrageCode,
    year: String(year),
    month: String(month),
  });
  return downloadFile(
    `/api/bilan/export?${query.toString()}`,
    `BILAN ${barrageCode} - ${year}-${String(month).padStart(2, "0")}.xlsx`
  );
}


export function getBarrageReferenceData() {
  return requestJson("/api/barrage-admin/reference-data");
}

export function getBarrageAdminList() {
  return requestJson("/api/barrage-admin/barrages");
}

export function createBarrageFull(payload) {
  return requestJson("/api/barrage-admin/barrages", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateBarrageConfiguration(code, payload) {
  return requestJson(`/api/barrage-admin/barrages/${encodeURIComponent(code)}/configuration`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getBarrageReadiness(code) {
  return requestJson(`/api/barrage-admin/barrages/${encodeURIComponent(code)}/readiness`);
}

export function importBarrageBaremePoints(code, payload) {
  return requestJson(`/api/barrage-admin/barrages/${encodeURIComponent(code)}/bareme-points`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export { API_BASE_URL };

export function initializeBarrageBilan(code, payload) {
  return requestJson(`/api/barrage-admin/barrages/${encodeURIComponent(code)}/initial-bilan`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getDashboardFilters() {
  return requestJson("/api/dashboard/filters");
}

export function getDashboardOverview(params) {
  const query = new URLSearchParams();

  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") {
      query.set(key, value);
    }
  });

  return requestJson(`/api/dashboard/overview?${query.toString()}`);
}

export function getDashboardTimeseries(params) {
  const query = new URLSearchParams();

  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") {
      query.set(key, value);
    }
  });

  return requestJson(`/api/dashboard/timeseries?${query.toString()}`);
}

export function getDashboardCustomValues(params) {
  const query = new URLSearchParams();

  Object.entries(params || {}).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== null && item !== undefined && item !== "") {
          query.append(key, item);
        }
      });
      return;
    }

    if (value !== null && value !== undefined && value !== "") {
      query.set(key, value);
    }
  });

  return requestJson(`/api/dashboard/custom-values?${query.toString()}`);
}


// ============================================================
// AUTHENTIFICATION ET UTILISATEURS
// ============================================================

export function signupAccount(payload) {
  return requestJson("/api/auth/signup", {
    method: "POST",
    body: JSON.stringify(payload),
    auth: false,
  });
}

export function loginAccount(payload) {
  return requestJson("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
    auth: false,
  });
}

export function getCurrentUser() {
  return requestJson("/api/auth/me");
}

export function logoutAccount() {
  return requestJson("/api/auth/logout", { method: "POST" });
}

export function changeOwnPassword(payload) {
  return requestJson("/api/auth/change-password", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAdminRoles() {
  return requestJson("/api/auth/admin/roles");
}

export function getAdminUsers() {
  return requestJson("/api/auth/admin/users");
}

export function adminCreateUser(payload) {
  return requestJson("/api/auth/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function adminUpdateUser(userId, payload) {
  return requestJson(`/api/auth/admin/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function adminResetUserPassword(userId, payload) {
  return requestJson(`/api/auth/admin/users/${encodeURIComponent(userId)}/reset-password`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}


// ============================================================
// IMPORTS ANNONCE / BILAN, VALIDATION ET RETOUR ARRIÈRE
// ============================================================

export function previewDataImport(moduleCode, file, context = {}) {
  const formData = new FormData();
  formData.append("module_code", moduleCode);
  formData.append("context_json", JSON.stringify(context || {}));
  formData.append("file", file);
  return requestJson("/api/imports/preview", {
    method: "POST",
    body: formData,
  });
}

export function submitDataImport(importUid, payload) {
  return requestJson(`/api/imports/${encodeURIComponent(importUid)}/submit`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function applyDataImport(importUid, payload) {
  return requestJson(`/api/imports/${encodeURIComponent(importUid)}/apply`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function rejectDataImport(importUid, payload) {
  return requestJson(`/api/imports/${encodeURIComponent(importUid)}/reject`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function rollbackDataImport(importUid, payload) {
  return requestJson(`/api/imports/${encodeURIComponent(importUid)}/rollback`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getDataImportHistory(moduleCode, limit = 30) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (moduleCode) query.set("module_code", moduleCode);
  return requestJson(`/api/imports/history?${query.toString()}`);
}

export function getDataImportDetails(importUid) {
  return requestJson(`/api/imports/${encodeURIComponent(importUid)}`);
}

export function downloadDataImportTemplate(moduleCode, context = {}) {
  const query = new URLSearchParams({
    module_code: moduleCode,
    context_json: JSON.stringify(context || {}),
  });
  return downloadFile(
    `/api/imports/template?${query.toString()}`,
    moduleCode === "ANNONCE" ? "modele_import_annonce.csv" : "modele_import_bilan.csv"
  );
}


export function getAssistantMetadata() {
  return requestJson("/api/assistant/metadata");
}

export function askAssistant(payload) {
  return requestJson("/api/assistant/query", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAssistantLlmStatus() {
  return requestJson("/api/assistant/llm-status");
}

export function testAssistantLlm() {
  return requestJson("/api/assistant/llm-test", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function getGuidedBarrageProfile(barrageCode) {
  const query = new URLSearchParams();
  if (barrageCode) query.set("barrage_code", barrageCode);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson(`/api/assistant/guided/profile${suffix}`);
}

export function runGuidedAssistantQuery(payload) {
  return requestJson("/api/assistant/guided/query", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// === ABHL BAREMES V27 START ===

export function getBaremeManagementBarrages() {
  return requestJson("/api/baremes/management/barrages");
}

export function getBaremeVersions(barrageCode = "") {
  const query = new URLSearchParams();
  if (barrageCode) query.set("barrage_code", barrageCode);
  return requestJson(`/api/baremes/versions?${query.toString()}`);
}

export function getBaremeVersion(versionId) {
  return requestJson(`/api/baremes/versions/${encodeURIComponent(versionId)}`);
}

export function getBaremeAudit(versionId = null, limit = 200) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (versionId !== null && versionId !== undefined && versionId !== "") {
    query.set("version_id", String(versionId));
  }
  return requestJson(`/api/baremes/audit?${query.toString()}`);
}

export function resolveBareme(barrageCode, dateReference) {
  const query = new URLSearchParams({
    barrage_code: barrageCode,
    date_reference: dateReference,
  });
  return requestJson(`/api/baremes/resolve?${query.toString()}`);
}

export function downloadBaremeTemplate() {
  return downloadFile("/api/baremes/template.xlsx", "Modele_Bareme_ABHL.xlsx");
}

export function previewBaremeImport(file) {
  const form = new FormData();
  form.append("file", file);
  return requestJson("/api/baremes/import/preview", {
    method: "POST",
    body: form,
  });
}

export function importBaremeDraft(file, metadata) {
  const form = new FormData();
  Object.entries(metadata || {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") {
      form.append(key, String(value));
    }
  });
  form.append("file", file);
  return requestJson("/api/baremes/import/draft", {
    method: "POST",
    body: form,
  });
}

export function createBaremeDraft(payload) {
  return requestJson("/api/baremes/versions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateBaremeDraft(versionId, payload) {
  return requestJson(`/api/baremes/versions/${encodeURIComponent(versionId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteBaremeDraft(versionId) {
  return requestJson(`/api/baremes/versions/${encodeURIComponent(versionId)}`, {
    method: "DELETE",
  });
}

export function cloneBaremeVersion(versionId, payload = {}) {
  return requestJson(`/api/baremes/versions/${encodeURIComponent(versionId)}/clone`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function previewBaremePeriod(versionId, payload) {
  return requestJson(`/api/baremes/versions/${encodeURIComponent(versionId)}/period/preview`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateBaremePeriod(versionId, payload) {
  return requestJson(`/api/baremes/versions/${encodeURIComponent(versionId)}/period`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function publishBaremeVersion(versionId, payload = { close_previous: true }) {
  return requestJson(`/api/baremes/versions/${encodeURIComponent(versionId)}/publish`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function archiveBaremeVersion(versionId, payload) {
  return requestJson(`/api/baremes/versions/${encodeURIComponent(versionId)}/archive`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// === ABHL BAREMES V27 END ===
