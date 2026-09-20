-- ==================================================================================================
-- ABHL Barrages Platform
-- Migration finale des modifications BASE DE DONNEES après la version Ouiame
-- Version finale validée après les corrections Annonce / BILAN / Situation dynamique
-- Date : 2026-07-19
--
-- A envoyer avec le projet à Ouiame.
--
-- IMPORTANT :
-- - Ce fichier contient UNIQUEMENT les modifications côté base de données nécessaires après sa version.
-- - Les corrections faites aujourd'hui sur Situation AR/FRA, Annonce et BILAN sont des corrections CODE.
--   Elles ne nécessitent pas de nouvelles tables SQL.
-- - Ce script ne crée PAS les barrages TEST_BARRAGE_01 / TEST_BARRAGE_02.
-- - Ce script ne modifie aucun fichier Excel original ABHL.
--
-- Pré-requis :
-- - La base doit déjà contenir le schéma principal ABHL :
--   barrages, bassins, provinces, bareme_versions, bareme_points,
--   types_restitution, barrage_types_restitution, bilans_journaliers, etc.
--
-- Exécution :
--   psql -U postgres -d abhl_barrages_local -f 20260719_db_changes_after_ouiame_FINAL.sql
-- ==================================================================================================

BEGIN;

-- --------------------------------------------------------------------------------------------------
-- 0) Fonction updated_at, utilisée par les triggers
-- --------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- --------------------------------------------------------------------------------------------------
-- 1) Table des agences / secteurs territoriaux
-- --------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.agences_territoriales (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(80) UNIQUE NOT NULL,
    nom VARCHAR(200) NOT NULL,
    description TEXT,
    actif BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_agences_territoriales_updated_at ON public.agences_territoriales;

CREATE TRIGGER trg_agences_territoriales_updated_at
BEFORE UPDATE ON public.agences_territoriales
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

INSERT INTO public.agences_territoriales (code, nom, description, actif)
VALUES
    ('LOUKKOS',      'Agence / secteur Loukkos',      'Barrages et données rattachés au secteur Loukkos',      TRUE),
    ('TANGER',       'Agence / secteur Tanger',       'Barrages et données rattachés au secteur Tanger',       TRUE),
    ('TETOUAN',      'Agence / secteur Tétouan',      'Barrages et données rattachés au secteur Tétouan',      TRUE),
    ('AL_HOCEIMA',   'Agence / secteur Al Hoceima',   'Barrages et données rattachés au secteur Al Hoceima',   TRUE),
    ('CHEFCHAOUEN',  'Agence / secteur Chefchaouen',  'Barrages et données rattachés au secteur Chefchaouen',  TRUE)
ON CONFLICT (code) DO UPDATE SET
    nom = EXCLUDED.nom,
    description = EXCLUDED.description,
    actif = TRUE,
    updated_at = now();


-- --------------------------------------------------------------------------------------------------
-- 2) Colonnes dynamiques ajoutées à public.barrages
-- --------------------------------------------------------------------------------------------------
ALTER TABLE public.barrages
    ADD COLUMN IF NOT EXISTS agence_id BIGINT,
    ADD COLUMN IF NOT EXISTS inclure_calculs BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS inclure_annonce BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS inclure_bilan BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS inclure_situation BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS ordre_annonce INTEGER,
    ADD COLUMN IF NOT EXISTS ordre_bilan INTEGER,
    ADD COLUMN IF NOT EXISTS ordre_situation INTEGER,
    ADD COLUMN IF NOT EXISTS date_mise_service DATE,
    ADD COLUMN IF NOT EXISTS mode_creation VARCHAR(80) NOT NULL DEFAULT 'IMPORT_INITIAL';

-- Ajouter la clé étrangère agence_id si elle n'existe pas encore.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_attribute a
          ON a.attrelid = c.conrelid
         AND a.attnum = ANY(c.conkey)
        WHERE c.conrelid = 'public.barrages'::regclass
          AND c.confrelid = 'public.agences_territoriales'::regclass
          AND c.contype = 'f'
          AND a.attname = 'agence_id'
    ) THEN
        ALTER TABLE public.barrages
        ADD CONSTRAINT fk_barrages_agence_id
        FOREIGN KEY (agence_id)
        REFERENCES public.agences_territoriales(id)
        ON DELETE SET NULL;
    END IF;
