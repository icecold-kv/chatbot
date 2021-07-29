import logging
import sys
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class Connection:
    def __init__(self, db_url, logger=logging.getLogger()):
        engine = create_engine(db_url, pool_recycle=600) if 'sqlite' in db_url else \
            create_engine(db_url, pool_recycle=600, isolation_level='READ COMMITTED')
        self.factory = sessionmaker(bind=engine)
        self.logger = logger

    @contextmanager
    def _session_scope(self):
        session = self.factory()
        try:
            yield session
            session.commit()
        except:
            session.rollback()
            raise
        finally:
            session.close()

    def set_parameter(self, param, val):
        with self._session_scope() as db_session:
            try:
                db_param = db_session.query(State).filter_by(parameter=param).first()
                if db_param is not None:
                    db_param.value = val
                else:
                    db_param = State(parameter=param, value=val)
                    db_session.add(db_param)
            except:
                self.logger.error('Exception while updating state in DB', exc_info=sys.exc_info())

    def get_parameter(self, param):
        with self._session_scope() as db_session:
            db_param = db_session.query(State).filter_by(parameter=param).first()
        return db_param.value if db_param else None


class State(Base):
    __tablename__ = 'state'
    id = Column(Integer, primary_key=True)
    parameter = Column(String)
    value = Column(String)

    def __repr__(self):
        return "<State(parameter='{}', value='{}')>".format(self.parameter, self.value)
