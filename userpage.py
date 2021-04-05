import aiomysql
from aiohttp import web
import aiohttp_jinja2
import aiohttp_session
from login import require_login
from login import User

@require_login
@aiohttp_jinja2.template('userpage.jinja2')
async def handle_userpage(request: web.Request):
    session = await aiohttp_session.get_session(request)
    # username = session["username"]
    uid = session["uid"]
    pool: aiomysql.pool.Pool = request.app['db_pool']
    async with pool.acquire() as conn:
        user = await User.get_by_id(uid=uid, conn=conn)

    return user.to_dict()
