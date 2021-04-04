import base64
import os

import aiohttp_jinja2
import jinja2
from cryptography import fernet
import aiomysql
from aiohttp import web
import aiofiles
from aiohttp_session import setup, get_session, session_middleware
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from login import handle_auth
from login import handle_register
import logging


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


async def make_app():
    app = web.Application()
    # secret_key must be 32 url-safe base64-encoded bytes
    fernet_key = fernet.Fernet.generate_key()
    secret_key = base64.urlsafe_b64decode(fernet_key)
    setup(app, EncryptedCookieStorage(secret_key))
    app.add_routes(
        [
            web.get("/", handle_html('index.html'), name='index'),
            # web.get("/login/", web('index.html')),
            web.post("/login/", handle_auth),
            # web.get("/register/", handle_html('register.jinja2')),
            web.get("/register/", handle_register),
            web.post("/register/", handle_register),
        ]
    )
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(TEMPLATE_DIR))

    pool = await aiomysql.create_pool(host='db', port=3306,
                                      user='root', password='password',
                                      db='socnet')
    app['db_pool'] = pool
    app.on_shutdown.append(shutdown)
    return app


def main():
    logging.basicConfig(level=logging.DEBUG)
    web.run_app(make_app(), port=8080)


if __name__ == '__main__':
    main()
