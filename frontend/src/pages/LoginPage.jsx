import { useMemo, useState } from "react";
import { useAuth } from "../auth/AuthContext";

const EMPTY_SIGNUP = {
  username: "",
  full_name: "",
  email: "",
  password: "",
  password_confirmation: "",
};

function passwordChecks(value) {
  return {
    length: value.length >= 10,
    uppercase: /[A-Z]/.test(value),
    lowercase: /[a-z]/.test(value),
    number: /\d/.test(value),
    special: /[^A-Za-z0-9]/.test(value),
  };
}

export default function LoginPage() {
  const { login, signup, authError, setAuthError } = useAuth();
  const [mode, setMode] = useState("login");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [signupForm, setSignupForm] = useState(EMPTY_SIGNUP);
  const [fieldErrors, setFieldErrors] = useState({});
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const checks = useMemo(() => passwordChecks(signupForm.password), [signupForm.password]);
  const passwordsMatch =
    signupForm.password_confirmation.length > 0 &&
    signupForm.password === signupForm.password_confirmation;
  const signupValid =
    signupForm.full_name.trim().length >= 2 &&
    /^[a-zA-Z0-9._-]{3,50}$/.test(signupForm.username.trim()) &&
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(signupForm.email.trim()) &&
    Object.values(checks).every(Boolean) &&
    passwordsMatch;

  function selectMode(nextMode) {
    setMode(nextMode);
    setError("");
    setMessage("");
    setFieldErrors({});
    setAuthError("");
  }

  async function handleLogin(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setMessage("");
    try {
      await login(identifier, password);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function validateSignup() {
    const next = {};
    if (signupForm.full_name.trim().length < 2) {
      next.full_name = "Saisissez le nom complet.";
    }
    if (!/^[a-zA-Z0-9._-]{3,50}$/.test(signupForm.username.trim())) {
      next.username = "3 à 50 caractères : lettres, chiffres, point, tiret ou underscore.";
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(signupForm.email.trim())) {
      next.email = "Saisissez une adresse e-mail valide.";
    }
    if (!Object.values(checks).every(Boolean)) {
      const missing = Math.max(0, 10 - signupForm.password.length);
      next.password = missing
        ? `Ajoutez encore ${missing} caractère${missing > 1 ? "s" : ""}.`
        : "Respectez toutes les règles du mot de passe.";
    }
    if (!passwordsMatch) {
      next.password_confirmation = "Les deux mots de passe ne correspondent pas.";
    }
    setFieldErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleSignup(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    if (!validateSignup()) return;

    setLoading(true);
    try {
      const result = await signup(signupForm);
      setMessage(result.message);
      setSignupForm(EMPTY_SIGNUP);
      setFieldErrors({});
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function updateSignup(field, value) {
    setSignupForm((current) => ({ ...current, [field]: value }));
    setFieldErrors((current) => ({ ...current, [field]: "" }));
    setError("");
  }

  return (
    <main className="auth-page">
      <section className="auth-brand-panel">
        <img className="auth-brand-logo" src="/images/abhl-logo.png" alt="Agence du Bassin Hydraulique du Loukkos" />
        <div className="auth-brand-copy">
          <span>Agence du Bassin Hydraulique du Loukkos</span>
          <h1>Plateforme Barrages</h1>
          <p>
            Accès sécurisé aux données hydrauliques, aux situations quotidiennes,
            aux annonces et aux bilans des barrages.
          </p>
        </div>
        <div className="auth-water-lines" aria-hidden="true" />
      </section>

      <section className="auth-form-panel">
        <div className="auth-card">
          <div className="auth-card-heading">
            <p className="auth-eyebrow">Espace sécurisé</p>
            <h2>{mode === "login" ? "Connexion" : "Demande de compte"}</h2>
            <p>
              {mode === "login"
                ? "Connectez-vous avec votre nom d’utilisateur ou votre e-mail."
                : "Le compte sera activé après validation par un administrateur ABHL."}
            </p>
          </div>

          <div className="auth-tabs" role="tablist">
            <button type="button" className={mode === "login" ? "active" : ""} onClick={() => selectMode("login")}>Se connecter</button>
            <button type="button" className={mode === "signup" ? "active" : ""} onClick={() => selectMode("signup")}>Créer un compte</button>
          </div>

          {(error || authError) && <div className="auth-alert error">{error || authError}</div>}
          {message && <div className="auth-alert success">{message}</div>}

          {mode === "login" ? (
            <form className="auth-form" onSubmit={handleLogin}>
              <label>
                Nom d’utilisateur ou e-mail
                <input autoComplete="username" value={identifier} onChange={(event) => setIdentifier(event.target.value)} required />
              </label>
              <label>
                Mot de passe
                <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
              </label>
              <button className="auth-submit" disabled={loading || !identifier || !password}>
                {loading ? "Connexion…" : "Accéder à la plateforme"}
              </button>
              <p className="auth-help">Mot de passe oublié ? Contactez un administrateur de la plateforme pour une réinitialisation sécurisée.</p>
            </form>
          ) : (
            <form className="auth-form" onSubmit={handleSignup} noValidate>
              <div className="auth-form-grid">
                <AuthField label="Nom complet" error={fieldErrors.full_name}>
                  <input
                    className={fieldErrors.full_name ? "input-error" : ""}
                    autoComplete="name"
                    value={signupForm.full_name}
                    onChange={(event) => updateSignup("full_name", event.target.value)}
                  />
                </AuthField>
                <AuthField label="Nom d’utilisateur" error={fieldErrors.username}>
                  <input
                    className={fieldErrors.username ? "input-error" : ""}
                    autoComplete="username"
                    value={signupForm.username}
                    onChange={(event) => updateSignup("username", event.target.value)}
                  />
                </AuthField>
              </div>

              <AuthField label="Adresse e-mail professionnelle" error={fieldErrors.email}>
                <input
                  className={fieldErrors.email ? "input-error" : ""}
                  type="email"
                  autoComplete="email"
                  value={signupForm.email}
                  onChange={(event) => updateSignup("email", event.target.value)}
                />
              </AuthField>

              <div className="auth-form-grid">
                <AuthField label="Mot de passe" error={fieldErrors.password}>
                  <input
                    className={fieldErrors.password ? "input-error" : ""}
                    type="password"
                    autoComplete="new-password"
                    value={signupForm.password}
                    onChange={(event) => updateSignup("password", event.target.value)}
                  />
                </AuthField>
                <AuthField label="Confirmation" error={fieldErrors.password_confirmation}>
                  <input
                    className={fieldErrors.password_confirmation ? "input-error" : ""}
                    type="password"
                    autoComplete="new-password"
                    value={signupForm.password_confirmation}
                    onChange={(event) => updateSignup("password_confirmation", event.target.value)}
                  />
                </AuthField>
              </div>

              <div className="auth-password-checklist" aria-live="polite">
                <PasswordRule ok={checks.length}>Au moins 10 caractères</PasswordRule>
                <PasswordRule ok={checks.uppercase}>Une lettre majuscule</PasswordRule>
                <PasswordRule ok={checks.lowercase}>Une lettre minuscule</PasswordRule>
                <PasswordRule ok={checks.number}>Un chiffre</PasswordRule>
                <PasswordRule ok={checks.special}>Un caractère spécial</PasswordRule>
                <PasswordRule ok={passwordsMatch}>Les deux mots de passe correspondent</PasswordRule>
              </div>

              <button className="auth-submit" disabled={loading || !signupValid}>
                {loading ? "Envoi…" : "Envoyer la demande"}
              </button>
            </form>
          )}
        </div>
      </section>
    </main>
  );
}

function AuthField({ label, error, children }) {
  return (
    <label>
      {label}
      {children}
      {error && <small className="auth-field-error">{error}</small>}
    </label>
  );
}

function PasswordRule({ ok, children }) {
  return (
    <span className={ok ? "valid" : "invalid"}>
      <b aria-hidden="true">{ok ? "✓" : "•"}</b> {children}
    </span>
  );
}
