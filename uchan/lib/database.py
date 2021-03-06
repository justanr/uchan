from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

from uchan import configuration

ModelBase = declarative_base()

_sessionconstruct = None
_engine = None

from sqlalchemy.orm.session import Session


def get_db() -> Session:
    global _sessionconstruct

    return _sessionconstruct()


def connect_string():
    return configuration.database.connect_string


def clean_up():
    global _sessionconstruct
    _sessionconstruct.remove()


def register_teardown(flask_app):
    @flask_app.teardown_appcontext
    def teardown_request(exception):
        clean_up()


# noinspection PyUnresolvedReferences
def init_db():
    """Initialize function for the database.
    """

    global _sessionconstruct
    global _engine
    global ModelBase

    _engine = create_engine(connect_string(), pool_size=configuration.database.pool_size,
                            echo=configuration.database.echo)
    _sessionconstruct = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=_engine))

    import uchan.lib.models


def metadata_create_all():
    ModelBase.metadata.create_all(_engine)
