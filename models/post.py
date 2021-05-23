import aiomysql

from .base import FILTER_OP
from .base import make_param_name
from .base import Model


class Post(Model):
    _table_name = 'post'

    id = None
    author_id = None
    text = None
    created_at = None
    updated_at = None

    _default_fields = ['id', 'author_id', 'text', 'created_at', 'updated_at', ]

    def __init__(self, author_id, text, _id=None, created_at=None, updated_at=None):
        self.id = _id
        self.author_id = author_id
        self.text = text
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def from_dict(cls, adict):
        return cls(
            _id=adict['id'],
            author_id=adict.get('author_id'),
            text=adict.get('text'),
            created_at=adict.get('created_at'),
            updated_at=adict.get('updated_at'),
        )

    def to_dict(self):
        return dict(
            id=self.id,
            author_id=self.author_id,
            text=self.text,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    async def save(self, conn):
        async with conn.cursor() as cur:
            if not self.id:
                await cur.execute(
                    f"INSERT INTO {self._table_name}(author_id, text, created_at, updated_at) "
                    f"VALUES(%(author_id)s, %(text)s, now(), NULL)",
                    dict(
                        author_id=self.author_id,
                        text=self.text,
                    ))
                _id = cur.lastrowid
                self.id = _id
                await conn.commit()
            else:
                await cur.execute(
                    f"UPDATE {self._table_name} SET text = %(text)s, updated_at=now() "
                    f" WHERE id = %(id)s",
                    dict(
                        id=self.id,
                        text=self.text,
                    ))
                await conn.commit()
        return self.id

    @classmethod
    async def filter(cls, conn, filter: dict = None, limit=20, offset=0, fields: list = None):

        where_sql = ''
        where = []

        join_sql = ''
        joins = []

        if not fields:
            fields = cls._default_fields
        else:
            for field in fields.copy():
                if field == 'author__name':
                    from .user import User
                    joins.append(f' JOIN {User._table_name} author ON author.id = {cls._table_name}.author_id ')
                    fields.remove(field)
                    fields.append(" concat(author.firstname, ' ' , author.lastname) as author__name ")
                    continue
                assert hasattr(cls, field), f'unknown field: {field}'
        fields = [
            (f"{cls._table_name}.{field}" if field in cls._default_fields else field)
            for field in fields
        ]

        query_params = dict(limit=int(limit), offset=int(offset))

        if filter:
            for field, value in filter.items():
                if field == 'post_of_friends':
                    # join`им friend чтобы найти посты друзей current_user_id
                    joins.append(' JOIN friend f ON author_id = f.friend_id ')
                    field = 'f.user_id'
                else:
                    assert hasattr(cls, field), f'unknown field: {field} in filter'
                op = '='
                if isinstance(value, dict):
                    op = FILTER_OP[value['op']]
                    value = value['v']

                filter_name = make_param_name(query_params, f"{field}_filter")
                field = (f"{cls._table_name}.{field}" if field in cls._default_fields else field)
                where.append(f"{field} {op} %({filter_name})s")
                query_params[filter_name] = value

        if joins:
            join_sql = ''.join(joins)

        if where:
            where_sql = f"WHERE {' AND '.join(where)}"

        async with conn.cursor(aiomysql.SSDictCursor) as cur:

            await cur.execute(f"SELECT "
                              f"{','.join(fields)}"
                              f" FROM {cls._table_name} "
                              f" {join_sql} "
                              f" {where_sql} "
                              f" ORDER BY created_at DESC "
                              f" LIMIT %(limit)s OFFSET %(offset)s",
                              query_params)
            result = await cur.fetchall()
            return result or []
