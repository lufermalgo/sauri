"""Rename Spanish schema to English (english-codebase-standard spec).

Renames every table/column/stored-literal from Spanish to English per
.spectra/specs/english-codebase-standard/design.md > Componentes e
Interfaces > "1. Esquema de base de datos". Uses op.rename_table /
op.alter_column exclusively (never drop_table/create_table) so existing
row data is preserved — see design.md > Decisiones de Diseño Clave >
"Una sola migración Alembic para todo el esquema" and "op.rename_table /
op.alter_column, nunca drop_table + create_table".

Revision ID: 007_rename_schema_to_english
Revises: 006_add_titulo_reunion
Create Date: 2026-07-21 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_rename_schema_to_english"
down_revision: Union[str, None] = "006_add_titulo_reunion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Literal translations (process/diarization state, failure cause, origin,
# capture origin, access-log result) — design.md > "Literales de estado/evento"
# ---------------------------------------------------------------------------

_MEETING_PROCESS_STATE = {
    "en_cola": "queued",
    "uniendose": "joining",
    "grabando": "recording",
    "transcribiendo": "transcribing",
    "completado": "completed",
    "fallido": "failed",
}

_MEETING_FAILURE_CAUSE = {
    "no_pudo_unirse": "could_not_join",
    "reunion_cancelada": "meeting_cancelled",
    "fallo_del_motor": "engine_failure",
}

_DIARIZATION_STATE = {
    "pendiente": "pending",
    "en_proceso": "in_progress",
    "completada": "completed",
    "fallida": "failed",
}

_MEETING_ORIGIN = {
    "enlace": "link",
    "invitacion_calendario": "calendar_invite",
    "manual": "manual",
}

_CAPTURE_ORIGIN = {
    "extension_chrome": "chrome_extension",
    "bot_servidor": "server_bot",
}

_ACCESS_LOG_RESULT = {
    "permitido": "allowed",
    "denegado": "denied",
}


def _translate_column_values(table: str, column: str, mapping: dict[str, str]) -> None:
    for old_value, new_value in mapping.items():
        op.execute(
            f"UPDATE {table} SET {column} = '{new_value}' "
            f"WHERE {column} = '{old_value}'"
        )


def upgrade() -> None:
    # --- meetings (was reuniones) ---
    op.rename_table("reuniones", "meetings")
    op.alter_column("meetings", "enlace_meet", new_column_name="meet_link")
    op.alter_column("meetings", "titulo", new_column_name="title")
    op.alter_column("meetings", "origen", new_column_name="origin")
    op.alter_column("meetings", "id_invitacion_calendario", new_column_name="calendar_invite_id")
    op.alter_column("meetings", "hora_inicio_programada", new_column_name="scheduled_start_time")
    op.alter_column("meetings", "estado_proceso", new_column_name="process_state")
    op.alter_column("meetings", "causa_fallo", new_column_name="failure_cause")
    op.alter_column("meetings", "creada_por", new_column_name="created_by")
    op.alter_column("meetings", "creada_en", new_column_name="created_at")
    _translate_column_values("meetings", "process_state", _MEETING_PROCESS_STATE)
    _translate_column_values("meetings", "failure_cause", _MEETING_FAILURE_CAUSE)
    _translate_column_values("meetings", "origin", _MEETING_ORIGIN)

    # --- state_history (was estado_historial) ---
    op.rename_table("estado_historial", "state_history")
    op.alter_column("state_history", "reunion_id", new_column_name="meeting_id")
    op.alter_column("state_history", "estado", new_column_name="state")
    op.alter_column("state_history", "causa_fallo", new_column_name="failure_cause")
    op.alter_column("state_history", "ocurrido_en", new_column_name="occurred_at")
    _translate_column_values("state_history", "state", _MEETING_PROCESS_STATE)
    _translate_column_values("state_history", "failure_cause", _MEETING_FAILURE_CAUSE)

    # --- session_recordings (was grabaciones_de_sesion) ---
    op.rename_table("grabaciones_de_sesion", "session_recordings")
    op.alter_column("session_recordings", "reunion_id", new_column_name="meeting_id")
    op.alter_column("session_recordings", "clave_idempotencia", new_column_name="idempotency_key")
    op.alter_column("session_recordings", "origen_captura", new_column_name="capture_origin")
    op.alter_column("session_recordings", "duracion_segundos", new_column_name="duration_seconds")
    op.alter_column("session_recordings", "interrumpida", new_column_name="interrupted")
    op.alter_column("session_recordings", "expira_en", new_column_name="expires_at")
    op.alter_column("session_recordings", "finalizada_en", new_column_name="finished_at")
    _translate_column_values("session_recordings", "capture_origin", _CAPTURE_ORIGIN)

    # --- transcripts (was transcripciones) ---
    op.rename_table("transcripciones", "transcripts")
    op.alter_column("transcripts", "reunion_id", new_column_name="meeting_id")
    op.alter_column("transcripts", "idioma", new_column_name="language")
    op.alter_column("transcripts", "proveedor", new_column_name="provider")
    op.alter_column("transcripts", "soporta_turnos", new_column_name="supports_turns")
    op.alter_column("transcripts", "expira_en", new_column_name="expires_at")
    op.alter_column("transcripts", "creada_en", new_column_name="created_at")

    # --- speech_turns (was turnos_de_habla) ---
    op.rename_table("turnos_de_habla", "speech_turns")
    op.alter_column("speech_turns", "transcripcion_id", new_column_name="transcript_id")
    op.alter_column("speech_turns", "texto", new_column_name="text")
    op.alter_column("speech_turns", "inicio_ms", new_column_name="start_ms")
    op.alter_column("speech_turns", "fin_ms", new_column_name="end_ms")
    op.alter_column("speech_turns", "orden", new_column_name="sequence")

    # --- recording_notices (was notificaciones_de_grabacion) ---
    op.rename_table("notificaciones_de_grabacion", "recording_notices")
    op.alter_column("recording_notices", "reunion_id", new_column_name="meeting_id")
    op.alter_column("recording_notices", "emitida_en", new_column_name="issued_at")

    # --- access_log (was registro_de_acceso) ---
    op.rename_table("registro_de_acceso", "access_log")
    op.alter_column("access_log", "usuario_id", new_column_name="user_id")
    op.alter_column("access_log", "recurso", new_column_name="resource")
    op.alter_column("access_log", "resultado", new_column_name="result")
    op.alter_column("access_log", "ocurrido_en", new_column_name="occurred_at")
    _translate_column_values("access_log", "result", _ACCESS_LOG_RESULT)

    # --- diarizations (was diarizaciones) ---
    op.rename_table("diarizaciones", "diarizations")
    op.alter_column("diarizations", "reunion_id", new_column_name="meeting_id")
    op.alter_column("diarizations", "transcripcion_id", new_column_name="transcript_id")
    op.alter_column("diarizations", "proveedor", new_column_name="provider")
    op.alter_column("diarizations", "num_hablantes", new_column_name="speaker_count")
    op.alter_column("diarizations", "estado_diarizacion", new_column_name="diarization_state")
    op.alter_column("diarizations", "causa_fallo", new_column_name="failure_cause")
    op.alter_column("diarizations", "creada_en", new_column_name="created_at")
    op.alter_column("diarizations", "actualizada_en", new_column_name="updated_at")
    _translate_column_values("diarizations", "diarization_state", _DIARIZATION_STATE)
    _translate_column_values("diarizations", "failure_cause", _MEETING_FAILURE_CAUSE)

    # --- speakers (was hablantes) ---
    op.rename_table("hablantes", "speakers")
    op.alter_column("speakers", "diarizacion_id", new_column_name="diarization_id")
    op.alter_column("speakers", "etiqueta_cruda", new_column_name="raw_label")
    op.alter_column("speakers", "etiqueta", new_column_name="label")
    op.alter_column("speakers", "orden", new_column_name="sequence")

    # --- speaker_assignments (was asignaciones_de_hablante) ---
    op.rename_table("asignaciones_de_hablante", "speaker_assignments")
    op.alter_column("speaker_assignments", "diarizacion_id", new_column_name="diarization_id")
    op.alter_column("speaker_assignments", "turno_id", new_column_name="turn_id")
    op.alter_column("speaker_assignments", "hablante_id", new_column_name="speaker_id")

    # --- users (was usuarios) ---
    op.rename_table("usuarios", "users")
    op.alter_column("users", "nombre", new_column_name="name")
    op.alter_column("users", "es_comercial", new_column_name="is_sales")
    op.alter_column("users", "creado_en", new_column_name="created_at")

    # --- Named unique constraints (design.md > "Constraints/índices") ---
    op.execute("ALTER TABLE session_recordings RENAME CONSTRAINT uq_grabacion_reunion_id TO uq_session_recording_meeting_id")
    op.execute("ALTER TABLE session_recordings RENAME CONSTRAINT uq_grabacion_clave_idempotencia TO uq_session_recording_idempotency_key")
    op.execute("ALTER TABLE transcripts RENAME CONSTRAINT uq_transcripcion_reunion_id TO uq_transcript_meeting_id")
    op.execute("ALTER TABLE diarizations RENAME CONSTRAINT uq_diarizacion_reunion_id TO uq_diarization_meeting_id")
    op.execute("ALTER TABLE speaker_assignments RENAME CONSTRAINT uq_asignacion_turno_id TO uq_speaker_assignment_turn_id")
    op.execute("ALTER TABLE users RENAME CONSTRAINT uq_usuario_email TO uq_user_email")


def downgrade() -> None:
    # --- Named unique constraints (reverse) ---
    op.execute("ALTER TABLE users RENAME CONSTRAINT uq_user_email TO uq_usuario_email")
    op.execute("ALTER TABLE speaker_assignments RENAME CONSTRAINT uq_speaker_assignment_turn_id TO uq_asignacion_turno_id")
    op.execute("ALTER TABLE diarizations RENAME CONSTRAINT uq_diarization_meeting_id TO uq_diarizacion_reunion_id")
    op.execute("ALTER TABLE transcripts RENAME CONSTRAINT uq_transcript_meeting_id TO uq_transcripcion_reunion_id")
    op.execute("ALTER TABLE session_recordings RENAME CONSTRAINT uq_session_recording_idempotency_key TO uq_grabacion_clave_idempotencia")
    op.execute("ALTER TABLE session_recordings RENAME CONSTRAINT uq_session_recording_meeting_id TO uq_grabacion_reunion_id")

    # --- users (was usuarios) ---
    op.alter_column("users", "created_at", new_column_name="creado_en")
    op.alter_column("users", "is_sales", new_column_name="es_comercial")
    op.alter_column("users", "name", new_column_name="nombre")
    op.rename_table("users", "usuarios")

    # --- speaker_assignments (was asignaciones_de_hablante) ---
    op.alter_column("speaker_assignments", "speaker_id", new_column_name="hablante_id")
    op.alter_column("speaker_assignments", "turn_id", new_column_name="turno_id")
    op.alter_column("speaker_assignments", "diarization_id", new_column_name="diarizacion_id")
    op.rename_table("speaker_assignments", "asignaciones_de_hablante")

    # --- speakers (was hablantes) ---
    op.alter_column("speakers", "sequence", new_column_name="orden")
    op.alter_column("speakers", "label", new_column_name="etiqueta")
    op.alter_column("speakers", "raw_label", new_column_name="etiqueta_cruda")
    op.alter_column("speakers", "diarization_id", new_column_name="diarizacion_id")
    op.rename_table("speakers", "hablantes")

    # --- diarizations (was diarizaciones) ---
    _translate_column_values("diarizations", "failure_cause", {v: k for k, v in _MEETING_FAILURE_CAUSE.items()})
    _translate_column_values("diarizations", "diarization_state", {v: k for k, v in _DIARIZATION_STATE.items()})
    op.alter_column("diarizations", "updated_at", new_column_name="actualizada_en")
    op.alter_column("diarizations", "created_at", new_column_name="creada_en")
    op.alter_column("diarizations", "failure_cause", new_column_name="causa_fallo")
    op.alter_column("diarizations", "diarization_state", new_column_name="estado_diarizacion")
    op.alter_column("diarizations", "speaker_count", new_column_name="num_hablantes")
    op.alter_column("diarizations", "provider", new_column_name="proveedor")
    op.alter_column("diarizations", "transcript_id", new_column_name="transcripcion_id")
    op.alter_column("diarizations", "meeting_id", new_column_name="reunion_id")
    op.rename_table("diarizations", "diarizaciones")

    # --- access_log (was registro_de_acceso) ---
    _translate_column_values("access_log", "result", {v: k for k, v in _ACCESS_LOG_RESULT.items()})
    op.alter_column("access_log", "occurred_at", new_column_name="ocurrido_en")
    op.alter_column("access_log", "result", new_column_name="resultado")
    op.alter_column("access_log", "resource", new_column_name="recurso")
    op.alter_column("access_log", "user_id", new_column_name="usuario_id")
    op.rename_table("access_log", "registro_de_acceso")

    # --- recording_notices (was notificaciones_de_grabacion) ---
    op.alter_column("recording_notices", "issued_at", new_column_name="emitida_en")
    op.alter_column("recording_notices", "meeting_id", new_column_name="reunion_id")
    op.rename_table("recording_notices", "notificaciones_de_grabacion")

    # --- speech_turns (was turnos_de_habla) ---
    op.alter_column("speech_turns", "sequence", new_column_name="orden")
    op.alter_column("speech_turns", "end_ms", new_column_name="fin_ms")
    op.alter_column("speech_turns", "start_ms", new_column_name="inicio_ms")
    op.alter_column("speech_turns", "text", new_column_name="texto")
    op.alter_column("speech_turns", "transcript_id", new_column_name="transcripcion_id")
    op.rename_table("speech_turns", "turnos_de_habla")

    # --- transcripts (was transcripciones) ---
    op.alter_column("transcripts", "created_at", new_column_name="creada_en")
    op.alter_column("transcripts", "expires_at", new_column_name="expira_en")
    op.alter_column("transcripts", "supports_turns", new_column_name="soporta_turnos")
    op.alter_column("transcripts", "provider", new_column_name="proveedor")
    op.alter_column("transcripts", "language", new_column_name="idioma")
    op.alter_column("transcripts", "meeting_id", new_column_name="reunion_id")
    op.rename_table("transcripts", "transcripciones")

    # --- session_recordings (was grabaciones_de_sesion) ---
    _translate_column_values("session_recordings", "capture_origin", {v: k for k, v in _CAPTURE_ORIGIN.items()})
    op.alter_column("session_recordings", "finished_at", new_column_name="finalizada_en")
    op.alter_column("session_recordings", "expires_at", new_column_name="expira_en")
    op.alter_column("session_recordings", "interrupted", new_column_name="interrumpida")
    op.alter_column("session_recordings", "duration_seconds", new_column_name="duracion_segundos")
    op.alter_column("session_recordings", "capture_origin", new_column_name="origen_captura")
    op.alter_column("session_recordings", "idempotency_key", new_column_name="clave_idempotencia")
    op.alter_column("session_recordings", "meeting_id", new_column_name="reunion_id")
    op.rename_table("session_recordings", "grabaciones_de_sesion")

    # --- state_history (was estado_historial) ---
    _translate_column_values("state_history", "failure_cause", {v: k for k, v in _MEETING_FAILURE_CAUSE.items()})
    _translate_column_values("state_history", "state", {v: k for k, v in _MEETING_PROCESS_STATE.items()})
    op.alter_column("state_history", "occurred_at", new_column_name="ocurrido_en")
    op.alter_column("state_history", "failure_cause", new_column_name="causa_fallo")
    op.alter_column("state_history", "state", new_column_name="estado")
    op.alter_column("state_history", "meeting_id", new_column_name="reunion_id")
    op.rename_table("state_history", "estado_historial")

    # --- meetings (was reuniones) ---
    _translate_column_values("meetings", "origin", {v: k for k, v in _MEETING_ORIGIN.items()})
    _translate_column_values("meetings", "failure_cause", {v: k for k, v in _MEETING_FAILURE_CAUSE.items()})
    _translate_column_values("meetings", "process_state", {v: k for k, v in _MEETING_PROCESS_STATE.items()})
    op.alter_column("meetings", "created_at", new_column_name="creada_en")
    op.alter_column("meetings", "created_by", new_column_name="creada_por")
    op.alter_column("meetings", "failure_cause", new_column_name="causa_fallo")
    op.alter_column("meetings", "process_state", new_column_name="estado_proceso")
    op.alter_column("meetings", "scheduled_start_time", new_column_name="hora_inicio_programada")
    op.alter_column("meetings", "calendar_invite_id", new_column_name="id_invitacion_calendario")
    op.alter_column("meetings", "origin", new_column_name="origen")
    op.alter_column("meetings", "title", new_column_name="titulo")
    op.alter_column("meetings", "meet_link", new_column_name="enlace_meet")
    op.rename_table("meetings", "reuniones")
