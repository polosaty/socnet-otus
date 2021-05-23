from typing import Any, Awaitable, Callable, Dict

from aiohttp import web
import aiohttp_jinja2
import aiohttp_session
import aiomysql

from models.user import User

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
    is_require_login = getattr(handler, "__require_login__", False)
    session = await aiohttp_session.get_session(request)
    username = session.get("username")
    if is_require_login:
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

        user = await User.get_by_username_and_password(form['username'], form['password'], conn, fields=['id'])
        if not user:
            return uid, 'wrong username and password combination'
        uid = user.id
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

            if request.app.get('arq_pool'):
                await request.app['arq_pool'].enqueue_job('build_news_cache', user_id=uid)

            next_location = form.get('next')
            location = next_location or request.app.router['index'].url_for()
            response = web.HTTPSeeOther(location)

            return response

    return web.HTTPFound(request.app.router['login'].url_for())


async def handle_logout_post(request: web.Request):
    session = await aiohttp_session.get_session(request)
    session["username"] = None
    session["uid"] = None
    location = request.app.router['index'].url_for()
    return web.HTTPSeeOther(location)


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

        result = await User.get_by_username(username=form['username'], fields=['id'], conn=conn)
        if result:
            return uid, 'username already taken'

        uid = await User.from_dict(dict(form, id=None)).save(conn=conn)

    return uid, ''


@aiohttp_jinja2.template('register.jinja2')
async def handle_register(request: web.Request):
    data = await request.post()

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
