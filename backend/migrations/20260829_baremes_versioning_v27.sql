-- ABHL BARRAGES - BAREMES VERSIONNES V27
-- Migration transactionnelle, relançable et rétrocompatible.

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

ALTER TABLE public.bareme_versions
    ADD COLUMN IF NOT EXISTS date_fin_validite DATE,
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'BROUILLON',
    ADD COLUMN IF NOT EXISTS locked_points BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(30),
    ADD COLUMN IF NOT EXISTS calculation_source VARCHAR(30) NOT NULL DEFAULT 'DATABASE_VERSIONED',
    ADD COLUMN IF NOT EXISTS source_sha256 VARCHAR(64),
    ADD COLUMN IF NOT EXISTS points_sha256 VARCHAR(64),
    ADD COLUMN IF NOT EXISTS cote_normale_ngm NUMERIC(30,15),
    ADD COLUMN IF NOT EXISTS volume_normal_mm3 NUMERIC(30,15),
    ADD COLUMN IF NOT EXISTS surface_normale_km2 NUMERIC(30,15),
    ADD COLUMN IF NOT EXISTS created_by BIGINT,
    ADD COLUMN IF NOT EXISTS published_by BIGINT,
    ADD COLUMN IF NOT EXISTS archived_by BIGINT,
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS publication_comment TEXT;

-- Première migration uniquement : parmi les versions héritées, conserver UNE version
-- courante par barrage (default/active la plus récente) et archiver les doublons hérités.
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY barrage_id
            ORDER BY COALESCE(is_default,FALSE) DESC,
                     COALESCE(actif,TRUE) DESC,
                     id DESC
        ) AS rn
    FROM public.bareme_versions
    WHERE source_type IS NULL
)
UPDATE public.bareme_versions bv
SET
    source_type='IMPORT_LEGACY',
    calculation_source='LEGACY_TEMPLATE',
    status=CASE WHEN r.rn=1 AND COALESCE(bv.actif,TRUE) THEN 'PUBLIE' ELSE 'ARCHIVE' END,
    actif=CASE WHEN r.rn=1 AND COALESCE(bv.actif,TRUE) THEN TRUE ELSE FALSE END,
    is_default=CASE WHEN r.rn=1 AND COALESCE(bv.actif,TRUE) THEN TRUE ELSE FALSE END,
    locked_points=TRUE,
    published_at=CASE WHEN r.rn=1 AND COALESCE(bv.actif,TRUE)
                      THEN COALESCE(bv.published_at,bv.created_at,now()) ELSE bv.published_at END,
    archived_at=CASE WHEN NOT (r.rn=1 AND COALESCE(bv.actif,TRUE))
                     THEN COALESCE(bv.archived_at,bv.updated_at,bv.created_at,now()) ELSE bv.archived_at END,
    updated_at=now()
FROM ranked r
WHERE bv.id=r.id;

-- Précision suffisante pour conserver les décimales officielles des futurs barèmes.
ALTER TABLE public.bareme_points
    ALTER COLUMN cote_ngm TYPE NUMERIC(30,15) USING cote_ngm::NUMERIC(30,15),
    ALTER COLUMN volume_mm3 TYPE NUMERIC(30,15) USING volume_mm3::NUMERIC(30,15),
    ALTER COLUMN surface_km2 TYPE NUMERIC(30,15) USING surface_km2::NUMERIC(30,15);

