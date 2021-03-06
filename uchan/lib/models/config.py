from sqlalchemy import Column, Integer, String
from sqlalchemy.dialects.postgresql import JSON

from uchan.lib.database import ModelBase


class Config(ModelBase):
    __tablename__ = 'config'

    id = Column(Integer(), primary_key=True)
    type = Column(String(), index=True)
    config = Column(JSON(), nullable=False, default='{}')