END $$;


-- --------------------------------------------------------------------------------------------------
-- 3) Index utiles
-- --------------------------------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_barrages_agence
    ON public.barrages(agence_id);

CREATE INDEX IF NOT EXISTS idx_barrages_inclure_calculs
    ON public.barrages(inclure_calculs);

CREATE INDEX IF NOT EXISTS idx_barrages_inclure_annonce
    ON public.barrages(inclure_annonce);

CREATE INDEX IF NOT EXISTS idx_barrages_inclure_bilan
    ON public.barrages(inclure_bilan);

CREATE INDEX IF NOT EXISTS idx_barrages_inclure_situation
    ON public.barrages(inclure_situation);

CREATE INDEX IF NOT EXISTS idx_barrages_ordres_exports
    ON public.barrages(ordre_annonce, ordre_bilan, ordre_situation);


-- --------------------------------------------------------------------------------------------------
-- 4) Affectation finale CORRECTE des agences aux barrages officiels
--
-- Correction importante par rapport au premier script :
-- - KHARROUB appartient à Tanger.
-- - CAI appartient à Tétouan.
-- - CHEFCHAOUEN reste seul dans le secteur Chefchaouen.
-- --------------------------------------------------------------------------------------------------
WITH mapping(code, agence_code) AS (
    VALUES
        ('BOEM',          'LOUKKOS'),
        ('DAR_KHROFA',    'LOUKKOS'),

        ('BIB',           'TANGER'),
        ('9_AVRIL',       'TANGER'),
        ('KHARROUB',      'TANGER'),
        ('TANGER_MED',    'TANGER'),

        ('NAKHLA',        'TETOUAN'),
        ('SMIR',          'TETOUAN'),
        ('MHB_MEHDI',     'TETOUAN'),
        ('CAI',           'TETOUAN'),

        ('CHEFCHAOUEN',   'CHEFCHAOUEN'),

        ('KHATTABI',      'AL_HOCEIMA'),
        ('JOUMOUA',       'AL_HOCEIMA'),
        ('RHISS',         'AL_HOCEIMA')
)
UPDATE public.barrages b
SET agence_id = a.id,
    updated_at = now()
FROM mapping m
JOIN public.agences_territoriales a
  ON a.code = m.agence_code
WHERE b.code = m.code;


-- --------------------------------------------------------------------------------------------------
-- 5) Paramètres finaux des exports pour les barrages officiels
--
-- RHISS reste dans la base, mais exclu des exports.
-- Les 13 barrages officiels restent actifs dans :
-- - Calculs
-- - Annonce
-- - BILAN
-- - Situation quotidienne
-- --------------------------------------------------------------------------------------------------

-- Valeurs par défaut sûres pour les barrages existants.
UPDATE public.barrages
SET
    inclure_calculs = COALESCE(inclure_calculs, TRUE),
    inclure_annonce = COALESCE(inclure_annonce, TRUE),
    inclure_bilan = COALESCE(inclure_bilan, TRUE),
    inclure_situation = COALESCE(inclure_situation, TRUE),
    ordre_annonce = COALESCE(ordre_annonce, ordre_affichage),
    ordre_bilan = COALESCE(ordre_bilan, ordre_affichage),
    ordre_situation = COALESCE(ordre_situation, ordre_affichage),
    mode_creation = COALESCE(mode_creation, 'IMPORT_INITIAL'),
    updated_at = now()
WHERE TRUE;

