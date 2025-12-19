"""Nueva columna de pagos

Revision ID: 46fab0277bee
Revises: 4fc6051b580f
Create Date: 2025-12-19 10:09:58.738288
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "46fab0277bee"
down_revision = "4fc6051b580f"
branch_labels = None
depends_on = None


def upgrade():
    # 1) Agrega columnas con DEFAULT a nivel DB para no romper filas existentes
    with op.batch_alter_table("liquidaciones", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "pagado",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),  # <- CLAVE
            )
        )
        batch_op.add_column(sa.Column("pagado_at", sa.DateTime(), nullable=True))

    # 2) (Opcional pero recomendado) quita el default permanente
    #    para que el "default" lo maneje tu modelo / app.
    op.alter_column("liquidaciones", "pagado", server_default=None)


def downgrade():
    with op.batch_alter_table("liquidaciones", schema=None) as batch_op:
        batch_op.drop_column("pagado_at")
        batch_op.drop_column("pagado")
