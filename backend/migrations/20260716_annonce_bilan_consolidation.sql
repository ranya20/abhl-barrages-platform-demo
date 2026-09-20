BEGIN;

-- Migration consolidée des modules Annonce, Calculs et BILAN.
-- Relançable : toutes les créations utilisent IF NOT EXISTS / ON CONFLICT.

ALTER TABLE public.types_restitution
    ADD COLUMN IF NOT EXISTS actif BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE public.barrage_types_restitution
    ADD COLUMN IF NOT EXISTS ordre_affichage INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS obligatoire BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS actif BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS colonne_bm VARCHAR(30),
    ADD COLUMN IF NOT EXISTS libelle_affichage VARCHAR(255),
    ADD COLUMN IF NOT EXISTS observation TEXT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE public.bareme_versions
    ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE public.bilans_journaliers
    ADD COLUMN IF NOT EXISTS hauteur_evaporee_mm NUMERIC(18,6),
    ADD COLUMN IF NOT EXISTS hauteur_corrigee_mm NUMERIC(18,6),
    ADD COLUMN IF NOT EXISTS apports_raw_m3 NUMERIC(18,6),
    ADD COLUMN IF NOT EXISTS evaporation_1000m3 NUMERIC(18,6),
    ADD COLUMN IF NOT EXISTS debit_evaporation_1000m3s NUMERIC(18,12),
    ADD COLUMN IF NOT EXISTS transfert_dar_khrofa_m3 NUMERIC(18,6),
    ADD COLUMN IF NOT EXISTS volume_jour_suivant_mm3 NUMERIC(18,6),
    ADD COLUMN IF NOT EXISTS surface_moyenne_km2 NUMERIC(18,6);

ALTER TABLE public.restitutions_journalieres
    ADD COLUMN IF NOT EXISTS source_colonne VARCHAR(50),
    ADD COLUMN IF NOT EXISTS observation TEXT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Les fichiers BILAN historiques contiennent des hauteurs de bac et parfois
-- des évaporations négatives. Elles sont conservées avec un avertissement.
ALTER TABLE public.bilans_journaliers
    DROP CONSTRAINT IF EXISTS chk_bilan_hauteur_bac;
ALTER TABLE public.bilans_journaliers
    DROP CONSTRAINT IF EXISTS chk_bilan_evaporation;

CREATE TABLE IF NOT EXISTS public.bilan_variables_journalieres (
    id BIGSERIAL PRIMARY KEY,
    bilan_journalier_id BIGINT NOT NULL
        REFERENCES public.bilans_journaliers(id) ON DELETE CASCADE,
    code_variable VARCHAR(150) NOT NULL,
    libelle_variable VARCHAR(255),
    valeur_numeric NUMERIC(18,6),
    valeur_text TEXT,
    unite VARCHAR(50),
    source_type VARCHAR(100),
    observation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_bilan_variable UNIQUE (bilan_journalier_id, code_variable)
);

CREATE INDEX IF NOT EXISTS idx_bilan_variables_bilan
    ON public.bilan_variables_journalieres(bilan_journalier_id);
CREATE INDEX IF NOT EXISTS idx_bilan_variables_code
    ON public.bilan_variables_journalieres(code_variable);

-- Autoriser la journalisation des exports BILAN.
ALTER TABLE public.exports DROP CONSTRAINT IF EXISTS chk_export_type;
ALTER TABLE public.exports
    ADD CONSTRAINT chk_export_type
    CHECK (type_export IN ('ANNONCE','BILAN','DJBARRAGE','SITUATION_QUOTIDIENNE','PDF','AUTRE'));

-- Types de restitution nécessaires aux 14 modèles BILAN.
INSERT INTO public.types_restitution(code, libelle, unite)
VALUES
    ('AEPI', 'AEPI', 'm3'),
    ('AEPI_JETS_CREUX', 'AEPI - Jets creux', 'm3'),
    ('AEPI_PRISES', 'AEPI - Prises', 'm3'),
    ('AEPI_TANGER', 'AEPI Tanger', 'm3'),
    ('BY_PASS', 'By-Pass', 'm3'),
    ('EVAC', 'EVAC', 'm3'),
    ('FUITES', 'Fuites', 'm3'),
    ('IRRIGATION', 'Irrigation', 'm3'),
    ('IRRIGATION_ASJEN_AMONT', 'Irrigation Asjen - Amont', 'm3'),
    ('IRRIGATION_LOUKKOS_PRISE', 'Irrigation Loukkos - Prise agricole', 'm3'),
    ('IRRIGATION_LOUKKOS_TURBINAGE', 'Irrigation Loukkos - Turbinage', 'm3'),
    ('JETS_CREUX', 'Jets creux', 'm3'),
    ('POMPES_DEVASAGE', 'Pompes de dévasage', 'm3'),
    ('PRISE_AGRICOLE_RD', 'Prise agricole RD', 'm3'),
    ('PRISE_AGRICOLE_RG', 'Prise agricole RG', 'm3'),
    ('RESTITUTION', 'Restitution', 'm3'),
    ('SEGUIA', 'Seguia', 'm3'),
    ('SIPHON', 'Siphon - Digue F', 'm3'),
    ('TMSA', 'TMSA', 'm3'),
    ('TRANSFERT_DAR_KHROFA', 'Transfert vers Dar Khrofa', 'm3'),
    ('TURBINAGE_EXCLUSIF', 'Turbinage exclusif', 'm3'),
    ('VDF', 'VDF', 'm3'),
    ('VDF_RD', 'VDF RD', 'm3'),
    ('VDF_RG', 'VDF RG', 'm3')
