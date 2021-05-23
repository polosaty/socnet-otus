import asyncio
import datetime
import json
import logging
import os

import aiomysql
import arq

from models.friend import Friend
from models.post import Post
from server import close_db_pool
from server import extract_database_credentials


def default(o):
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()


# NEWS_CACHE_SIZE = 1000
NEWS_CACHE_SIZE = 3
NEWS_CACHE_TTL = 300


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
            fields=['author__name', 'id', 'author_id', 'text', 'created_at', 'updated_at'], limit=3)
        pipe = redis.pipeline()

        pipe.delete(key)
        for post in posts:
            post_json = json.dumps(post, default=default)
            pipe.rpush(key, post_json)

        pipe.ltrim(key, 0, NEWS_CACHE_SIZE - 1)
        pipe.expire(key, NEWS_CACHE_TTL)
        await pipe.execute()

    return 'build_cache done'


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
                fields=['user_id'], limit=20):
            pipe = redis.pipeline()
            key = f'news:{subscriber["user_id"]}'
            pipe.lpush(key, post_json)

            pipe.ltrim(key, 0, NEWS_CACHE_SIZE - 1)
            pipe.expire(key, NEWS_CACHE_TTL)
            await pipe.execute()
    return 'add_post_to_cache done'


async def startup(ctx):
    logging.basicConfig(level=logging.DEBUG)
    databse_url = os.getenv('CLEARDB_DATABASE_URL', None) or os.getenv('DATABASE_URL', None)
    pool = await aiomysql.create_pool(
        **extract_database_credentials(databse_url),
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


async def shutdown(ctx):
    if ctx['db_pool'] == ctx['db_ro_pool']:
        await close_db_pool(ctx['db_ro_pool'])
    await close_db_pool(ctx['db_pool'])


class WorkerSettings:
    functions = [build_news_cache, add_post_to_cache]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = arq.connections.RedisSettings.from_dsn(os.getenv('REDIS_URL', None))


async def main():
    redis_url = os.getenv('REDIS_URL', None)
    arq_pool = await arq.create_pool(arq.connections.RedisSettings.from_dsn(redis_url))
    user_id = 1001004
    await arq_pool.enqueue_job('build_cache', user_id)
    arq_pool.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(main())
