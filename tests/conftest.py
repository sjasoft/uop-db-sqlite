import pytest
from uop.core.plugin_testing.harness import Plugin
from uop.db.sqlite import adaptor
from uop.meta.schemas.predefined import pkm_schema


@pytest.fixture(scope="session")
def db_harness():
    """
    Pytest fixture to set up and tear down a SQLite test database.
    """
    db = adaptor.SQLiteDatabase("", pkm_schema, in_memory=True)
    db.open_db()
    plug_in = Plugin(db)

    yield plug_in  # Provide the database adapter instance to the tests

    # No need to drop the default database, just close the connection
    db.close()
