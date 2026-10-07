"""tabla ubicaciones

Revision ID: ec0415556b15
Revises: 7b7f58b8f9ef
Create Date: 2026-10-07 16:29:56.967057

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ec0415556b15'
down_revision: Union[str, Sequence[str], None] = '7b7f58b8f9ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ubicaciones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("codigo", sa.String(length=12), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("nombre_normalizado", sa.String(length=100), nullable=False),
        sa.Column("departamento", sa.String(length=100), nullable=False),
        sa.Column("pais", sa.String(length=60), nullable=False),
        sa.Column("codigo_pais", sa.String(length=2), nullable=False),
        sa.Column("latitud", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("longitud", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("tipo", sa.String(length=20), server_default="ciudad", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("codigo", name="uq_ubicaciones_codigo"),
        sa.UniqueConstraint("codigo_pais", "nombre_normalizado", "departamento", name="uq_ubicaciones_pais_nombre_depto"),
    )
    op.create_index("ix_ubicaciones_nombre_normalizado", "ubicaciones", ["nombre_normalizado"])
    op.create_index("ix_ubicaciones_codigo_pais", "ubicaciones", ["codigo_pais"])


def downgrade() -> None:
    op.drop_index("ix_ubicaciones_codigo_pais", table_name="ubicaciones")
    op.drop_index("ix_ubicaciones_nombre_normalizado", table_name="ubicaciones")
    op.drop_table("ubicaciones")