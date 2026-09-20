import { useAuth } from "../auth/AuthContext";
import { ChangePasswordForm } from "./ChangePasswordPage";


export default function ProfilePage() {
  const { user } = useAuth();

  return (
    <section className="page auth-profile-page">
      <div className="page-header">
        <h2>Mon profil</h2>
        <p>Informations du compte et paramètres de sécurité.</p>
      </div>

      <div className="auth-profile-grid">
        <div className="panel auth-profile-card">
          <div className="auth-profile-avatar">
            {(user.full_name || user.username).slice(0, 1).toUpperCase()}
          </div>
          <h3>{user.full_name || user.username}</h3>
          <span className="auth-role-pill">{user.role_label || user.role_code}</span>
          <dl>
            <div><dt>Nom d’utilisateur</dt><dd>{user.username}</dd></div>
            <div><dt>E-mail</dt><dd>{user.email || "—"}</dd></div>
            <div><dt>Dernière connexion</dt><dd>{formatDate(user.last_login_at)}</dd></div>
            <div><dt>État</dt><dd>{user.is_active ? "Actif" : "Inactif"}</dd></div>
          </dl>
        </div>

        <div className="panel auth-profile-security">
          <h3>Modifier mon mot de passe</h3>
          <p>La modification déconnecte les autres sessions actives de votre compte.</p>
          <ChangePasswordForm compact />
        </div>
      </div>
    </section>
  );
}


function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
