import asyncio
import datetime
import json
import logging
import os

import aio_pika
import aiomysql
import arq

from models.friend import Friend
from models.post import Post
from server import close_db_pool
from server import extract_database_credentials
from utils import default

# NEWS_CACHE_SIZE = 1000
NEWS_CACHE_SIZE = 3
NEWS_CACHE_TTL = 300
NEWS_CACHE_SUBSCRIBERS_LIMIT = 20


async def build_news_cache(ctx, user_id, force=False):
    logging.debug(f'build_cache user_id={user_id}...')
    pool: aiomysql.pool.Pool = ctx['db_ro_pool']
    redis = ctx['arq_pool']
    key = f'news:{user_id}'
    if not force and await redis.llen(key):
        return 'build_cache skiped'

    async with pool.acquire() as conn:
        posts = await Post.filter(
            conn=conn, filter=dict(post_of_friends=user_id),
            fields=['author__name', 'id', 'author_id', 'text', 'created_at', 'updated_at'], limit=NEWS_CACHE_SIZE)
        pipe = redis.pipeline()

        pipe.delete(key)
        for post in posts:
            post_json = json.dumps(post, default=default)
            pipe.rpush(key, post_json)

        pipe.ltrim(key, 0, NEWS_CACHE_SIZE - 1)
        pipe.expire(key, NEWS_CACHE_TTL)
        await pipe.execute()

    return 'build_cache done'


async def send_post_to_subscriber(ctx, post, subscriber_id):
    logging.debug('send_post_to_subscriber %r %r', post, subscriber_id)
    rabbit: aio_pika.Connection = ctx.get('rabbit')
    redis: arq.ArqRedis = ctx['arq_pool']
    if not rabbit:
        return

    for instance_id in await redis.smembers(f'news:{subscriber_id}:instances'):
        channel = await rabbit.channel()
        exchange = await channel.get_exchange('news')
        msg: aio_pika.Message = aio_pika.Message(
            body=json.dumps(dict(post, subscriber_id=subscriber_id), default=default).encode(),
            content_type='application/json')
        await exchange.publish(msg, routing_key=instance_id)
        logging.debug('publish post %r to ex: %r with routing_key: %r', post, exchange, instance_id)


async def add_post_to_cache(ctx, post_id):
    logging.debug(f'add_post_to_cache post_id={post_id}...')
    pool: aiomysql.pool.Pool = ctx['db_pool']
    async with pool.acquire() as conn:
        post: dict = (await Post.filter(
            filter={'id': post_id}, conn=conn,
            fields=['author__name', 'id', 'author_id', 'text', 'created_at', 'updated_at']))[0]
        post_json = json.dumps(post, default=default)
        redis = ctx['arq_pool']
        for subscriber in await Friend.filter(
                conn=conn,
                filter=dict(friend_id=post['author_id']),
                fields=['user_id'], limit=NEWS_CACHE_SUBSCRIBERS_LIMIT):
            pipe = redis.pipeline()
            key = f'news:{subscriber["user_id"]}'
            if await redis.llen(key):
                pipe.lpush(key, post_json)

                pipe.ltrim(key, 0, NEWS_CACHE_SIZE - 1)
                pipe.expire(key, NEWS_CACHE_TTL)
                await pipe.execute()
            else:
                await build_news_cache(ctx, subscriber["user_id"])

            await send_post_to_subscriber(ctx, post, subscriber_id=subscriber["user_id"])
    return 'add_post_to_cache done'


async def startup(ctx):
    logging.basicConfig(level=logging.DEBUG)
    database_url = os.getenv('CLEARDB_DATABASE_URL', None) or os.getenv('DATABASE_URL', None)
    pool = await aiomysql.create_pool(
        **extract_database_credentials(database_url),
        maxsize=50,
        autocommit=True)
    ctx['db_pool'] = pool

    databse_ro_url = os.getenv('DATABASE_RO_URL', None)
    if databse_ro_url:
        ro_pool = await aiomysql.create_pool(
            **extract_database_credentials(databse_ro_url),
            maxsize=50,
            autocommit=True)

        ctx['db_ro_pool'] = ro_pool
    else:
        logging.warning('DATABASE_RO_URL not set')
        ctx['db_ro_pool'] = pool

    redis_url = os.getenv('REDIS_URL', None)
    if redis_url:
        ctx['arq_pool'] = await arq.create_pool(arq.connections.RedisSettings.from_dsn(redis_url))

    rabbit_url = os.getenv('CLOUDAMQP_URL', os.getenv('RABBIT_URL', None))
    if rabbit_url:
        connection: aio_pika.Connection = await aio_pika.connect_robust(rabbit_url)
        ctx['rabbit'] = connection
        # async with connection:  closes connection
        channel = await connection.channel()
        await channel.declare_exchange("news", durable=True)


async def shutdown(ctx):

    if ctx['db_pool'] == ctx['db_ro_pool']:
        await close_db_pool(ctx['db_ro_pool'])
    await close_db_pool(ctx['db_pool'])

    if ctx.get('rabbit'):
        await ctx['rabbit'].close()


class WorkerSettings:
    functions = [build_news_cache, add_post_to_cache]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = arq.connections.RedisSettings.from_dsn(os.getenv('REDIS_URL', None))


async def main():
    redis_url = os.getenv('REDIS_URL', None)
    arq_pool = await arq.create_pool(arq.connections.RedisSettings.from_dsn(redis_url))
    user_id = os.getenv('USER_ID', 1001004)
    await arq_pool.enqueue_job('build_news_cache', user_id)
    arq_pool.close()


if __name__ == '__main__':
    logging.basicConfig(level=os.getenv('LOG_LEVEL', logging.DEBUG))
    asyncio.run(main())
