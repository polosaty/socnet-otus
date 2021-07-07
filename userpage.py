import asyncio
import os
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse

from aiohttp import web
import aiohttp_jinja2
import aiohttp_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import aiomysql

from login import require_login
from models.post import Post
from models.user import User


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

    pool: aiomysql.pool.Pool = request.app['db_ro_pool']

    async def get_friends(user):
        async with pool.acquire() as conn:
            return await user.get_friends(conn=conn)

    async def get_subscribers(user):
        async with pool.acquire() as conn:
            return await user.get_subscribers(conn=conn)

    async def get_user():
        async with pool.acquire() as conn:
            return await User.get_by_id(uid=current_user_uid, conn=conn)

    async def get_posts(user):
        async with pool.acquire() as conn:
            return await Post.filter(filter=dict(author_id=user.id), conn=conn)

    u = User(uid=current_user_uid)
    user, friends, subscribers, posts = await asyncio.gather(
        get_user(),
        get_friends(user=u),
        get_subscribers(user=u),
        get_posts(user=u)
    )
    return dict(current_user=user, session=session, friends=friends,
                subscribers=subscribers, posts=posts, uid=uid,
                chat_url=os.getenv('CHAT_URL'))


def update_url(url, params):
    url_parse = urlparse(url)
    query = url_parse.query
    url_dict = dict(parse_qsl(query))
    url_dict.update(params)
    url_new_query = urlencode(url_dict)
    url_parse = url_parse._replace(query=url_new_query)
    new_url = urlunparse(url_parse)
    return new_url


@require_login
@aiohttp_jinja2.template('chat.jinja2')
async def handle_chat(request: web.Request):
    chat_url = os.getenv('CHAT_URL')
    if not chat_url:
        raise web.HTTPBadRequest(reason='CHAT_URL env not set')
        # location = request.headers.get('Referer', '/userlist/')
        # raise web.HTTPFound(location=location)

    session = await aiohttp_session.get_session(request)
    uid = session["uid"]

    form = await request.post()
    friend_id = form.get('user_id')

    pool: aiomysql.pool.Pool = request.app['db_pool']
    conn: aiomysql.Connection
    async with pool.acquire() as conn:
        cur: aiomysql.cursors.DictCursor
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                'SELECT chat_id FROM chat_user cu WHERE user_id = %(friend_id)s '
                ' AND EXISTS(select 1 from chat_user WHERE user_id = %(uid)s '
                ' AND chat_id = cu.chat_id) '
                ' ORDER BY chat_id desc LIMIT 1',
                dict(
                    friend_id=friend_id,
                    uid=uid
                )
            )
            chat_row = await cur.fetchone()
            if chat_row:
                chat_id = chat_row['chat_id']
            else:
                # smallest_shard_id get by max(chat_message.id) from shards
                await cur.execute("select id from shard order by size limit 1")
                smallest_shard_id = (await cur.fetchone())['id']

                await conn.begin()
                await cur.execute(
                    "INSERT INTO chat (`type`, `key`) VALUES ('peer2peer', uuid()); "
                )
                chat_id = cur.lastrowid
                await cur.execute(
                    "INSERT INTO chat_user (user_id, chat_id) "
                    " VALUES  (%(friend_id)s, %(chat_id)s), (%(uid)s, %(chat_id)s);",
                    dict(
                        friend_id=friend_id,
                        uid=uid,
                        chat_id=chat_id
                    )
                )
                await cur.execute(
                    "INSERT INTO chat_shard (chat_id, shard_id, `read`, `write`) "
                    "VALUES  (%(chat_id)s, %(shard_id)s, 1, 1);",
                    dict(
                        shard_id=smallest_shard_id,
                        chat_id=chat_id
                    )
                )
                await conn.commit()

            await cur.execute("SELECT `key` FROM chat WHERE id = %(chat_id)s", dict(chat_id=chat_id))
            chat_key = (await cur.fetchone())['key']

    storage: EncryptedCookieStorage = request.get(aiohttp_session.STORAGE_KEY)
    chat_session = storage.load_cookie(request)

    new_chat_url = update_url(chat_url, dict(
        chat_key=chat_key,
        session=chat_session,
        userId=uid
    ))

    return dict(uid=uid, chat_url=new_chat_url)
