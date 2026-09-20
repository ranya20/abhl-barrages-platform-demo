import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth/AuthContext";


function initials(user) {
  const source = user?.full_name || user?.username || "AB";
  return source
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}


export default function AuthUserMenu({ onOpenProfile, onOpenUsers }) {
  const { user, logout, isAdmin } = useAuth();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef(null);

  useEffect(() => {
    function closeOutside(event) {
      if (!wrapperRef.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener("mousedown", closeOutside);
    return () => document.removeEventListener("mousedown", closeOutside);
  }, []);

  return (
    <div className="auth-user-menu" ref={wrapperRef}>
      <button
        type="button"
        className="auth-user-trigger"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="auth-user-avatar">{initials(user)}</span>
        <span className="auth-user-copy">
          <strong>{user?.full_name || user?.username}</strong>
          <small>{user?.role_label || user?.role_code}</small>
        </span>
        <span className="auth-user-chevron">⌄</span>
      </button>

      {open && (
        <div className="auth-user-dropdown">
          <div className="auth-user-dropdown-head">
            <strong>{user?.username}</strong>
            <span>{user?.email || "Aucun e-mail"}</span>
          </div>
          <button type="button" onClick={() => { setOpen(false); onOpenProfile(); }}>
            Mon profil et sécurité
          </button>
          {isAdmin && (
            <button type="button" onClick={() => { setOpen(false); onOpenUsers(); }}>
              Gestion des utilisateurs
            </button>
          )}
          <div className="auth-user-separator" />
          <button type="button" className="logout" onClick={logout}>
            Se déconnecter
          </button>
        </div>
      )}
    </div>
  );
}
