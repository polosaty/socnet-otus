import asyncio
from functools import partial
import json
import logging

import aio_pika
import aiohttp
from aiohttp import web
import aiohttp_jinja2
import aiohttp_session
import aiomysql
import arq

from login import require_login
from models.post import Post
from utils import default

logger = logging.getLogger('news')


@require_login
@aiohttp_jinja2.template('newspage.jinja2')
async def hanlde_newspage(request: web.Request):
    session = await aiohttp_session.get_session(request)
    uid = session["uid"]

    posts = []
    redis = request.app.get("arq_pool")
    if redis:
        key = f'news:{uid}'
        posts_jsons = await redis.lrange(key, 0, -1)
        posts = list(map(json.loads, posts_jsons))
        logging.debug('posts from cache: %r', posts)
    if not posts:
        pool: aiomysql.pool.Pool = request.app['db_ro_pool']
        async with pool.acquire() as conn:
            posts = await Post.filter(
                conn=conn, filter=dict(post_of_friends=uid),
                fields=['author__name', 'id', 'author_id', 'text', 'created_at', 'updated_at'])

    return dict(posts=posts, session=session)


@require_login
async def hanlde_add_post(request: web.Request):
    session = await aiohttp_session.get_session(request)
    form = await request.post()
    pool: aiomysql.pool.Pool = request.app['db_pool']
    async with pool.acquire() as conn:
        post_id = await Post(author_id=session['uid'], text=form["text"]).save(conn)
        await conn.commit()
        arq_pool: arq.ArqRedis = request.app['arq_pool']
        await arq_pool.enqueue_job('add_post_to_cache', post_id)
    location = request.headers.get('Referer', '/userpage/')
    return web.HTTPFound(location=location)


@require_login
async def handle_news_ws(request: web.Request):
    session = await aiohttp_session.get_session(request)
    uid = session["uid"]
    logger.debug('Websocket connection starting uid: %r', uid)
    ws = aiohttp.web.WebSocketResponse(protocols=['jsonp'])
    await ws.prepare(request)
    logger.debug('Websocket connection ready uid: %r', uid)
    app = request.app
    sid = request.headers['Sec-WebSocket-Key']  # TODO: generate uniq session
    app['news_subscribers'][uid][sid] = ws

    await set_subscriber(uid, sid, app)
    try:
        msg: aiohttp.WSMessage
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                logger.debug('%r %r %r', uid, sid, msg.data)
                if msg.data == 'close':
                    await ws.close()
                else:
                    # await ws.send_str()
                    jmsg = json.loads(msg.data)
                    await ws.send_json({'request': jmsg, 'sid': sid})
                    if jmsg.get('type') == 'ping':
                        await set_subscriber(uid, sid, app)

    finally:
        await delete_subscriber(uid, sid, app)

    logger.debug('Websocket connection closed uid: %r', uid)
    return ws


def get_subscriber_instances_key(uid, sid, topic='news'):
    return f'{topic}:{uid}:instances'


async def set_subscriber(uid, sid, app, ttl=5):
    redis: arq.ArqRedis = app.get('arq_pool')
    subscriber_key = get_subscriber_instances_key(uid, sid)
    if redis:
        await redis.sadd(subscriber_key, app['instance_id'])
        await redis.expire(subscriber_key, ttl)


async def delete_subscriber(uid, sid, app):
    redis: arq.ArqRedis = app.get('arq_pool')
    subscriber_key = get_subscriber_instances_key(uid, sid)

    sessions_dict = app['news_subscribers'].get(uid)
    if sessions_dict:
        sessions_dict.pop(sid, None)
    if not sessions_dict:
        app['news_subscribers'].pop(uid, None)

    if redis:
        try:
            await redis.srem(subscriber_key, app['instance_id'])
        except Exception as ex:
            logger.exception('redis.srem %r', ex)

async def listen_news_updates(app):
    rabbit: aio_pika.Connection = app.get('rabbit')
    if not rabbit:
        return

    exchange_name = 'news'
    logger.debug('listen_news_updates: started')
    while True:
        try:
            channel: aio_pika.Channel = await rabbit.channel()
            # await channel.declare_exchange("news", durable=True)
            # Declaring queue
            queue_name = f"news_q_{app['instance_id']}"
            queue = await channel.declare_queue(queue_name, auto_delete=True)
            await queue.bind(exchange=exchange_name,
                             routing_key=app['instance_id'])

            async with queue.iterator() as queue_iter:
                message: aio_pika.IncomingMessage
                async for message in queue_iter:
                    async with message.process():
                        logger.debug('listen_news_updates: message: %r', message.body)
                        if message.content_type != 'application/json':
                            continue
                        post = json.loads(message.body)
                        if not post:
                            continue
                        subscriber_id = post.get('subscriber_id')
                        if not subscriber_id:
                            continue

                        for sid, ws in app['news_subscribers'].get(subscriber_id, {}).items():
                            logger.debug('send message to websocket %r %r', ws, sid)
                            try:
                                await ws.send_json({'type': 'posts', 'data': [post]})
                            except ConnectionResetError:
                                logger.debug('Outdated connection %r', sid)
        except asyncio.CancelledError:
            break
        except Exception as ex:
            logger.error('listen_news_updates: %r', ex)
