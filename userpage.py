import asyncio

from aiohttp import web
import aiohttp_jinja2
import aiohttp_session
import aiomysql

from login import require_login
from models import User


@require_login
@aiohttp_jinja2.template('userpage.jinja2')
async def handle_userpage(request: web.Request):
    uid = request.match_info.get('uid')
    session = await aiohttp_session.get_session(request)
    if not uid:
        uid = session["uid"]

    pool: aiomysql.pool.Pool = request.app['db_pool']
    async with pool.acquire() as conn1, pool.acquire() as conn2, pool.acquire() as conn3:

        u = User(uid=uid)
        user, friends, subscribers = await asyncio.gather(
            User.get_by_id(uid=uid, conn=conn1),
            u.get_friends(conn=conn2),
            u.get_subscribers(conn=conn3)
        )
    return dict(current_user=user, session=session, friends=friends, subscribers=subscribers)
