import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { AuthProvider } from "./auth/AuthContext.jsx";
import AuthGate from "./auth/AuthGate.jsx";
import "./styles.css";
import "./auth.css";
import "./import-workflow.css";
import "./theme-pages.css";
import "./annonce-bilan-layout.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AuthProvider>
      <AuthGate>
        <App />
      </AuthGate>
    </AuthProvider>
  </React.StrictMode>
);








