import aiomysql


class Model:
    id = None
    _table_name = None
    _default_fields = ['id']

    @classmethod
    def from_dict(cls, adict):
        raise NotImplementedError()

    def to_dict(self):
        raise NotImplementedError()

    def __str__(self):
        return f'<{self.__class__.__name__} {self.id}>'

    @classmethod
    async def get_by_id(cls, _id, conn, fields: list = None):
        if not fields:
            fields = cls._default_fields
        else:
            for field in fields:
                assert hasattr(cls, field), f'unknown field: {field}'

        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"SELECT {','.join(fields)} FROM {cls._table_name} WHERE id = %(id)s",
                              dict(id=_id))
            result = await cur.fetchone()
            if not result:
                return None
            return cls.from_dict(result)


def make_param_name(existing_params, param):
    i = 1
    param_name = param
    while param_name in existing_params:
        param_name = f"{param}_{i}"
        i += 1

    return param_name


FILTER_OP = {
    'eq': '=',
    'ne': '!=',
    'lt': '<',
    'le': '<=',
    'gt': '>',
    'ge': '>=',
    'like': 'like'
}
