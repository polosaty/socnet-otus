import aiomysql

from .base import FILTER_OP
from .base import make_param_name
from .base import Model


class User(Model):
    _table_name = 'user'

    id = None
    username = None
    password = None
    firstname = None
    lastname = None
    sex = None
    city = None
    interest = None

    # TODO: metaclass
    _default_fields = [
        'id', 'username',
        # 'password',
        'firstname', 'lastname', 'sex', 'city', 'interest', ]

    def __str__(self):
        return f'<User {self.id}>'

    def __init__(self, uid, username=None, password=None, firstname=None,
                 lastname=None, sex=None, city=None, interest=None):
        self.id = uid
        self.username = username
        self.password = password
        self.firstname = firstname
        self.lastname = lastname
        self.sex = sex
        self.city = city
        self.interest = interest

    @classmethod
    def from_dict(cls, adict):
        return User(
            uid=adict['id'],
            username=adict.get('username'),
            password=adict.get('password'),
            firstname=adict.get('firstname'),
            lastname=adict.get('lastname'),
            sex=adict.get('sex'),
            city=adict.get('city'),
            interest=adict.get('interest'),
        )

    def to_dict(self):
        return dict(
            uid=self.id,
            username=self.username,
            password=self.password,
            firstname=self.firstname,
            lastname=self.lastname,
            sex=self.sex,
            city=self.city,
            interest=self.interest,
        )

    @classmethod
    def get_by_id(cls, uid, conn, fields: list = None):
        return super(User, cls).get_by_id(uid, conn, fields)

    async def save(self, conn):
        async with conn.cursor() as cur:
            if not self.id:
                await cur.execute(
                    f"INSERT INTO {self._table_name}(username, password, firstname, lastname, sex, city, interest) "
                    f"VALUES(%(username)s, sha(%(password)s), %(firstname)s, %(lastname)s, "
                    f"%(sex)s, %(city)s, %(interest)s)",
                    dict(
                        username=self.username,
                        password=self.password,
                        firstname=self.firstname,
                        lastname=self.lastname,
                        sex=self.sex,
                        city=self.city,
                        interest=self.interest,
                    ))
                uid = cur.lastrowid
                self.id = uid
                await conn.commit()
            else:
                # TODO: update
                raise NotImplementedError()
        return self.id

    @classmethod
    async def get_by_username(cls, username, conn, fields: list = None):
        if not fields:
            fields = cls._default_fields
        else:
            for field in fields:
                assert hasattr(cls, field), f'unknown field: {field}'

        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"SELECT {','.join(fields)} FROM user WHERE username = %(username)s",
                              dict(username=str(username)))
            result = await cur.fetchone()
            if not result:
                return None
            return cls.from_dict(result)

    @classmethod
    async def get_by_username_and_password(cls, username, password, conn, fields: list = None):
        if not fields:
            fields = cls._default_fields
        else:
            for field in fields:  # TODO можно сломать если скормить к примеру _default_fields или __init__ и т.п.
                assert hasattr(cls, field), f'unknown field: {field}'

        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"SELECT {','.join(fields)} FROM user "
                              f"WHERE username = %(username)s and password = sha(%(password)s)",
                              dict(username=str(username),
                                   password=str(password)))
            result = await cur.fetchone()
            if not result:
                return None
            return cls.from_dict(result)

    @classmethod
    async def filter(cls, conn, current_user_id: int = None,
                     filter: dict = None, limit=20, offset=0, fields: list = None):
        if not fields:
            fields = cls._default_fields
        else:
            for field in fields:
                assert hasattr(cls, field), f'unknown field: {field}'

        query_params = dict(limit=int(limit), offset=int(offset))

        is_friend_subquery = ''
        where_sql = ''
        where = []
        if current_user_id is not None:
            is_friend_subquery = (
                ', EXISTS(SELECT 1 FROM friend f '
                'WHERE user.id = f.user_id AND f.friend_id = %(current_user_id)s ) is_subscriber '
                ', EXISTS(SELECT 1 FROM friend f '
                'WHERE user.id = f.friend_id AND f.user_id = %(current_user_id)s ) is_friend '
            )
            where.append('id != %(current_user_id)s')
            query_params['current_user_id'] = current_user_id

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
                              f"{is_friend_subquery}"
                              f" FROM {cls._table_name} "
                              f" {where_sql} "
                              f" ORDER BY lastname, firstname, id "
                              f"LIMIT %(limit)s OFFSET %(offset)s",
                              query_params)
            result = await cur.fetchall()
            if not result:
                return None

            return result

    async def add_friend(self, friend_id, conn):
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO friend(user_id, friend_id) "
                              "VALUES(%(uid)s, %(friend_id)s)",
                              dict(uid=self.id, friend_id=friend_id))
            inserted_rec_id = cur.lastrowid
            return inserted_rec_id

    async def del_friend(self, friend_id, conn):
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM friend "
                              "WHERE user_id=%(uid)s and friend_id=%(friend_id)s",
                              dict(uid=self.id, friend_id=friend_id))
            deleted_rows = cur.rowcount
            return deleted_rows

    async def get_friends(self, conn, fields=None, offset=0, limit=20):
        if not fields:
            fields = self._default_fields
        else:
            for field in fields:
                assert hasattr(self, field), f'unknown field: {field}'

        query_params = dict(limit=int(limit), offset=int(offset))
        query_params['current_user_id'] = self.id

        async with conn.cursor(aiomysql.DictCursor) as cur:
            fields = map(lambda field: f'u.{field}', fields)
            await cur.execute(f"SELECT {','.join(fields)} "
                              f"FROM user u "
                              f"JOIN friend f on u.id = f.friend_id "
                              f"WHERE f.user_id = %(current_user_id)s "
                              f" AND u.id != %(current_user_id)s "
                              f" ORDER BY firstname, id "
                              f"LIMIT %(limit)s OFFSET %(offset)s",
                              query_params)
            result = await cur.fetchall()
            if not result:
                return None
            # return [self.from_dict(user) for user in result]
            return result

    async def get_subscribers(self, conn, fields=None, offset=0, limit=20):
        if not fields:
            fields = self._default_fields
        else:
            for field in fields:
                assert hasattr(self, field), f'unknown field: {field}'

        query_params = dict(limit=int(limit), offset=int(offset))
        query_params['current_user_id'] = self.id

        async with conn.cursor(aiomysql.DictCursor) as cur:
            fields = map(lambda field: f'u.{field}', fields)
            await cur.execute(f"SELECT {','.join(fields)} "
                              f"FROM user u "
                              f"JOIN friend s on u.id = s.user_id "
                              f"WHERE s.friend_id = %(current_user_id)s "
                              f" AND u.id != %(current_user_id)s "
                              f" AND NOT EXISTS(SELECT 1 FROM friend f "
                              f"                WHERE u.id = f.friend_id "
                              f"                      AND f.user_id = %(current_user_id)s ) "
                              f" ORDER BY firstname, id "
                              f"LIMIT %(limit)s OFFSET %(offset)s",
                              query_params)
            result = await cur.fetchall()
            if not result:
                return None
            # return [self.from_dict(user) for user in result]
            return result
