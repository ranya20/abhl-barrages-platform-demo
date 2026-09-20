import { useEffect, useMemo, useState } from "react";
import {
  adminCreateUser,
  adminResetUserPassword,
  adminUpdateUser,
  getAdminRoles,
  getAdminUsers,
} from "../api";
import { useAuth } from "../auth/AuthContext";


const EMPTY_CREATE = {
  username: "",
  full_name: "",
  email: "",
  role_code: "CONSULTATION",
  password: "",
  is_active: true,
  must_change_password: true,
};


export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [createForm, setCreateForm] = useState(EMPTY_CREATE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");

  const filteredUsers = useMemo(() => {
    const value = search.trim().toLowerCase();
    if (!value) return users;
    return users.filter((item) =>
      [item.username, item.full_name, item.email, item.role_code]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(value))
    );
  }, [users, search]);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [usersResult, rolesResult] = await Promise.all([
        getAdminUsers(),
        getAdminRoles(),
      ]);
      setUsers(usersResult.users || []);
      setRoles(rolesResult.roles || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function createUser(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setMessage("");
    try {
      await adminCreateUser(createForm);
      setCreateForm(EMPTY_CREATE);
      setMessage("Utilisateur créé avec succès.");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function saveUser(item) {
    setLoading(true);
    setError("");
    setMessage("");
    try {
      await adminUpdateUser(item.id, {
        full_name: item.full_name,
        email: item.email || null,
        role_code: item.role_code,
        is_active: item.is_active,
      });
      setMessage(`Compte ${item.username} mis à jour.`);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function resetPassword(item) {
    const password = window.prompt(
      `Nouveau mot de passe temporaire pour ${item.username} :\n\n` +
      "Minimum 10 caractères avec majuscule, minuscule, chiffre et caractère spécial."
    );
    if (!password) return;

    setLoading(true);
    setError("");
    setMessage("");
    try {
      await adminResetUserPassword(item.id, {
        new_password: password,
        must_change_password: true,
      });
      setMessage(`Mot de passe de ${item.username} réinitialisé. L'utilisateur devra le modifier.`);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function updateUserLocal(id, field, value) {
    setUsers((current) =>
      current.map((item) => item.id === id ? { ...item, [field]: value } : item)
    );
  }

  return (
    <section className="page admin-users-page">
      <div className="page-header">
        <h2>Gestion des utilisateurs</h2>
        <p>Approbation des inscriptions, rôles, activation et sécurité des comptes.</p>
      </div>

      {loading && <div className="alert info">Traitement en cours…</div>}
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}

      <div className="panel admin-user-create-panel">
        <div className="section-title-row">
          <div>
            <h3>Créer un utilisateur</h3>
            <p>Le mot de passe temporaire devra être modifié à la première connexion.</p>
          </div>
        </div>
        <form className="admin-user-create-form" onSubmit={createUser}>
          <label>
            Nom complet
            <input
              value={createForm.full_name}
              onChange={(event) => setCreateForm({ ...createForm, full_name: event.target.value })}
              required
            />
          </label>
          <label>
            Nom d’utilisateur
            <input
              value={createForm.username}
              onChange={(event) => setCreateForm({ ...createForm, username: event.target.value })}
              required
            />
          </label>
          <label>
            E-mail
            <input
              type="email"
              value={createForm.email}
              onChange={(event) => setCreateForm({ ...createForm, email: event.target.value })}
            />
          </label>
          <label>
            Rôle
            <select
              value={createForm.role_code}
              onChange={(event) => setCreateForm({ ...createForm, role_code: event.target.value })}
            >
              {roles.map((role) => <option key={role.code} value={role.code}>{role.libelle}</option>)}
            </select>
          </label>
          <label>
            Mot de passe temporaire
            <input
              type="password"
              value={createForm.password}
              onChange={(event) => setCreateForm({ ...createForm, password: event.target.value })}
              required
            />
          </label>
          <label className="admin-checkbox-label">
            <input
              type="checkbox"
              checked={createForm.is_active}
              onChange={(event) => setCreateForm({ ...createForm, is_active: event.target.checked })}
            />
            Compte actif
          </label>
          <button className="primary" disabled={loading}>Créer le compte</button>
        </form>
      </div>

      <div className="panel admin-user-list-panel">
        <div className="admin-user-list-head">
          <div>
            <h3>Comptes de la plateforme</h3>
            <p>{users.length} utilisateur(s), dont {users.filter((item) => !item.is_active).length} en attente ou inactif(s).</p>
          </div>
          <input
            className="admin-user-search"
            placeholder="Rechercher un utilisateur…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>

        <div className="admin-users-table-wrap">
          <table className="admin-users-table">
            <thead>
              <tr>
                <th>Utilisateur</th>
                <th>Nom complet</th>
                <th>E-mail</th>
                <th>Rôle</th>
                <th>État</th>
                <th>Dernière connexion</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((item) => (
                <tr key={item.id} className={!item.is_active ? "pending" : ""}>
                  <td>
                    <strong>{item.username}</strong>
                    {item.id === currentUser.id && <small className="current-user-mark">Vous</small>}
                  </td>
                  <td>
                    <input
                      value={item.full_name || ""}
                      onChange={(event) => updateUserLocal(item.id, "full_name", event.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="email"
                      value={item.email || ""}
                      onChange={(event) => updateUserLocal(item.id, "email", event.target.value)}
                    />
                  </td>
                  <td>
                    <select
                      value={item.role_code}
                      disabled={item.id === currentUser.id}
                      onChange={(event) => updateUserLocal(item.id, "role_code", event.target.value)}
                    >
                      {roles.map((role) => <option key={role.code} value={role.code}>{role.libelle}</option>)}
                    </select>
                  </td>
                  <td>
                    <label className="admin-status-switch">
                      <input
                        type="checkbox"
                        checked={item.is_active}
                        disabled={item.id === currentUser.id}
                        onChange={(event) => updateUserLocal(item.id, "is_active", event.target.checked)}
                      />
                      <span>{item.is_active ? "Actif" : "En attente / inactif"}</span>
                    </label>
                  </td>
                  <td>{formatDate(item.last_login_at)}</td>
                  <td>
                    <div className="admin-user-actions">
                      <button type="button" onClick={() => saveUser(item)} disabled={loading}>Enregistrer</button>
                      <button type="button" onClick={() => resetPassword(item)} disabled={loading}>Réinitialiser</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}


function formatDate(value) {
  if (!value) return "Jamais";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}
