from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Dict

import aiohttp_jinja2
import aiohttp_session
import aiomysql
from aiohttp import web


class Model:
    pass

class User(Model):
    id = None
    username = None
    password = None
    firstname = None
    lastname = None
    sex = None
    city = None
    interest = None

    def __init__(self, uid, username, password, firstname=None, lastname=None, sex=None, city=None, interest=None):
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
            username=adict['username'],
            password=adict.get('password'),
            firstname=adict['firstname'],
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
    async def get_by_id(cls, uid, conn, fields: list=None):
        if not fields:
            fields = [
                'id',
                'username',
                # 'password',
                'firstname',
                'lastname',
                'sex',
                'city',
                'interest',
            ]
        else:
            for field in fields:
                assert hasattr(cls, field), f'unknown field: {field}'

        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(f"SELECT {','.join(fields)} FROM user WHERE id = %(uid)s",
                              dict(uid=uid))
            result = await cur.fetchone()
            return cls.from_dict(result)


_WebHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def require_login(func: _WebHandler) -> _WebHandler:
    func.__require_login__ = True  # type: ignore
    return func


async def username_ctx_processor(request: web.Request) -> Dict[str, Any]:
    # Jinja2 context processor
    session = await aiohttp_session.get_session(request)
    username = session.get("username")
    uid = session.get("uid")
    return {"username": username, "uid": uid}


@web.middleware
async def check_login(request: web.Request,
                      handler: _WebHandler) -> web.StreamResponse:
    require_login = getattr(handler, "__require_login__", False)
    session = await aiohttp_session.get_session(request)
    username = session.get("username")
    if require_login:
        if not username:
            location = request.app.router['login'].url_for().with_query(dict(next=str(request.rel_url)))
            raise web.HTTPSeeOther(location=location)
    return await handler(request)


async def validate_login(form, app):
    uid = None
    if not ('username' in form
        and 'password' in form):
        return uid, 'username and password required'
    pool: aiomysql.pool.Pool = app['db_pool']
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM user WHERE username = %(username)s and password = sha(%(password)s)",
                              dict(username=str(form['username']),
                                   password=str(form['password'])))

            print(cur.description)
            result = await cur.fetchone()
            if not result:
                return uid, 'wrong username and password combination'
            uid = result[0]
            return uid, ''


@aiohttp_jinja2.template('login.jinja2')
async def handle_login_get(request: web.Request):
    if 'next' in request.rel_url.query:
        return {'next': request.rel_url.query['next']}
    return {}


async def handle_login_post(request: web.Request):
    # return web.Response(text='OK', content_type="text/html")
    if request.method == 'POST':
        form = await request.post()
        uid, error = await validate_login(form, request.app)
        if error:
            response = aiohttp_jinja2.render_template('login.jinja2',
                                                      request,
                                                      {'error': error})
            response.headers['Content-Language'] = 'ru'
            return response
        else:
            # login form is valid
            # make session and set token
            session = await aiohttp_session.get_session(request)
            session["username"] = form["username"]
            session["uid"] = uid

            next_location = form.get('next')
            location = next_location or request.app.router['index'].url_for()
            response = web.HTTPSeeOther(location)
            response.cookies['test'] = '1'
            return response

    return web.HTTPFound(request.app.router['login'].url_for())


async def validate_register(form, app):
    uid = None

    required = [
        'username',
        'password',
        'psw-repeat',
        'firstname',
    ]
    if not (all(map(lambda x: x in form, required))):
        return uid, f"{', '.join(required[:-2])} and {required[-1]} required"

    if form['password'] != form['psw-repeat']:
        return uid, "wrong psw-repeat"

    pool: aiomysql.pool.Pool = app['db_pool']
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM user WHERE username = %(username)s",
                              dict(username=str(form['username'])))

            result = await cur.fetchone()
            if result:
                return uid, 'username already taken'

            await cur.execute(
                "INSERT INTO user(username, password, firstname, lastname, sex, city, interest) "
                "VALUES(%(username)s, sha(%(password)s), %(firstname)s, %(lastname)s, %(sex)s, %(city)s, %(interest)s)",
                dict(
                    username=form.get('username'),
                    password=form.get('password'),
                    firstname=form.get('firstname'),
                    lastname=form.get('lastname'),
                    sex=form.get('sex'),
                    city=form.get('city'),
                    interest=form.get('interest'),
                ))
            uid = cur.lastrowid
        await conn.commit()
    return uid, ''


@aiohttp_jinja2.template('register.jinja2')
async def handle_register(request: web.Request):
    data = await request.post()
    print(data)
    # return web.Response(text='OK', content_type="text/html")
    if request.method == 'POST':
        form = await request.post()
        uid, error = await validate_register(form, request.app)
        if error:
            return {'error': error}
        else:
            # login form is valid
            # make session
            session = await aiohttp_session.get_session(request)
            session["username"] = form["username"]
            session["uid"] = uid

            location = request.app.router['index'].url_for()
            raise web.HTTPFound(location=location)

    return {}
