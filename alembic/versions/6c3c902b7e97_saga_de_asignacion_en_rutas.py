"""saga de asignacion en rutas

Revision ID: 6c3c902b7e97
Revises: fd922d88f28c
Create Date: 2026-10-08 17:30:43.729066

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6c3c902b7e97'
down_revision: Union[str, Sequence[str], None] = 'fd922d88f28c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rutas", sa.Column("estado", sa.String(length=20), server_default="manual", nullable=False))
    op.execute("UPDATE rutas SET estado = 'historica'")  # las rutas existentes son del flujo anterior
    op.add_column("rutas", sa.Column("conductor_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("rutas", sa.Column("reserva_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("rutas", sa.Column("ruta_maestra_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("rutas", sa.Column("requisitos", postgresql.JSONB(), nullable=True))
    op.add_column("rutas", sa.Column("detalle_asignacion", postgresql.JSONB(), nullable=True))
    op.add_column("rutas", sa.Column("distancia_planificada_km", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("rutas", sa.Column("intentos", sa.Integer(), server_default="0", nullable=False))
    op.add_column("rutas", sa.Column("proximo_reintento_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column("rutas", sa.Column("ultimo_error", sa.Text(), nullable=True))
    op.add_column("rutas", sa.Column("evento_pendiente", sa.String(length=30), nullable=True))
    op.create_foreign_key("fk_rutas_ruta_maestra", "rutas", "rutas_maestras", ["ruta_maestra_id"], ["id"])
    op.create_index("ix_rutas_estado", "rutas", ["estado"])
    op.create_index(
        "uq_rutas_envio_vigente", "rutas", ["envio_id"],
        unique=True, postgresql_where=sa.text("estado NOT IN ('historica', 'manual')"),
    )


def downgrade() -> None:
    op.drop_index("uq_rutas_envio_vigente", table_name="rutas")
    op.drop_index("ix_rutas_estado", table_name="rutas")
    op.drop_constraint("fk_rutas_ruta_maestra", "rutas", type_="foreignkey")
    for columna in ("evento_pendiente", "ultimo_error", "proximo_reintento_en", "intentos",
                    "distancia_planificada_km", "detalle_asignacion", "requisitos",
                    "ruta_maestra_id", "reserva_id", "conductor_id", "estado"):
        op.drop_column("rutas", columna)