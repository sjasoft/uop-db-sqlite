from uop.db.alchemy.adaptor import AlchemyDatabase


class SQLiteDatabase(AlchemyDatabase):
    def __init__(self, dbname, tenant_id=None, *schemas, **db_credentials):
        super().__init__(
            dbname, tenant_id=tenant_id, db_brand="sqlite", *schemas, **db_credentials
        )
