from aiohttp import web
import aiohttp_jinja2
import aiohttp_session
import aiomysql

from login import require_login
from models import User

PAGE_SIZE = 20


@aiohttp_jinja2.template('userlist.jinja2')
@require_login
async def hanlde_userlist(request: web.Request):
    session = await aiohttp_session.get_session(request)

    offset = int(request.rel_url.query.get('offset', 0))
    search = request.rel_url.query.get('search', '')
    filter = None
    if search:
        filter = {
            'firstname': {'op': 'like', 'v': f"{search}%"},
            'lastname': {'op': 'like', 'v': f"{search}%"}
        }
    users = []
    # pool: aiomysql.pool.Pool = request.app['db_pool']
    pool: aiomysql.pool.Pool = request.app['db_ro_pool']
    async with pool.acquire() as conn:
        users = await User.get_by_limit(
            filter=filter,
            fields=['id', 'firstname', 'lastname'],
            limit=PAGE_SIZE + 1, offset=offset, conn=conn,
            current_user_id=session['uid']) or []

    return dict(users=users[:PAGE_SIZE],
                offset=offset,
                limit=PAGE_SIZE,
                session=session,
                last_page=len(users) <= PAGE_SIZE,
                search=search,
                )


@require_login
async def hanlde_add_friend(request: web.Request):
    session = await aiohttp_session.get_session(request)
    friend_id = request.match_info.get('uid')
    pool: aiomysql.pool.Pool = request.app['db_pool']
    async with pool.acquire() as conn:
        await User(uid=session['uid']).add_friend(friend_id=friend_id, conn=conn)
        await conn.commit()
    location = request.headers.get('Referer', '/userlist/')
    return web.HTTPFound(location=location)


@require_login
async def hanlde_del_friend(request: web.Request):
    session = await aiohttp_session.get_session(request)
    friend_id = request.match_info.get('uid')
    pool: aiomysql.pool.Pool = request.app['db_pool']
    async with pool.acquire() as conn:
        await User(uid=session['uid']).del_friend(friend_id=friend_id, conn=conn)
        await conn.commit()
    location = request.headers.get('Referer', '/userlist/')
    return web.HTTPFound(location=location)
