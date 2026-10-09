-- =============================================================================
-- 001 · FASE 2 (EXPAND) · document_process_details
-- =============================================================================
-- Qué hace:
--   1. Crea public.document_process_details (relación 1:N con documents).
--   2. Índices: historial por documento y "un solo proceso activo por documento".
--   3. Trigger updated_at, RLS activado (sin políticas) y permisos cerrados.
--   4. Backfill: un proceso por cada documento existente.
--   5. RPC create_document_with_process (creación atómica documento + proceso).
--   6. RPC fail_stale_document_processes (barrido de procesos zombi).
--   7. Vista document_current_process (último proceso por documento, sin N+1).
--
-- Qué NO hace:
--   - NO toca ni elimina columnas de public.documents (eso es la migración 002).
--   - documents.status / error_message / error_stage siguen vivas durante el
--     dual-write y por eso las funciones de abajo también las mantienen.
--
-- Decisiones de diseño:
--   - document_type y user_id se quedan SOLO en documents.
--   - status vive en el proceso. "Proceso vigente" = el más reciente por
--     created_at (sin flag is_current).
--   - source_ids del proceso = fuentes procesadas en ESA ejecución.
--   - ai_model_used = modelo que tuvo éxito; ai_provider = su proveedor;
--     ai_attempts = historial de intentos (incluye fallidos) en JSONB.
-- =============================================================================

begin;

-- -----------------------------------------------------------------------------
-- 1. Tabla
-- -----------------------------------------------------------------------------
create table if not exists public.document_process_details (
  id            uuid        not null default gen_random_uuid(),
  document_id   uuid        not null,
  process_type  text        not null default 'generation',
  status        text        not null default 'pending',
  error_stage   text        null,
  error_message text        null,
  source_ids    uuid[]      not null default '{}'::uuid[],
  ai_provider   text        null,
  ai_model_used text        null,
  ai_attempts   jsonb       not null default '[]'::jsonb,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  constraint document_process_details_pkey
    primary key (id),

  constraint document_process_details_document_id_fkey
    foreign key (document_id) references public.documents (id) on delete cascade,

  constraint document_process_details_process_type_check
    check (process_type in ('generation', 'expansion')),

  constraint document_process_details_status_check
    check (status in (
      'pending', 'extracting', 'generating', 'expanding',
      'drafting', 'done', 'failed'
    )),

  constraint document_process_details_error_stage_check
    check (error_stage is null or error_stage in (
      'source_extraction', 'ai_generation', 'ai_expansion',
      'document_drafting', 'document_export', 'internal'
    )),

  constraint document_process_details_ai_attempts_is_array
    check (jsonb_typeof(ai_attempts) = 'array')
);

comment on table public.document_process_details is
  'Historial de procesos (generación/ampliación) de cada documento. 1:N con documents.';
comment on column public.document_process_details.ai_attempts is
  'Array JSON de intentos: [{provider, model, outcome, error_kind, error_detail, latency_ms}]. El error crudo del proveedor va aquí, nunca en error_message.';
comment on column public.document_process_details.error_message is
  'Mensaje apto para el usuario (se expone en la API).';

-- -----------------------------------------------------------------------------
-- 2. Índices
-- -----------------------------------------------------------------------------
-- Historial y "proceso vigente" (ORDER BY created_at DESC LIMIT 1).
create index if not exists idx_document_process_details_document_created
  on public.document_process_details (document_id, created_at desc);

-- Un solo proceso activo por documento (evita dos ampliaciones simultáneas).
-- Un INSERT que lo viole lanza SQLSTATE 23505: la app debe mapearlo a un error
-- de dominio (409 / conflicto).
create unique index if not exists uq_document_process_details_one_active
  on public.document_process_details (document_id)
  where status in ('pending', 'extracting', 'generating', 'expanding', 'drafting');

-- -----------------------------------------------------------------------------
-- 3. Trigger updated_at, RLS y permisos
-- -----------------------------------------------------------------------------
drop trigger if exists update_document_process_details_updated_at
  on public.document_process_details;

create trigger update_document_process_details_updated_at
  before update on public.document_process_details
  for each row
  execute function public.update_updated_at_column();

-- RLS activado SIN políticas: anon/authenticated no ven nada por PostgREST.
-- El backend usa la service key (bypassea RLS).
alter table public.document_process_details enable row level security;

revoke all on public.document_process_details from anon, authenticated;

