from uop.db.alchemy.adaptor import AlchemyDatabase


class SQLiteDatabase(AlchemyDatabase):
    def __init__(self, dbname, *schemas, tenant_id=None, **db_credentials):
        super().__init__(
            dbname, *schemas, tenant_id=tenant_id, db_brand="sqlite", **db_credentials
        )