ON CONFLICT (code) DO UPDATE SET
    libelle = EXCLUDED.libelle,
    unite = EXCLUDED.unite,
    actif = TRUE,
    updated_at = now();

-- Association exacte barrage / colonne du fichier BILAN.
WITH mappings(barrage_code, type_code, ordre, colonne_bm, libelle_affichage) AS (
    VALUES
    ('NAKHLA', 'AEPI', 1, 'F', 'AEPI'),
    ('NAKHLA', 'VDF', 2, 'G', 'VDF'),
    ('NAKHLA', 'EVAC', 3, 'H', 'EVAC'),
    ('NAKHLA', 'FUITES', 4, 'I', 'Fuites'),
    ('SMIR', 'AEPI', 1, 'F', 'AEPI'),
    ('SMIR', 'VDF', 2, 'G', 'VDF'),
    ('SMIR', 'BY_PASS', 3, 'H', 'By-Pass'),
    ('SMIR', 'EVAC', 4, 'I', 'EVAC'),
    ('SMIR', 'FUITES', 5, 'J', 'Fuites'),
    ('MHB_MEHDI', 'AEPI', 1, 'F', 'AEPI'),
    ('MHB_MEHDI', 'VDF', 2, 'G', 'VDF'),
    ('MHB_MEHDI', 'BY_PASS', 3, 'H', 'By-Pass'),
    ('MHB_MEHDI', 'EVAC', 4, 'I', 'EVAC'),
    ('MHB_MEHDI', 'FUITES', 5, 'J', 'Fuites'),
    ('CAI', 'AEPI', 1, 'F', 'AEPI'),
    ('CAI', 'IRRIGATION', 2, 'G', 'Irrigation'),
    ('CAI', 'VDF_RD', 3, 'H', 'VDF RD'),
    ('CAI', 'VDF_RG', 4, 'I', 'VDF RG'),
    ('CAI', 'BY_PASS', 5, 'J', 'By-Pass'),
    ('CAI', 'EVAC', 6, 'K', 'EVAC'),
    ('CAI', 'FUITES', 7, 'L', 'Fuites'),
    ('CHEFCHAOUEN', 'AEPI', 1, 'F', 'AEPI'),
    ('CHEFCHAOUEN', 'IRRIGATION', 2, 'G', 'Irrigation'),
    ('CHEFCHAOUEN', 'VDF', 3, 'H', 'VDF'),
    ('CHEFCHAOUEN', 'BY_PASS', 4, 'I', 'By-Pass'),
    ('CHEFCHAOUEN', 'EVAC', 5, 'J', 'EVAC'),
    ('CHEFCHAOUEN', 'FUITES', 6, 'K', 'Fuites'),
    ('TANGER_MED', 'AEPI', 1, 'F', 'AEPI'),
    ('TANGER_MED', 'VDF', 2, 'G', 'VDF'),
    ('TANGER_MED', 'EVAC', 3, 'H', 'EVAC'),
    ('TANGER_MED', 'TMSA', 4, 'I', 'TMSA'),
    ('TANGER_MED', 'FUITES', 5, 'J', 'Fuites'),
    ('BIB', 'AEPI_PRISES', 1, 'F', 'AEPI - Prises'),
    ('BIB', 'AEPI_JETS_CREUX', 2, 'G', 'AEPI - Jets creux'),
    ('BIB', 'JETS_CREUX', 3, 'H', 'Jets creux'),
    ('BIB', 'VDF', 4, 'I', 'VDF'),
    ('BIB', 'BY_PASS', 5, 'J', 'By-Pass'),
    ('BIB', 'POMPES_DEVASAGE', 6, 'K', 'Pompes de dévasage'),
    ('BIB', 'EVAC', 7, 'L', 'EVAC'),
    ('BIB', 'FUITES', 8, 'M', 'Fuites'),
    ('9_AVRIL', 'AEPI', 1, 'F', 'AEPI'),
    ('9_AVRIL', 'VDF', 2, 'G', 'VDF'),
    ('9_AVRIL', 'BY_PASS', 3, 'H', 'By-Pass'),
    ('9_AVRIL', 'EVAC', 4, 'I', 'EVAC'),
    ('9_AVRIL', 'FUITES', 5, 'J', 'Fuites'),
    ('KHARROUB', 'AEPI', 1, 'F', 'AEPI'),
    ('KHARROUB', 'VDF', 2, 'G', 'VDF'),
    ('KHARROUB', 'BY_PASS', 3, 'H', 'By-Pass'),
    ('KHARROUB', 'EVAC', 4, 'I', 'EVAC'),
    ('KHARROUB', 'FUITES', 5, 'J', 'Fuites'),
    ('BOEM', 'IRRIGATION_LOUKKOS_TURBINAGE', 1, 'F', 'Irrigation Loukkos - Turbinage'),
    ('BOEM', 'IRRIGATION_LOUKKOS_PRISE', 2, 'G', 'Irrigation Loukkos - Prise agricole'),
    ('BOEM', 'IRRIGATION_ASJEN_AMONT', 3, 'H', 'Irrigation Asjen - Amont'),
    ('BOEM', 'TURBINAGE_EXCLUSIF', 4, 'I', 'Turbinage exclusif'),
    ('BOEM', 'AEPI', 5, 'J', 'AEPI'),
    ('BOEM', 'TRANSFERT_DAR_KHROFA', 6, 'K', 'Transfert vers Dar Khrofa'),
    ('BOEM', 'VDF_RD', 7, 'L', 'VDF RD'),
    ('BOEM', 'VDF_RG', 8, 'M', 'VDF RG'),
    ('BOEM', 'EVAC', 9, 'N', 'EVAC'),
    ('BOEM', 'FUITES', 10, 'O', 'Fuites'),
    ('DAR_KHROFA', 'PRISE_AGRICOLE_RD', 1, 'F', 'Prise agricole RD'),
    ('DAR_KHROFA', 'PRISE_AGRICOLE_RG', 2, 'G', 'Prise agricole RG'),
    ('DAR_KHROFA', 'AEPI_PRISES', 3, 'H', 'AEPI - Prises'),
    ('DAR_KHROFA', 'VDF_RD', 4, 'I', 'VDF RD'),
    ('DAR_KHROFA', 'VDF_RG', 5, 'J', 'VDF RG'),
    ('DAR_KHROFA', 'BY_PASS', 6, 'K', 'By-Pass'),
    ('DAR_KHROFA', 'EVAC', 7, 'L', 'EVAC'),
    ('DAR_KHROFA', 'FUITES', 8, 'M', 'Fuites'),
    ('DAR_KHROFA', 'AEPI_TANGER', 9, 'O', 'AEPI Tanger'),
    ('DAR_KHROFA', 'TRANSFERT_DAR_KHROFA', 10, 'Q', 'Transfert reçu depuis BOEM'),
    ('KHATTABI', 'AEPI', 1, 'F', 'AEPI'),
    ('KHATTABI', 'PRISE_AGRICOLE_RD', 2, 'G', 'Prise agricole RD - Digue B'),
    ('KHATTABI', 'PRISE_AGRICOLE_RG', 3, 'H', 'Prise agricole RG - Digue A'),
    ('KHATTABI', 'SIPHON', 4, 'I', 'Siphon - Digue F'),
    ('KHATTABI', 'EVAC', 5, 'J', 'EVAC'),
    ('KHATTABI', 'FUITES', 6, 'K', 'Fuites'),
    ('JOUMOUA', 'AEPI', 1, 'F', 'AEPI'),
    ('JOUMOUA', 'VDF_RD', 2, 'G', 'VDF RD'),
    ('JOUMOUA', 'VDF_RG', 3, 'H', 'VDF RG'),
    ('JOUMOUA', 'EVAC', 4, 'I', 'EVAC'),
    ('JOUMOUA', 'FUITES', 5, 'J', 'Fuites'),
    ('RHISS', 'AEPI', 1, 'F', 'AEPI'),
    ('RHISS', 'RESTITUTION', 2, 'G', 'Restitution'),
    ('RHISS', 'SEGUIA', 3, 'H', 'Seguia'),
    ('RHISS', 'VDF', 4, 'I', 'VDF'),
    ('RHISS', 'EVAC', 5, 'J', 'EVAC'),
    ('RHISS', 'FUITES', 6, 'K', 'Fuites')
)
INSERT INTO public.barrage_types_restitution(
    barrage_id,
    type_restitution_id,
    ordre_affichage,
    obligatoire,
    actif,
    colonne_bm,
    libelle_affichage
)
SELECT
    b.id,
    tr.id,
    m.ordre,
    FALSE,
    TRUE,
    m.colonne_bm,
    m.libelle_affichage
FROM mappings m
JOIN public.barrages b ON b.code = m.barrage_code
JOIN public.types_restitution tr ON tr.code = m.type_code
ON CONFLICT (barrage_id, type_restitution_id) DO UPDATE SET
    ordre_affichage = EXCLUDED.ordre_affichage,
    actif = TRUE,
    colonne_bm = EXCLUDED.colonne_bm,
    libelle_affichage = EXCLUDED.libelle_affichage,
    updated_at = now();

COMMIT;