-- Configuration validée pour les 13 barrages officiels.
WITH official_config(
    code,
    inclure_calculs,
    inclure_annonce,
    inclure_bilan,
    inclure_situation,
    ordre_annonce,
    ordre_bilan,
    ordre_situation
) AS (
    VALUES
        -- ordre_annonce / ordre_bilan = ordre historique des fichiers BILAN / Annonce
        -- ordre_situation = ordre validé dans la Situation quotidienne
        ('NAKHLA',        TRUE, TRUE, TRUE, TRUE,  1,  1,  7),
        ('SMIR',          TRUE, TRUE, TRUE, TRUE,  2,  2,  8),
        ('MHB_MEHDI',     TRUE, TRUE, TRUE, TRUE,  3,  3,  9),
        ('CAI',           TRUE, TRUE, TRUE, TRUE,  4,  4, 10),
        ('CHEFCHAOUEN',   TRUE, TRUE, TRUE, TRUE,  5,  5, 11),
        ('TANGER_MED',    TRUE, TRUE, TRUE, TRUE,  6,  6,  6),
        ('BIB',           TRUE, TRUE, TRUE, TRUE,  7,  7,  3),
        ('9_AVRIL',       TRUE, TRUE, TRUE, TRUE,  8,  8,  4),
        ('KHARROUB',      TRUE, TRUE, TRUE, TRUE,  9,  9,  5),
        ('BOEM',          TRUE, TRUE, TRUE, TRUE, 10, 10,  1),
        ('DAR_KHROFA',    TRUE, TRUE, TRUE, TRUE, 11, 11,  2),
        ('KHATTABI',      TRUE, TRUE, TRUE, TRUE, 12, 12, 12),
        ('JOUMOUA',       TRUE, TRUE, TRUE, TRUE, 13, 13, 13),

        -- RHISS : pas de DJBarrage / pas de situation validée / pas de BILAN mensuel standard.
        ('RHISS',         FALSE, FALSE, FALSE, FALSE, NULL, NULL, NULL)
)
UPDATE public.barrages b
SET
    actif = TRUE,
    inclure_calculs = oc.inclure_calculs,
    inclure_annonce = oc.inclure_annonce,
    inclure_bilan = oc.inclure_bilan,
    inclure_situation = oc.inclure_situation,
    ordre_annonce = oc.ordre_annonce,
    ordre_bilan = oc.ordre_bilan,
    ordre_situation = oc.ordre_situation,
    mode_creation = COALESCE(b.mode_creation, 'IMPORT_INITIAL'),
    updated_at = now()
FROM official_config oc
WHERE b.code = oc.code;


-- --------------------------------------------------------------------------------------------------
-- 6) Sécurité : garder les barrages TEST hors exports s'ils existent dans une base copiée
--
-- Cette partie ne crée pas de test. Elle évite seulement qu'un ancien TEST sorte dans les fichiers
-- si quelqu'un restaure une base où TEST_BARRAGE_01 / TEST_BARRAGE_02 existent encore.
-- --------------------------------------------------------------------------------------------------
UPDATE public.barrages
SET
    actif = FALSE,
    inclure_calculs = FALSE,
    inclure_annonce = FALSE,
    inclure_bilan = FALSE,
    inclure_situation = FALSE,
    updated_at = now()
WHERE code LIKE 'TEST_BARRAGE_%';


COMMIT;


-- ==================================================================================================
-- Vérifications après exécution
-- ==================================================================================================

-- 1) Les agences :
-- SELECT code, nom, actif FROM public.agences_territoriales ORDER BY code;

-- 2) Les barrages et leurs paramètres :
-- SELECT
--     b.code,
--     b.nom_court,
--     a.code AS agence_code,
--     b.actif,
--     b.inclure_calculs,
--     b.inclure_annonce,
--     b.inclure_bilan,
--     b.inclure_situation,
--     b.ordre_annonce,
--     b.ordre_bilan,
--     b.ordre_situation
-- FROM public.barrages b
-- LEFT JOIN public.agences_territoriales a ON a.id = b.agence_id
-- ORDER BY COALESCE(b.ordre_situation, 999), b.code;

-- 3) Vérification attendue :
--    - BILAN catalog doit retourner count = 13.
--    - Situation quotidienne sans TEST doit retourner capacité totale 1956,6.
--    - TEST_BARRAGE_01 / TEST_BARRAGE_02, s'ils existent, doivent être actif=false.
-- ==================================================================================================
