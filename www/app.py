#!usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = "Liuyzh"

'''
async web application.
'''

import logging
logging.basicConfig(level=logging.INFO)

import asyncio, os, json, time
from datetime import datetime

from aiohttp import web
#Environment与jinja2模板的环境配置有关，FileSystemLoader是文件系统加载器，用来加载模板路径
from jinja2 import Environment, FileSystemLoader

from config import configs

import orm
from coroweb import add_routes, add_static

from handlers import cookie2user, COOKIE_NAME

#初始化jinja2模板，配置jinja2环境
def init_jinja2(app, **kw):
    logging.info('init jinja2...')
    #配置如何解析模板
    options = dict(
            #自动转义xml/html的特殊字符，不明白
            autoescape = kw.get('autoescape', True),
            #设置代码块起始字符串
            block_start_string = kw.get('block_start_string', '{%'),
            #设置代码块结束字符串，即{%和%}中间的是python代码，不是html
            block_end_string = kw.get('block_end_string', '%}'),
            #设置变量的起始和结束字符串，即{{和}}中间是变量
            variable_start_string = kw.get('variable_start_string', '{{'),
            variable_end_string = kw.get('variable_end_string', '}}'),
            #当模板文件被修改后，下次请求加载该模板文件的时候会自动重新加载修改后的模板文件
            auto_reload = kw.get('auto_reload', True)
            )
    #获取模板路径到path，默认为/templates目录
    path = kw.get('path', None)
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    logging.info('set jinja2 template path: %s' % path)
    #loader=FileSystemLoader(path)指到path目录下加载模板文件
    #env中存储了jinja2配置信息，包括模板路径和解析配置
    env = Environment(loader=FileSystemLoader(path), **options)
    #过滤器，不明白
    filters = kw.get('filters', None)
    if filter is not None:
        for name, f in filters.items():
            env.filters[name] = f
    #把env存入app中
    app['__templating__'] = env

#拦截器middlewares的作用是URL在被URL函数处理前，对其进行处理，改变URL的输入输出等
#middlewares作用: 把通用功能从URL处理函数中拿出来
#当有HTTP请求时，输出请求信息
async def logger_factory(app, handler):
    async def logger(request):
        logging.info('Request: %s %s' % (request.method, request.path))
        #await asyncio.sleep(0.3)
        return (await handler(request))
    return logger

async def auth_factory(app, handler):
    async def auth(request):
        logging.info('check user: %s %s' % (request.method, request.path))
        request.__user__ = None
        cookie_str = request.cookies.get(COOKIE_NAME)
        if cookie_str:
            user = await cookie2user(cookie_str)
            if user:
                logging.info('set current user: %s' % user.email)
                request.__user__ = user
        if request.path.startswith('/manage/') and (request.__user__ is None or not request.__user__.admin):
            return web.HTTPFound('/signin')
        return (await handler(request))
    return auth

#当请求方法为POST时才有效，与reques的__data__属性有关
async def data_factory(app, handler):
    async def parse_data(request):
        if request.method == 'POST':
            if request.content_type.startswith('application/json'):
                request.__data__ = await request.json()
                logging.info('request json: %s' % str(request.__data__))
            elif request.content_type.startswith('application/x-www-form-urlencoded'):
                request.__data__ = await request.post()
                logging.info('request form: %s' % str(request.__data__))
        return (await handler(request))
    return parse_data

#把URL函数的返回内容处理成web.Response类型
async def response_factory(app, handler):
    async def response(request):
        logging.info('Response handler...')
        #调用handler来处理HTTP请求，并返回响应结果
        #为什么要把URL函数处理过程放在拦截器里，不明白
        r = await handler(request)
        #若响应结果为web.StreamResponse，直接返回作为响应
        #StreamResponse是aiohttp定义response的基类
        if isinstance(r, web.StreamResponse):
            return r
        #若响应结果类型为字节流，则将其作为响应的body部分，响应类型为octet-stream
        if isinstance(r, bytes):
            resp = web.Response(body=r)
            resp.content_type = 'application/octet-stream'
            return resp
        #若响应结果为字符串
        if isinstance(r, str):
            #判断响应结果是否为重定向，若是，返回重定向的地址
            if r.startswith('redirect:'):
                return web.HTTPFound(r[9:])
            #响应结果不是重定向，则对字符串进行utf-8编码，作为响应的body，设置相应的响应类型
            resp = web.Response(body=r.encode('utf-8'))
            resp.content_type = 'text/html;charset=utf-8'
            return resp
        #若响应结果为字典，r['__template__']存有模板文件名
        if isinstance(r, dict):
            template = r.get('__template__')
            #若不存在对应模板，则调整r为json格式作为响应body，并设置响应类型
            if template is None:
                resp = web.Response(body=json.dumps(r, ensure_ascii=False, default=lambda o: o.__dict__).encode('utf-8'))
                resp.content_type = 'application/json;charset=utf-8'
                return resp
            #存在对应模板，则套用模板
            #app['__templating__']存储的是env
            else:
                r['__user__'] = request.__user__
                resp = web.Response(body=app["__templating__"].get_template(template).render(**r).encode("utf-8"))
                logging.info('test %s' % str(r))
                resp.content_type = "text/html;charset=utf-8"
                return resp
        #若响应结果为整形，即r为状态码
        if isinstance(r, int) and r >= 100 and r < 600:
            return web.Response(r)
        #若响应结果为tuple，并且长度为2
        if isinstance(r, tuple) and len(r) == 2:
            t, m = r
            #t为状态码，m为错误描述
            #返回状态码和错误描述
            if isinstance(t, int) and t >= 100 and t < 600:
                return web.Response(t, str(m))
        #默认以字符串形式返回响应结果，并设置响应类型为普通文本
        resp = web.Response(body=str(r).encode('utf-8'))
        resp.content_type = 'text/plain;charset=utf-8'
        return resp
    return response

#返回创建时间
def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:
        return u'1分钟前'
    if delta < 3600:
        return u'%s分钟前' % (delta // 60)
    if delta < 86400:
        return u'%s小时前' % (delta // 3600)
    if delta < 604800:
        return u'%s天前' % (delta // 86400)
    dt = datetime.fromtimestamp(t)
    return u'%s年%s月%s日' % (dt.year, dt.month, dt.day)

async def init(loop):
    #创建数据库连接池
    await orm.create_pool(loop=loop, **configs.db)
    #初始化app，包括loop，middlewares
    #logger_factory处理请求，response_factory处理响应
    app = web.Application(loop=loop, middlewares=[
        logger_factory, auth_factory, response_factory
        ])
    #初始化jinja2模板
    init_jinja2(app, filters=dict(datetime=datetime_filter))
    #注册URL函数
    add_routes(app, 'handlers')
    add_static(app)
    #监听127.0.0.1的9000端口的访问请求
    srv = await loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    logging.info('server started at http://127.0.0.1:9000...')
    return srv

loop = asyncio.get_event_loop()
loop.run_until_complete(init(loop))
loop.run_forever()
