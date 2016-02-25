from sqlalchemy import Column, String, BigInteger

from uchan.lib.database import ModelBase


class Session(ModelBase):
    __tablename__ = 'session'

    session_id = Column(String(32), primary_key=True)  # Length of a uuid4 with the - stripped
    data = Column(String(), nullable=False, index=True)
    expires = Column(BigInteger(), nullable=False, index=True)
