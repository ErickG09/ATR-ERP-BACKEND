"""fecha de pago liquidacion3

Revision ID: c012c075146b
Revises: 3cbd65b9b0f8
Create Date: 2025-12-19 09:38:06.051177

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c012c075146b'
down_revision = '3cbd65b9b0f8'
branch_labels = None
depends_on = None



def upgrade():
    with op.batch_alter_table("liquidaciones") as batch_op:
        batch_op.add_column(
            sa.Column("pagado", sa.Boolean(), nullable=False, server_default=sa.text("false"))
        )
        batch_op.add_column(
            sa.Column("pagado_at", sa.DateTime(), nullable=True)
        )

    # opcional: quitar el default a futuro (si no quieres que quede en la BD)
    op.alter_column("liquidaciones", "pagado", server_default=None)

def downgrade():
    with op.batch_alter_table("liquidaciones") as batch_op:
        batch_op.drop_column("pagado_at")
        batch_op.drop_column("pagado")


    # ### end Alembic commands ###
