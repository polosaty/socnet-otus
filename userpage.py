import asyncio
import logging
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
import aiozipkin as az

from login import require_login
from models.post import Post
from models.user import User

logger = logging.getLogger(__name__)


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


async def chat_api_get_key(session, user_id, friend_id):
    chat_rest_url = os.getenv('CHAT_REST_URL') + 'make_chat/'
    if not chat_rest_url:
        return None

    # async with aiohttp.ClientSession() as session:
    resp = await session.post(chat_rest_url,
                              json={'user_id': user_id,
                                    'friend_id': friend_id})
    logger.debug('Chat rest response: %r', resp.status)
    res = await resp.json()
    return res.get('chat_key')


@require_login
@aiohttp_jinja2.template('chat.jinja2')
async def handle_chat(request: web.Request):
    chat_url = os.getenv('CHAT_URL')
    if not chat_url:
        raise web.HTTPBadRequest(reason='CHAT_URL env not set')

    session = await aiohttp_session.get_session(request)
    uid = session["uid"]

    form = await request.post()
    friend_id = form.get('user_id')
    client_session = request.app['client_session']
    tracer = az.get_tracer(request.app)
    span = az.request_span(request)
    with tracer.new_child(span.context) as child_span:
        child_span.name("chat_api_get_key")
        child_span.tag('user_id', uid)
        child_span.tag('friend_id', friend_id)
        chat_key = await chat_api_get_key(client_session, user_id=uid, friend_id=friend_id)
        child_span.tag('chat_key', chat_key)

    storage: EncryptedCookieStorage = request.get(aiohttp_session.STORAGE_KEY)
    chat_session = storage.load_cookie(request)

    new_chat_url = update_url(chat_url, dict(
        chat_key=chat_key,
        session=chat_session,
        userId=uid
    ))

    return dict(uid=uid, chat_url=new_chat_url)
