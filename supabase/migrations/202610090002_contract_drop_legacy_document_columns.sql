-- =============================================================================
-- 002 · FASE 4 (CONTRACT) · eliminar columnas legacy de public.documents
-- =============================================================================
-- ⚠️  DESTRUCTIVA. NO aplicar hasta que:
--   1. La fase 3 esté desplegada y estable (lecturas ya salen de los procesos).
--   2. Ningún código lea ni escriba documents.status / error_message / error_stage.
--   3. Exista un backup/snapshot de la base de datos.
--   4. La persona responsable del proyecto lo confirme explícitamente.
--
-- Qué hace:
--   - Verifica que todo documento tenga al menos un proceso.
--   - Redefine las funciones de la 001 SIN referencias a las columnas legacy.
--   - Elimina documents.status, documents.error_message y documents.error_stage.
-- =============================================================================

begin;

-- -----------------------------------------------------------------------------
-- 1. Precondición: ningún documento sin proceso
-- -----------------------------------------------------------------------------
do $$
begin
  if exists (
    select 1
    from public.documents d
    where not exists (
      select 1 from public.document_process_details p where p.document_id = d.id
    )
  ) then
    raise exception
      'Abortando contract: existen documentos sin proceso en document_process_details.';
  end if;
end;
$$;

-- -----------------------------------------------------------------------------
-- 2. Redefinir funciones sin columnas legacy (mismas firmas que en la 001)
-- -----------------------------------------------------------------------------
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
    id, user_id, title, document_type, sources, source_ids
  ) values (
    p_document_id, p_user_id, p_title, p_document_type,
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
    returning id
  )
  select count(*) into v_count from stale;

  return v_count;
end;
$$;

-- create or replace conserva los GRANT/REVOKE de la 001, pero se reafirman.
revoke all on function public.create_document_with_process(uuid, uuid, text, text, jsonb, uuid[])
  from public, anon, authenticated;
grant execute on function public.create_document_with_process(uuid, uuid, text, text, jsonb, uuid[])
  to service_role;

revoke all on function public.fail_stale_document_processes(interval)
  from public, anon, authenticated;
grant execute on function public.fail_stale_document_processes(interval)
  to service_role;

-- -----------------------------------------------------------------------------
-- 3. Eliminar columnas legacy
-- -----------------------------------------------------------------------------
-- Si falla por dependencias (vistas, índices), NO usar CASCADE a ciegas:
-- revisar primero qué depende de la columna.
alter table public.documents
  drop column if exists status,
  drop column if exists error_message,
  drop column if exists error_stage;

commit;

-- =============================================================================
-- Sin rollback automático: recuperar desde el backup previo, o re-agregar las
-- columnas y rellenarlas desde document_current_process.
-- =============================================================================
