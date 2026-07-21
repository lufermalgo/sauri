"""Modelos SQLAlchemy del dominio de sauri — módulo Captura y Transcripción."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database import Base


# ---------------------------------------------------------------------------
# Reunion
# ---------------------------------------------------------------------------


class Reunion(Base):
    """Registro de una reunión de Google Meet gestionada por sauri (Req. 1, 4)."""

    __tablename__ = "reuniones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    enlace_meet: Mapped[str] = mapped_column(String(512), nullable=False)
    titulo: Mapped[str | None] = mapped_column(String(512), nullable=True)
    origen: Mapped[str] = mapped_column(String(64), nullable=False)  # enlace | invitacion_calendario | manual
    id_invitacion_calendario: Mapped[str | None] = mapped_column(String(256), nullable=True)
    hora_inicio_programada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estado_proceso: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # en_cola | uniendose | grabando | transcribiendo | completado | fallido
    causa_fallo: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # no_pudo_unirse | reunion_cancelada | fallo_del_motor
    creada_por: Mapped[str] = mapped_column(String(36), nullable=False)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# EstadoHistorial
# ---------------------------------------------------------------------------


class EstadoHistorial(Base):
    """Historial de transiciones de estado de una Reunion (Req. 4.2)."""

    __tablename__ = "estado_historial"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reunion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reuniones.id", ondelete="CASCADE"), nullable=False
    )
    estado: Mapped[str] = mapped_column(String(64), nullable=False)
    causa_fallo: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ocurrido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# GrabacionDeSesion
# ---------------------------------------------------------------------------


class GrabacionDeSesion(Base):
    """Grabación de audio+video asociada 1:1 a una Reunion (Req. 2.3)."""

    __tablename__ = "grabaciones_de_sesion"
    __table_args__ = (
        UniqueConstraint("reunion_id", name="uq_grabacion_reunion_id"),
        UniqueConstraint("clave_idempotencia", name="uq_grabacion_clave_idempotencia"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reunion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reuniones.id", ondelete="CASCADE"), nullable=False
    )
    clave_idempotencia: Mapped[str] = mapped_column(String(256), nullable=False)
    origen_captura: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # extension_chrome | bot_servidor
    audio_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    video_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    duracion_segundos: Mapped[int] = mapped_column(Integer, nullable=False)
    interrumpida: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expira_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalizada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Transcripcion
# ---------------------------------------------------------------------------


class Transcripcion(Base):
    """Transcripción en español generada a partir de la grabación (Req. 3)."""

    __tablename__ = "transcripciones"
    __table_args__ = (UniqueConstraint("reunion_id", name="uq_transcripcion_reunion_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reunion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reuniones.id", ondelete="CASCADE"), nullable=False
    )
    idioma: Mapped[str] = mapped_column(String(16), nullable=False, default="es-CO")
    proveedor: Mapped[str] = mapped_column(String(128), nullable=False)
    soporta_turnos: Mapped[bool] = mapped_column(Boolean, nullable=False)
    expira_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    turnos: Mapped[list["TurnoDeHabla"]] = relationship(
        "TurnoDeHabla", back_populates="transcripcion", lazy="select"
    )


# ---------------------------------------------------------------------------
# TurnoDeHabla
# ---------------------------------------------------------------------------


class TurnoDeHabla(Base):
    """Segmento temporal de texto dentro de una Transcripcion (Req. 3.4, 3.5)."""

    __tablename__ = "turnos_de_habla"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transcripcion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripciones.id", ondelete="CASCADE"), nullable=False
    )
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    inicio_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    fin_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)

    transcripcion: Mapped["Transcripcion"] = relationship(
        "Transcripcion", back_populates="turnos"
    )


# ---------------------------------------------------------------------------
# NotificacionDeGrabacion
# ---------------------------------------------------------------------------


class NotificacionDeGrabacion(Base):
    """Registro auditable de la notificación de grabación emitida (Req. 6.1, 6.5)."""

    __tablename__ = "notificaciones_de_grabacion"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reunion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reuniones.id", ondelete="CASCADE"), nullable=False
    )
    emitida_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# RegistroDeAcceso
# ---------------------------------------------------------------------------


class RegistroDeAcceso(Base):
    """Auditoría de acceso — registra intentos permitidos y denegados (Req. 7.4)."""

    __tablename__ = "registro_de_acceso"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    usuario_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recurso: Mapped[str] = mapped_column(String(512), nullable=False)
    resultado: Mapped[str] = mapped_column(String(16), nullable=False)  # "permitido" | "denegado"
    ocurrido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Diarizacion
# ---------------------------------------------------------------------------


class Diarizacion(Base):
    """Resultado de diarización asociado 1:1 a una Reunion (Req. 8.1, 8.4, 9.3, 9.4, 10.5)."""

    __tablename__ = "diarizaciones"
    __table_args__ = (UniqueConstraint("reunion_id", name="uq_diarizacion_reunion_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reunion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reuniones.id"), nullable=False
    )
    transcripcion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripciones.id"), nullable=False
    )
    proveedor: Mapped[str] = mapped_column(String(128), nullable=False)
    num_hablantes: Mapped[int] = mapped_column(Integer, nullable=False)
    estado_diarizacion: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # pendiente | en_proceso | completada | fallida
    causa_fallo: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # fallo_del_motor cuando fallida
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actualizada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    hablantes: Mapped[list["Hablante"]] = relationship(
        "Hablante", back_populates="diarizacion", lazy="select"
    )
    asignaciones: Mapped[list["AsignacionDeHablante"]] = relationship(
        "AsignacionDeHablante", back_populates="diarizacion", lazy="select"
    )


# ---------------------------------------------------------------------------
# Hablante
# ---------------------------------------------------------------------------


class Hablante(Base):
    """Hablante anónimo detectado por la diarización (Req. 6.1, 6.2, 6.3)."""

    __tablename__ = "hablantes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    diarizacion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diarizaciones.id", ondelete="CASCADE"), nullable=False
    )
    etiqueta_cruda: Mapped[str] = mapped_column(String(128), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(64), nullable=False)  # "Hablante N"
    orden: Mapped[int] = mapped_column(Integer, nullable=False)  # consecutivo desde 1

    diarizacion: Mapped["Diarizacion"] = relationship(
        "Diarizacion", back_populates="hablantes"
    )


# ---------------------------------------------------------------------------
# AsignacionDeHablante
# ---------------------------------------------------------------------------


class AsignacionDeHablante(Base):
    """Asignación de un TurnoDeHabla a un Hablante (Req. 7.1)."""

    __tablename__ = "asignaciones_de_hablante"
    __table_args__ = (UniqueConstraint("turno_id", name="uq_asignacion_turno_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    diarizacion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diarizaciones.id", ondelete="CASCADE"), nullable=False
    )
    turno_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("turnos_de_habla.id"), nullable=False
    )
    hablante_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("hablantes.id", ondelete="CASCADE"), nullable=False
    )

    diarizacion: Mapped["Diarizacion"] = relationship(
        "Diarizacion", back_populates="asignaciones"
    )
    hablante: Mapped["Hablante"] = relationship("Hablante")


# ---------------------------------------------------------------------------
# Usuario
# ---------------------------------------------------------------------------


class Usuario(Base):
    """Almacén mínimo de usuarios comerciales autorizados de sauri (Req. 13.1, 13.2).

    NO es una integración con el IdP de Summan: es un almacén mínimo,
    semillado de forma determinista, que respalda el Servicio_De_Autenticacion
    (`POST /api/v1/auth/login`) mientras no exista una integración con el IdP.
    """

    __tablename__ = "usuarios"
    __table_args__ = (UniqueConstraint("email", name="uq_usuario_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    nombre: Mapped[str] = mapped_column(String(256), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    es_comercial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
