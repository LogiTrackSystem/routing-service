"""carga compartida y reposicionamiento en rutas

Revision ID: b81f3c0d7a24
Revises: 6c3c902b7e97
Create Date: 2026-10-21 10:00:00.000000

Solo agrega columnas (con valor por defecto): las rutas existentes quedan como "exclusiva", sin reposición.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b81f3c0d7a24'
down_revision: Union[str, Sequence[str], None] = '6c3c902b7e97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rutas", sa.Column("modo", sa.String(length=12), server_default="exclusiva", nullable=False))
    op.add_column("rutas", sa.Column("ruta_anfitriona_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("rutas", sa.Column("km_recogida", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("rutas", sa.Column("km_entrega", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("rutas", sa.Column("reposicion", postgresql.JSONB(), nullable=True))
    op.create_foreign_key("fk_rutas_ruta_anfitriona", "rutas", "rutas", ["ruta_anfitriona_id"], ["id"])
    op.create_index("ix_rutas_ruta_anfitriona_id", "rutas", ["ruta_anfitriona_id"])
    op.create_index("ix_rutas_vehiculo_estado", "rutas", ["vehiculo_id", "estado"])


def downgrade() -> None:
    op.drop_index("ix_rutas_vehiculo_estado", table_name="rutas")
    op.drop_index("ix_rutas_ruta_anfitriona_id", table_name="rutas")
    op.drop_constraint("fk_rutas_ruta_anfitriona", "rutas", type_="foreignkey")
    for columna in ("reposicion", "km_entrega", "km_recogida", "ruta_anfitriona_id", "modo"):
        op.drop_column("rutas", columna)
