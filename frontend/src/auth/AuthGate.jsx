import { useAuth } from "./AuthContext";
import LoginPage from "../pages/LoginPage";
import ChangePasswordPage from "../pages/ChangePasswordPage";


export default function AuthGate({ children }) {
  const { loading, user } = useAuth();

  if (loading) {
    return (
      <div className="auth-loading-screen">
        <div className="auth-loading-mark">ABHL</div>
        <div className="auth-spinner" />
        <p>Chargement sécurisé de la plateforme…</p>
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
  }

  if (user.must_change_password) {
    return <ChangePasswordPage required />;
  }

  return children;
}
