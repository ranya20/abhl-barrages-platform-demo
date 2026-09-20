import { useState } from "react";
import { useAuth } from "../auth/AuthContext";


export function ChangePasswordForm({ required = false, compact = false }) {
  const { changePassword, logout } = useAuth();
  const [form, setForm] = useState({
    current_password: "",
    new_password: "",
    new_password_confirmation: "",
  });
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    setError("");
    try {
      const result = await changePassword(form);
      setMessage(result.message);
      setForm({ current_password: "", new_password: "", new_password_confirmation: "" });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className={compact ? "auth-form profile-password-form" : "auth-form"} onSubmit={submit}>
      {required && (
        <div className="auth-alert warning">
          Un administrateur a demandé la modification de votre mot de passe avant l’accès à la plateforme.
        </div>
      )}
      {error && <div className="auth-alert error">{error}</div>}
      {message && <div className="auth-alert success">{message}</div>}
      <label>
        Mot de passe actuel
        <input
          type="password"
          autoComplete="current-password"
          value={form.current_password}
          onChange={(event) => setForm({ ...form, current_password: event.target.value })}
          required
        />
      </label>
      <div className="auth-form-grid">
        <label>
          Nouveau mot de passe
          <input
            type="password"
            autoComplete="new-password"
            value={form.new_password}
            onChange={(event) => setForm({ ...form, new_password: event.target.value })}
            required
          />
        </label>
        <label>
          Confirmation
          <input
            type="password"
            autoComplete="new-password"
            value={form.new_password_confirmation}
            onChange={(event) => setForm({ ...form, new_password_confirmation: event.target.value })}
            required
          />
        </label>
      </div>
      <p className="auth-password-rules">
        10 caractères minimum, avec majuscule, minuscule, chiffre et caractère spécial.
      </p>
      <div className="auth-password-actions">
        <button className="auth-submit" disabled={loading}>
          {loading ? "Modification…" : "Modifier le mot de passe"}
        </button>
        {required && (
          <button type="button" className="auth-secondary" onClick={logout}>
            Se déconnecter
          </button>
        )}
      </div>
    </form>
  );
}


export default function ChangePasswordPage({ required = false }) {
  return (
    <main className="auth-page auth-password-page">
      <section className="auth-form-panel">
        <div className="auth-card">
          <div className="auth-card-heading">
            <p className="auth-eyebrow">Sécurité du compte</p>
            <h2>Modifier le mot de passe</h2>
            <p>Choisissez un mot de passe personnel et difficile à deviner.</p>
          </div>
          <ChangePasswordForm required={required} />
        </div>
      </section>
    </main>
  );
}
