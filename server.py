import base64
import logging
import os
from typing import Any, Dict
from urllib.parse import urlparse

import aiofiles
from aiohttp import web
import aiohttp_jinja2
import aiohttp_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import aiomysql
from cryptography import fernet
import jinja2

import api.user as api_user
from login import check_login
from login import handle_login_get
from login import handle_login_post
from login import handle_logout_post
from login import handle_register
from login import username_ctx_processor
from userlist import hanlde_add_friend
from userlist import hanlde_del_friend
from userlist import hanlde_userlist
from userpage import handle_userpage

STATIC_DIR = 'static'
TEMPLATE_DIR = 'templates'


def handle_html(file_name):
    async def handle_file(_: web.BaseRequest):
        async with aiofiles.open(os.path.join(STATIC_DIR, file_name), mode="r") as file:
            file_content = await file.read()
        return web.Response(text=file_content, content_type="text/html")

    return handle_file


async def shutdown(app):
    db_pool = app['db_pool']
    if db_pool:
        db_pool.close()
        await app['db_pool'].wait_closed()


async def test_cookie(request):
    response = web.HTTPSeeOther('/')
    response.cookies['test'] = '1'
    return response


@aiohttp_jinja2.template('index.jinja2')
async def handle_index(request):
    session = await aiohttp_session.get_session(request)
    if session.get('uid') is not None:
        raise web.HTTPFound(request.app.router['user_page'].url_for())

    return dict(session=session)


async def migrate_schema(pool):
    conn: aiomysql.connection.Connection
    async with pool.acquire() as conn:
        cur: aiomysql.cursors.Cursor
        async with conn.cursor() as cur:
            try:
                await cur.execute("SELECT * FROM user LIMIT 1")
                await cur.fetchone()
            except Exception:
                with open("schema.sql") as f:
                    schema = f.read()
                    await cur.execute(schema)


def extract_database_credentials(database_url) -> Dict[str, Any]:
    """Extract database credentials from the database URL.
    :return: database credentials
    :rtype: Dict[str, Any]
    """
    parsed_url = urlparse(database_url)
    return {
        "host": parsed_url.hostname,
        "port": parsed_url.port or 3306,
        "user": parsed_url.username,
        "password": parsed_url.password,
        "db": parsed_url.path[1:],
    }


async def make_app():
    app = web.Application()

    app.add_routes(
        [
            web.static('/static', STATIC_DIR),
            web.get("/", handle_index, name='index'),
            web.get("/login/", handle_login_get, name='login'),
            web.post("/login/", handle_login_post),
            web.get("/logout/", handle_logout_post),
            # web.get("/test_cookie/", test_cookie),
            # web.get("/register/", handle_html('register.jinja2')),
            web.get("/register/", handle_register),
            web.post("/register/", handle_register),
            web.get("/userpage/", handle_userpage, name='user_page'),
            web.get("/userpage/{uid}/", handle_userpage),
            web.get("/userlist/", hanlde_userlist),
            web.post("/add_friend/{uid}/", hanlde_add_friend),
            web.post("/del_friend/{uid}/", hanlde_del_friend),

            web.get('/api/user/', api_user.handle_user)
        ]
    )

    # secret_key must be 32 url-safe base64-encoded bytes
    fernet_key = fernet.Fernet.generate_key()
    secret_key = base64.urlsafe_b64decode(fernet_key)
    aiohttp_session.setup(app, EncryptedCookieStorage(secret_key))
    logging.debug('fernet_key: %r secret_key: %r', fernet_key, secret_key)
    # aiohttp_session.setup(app, aiohttp_session.SimpleCookieStorage())
    app.middlewares.append(check_login)

    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
        context_processors=[username_ctx_processor],
    )

    databse_url = os.getenv('CLEARDB_DATABASE_URL', None)
    if databse_url:
        db_credentials = extract_database_credentials(databse_url)
    else:
        db_credentials = dict(
            host=os.environ.get('DATABASE_HOST', 'db'),
            port=int(os.environ.get('DATABASE_PORT', 3306)),
            user=os.environ.get('DATABASE_USER', 'root'),
            password=os.environ.get('DATABASE_PASSWORD', 'password'),
            db=os.environ.get('DATABASE_DB', 'socnet'))

    pool = await aiomysql.create_pool(
        **db_credentials,
        autocommit=True)

    app['db_pool'] = pool

    await migrate_schema(pool)

    app.on_shutdown.append(shutdown)
    return app


def main():
    logging.basicConfig(level=logging.DEBUG)
    web.run_app(make_app(), port=int(os.getenv('PORT', 8080)))


if __name__ == '__main__':
    main()