-- -----------------------------------------------------------------------------
-- 4. Backfill (idempotente): un proceso 'generation' por documento sin proceso
-- -----------------------------------------------------------------------------
-- Reglas:
--   - done / failed se copian tal cual.
--   - Estados activos con updated_at de hace más de 1 hora se consideran zombis
--     y pasan a failed (si no, el índice de proceso activo bloquearía el
--     documento para siempre).
--   - status NULL o desconocido -> failed.
--   - error_stage fuera del catálogo -> 'internal'.
--   - ai_provider = 'gemini' solo en documentos done (modelo exacto desconocido).
with src as (
  select
    d.*,
    case
      when d.status in ('done', 'failed') then d.status
      when d.status in ('pending', 'extracting', 'generating', 'expanding', 'drafting')
           and d.updated_at >= now() - interval '1 hour' then d.status
      else 'failed'
    end as new_status,
    (d.status in ('pending', 'extracting', 'generating', 'expanding', 'drafting')
       and d.updated_at < now() - interval '1 hour') as was_stale
  from public.documents d
  where not exists (
    select 1 from public.document_process_details p where p.document_id = d.id
  )
)
insert into public.document_process_details (
  document_id, process_type, status, error_stage, error_message,
  source_ids, ai_provider, created_at, updated_at
)
select
  s.id,
  'generation',
  s.new_status,
  case
    when s.new_status <> 'failed' then null
    when s.error_stage in (
      'source_extraction', 'ai_generation', 'ai_expansion',
      'document_drafting', 'document_export', 'internal'
    ) then s.error_stage
    else 'internal'
  end,
  case
    when s.new_status <> 'failed' then null
    when s.error_message is not null then s.error_message
    when s.was_stale then 'Proceso interrumpido antes de finalizar (detectado en migración).'
    else 'Estado desconocido detectado en migración.'
  end,
  coalesce(s.source_ids, '{}'::uuid[]),
  case when s.new_status = 'done' then 'gemini' end,
  s.created_at,
  s.updated_at
from src s;

-- -----------------------------------------------------------------------------
-- 5. RPC: creación atómica documento + proceso inicial
-- -----------------------------------------------------------------------------
-- Durante el dual-write también escribe documents.status = 'pending'.
-- Si create_document hoy persiste más campos, ampliar los parámetros.
create or replace function public.create_document_with_process(
  p_document_id   uuid,
  p_user_id       uuid,
  p_title         text,
  p_document_type text,
  p_sources       jsonb,
  p_source_ids    uuid[]
) returns uuid
language plpgsql
set search_path = public
as $$
declare
  v_process_id uuid;
begin
  insert into public.documents (
    id, user_id, title, document_type, status, sources, source_ids
  ) values (
    p_document_id, p_user_id, p_title, p_document_type, 'pending',
    coalesce(p_sources, '[]'::jsonb),
    coalesce(p_source_ids, '{}'::uuid[])
  );

  insert into public.document_process_details (
    document_id, process_type, status, source_ids
  ) values (
    p_document_id, 'generation', 'pending',
    coalesce(p_source_ids, '{}'::uuid[])
  )
  returning id into v_process_id;

  return v_process_id;
end;
$$;

revoke all on function public.create_document_with_process(uuid, uuid, text, text, jsonb, uuid[])
  from public, anon, authenticated;
grant execute on function public.create_document_with_process(uuid, uuid, text, text, jsonb, uuid[])
  to service_role;

-- -----------------------------------------------------------------------------
-- 6. RPC: barrido de procesos zombi
-- -----------------------------------------------------------------------------
-- p_max_age debe ser MAYOR que el presupuesto total de IA + extracción, o se
-- marcarán como fallidos procesos que siguen vivos.
-- Devuelve la cantidad de procesos marcados como failed.
create or replace function public.fail_stale_document_processes(
  p_max_age interval default interval '15 minutes'
) returns integer
language plpgsql
set search_path = public
as $$
declare
  v_count integer;
begin
  with stale as (
    update public.document_process_details
       set status        = 'failed',
           error_stage   = 'internal',
           error_message = 'El proceso fue interrumpido antes de finalizar.'
     where status in ('pending', 'extracting', 'generating', 'expanding', 'drafting')
       and updated_at < now() - p_max_age
    returning document_id
  ),
  legacy as (
    -- Dual-write: mantener documents.* sincronizado (se elimina en la 002).
    update public.documents d
       set status        = 'failed',
           error_stage   = 'internal',
           error_message = 'El proceso fue interrumpido antes de finalizar.'
     where d.id in (select document_id from stale)
       and d.status in ('pending', 'extracting', 'generating', 'expanding', 'drafting')
    returning d.id
  )
  select count(*) into v_count from stale;

  return v_count;
end;
$$;

revoke all on function public.fail_stale_document_processes(interval)
  from public, anon, authenticated;
grant execute on function public.fail_stale_document_processes(interval)
  to service_role;

-- -----------------------------------------------------------------------------
-- 7. Vista: último proceso por documento (para listados sin N+1)
-- -----------------------------------------------------------------------------
-- security_invoker = true => respeta el RLS de la tabla base.
create or replace view public.document_current_process
with (security_invoker = true) as
select distinct on (p.document_id) p.*
from public.document_process_details p
order by p.document_id, p.created_at desc, p.id desc;

revoke all on public.document_current_process from anon, authenticated;

commit;

-- =============================================================================
-- ROLLBACK manual (solo mientras documents siga intacta):
--   drop view     if exists public.document_current_process;
--   drop function if exists public.fail_stale_document_processes(interval);
--   drop function if exists public.create_document_with_process(uuid, uuid, text, text, jsonb, uuid[]);
--   drop table    if exists public.document_process_details;
-- =============================================================================
