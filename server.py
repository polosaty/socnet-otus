import asyncio
import base64
from collections import defaultdict
import logging
import os
from typing import Any, Dict
from urllib.parse import urlparse

import aio_pika
import aiofiles
import aiohttp
from aiohttp import web
import aiohttp_jinja2
import aiohttp_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import aiomysql
# import aiojaeger as az
import aiozipkin as az
import arq
import asynctnt
from cryptography import fernet
import jinja2

import api.user as api_user
from login import check_login
from login import handle_login_get
from login import handle_login_post
from login import handle_logout_post
from login import handle_register
from login import username_ctx_processor
from news import handle_news_ws
from news import hanlde_add_post
from news import hanlde_newspage
from news import listen_news_updates
from userlist import hanlde_add_friend
from userlist import hanlde_del_friend
from userlist import hanlde_userlist
from userpage import handle_chat
from userpage import handle_userpage

STATIC_DIR = 'static'
TEMPLATE_DIR = 'templates'


def handle_html(file_name):
    async def handle_file(_: web.BaseRequest):
        async with aiofiles.open(os.path.join(STATIC_DIR, file_name), mode="r") as file:
            file_content = await file.read()
        return web.Response(text=file_content, content_type="text/html")

    return handle_file


async def close_db_pool(dp_pool):
    dp_pool.close()
    await dp_pool.wait_closed()


@aiohttp_jinja2.template('index.jinja2')
async def handle_index(request):
    session = await aiohttp_session.get_session(request)
    if session.get('uid') is not None:
        raise web.HTTPFound(request.app.router['user_page'].url_for())

    return dict(session=session)


async def migrate_schema(pool):
    logging.debug('migrate schema')
    conn: aiomysql.connection.Connection
    async with pool.acquire() as conn:
        cur: aiomysql.cursors.Cursor
        async with conn.cursor() as cur:
            try:
                await cur.execute("SELECT * FROM post LIMIT 1")
                await cur.fetchone()
                logging.debug('migrate schema not needed')
            except Exception:
                with open("schema.sql") as f:
                    schema = f.read()
                    await cur.execute(schema)
                logging.debug('migrate schema finished')


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


def extract_tarantool_credentials(tar_url) -> Dict[str, Any]:
    parsed_url = urlparse(tar_url)
    return {
        "host": parsed_url.hostname,
        "port": parsed_url.port or 3301,
    }


async def make_app(host, port):
    app = web.Application()
    app['instance_id'] = os.getenv('INSTANCE_ID', '1')
    app['tasks'] = []

    jaeger_address = os.getenv('JAEGER_ADDRESS')
    if jaeger_address:
        endpoint = az.create_endpoint(f"social_net_server_{app['instance_id']}", ipv4=host, port=port)
        tracer = await az.create(jaeger_address, endpoint, sample_rate=1.0)

        trace_config = az.make_trace_config(tracer)
        app['client_session'] = aiohttp.ClientSession(trace_configs=[trace_config])
    else:
        app['client_session'] = aiohttp.ClientSession()

    async def close_session(app):
        await app["client_session"].close()

    app.on_cleanup.append(close_session)

    app.add_routes(
        [
            web.static('/static', STATIC_DIR),
            web.get("/", handle_index, name='index'),

            web.get("/login/", handle_login_get, name='login'),
            web.post("/login/", handle_login_post),
            web.get("/logout/", handle_logout_post),
            web.get("/register/", handle_register),
            web.post("/register/", handle_register),

            web.get("/userpage/", handle_userpage, name='user_page'),
            web.post("/chat/", handle_chat, name='chat_page'),
            web.get("/userpage/{uid}/", handle_userpage),
            web.get("/userlist/", hanlde_userlist),
            web.post("/add_friend/{uid}/", hanlde_add_friend),
            web.post("/del_friend/{uid}/", hanlde_del_friend),

            web.get("/newspage/", hanlde_newspage, name='news_page'),
            web.post("/add_post/", hanlde_add_post),
            web.view("/news_ws/", handle_news_ws),

            web.get('/api/user/', api_user.handle_user),
        ]
    )

    # secret_key must be 32 url-safe base64-encoded bytes
    fernet_key = os.getenv('FERNET_KEY', fernet.Fernet.generate_key())
    secret_key = base64.urlsafe_b64decode(fernet_key)
    aiohttp_session.setup(app, EncryptedCookieStorage(secret_key))
    logging.debug('fernet_key: %r secret_key: %r', fernet_key, secret_key)

    app.middlewares.append(check_login)

    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
        context_processors=[username_ctx_processor],
    )

    database_url = os.getenv('CLEARDB_DATABASE_URL', None) or os.getenv('DATABASE_URL', None)

    pool = await aiomysql.create_pool(
        **extract_database_credentials(database_url),
        maxsize=50,
        autocommit=True)

    app['db_pool'] = pool
    app.on_shutdown.append(lambda _app: close_db_pool(_app['db_pool']))

    databse_ro_url = os.getenv('DATABASE_RO_URL', None)
    if databse_ro_url:
        ro_pool = await aiomysql.create_pool(
            **extract_database_credentials(databse_ro_url),
            maxsize=50,
            autocommit=True)

        app['db_ro_pool'] = ro_pool
        app.on_shutdown.append(lambda _app: close_db_pool(_app['db_ro_pool']))
    else:
        logging.warning('DATABASE_RO_URL not set')
        app['db_ro_pool'] = pool

    redis_url = os.getenv('REDIS_URL', None)
    if redis_url:
        app['arq_pool'] = await arq.create_pool(arq.connections.RedisSettings.from_dsn(redis_url))

        async def close_arq_pool(_app):
            _app['arq_pool'].close()
            await _app['arq_pool'].wait_closed()

        app.on_shutdown.append(close_arq_pool)

    tarantool_url = os.getenv('TARANTOOL_URL', None)
    if tarantool_url:

        app['tnt'] = asynctnt.Connection(**extract_tarantool_credentials(tarantool_url))
        await app['tnt'].connect()
        app.on_shutdown.append(app['tnt'].disconnect)

    rabbit_url = os.getenv('CLOUDAMQP_URL', os.getenv('RABBIT_URL', None))
    if rabbit_url:
        connection: aio_pika.Connection = await aio_pika.connect_robust(rabbit_url)
        app['rabbit'] = connection  # await connection.channel()
        await start_background_task(app, listen_news_updates(app))

    app['news_subscribers'] = defaultdict(dict)

    app.on_shutdown.append(stop_tasks)

    if jaeger_address:
        az.setup(app, tracer)

    await migrate_schema(pool)
    return app


async def start_background_task(app, coro):
    app['tasks'].append(asyncio.create_task(coro))


async def stop_tasks(app):
    t: asyncio.Task
    for t in app['tasks']:
        t.cancel()

    await asyncio.gather(*app['tasks'])


async def run_app(port, host='0.0.0.0'):
    try:
        app = await make_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
    except asyncio.CancelledError as ex:
        logging.exception('run_app: %r', ex)
    except Exception as ex:
        logging.exception('run_app: %r', ex)


def main():
    logging.basicConfig(level=os.getenv('LOG_LEVEL', logging.DEBUG))
    port = int(os.getenv('PORT', 8080))
    host = '0.0.0.0'
    web.run_app(make_app(host, port), port=port)
    # asyncio.run(run_app(port=int(os.getenv('PORT', 8080))))


if __name__ == '__main__':
    main()
