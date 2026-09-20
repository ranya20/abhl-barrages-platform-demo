-- ============================================================
-- ABHL - Imports Annonce/BILAN avec validation et retour arrière
-- Base cible : abhl_barrages
-- Migration additive et relançable
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.data_import_batches (
    id BIGSERIAL PRIMARY KEY,
    import_uid VARCHAR(64) NOT NULL UNIQUE,
    module_code VARCHAR(30) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PREVIEW',
    selected_mode VARCHAR(50),

    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255),
    file_sha256 VARCHAR(64),
    file_size_bytes BIGINT,
    source_format VARCHAR(40),

    import_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,

    created_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    submitted_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    validated_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    applied_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    rolled_back_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at TIMESTAMPTZ,
    validated_at TIMESTAMPTZ,
    applied_at TIMESTAMPTZ,
    rolled_back_at TIMESTAMPTZ,

    validation_reason TEXT,
    rollback_reason TEXT,
    can_rollback BOOLEAN NOT NULL DEFAULT FALSE,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_data_import_batches_module_created
    ON public.data_import_batches(module_code, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_data_import_batches_status
    ON public.data_import_batches(status);
CREATE INDEX IF NOT EXISTS idx_data_import_batches_created_by
    ON public.data_import_batches(created_by);

CREATE TABLE IF NOT EXISTS public.data_import_rows (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES public.data_import_batches(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    sheet_name VARCHAR(150),
    barrage_code VARCHAR(80),
    date_bilan DATE,
    row_status VARCHAR(50) NOT NULL DEFAULT 'PENDING',

    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    existing_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    comparison JSONB NOT NULL DEFAULT '{}'::jsonb,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,

    selected_for_apply BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_data_import_row UNIQUE(batch_id, sheet_name, row_number)
);

CREATE INDEX IF NOT EXISTS idx_data_import_rows_batch
    ON public.data_import_rows(batch_id, row_number);
CREATE INDEX IF NOT EXISTS idx_data_import_rows_status
    ON public.data_import_rows(row_status);
CREATE INDEX IF NOT EXISTS idx_data_import_rows_barrage_date
    ON public.data_import_rows(barrage_code, date_bilan);

CREATE TABLE IF NOT EXISTS public.data_import_changes (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES public.data_import_batches(id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    barrage_id BIGINT NOT NULL REFERENCES public.barrages(id) ON DELETE RESTRICT,
    date_bilan DATE NOT NULL,
    before_state JSONB NOT NULL,
    after_state JSONB NOT NULL,
    changed_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    rolled_back_at TIMESTAMPTZ,

    CONSTRAINT uq_data_import_change_target UNIQUE(batch_id, barrage_id, date_bilan)
);

CREATE INDEX IF NOT EXISTS idx_data_import_changes_batch
    ON public.data_import_changes(batch_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_data_import_changes_target
    ON public.data_import_changes(barrage_id, date_bilan);

CREATE TABLE IF NOT EXISTS public.data_import_events (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES public.data_import_batches(id) ON DELETE CASCADE,
    event_type VARCHAR(60) NOT NULL,
    event_status VARCHAR(30) NOT NULL DEFAULT 'SUCCESS',
    user_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_data_import_events_batch
    ON public.data_import_events(batch_id, created_at);

GRANT USAGE ON SCHEMA public TO abhl_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON
    public.data_import_batches,
    public.data_import_rows,
    public.data_import_changes,
    public.data_import_events
TO abhl_app;

GRANT USAGE, SELECT, UPDATE ON
    public.data_import_batches_id_seq,
    public.data_import_rows_id_seq,
    public.data_import_changes_id_seq,
    public.data_import_events_id_seq
TO abhl_app;

-- Les opérations d'import écrivent également dans les tables métier.
GRANT SELECT, INSERT, UPDATE, DELETE ON
    public.bilans_journaliers,
    public.restitutions_journalieres,
    public.bilan_variables_journalieres,
    public.journees_situation
TO abhl_app;

GRANT SELECT ON
    public.barrages,
    public.types_restitution,
    public.barrage_types_restitution,
    public.bareme_versions,
    public.bareme_points
TO abhl_app;

GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO abhl_app;

COMMIT;
