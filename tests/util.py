"""
Defines setup and teardown functions for test modules.
Also injects the --schema=doko_test option.
"""
import unittest

from dokomoforms.options import inject_options

inject_options(schema='doko_test')

from sqlalchemy import DDL
from sqlalchemy.orm import sessionmaker
from dokomoforms.models import create_engine, Base

engine = create_engine(echo=False)
Session = sessionmaker()


def setUpModule():
    """Creates the tables in the doko_test schema."""
    Base.metadata.create_all(engine)


def tearDownModule():
    """Drops the doko_test schema."""
    engine.execute(DDL('DROP SCHEMA IF EXISTS doko_test CASCADE'))


class DokoTest(unittest.TestCase):
    def setUp(self):
        """Starts a transaction"""
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(bind=self.connection, autocommit=True)

    def tearDown(self):
        """Rolls back the transaction"""
        self.session.close()
        self.transaction.rollback()
        self.connection.close()