import aiomysql

from .base import FILTER_OP
from .base import make_param_name
from .base import Model


class Friend(Model):
    _table_name = 'friend'
    _default_fields = ['id', 'user_id', 'friend_id']

    id = None
    user_id = None
    friend_id = None

    def __init__(self, _id=None, user_id=None, friend_id=None):
        self.id = _id
        self.user_id = user_id
        self.friend_id = friend_id

    @classmethod
    def from_dict(cls, adict):
        return cls(
            _id=adict.get('id'),
            user_id=adict.get('user_id'),
            friend_id=adict.get('friend_id'),
        )

    def to_dict(self):
        return dict(
            id=self.id,
            user_id=self.user_id,
            friend_id=self.friend_id,
        )

    @classmethod
    async def filter(cls, conn, filter: dict = None, limit=20, offset=0, fields: list = None):
        if not fields:
            fields = cls._default_fields
        else:
            for field in fields:
                assert hasattr(cls, field), f'unknown field: {field}'

        query_params = dict(limit=int(limit), offset=int(offset))
        where_sql = ''
        where = []

        if filter:
            for field, value in filter.items():
                assert hasattr(cls, field), f'unknown field: {field} in filter'
                op = '='
                if isinstance(value, dict):
                    op = FILTER_OP[value['op']]
                    value = value['v']

                filter_name = make_param_name(query_params, f"{field}_filter")
                where.append(f"{field} {op} %({filter_name})s")
                query_params[filter_name] = value

        if where:
            where_sql = f"WHERE {' AND '.join(where)}"

        async with conn.cursor(aiomysql.SSDictCursor) as cur:
            await cur.execute(f"SELECT "
                              f"{','.join(fields)}"
                              f" FROM {cls._table_name} "
                              f" {where_sql} "
                              f" ORDER BY user_id "
                              f"LIMIT %(limit)s OFFSET %(offset)s",
                              query_params)
            result = await cur.fetchall()
            return result or []
