-- ============================================================
-- ABHL BARRAGES - AUTHENTIFICATION COMPLETE
-- Login, logout réel, inscription avec approbation, rôles et audit
-- Relançable sur la base abhl_barrages
-- ============================================================

BEGIN;

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS public.roles (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    libelle VARCHAR(150) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    full_name VARCHAR(200),
    email VARCHAR(250) UNIQUE,
    password_hash TEXT,
    role_id BIGINT REFERENCES public.roles(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS approved_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL;

DROP TRIGGER IF EXISTS trg_users_updated_at ON public.users;
CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON public.users
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

INSERT INTO public.roles(code, libelle, description) VALUES
('ADMIN', 'Administrateur', 'Gestion complète de la plateforme et des comptes.'),
('SAISIE', 'Utilisateur de saisie', 'Saisie, calcul et enregistrement des données.'),
('VALIDATEUR', 'Validateur', 'Contrôle, validation et correction des données.'),
('CONSULTATION', 'Consultation', 'Consultation des tableaux, historiques et exports.')
ON CONFLICT (code) DO UPDATE SET
    libelle = EXCLUDED.libelle,
    description = EXCLUDED.description,
    updated_at = now();

CREATE TABLE IF NOT EXISTS public.auth_sessions (
    id BIGSERIAL PRIMARY KEY,
    jti VARCHAR(64) UNIQUE NOT NULL,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    ip_address VARCHAR(100),
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_active
    ON public.auth_sessions(user_id, expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS public.auth_audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    username_attempted VARCHAR(250),
    action VARCHAR(80) NOT NULL,
    success BOOLEAN NOT NULL,
    ip_address VARCHAR(100),
    user_agent TEXT,
    details TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auth_audit_created_at
    ON public.auth_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_audit_user
    ON public.auth_audit_log(user_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username_lower
    ON public.users(LOWER(username));
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower
    ON public.users(LOWER(email))
    WHERE email IS NOT NULL AND BTRIM(email) <> '';

GRANT USAGE ON SCHEMA public TO abhl_app;
GRANT SELECT ON public.roles TO abhl_app;
GRANT SELECT, INSERT, UPDATE ON public.users TO abhl_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.auth_sessions TO abhl_app;
GRANT SELECT, INSERT ON public.auth_audit_log TO abhl_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO abhl_app;

COMMIT;