ALTER TABLE public.bareme_points
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_bareme_version_status' AND conrelid='public.bareme_versions'::regclass) THEN
        ALTER TABLE public.bareme_versions ADD CONSTRAINT chk_bareme_version_status CHECK (status IN ('BROUILLON','PUBLIE','ARCHIVE'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_bareme_version_source' AND conrelid='public.bareme_versions'::regclass) THEN
        ALTER TABLE public.bareme_versions ADD CONSTRAINT chk_bareme_version_source CHECK (calculation_source IN ('LEGACY_TEMPLATE','DATABASE_VERSIONED'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_bareme_versions_created_by' AND conrelid='public.bareme_versions'::regclass) THEN
        ALTER TABLE public.bareme_versions ADD CONSTRAINT fk_bareme_versions_created_by FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_bareme_versions_published_by' AND conrelid='public.bareme_versions'::regclass) THEN
        ALTER TABLE public.bareme_versions ADD CONSTRAINT fk_bareme_versions_published_by FOREIGN KEY (published_by) REFERENCES public.users(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_bareme_versions_archived_by' AND conrelid='public.bareme_versions'::regclass) THEN
        ALTER TABLE public.bareme_versions ADD CONSTRAINT fk_bareme_versions_archived_by FOREIGN KEY (archived_by) REFERENCES public.users(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bareme_versions_period
ON public.bareme_versions(barrage_id,date_debut_validite,date_fin_validite)
WHERE status='PUBLIE' AND actif=TRUE;
CREATE INDEX IF NOT EXISTS idx_bareme_versions_status ON public.bareme_versions(status,barrage_id);

CREATE TABLE IF NOT EXISTS public.bareme_audit_log (
    id BIGSERIAL PRIMARY KEY,
    bareme_version_id BIGINT REFERENCES public.bareme_versions(id) ON DELETE SET NULL,
    barrage_id BIGINT REFERENCES public.barrages(id) ON DELETE SET NULL,
    action VARCHAR(80) NOT NULL,
    user_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    old_values JSONB NOT NULL DEFAULT '{}'::jsonb,
    new_values JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bareme_audit_version ON public.bareme_audit_log(bareme_version_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bareme_audit_barrage ON public.bareme_audit_log(barrage_id,created_at DESC);

INSERT INTO public.bareme_audit_log(bareme_version_id,barrage_id,action,details)
SELECT bv.id,bv.barrage_id,'MIGRATION_V27',jsonb_build_object('source','legacy','status',bv.status)
FROM public.bareme_versions bv
WHERE bv.source_type='IMPORT_LEGACY'
  AND NOT EXISTS (SELECT 1 FROM public.bareme_audit_log a WHERE a.bareme_version_id=bv.id AND a.action='MIGRATION_V27');

CREATE OR REPLACE FUNCTION public.abhl_check_bareme_period_overlap()
RETURNS TRIGGER AS $$
DECLARE conflict_id BIGINT; conflict_name TEXT;
BEGIN
    IF ((NEW.status='PUBLIE' AND COALESCE(NEW.actif,TRUE)) OR (NEW.status='ARCHIVE' AND NEW.published_at IS NOT NULL))
       AND NEW.date_debut_validite IS NOT NULL THEN
        SELECT bv.id,bv.nom INTO conflict_id,conflict_name
        FROM public.bareme_versions bv
        WHERE bv.barrage_id=NEW.barrage_id
          AND bv.id<>COALESCE(NEW.id,-1)
          AND ((bv.status='PUBLIE' AND COALESCE(bv.actif,TRUE)) OR (bv.status='ARCHIVE' AND bv.published_at IS NOT NULL))
          AND bv.date_debut_validite IS NOT NULL
          AND bv.date_debut_validite <= COALESCE(NEW.date_fin_validite,DATE '9999-12-31')
          AND NEW.date_debut_validite <= COALESCE(bv.date_fin_validite,DATE '9999-12-31')
        ORDER BY bv.date_debut_validite LIMIT 1;
        IF conflict_id IS NOT NULL THEN
            RAISE EXCEPTION 'Chevauchement de barèmes : la version % (%) couvre déjà une partie de cette période.', conflict_id, conflict_name;
        END IF;
    END IF;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_bareme_version_no_overlap ON public.bareme_versions;
CREATE TRIGGER trg_bareme_version_no_overlap
BEFORE INSERT OR UPDATE OF barrage_id,status,actif,published_at,date_debut_validite,date_fin_validite
ON public.bareme_versions FOR EACH ROW EXECUTE FUNCTION public.abhl_check_bareme_period_overlap();

CREATE OR REPLACE FUNCTION public.abhl_lock_published_bareme_points()
RETURNS TRIGGER AS $$
DECLARE version_id BIGINT; v_status VARCHAR(20); v_locked BOOLEAN;
BEGIN
    version_id := CASE WHEN TG_OP='DELETE' THEN OLD.bareme_version_id ELSE NEW.bareme_version_id END;
    SELECT status,locked_points INTO v_status,v_locked FROM public.bareme_versions WHERE id=version_id;
    IF v_status IN ('PUBLIE','ARCHIVE') AND COALESCE(v_locked,FALSE) THEN
        RAISE EXCEPTION 'Les points de la version % sont verrouillés. Créez une nouvelle version.',version_id;
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_lock_published_bareme_points ON public.bareme_points;
CREATE TRIGGER trg_lock_published_bareme_points BEFORE INSERT OR UPDATE OR DELETE ON public.bareme_points
FOR EACH ROW EXECUTE FUNCTION public.abhl_lock_published_bareme_points();

CREATE OR REPLACE FUNCTION public.abhl_prevent_delete_published_bareme()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status <> 'BROUILLON' THEN
        RAISE EXCEPTION 'Seul un brouillon de barème peut être supprimé.';
    END IF;
    RETURN OLD;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_prevent_delete_published_bareme ON public.bareme_versions;
CREATE TRIGGER trg_prevent_delete_published_bareme BEFORE DELETE ON public.bareme_versions
FOR EACH ROW EXECUTE FUNCTION public.abhl_prevent_delete_published_bareme();

DROP TRIGGER IF EXISTS trg_bareme_points_updated_at ON public.bareme_points;
CREATE TRIGGER trg_bareme_points_updated_at BEFORE UPDATE ON public.bareme_points
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
