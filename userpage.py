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
    current_user_uid = request.match_info.get('uid')
    # TODO: можно сделать страницы по логинам /userpage/<login>/
    # username = None
    # if uid and uid.isdigit():
    #     username = None
    # else:
    #     username = uid

    session = await aiohttp_session.get_session(request)
    uid = session["uid"]
    if not current_user_uid:
        current_user_uid = uid

    pool: aiomysql.pool.Pool = request.app['db_pool']

    async def get_friends(user):
        async with pool.acquire() as conn:
            return await user.get_friends(conn=conn)

    async def get_subscribers(user):
        async with pool.acquire() as conn:
            return await user.get_subscribers(conn=conn)

    async def get_user():
        async with pool.acquire() as conn:
            return await User.get_by_id(uid=current_user_uid, conn=conn)

    u = User(uid=current_user_uid)
    user, friends, subscribers = await asyncio.gather(
        get_user(),
        get_friends(user=u),
        get_subscribers(user=u)
    )
    return dict(current_user=user, session=session, friends=friends, subscribers=subscribers, uid=uid)
