BEGIN;

-- Ajouter la colonne attendue par le nouveau backend
ALTER TABLE public.bareme_versions
ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE;

-- Réinitialiser les valeurs pour garantir un seul barème par défaut
UPDATE public.bareme_versions
SET is_default = FALSE;

-- Définir comme barème par défaut la version active la plus récente
-- pour chaque barrage
WITH latest_active AS (
    SELECT DISTINCT ON (barrage_id)
        id,
        barrage_id
    FROM public.bareme_versions
    WHERE actif = TRUE
    ORDER BY barrage_id, id DESC
)
UPDATE public.bareme_versions bv
SET is_default = TRUE
FROM latest_active la
WHERE bv.id = la.id;

-- Empêcher plusieurs barèmes par défaut pour le même barrage
CREATE UNIQUE INDEX IF NOT EXISTS
uq_bareme_versions_one_default_per_barrage
ON public.bareme_versions(barrage_id)
WHERE is_default = TRUE;

COMMIT;