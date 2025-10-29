from sjasoft.uop import db_collection as db_coll, database
from sjasoft.uop.collections import uop_collection_names
from pydantic import BaseModel
from sqlalchemy import (inspect, PrimaryKeyConstraint, Column, Date,
                        DateTime, Double, Integer, Boolean,  String,
                        Text, Float, JSON, create_engine, Index, Table,
                        insert, update, delete, and_, or_)
from sqlalchemy.ext.declarative import declarative_base
from sjasoft.uopmeta.schemas import meta
from sjasoft.utils.dicts import first_kv
from sjasoft.utils.env import home_path
from sqlalchemy.orm import sessionmaker
import json

python_sql = dict(
    str = String,
    int = Integer,
    float = Float,
    bool = Boolean,
    json = JSON,
    email = String,
    phone = String,
    long = Double,
    uuid = String,
    string = String,
    text = Text,
    epoch = Float,
    date = Float,
    datetime = Float
)

def column_type(pydantic_type, outer):
    if (outer != pydantic_type) and outer._name == 'List':
        return JSON
    if isinstance(pydantic_type, str):
        return python_sql[pydantic_type]
    elif issubclass(pydantic_type, BaseModel):
        return JSON # stringified json
    elif isinstance(pydantic_type, type):
        if pydantic_type == str:
            return String
        elif pydantic_type == int:
            return Integer
        elif pydantic_type == float:
            return Float
        elif pydantic_type == bool:
            return Boolean

    return JSON


Base = declarative_base()

def extract_model_fields(model):
    fields = {}
    for field_name, field_info in model.__fields__.items():
        if field_name == 'kind':
            continue
        field_type = field_info.type_
        sql_type = column_type(field_type, field_info.outer_type_)
        fields[field_name] = sql_type
    return fields

def extract_class_fields(cls):
    cls = cls if isinstance(cls, dict) else cls.dict()
    return {a['name']:python_sql[a['type']] for a in cls['attributes']}

def columns_from(source, extractor):
    fields = extractor(source)
    keys = ['id'] if 'id' in fields else list(fields.keys())
    return [Column(key, type, primary_key=(key in keys)) for key, type in fields.items()]

def make_table(base, table_name, columns):
    return Table(table_name, base, *columns)

def table_from_schema(schema, name):
    if isinstance(schema, meta.MetaClass):
        return table_from_attrs(schema, Base.metadata, name)
    elif isinstance(schema, BaseModel):
        return table_from_pydantic(schema, Base.metadata, name)
    else:
        raise Exception(f'Expected MetaClass or MetaModel, got {type(schema)}')

def table_from_pydantic(model, base, table_name=''):
    if not table_name:
        table_name = model.__name__.lower()
    columns = columns_from(model, extract_model_fields)
    return make_table(base, table_name, columns)

def table_from_attrs(cls, base, table_name):
    columns = columns_from(cls, extract_class_fields)
    return make_table(base, table_name, columns)

def create_index(table, columns):
    pass

