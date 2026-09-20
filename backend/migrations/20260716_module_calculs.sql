BEGIN;

-- ============================================================
-- Colonnes nécessaires aux restitutions
-- ============================================================

ALTER TABLE public.barrage_types_restitution
ADD COLUMN IF NOT EXISTS ordre_affichage INTEGER DEFAULT 0;

ALTER TABLE public.barrage_types_restitution
ADD COLUMN IF NOT EXISTS obligatoire BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE public.barrage_types_restitution
ADD COLUMN IF NOT EXISTS libelle_affichage VARCHAR(255);

ALTER TABLE public.barrage_types_restitution
ADD COLUMN IF NOT EXISTS actif BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE public.types_restitution
ADD COLUMN IF NOT EXISTS actif BOOLEAN NOT NULL DEFAULT TRUE;


-- ============================================================
-- Colonnes du module calculs hydrauliques
-- ============================================================

ALTER TABLE public.bilans_journaliers
ADD COLUMN IF NOT EXISTS hauteur_evaporee_mm NUMERIC(18,6);

ALTER TABLE public.bilans_journaliers
ADD COLUMN IF NOT EXISTS hauteur_corrigee_mm NUMERIC(18,6);

ALTER TABLE public.bilans_journaliers
ADD COLUMN IF NOT EXISTS apports_raw_m3 NUMERIC(18,6);

ALTER TABLE public.bilans_journaliers
ADD COLUMN IF NOT EXISTS evaporation_1000m3 NUMERIC(18,6);

ALTER TABLE public.bilans_journaliers
ADD COLUMN IF NOT EXISTS debit_evaporation_1000m3s NUMERIC(18,12);

ALTER TABLE public.bilans_journaliers
ADD COLUMN IF NOT EXISTS transfert_dar_khrofa_m3 NUMERIC(18,6);


-- ============================================================
-- Variables auxiliaires journalières
-- ============================================================

CREATE TABLE IF NOT EXISTS public.bilan_variables_journalieres (
    id BIGSERIAL PRIMARY KEY,

    bilan_journalier_id BIGINT NOT NULL
        REFERENCES public.bilans_journaliers(id)
        ON DELETE CASCADE,

    code_variable VARCHAR(150) NOT NULL,
    libelle_variable VARCHAR(255),

    valeur_numeric NUMERIC(18,6),
    valeur_text TEXT,
    unite VARCHAR(50),

    source_type VARCHAR(100),
    observation TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_bilan_variable
        UNIQUE (bilan_journalier_id, code_variable)
);


-- ============================================================
-- Index
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_bilan_variables_bilan
ON public.bilan_variables_journalieres(bilan_journalier_id);

CREATE INDEX IF NOT EXISTS idx_bilan_variables_code
ON public.bilan_variables_journalieres(code_variable);

COMMIT;