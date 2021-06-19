import logging

from aiohttp import web
import aiohttp_jinja2
import aiohttp_session
import aiomysql

from login import require_login
from models.user import User

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

    if search and request.app.get('tnt'):
        tnt = request.app['tnt']
        res = await tnt.call(
            'search_with_friend_and_subscriber', [search, session['uid'], PAGE_SIZE + 1, offset])
        if res and res[0]:
            for row in res[0]:
                user_tuple = row[0]
                is_subscriber, is_friend = row[1]
                users.append(
                    {
                        'id': user_tuple[0],
                        'username': user_tuple[1],
                        'password': user_tuple[2],
                        'firstname': user_tuple[3],
                        'lastname': user_tuple[4],
                        'city': user_tuple[5],
                        'sex': user_tuple[6],
                        'interest': user_tuple[7],
                        'is_subscriber': is_subscriber,
                        'is_friend': is_friend,
                    }
                )
            logging.debug('users from tarantool: %r', len(users))

    else:
        pool: aiomysql.pool.Pool = request.app['db_ro_pool']
        async with pool.acquire() as conn:
            users = await User.filter(
                filter=filter,
                # fields=['id', 'firstname', 'lastname'],
                fields=['id', 'username', 'password', 'firstname', 'lastname', 'city', 'sex', 'interest'],
                limit=PAGE_SIZE + 1, offset=offset, conn=conn,
                current_user_id=session['uid']) or []

            logging.debug('users from mysql: %r', len(users))

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

    if request.app.get('arq_pool'):
        await request.app['arq_pool'].enqueue_job('build_news_cache', user_id=session['uid'], force=True)

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

    if request.app.get('arq_pool'):
        await request.app['arq_pool'].enqueue_job('build_news_cache', user_id=session['uid'], force=True)

    location = request.headers.get('Referer', '/userlist/')
    return web.HTTPFound(location=location)
