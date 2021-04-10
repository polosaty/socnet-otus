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

    async def get_friends(user):
        async with pool.acquire() as conn:
            return await user.get_friends(conn=conn)

    async def get_subscribers(user):
        async with pool.acquire() as conn:
            return await user.get_subscribers(conn=conn)

    async def get_user():
        async with pool.acquire() as conn:
            return await User.get_by_id(uid=uid, conn=conn)

    u = User(uid=uid)
    user, friends, subscribers = await asyncio.gather(
        get_user(),
        get_friends(user=u),
        get_subscribers(user=u)
    )
    return dict(current_user=user, session=session, friends=friends, subscribers=subscribers)
