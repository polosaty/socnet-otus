import json
import logging

from aiohttp import web
import aiohttp_jinja2
import aiohttp_session
import aiomysql

from login import require_login
from models.post import Post


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
        arq_pool = request.app['arq_pool']
        await arq_pool.enqueue_job('add_post_to_cache', post_id)
    location = request.headers.get('Referer', '/userpage/')
    return web.HTTPFound(location=location)
