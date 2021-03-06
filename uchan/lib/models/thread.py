from sqlalchemy import Column, Integer, ForeignKey, BigInteger, Boolean
from sqlalchemy.orm import relationship

from uchan.lib.database import ModelBase


class Thread(ModelBase):
    __tablename__ = 'thread'

    id = Column(Integer(), primary_key=True)

    board_id = Column(Integer(), ForeignKey('board.id'), nullable=False, index=True)
    # board is a backref property
    refno = Column(Integer(), nullable=False, index=True)

    last_modified = Column(BigInteger(), nullable=False, index=True)
    refno_counter = Column(Integer(), nullable=False, default=1)
    sticky = Column(Boolean(), nullable=False, default=False)
    locked = Column(Boolean(), nullable=False, default=False)

    posts = relationship('Post', order_by='Post.id', backref='thread', cascade='all, delete-orphan')
