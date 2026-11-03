"""tabla rutas_maestras

Revision ID: fd922d88f28c
Revises: ec0415556b15
Create Date: 2026-10-07 17:06:25.639889

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'fd922d88f28c'
down_revision: Union[str, Sequence[str], None] = 'ec0415556b15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS seq_codigo_ruta START WITH 1 MINVALUE 1 MAXVALUE 99999999")
    op.create_table(
        "rutas_maestras",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("codigo_ruta", sa.String(length=12),
                  server_default=sa.text("'RUT-' || lpad(nextval('seq_codigo_ruta')::text, 8, '0')"), nullable=False),
        sa.Column("origen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ubicaciones.id"), nullable=False),
        sa.Column("destino_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ubicaciones.id"), nullable=False),
        sa.Column("distancia_km", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("duracion_horas", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("geometria", sa.Text(), nullable=False),
        sa.Column("paradas", postgresql.JSONB(), nullable=True),
        sa.Column("fuente", sa.String(length=10), server_default="osrm", nullable=False),
        sa.Column("calculada_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("codigo_ruta", name="uq_rutas_maestras_codigo"),
        sa.UniqueConstraint("origen_id", "destino_id", name="uq_rutas_maestras_par"),
    )
    op.execute("ALTER SEQUENCE seq_codigo_ruta OWNED BY rutas_maestras.codigo_ruta")


def downgrade() -> None:
    op.drop_table("rutas_maestras")
    op.execute("DROP SEQUENCE IF EXISTS seq_codigo_ruta")