class AlchemyCollection(db_coll.DBCollection):
    def __init__(self, db, table, indexed=False, *constraints):
        # TODO consider preprocessed statements
        self._db= db
        self._engine = self._db._engine
        self._table = table
        super().__init__(self._table, indexed=indexed, tenant_modifier=tenant_modifier, *constraints)

    def connect(self):
        return self._db._connection or self._engine.connect()

    def column_class_check(self, column_name, cls_id):
        return {'$like': {column_name: f'%{cls_id}'}}

    def add_index(self, index_name, field_names):
        columns = [self._table.getattr(s) for s in field_names]
        Index(None, _table=self._table, )

    def in_long_transaction(self):
        return self._db._connection is not None

    def column_is_json(self, name):
        column = getattr(self._table.c, name)
        return isinstance(column.type, JSON)

    def stringify_json(self, fields):
        """
        For all columns that are JSON convert to json string
        :param fields: map of field_name -> value
        :return: new map with adjusted field values
        """
        import json
        def maybe_json_stringify(key, value):
            c = getattr(self._table.c, key)
            if isinstance(c.type, JSON):
                return json.dumps(value)
            return value
        return {k: maybe_json_stringify(k,v) for k,v in fields.items()}
    def insert(self, **fields):

        stmt = self._table.insert().values(**fields)
        return self.execute_sql(stmt, commit=True)

    def replace_one(self, an_id, data):
        return self.update({'id':an_id}, data)

    def count(self, criteria):
        stmt = self._table.select().where(self.modify_criteria(criteria))
        rows = [r for r in self.execute_sql(stmt)]
        return len(rows)


    def update(self, selector, mods, partial=True):
        selector = selector or {}
        selector = self.modify_criteria(selector)
        stmt = self._table.update().where(selector).values(**mods)
        return self.execute_sql(stmt, commit=True)

    def update_one(self, key, mods):
        return self.update({'id':key}, mods)


    def remove(self, dict_or_key):
        condition = dict_or_key if isinstance(dict_or_key, dict) else {'id':dict_or_key}
        condition = self.modify_criteria(condition)
        stmt = self._table.delete().where(condition)

        return self.execute_sql(stmt, commit=True)


    def remove_all(self):
        self.execute_sql(self._table.delete())

    def get_column(self, name):
        return getattr(self._table.c, name)


    def modify_criteria(self, criteria):
        to_method = {
            '$gt': '__gt__',
            '$lt': '__lt__',
            '$ge': '__ge__',
            '$le': '__le__',
            '$eq': '__eq__',
            '$ne': '__ne__',
            '$regex': 'regexp'
        }
        if not criteria:
            return []
        keys = list(criteria.keys())
        if len(keys) > 1:
            parts = [self.modify_criteria({k:criteria[k]}) for k in keys]
            return and_(*parts)
        key = keys[0] if keys else None
        if key in ('$and', '$or'):
            rest = [self.modify_criteria(c) for c in criteria[key]]
            if key == '$and':
                return and_(*rest)
            elif key == '$or':
                return or_(*rest)
        elif key in to_method.keys():
            prop, val = first_kv(criteria[key])
            column = getattr(self._table.c, prop)
            if column is not None:
                fn = getattr(column, to_method[key])
                return fn(val)
        else:
            column = getattr(self._table.c, key)
            if column is not None:
                return column == criteria[key]
        raise Exception(f'cannot parse criteria: {criteria}')


    def execute_sql(self, stmt, commit=False):

        if self.in_long_transaction():
            return self._db._connection.execute(stmt)
        else:
            with self._engine.connect() as c:
                try:
                    res = c.execute(stmt)
                    if commit:
                        c.commit()
                    return res
                except Exception as e:
                    print(f'Error executing sql: {e}')
                    c.rollback()
                    raise e





    def find(self, criteria=None, only_cols=None,
                   order_by=None, limit=None, ids_only=False):
        mod_criteria = self.modify_criteria(criteria)
        if ids_only:
            only_cols = ['id']
        only_cols = only_cols or []
        stmt = self._table.select()
        if criteria:
            stmt = stmt.where(mod_criteria)
        if order_by:
            stmt = stmt.order_by(*order_by)
        rows = [r for r in self.execute_sql(stmt)]
        if ids_only:
            return [row[0] for row in rows]
        else:
            res =  [dict(row._mapping) for row in rows]
            if only_cols:
                if len(only_cols) == 1:
                    res = [r[only_cols[0]] for r in res]
                else:
                    res = [{k:v for k,v in row.items()} for row in res]
            return res

    def get(self, an_id):
        stmt = self._table.select().where(self._table.c.id == an_id)
        rows = [r for r in self.execute_sql(stmt)]
        return dict(rows[0]._mapping) if rows else None





class AlchemyDatabase(database.Database):
    def __init__(self, dbname, tenant_id=None, db_brand='sqlite', *schemas, **dbcredentials):
        self._db_name = dbname
        self._db_brand = db_brand
        self._tables = None
        self._root_txn = None
        self._connection = None
        self._credentials = dbcredentials
        super().__init__(tenant_id=tenant_id, *schemas, **dbcredentials)

    def open_db(self):
        self._connection_string = self.get_connection_string(db_brand, dbcredentials)
        self._engine = create_engine(self._connection_string, json_serializer=json.dumps, json_deserializer=json.loads)
        self._tables = self.get_tables()
        super().open_db()

    def start_long_transaction(self):
        self._connection = self._engine.connect().__enter__()
        self._root_txn = self._connection.begin().__enter__()

    def end_long_transaction(self):
        self._root_txn.__exit__(None, None, None)
        self._connection.__exit__(None, None, None)
        self._connection = None
        self._root_txn = None
        super().end_long_transaction()

    def really_commit(self):
        self._root_txn.commit()


    def abort(self):
        if self._root_txn:
            self._root_txn.rollback()
        self.end_long_transaction()



    def get_existing_table(self, table_name):
        return self.get_tables().get(table_name)

    def _has_collection(self, name):
        "returns whether database has lov level collection by given name"
        return bool(self.get_existing_table(name))

    def get_connection_string(self, db_brand, dbcredentials):
        if self._db_brand == 'sqlite':
            in_memory = dbcredentials.pop('in_memory', False)
            if in_memory:
                return f'{self._db_brand}://:memory:'
            else:
                return f'{self._db_brand}:///{home_path(self._db_name)}'
        else:
            driver = self._credentials.pop('driver','')
            if driver:
                db_brand = f'{self._db_brand}+{driver}'
            username = self._credentials.pop('username', '')
            password = self._credentials.pop('password', '')
            host = self._credentials.pop('host', 'localhost')
            port = self._credentials.pop('port', '')
            host_string = f'{host}:{port}' if port else host
            if username and password:
                return f'{db_brand}://{username}:{password}@{host_string}/{self._db_name}'
            else:
                raise Exception('username and database required')


    def wrap_raw_collection(self, raw):
        return AlchemyCollection(self, raw)

    def get_raw_collection(self, name, schema):
        existing = self.get_existing_table(name)
        return existing or table_from_schema(schema, name)

    def get_tables(self):
        metadata = Base.metadata
        metadata.reflect(self._engine)
        return metadata.tables



def test_basics():
    metadata = Base.metadata
    db = AlchemyDatabase('foobar')
