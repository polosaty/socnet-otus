# from pprint import pprint

from aiohttp import web

from login import require_login
from models import User


@require_login
async def handle_user(request: web.Request):
    async with request.app['db_pool'].acquire() as conn:
        offset = int(request.rel_url.query.get('offset', 0))
        users = await User.get_by_limit(conn=conn, offset=offset)
        # pprint(users)
        return web.json_response(users)

