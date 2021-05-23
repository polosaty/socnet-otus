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

    pool: aiomysql.pool.Pool = request.app['db_ro_pool']
    async with pool.acquire() as conn:
        posts = await Post.filter(
            conn=conn, filter=dict(post_of_friends=uid),
            fields=['author__name', 'id', 'author_id', 'text', 'created_at', 'updated_at'])

    return dict(posts=posts, session=session)
