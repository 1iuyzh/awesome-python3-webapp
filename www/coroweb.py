#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'Liuyzh'

import asyncio, os, inspect, logging, functools

from urllib import parse

from aiohttp import web

from apis import APIError

#被修饰函数func获得属性__method__和__route__
def get(path):
    '''
    Define decorator @get('/path')
    '''
    def decorator(func):
        #__name__
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator

#给被@post修饰的函数func添加属性__method__和__route__
def post(path):
    '''
    Define decorator @post('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator

#提取fn的所有未指定默认值的命名关键字参数name
def get_required_kw_args(fn):
    args = []
    #获取fn的所有参数构成一个dict
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)

#提取fn的所有命名关键字参数name
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)

#判断fn有没有命名关键字参数
def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

#判断fn有没有关键字参数，注意关键字参数和命名关键字参数的区别
def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

#POSITIONAL_OR_KEYWORD 位置或命名参数
#VAR_POSITIONAL 可变参数
#KEYWORD_ONLY 命名关键字参数
#VAR_KEYWORD 关键字参数
#判断fn有没有名为request的参数，且request后没有可变参数，命名关键字参数和关键字参数
def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue
        if found and (param.kind != inspect.Paramater.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function: %s%s' % (fn.__name__, str(sig)))
    return found

#RequestHandler实例RequestHandler(app, fn)(request)为封装后的URL函数fn
#从URL函数中分析其需要接收的参数，从request中获取必要的参数
#app.py中的response_factory负责将结果处理成web.Response对象
class RequestHandler(object):

    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        #fn有没有名为request的参数
        self._has_request_arg = has_request_arg(fn)
        #fn有没有关键字参数
        self._has_var_kw_arg = has_var_kw_arg(fn)
        #fn有没有命名关键字参数
        self._has_named_kw_args = has_named_kw_args(fn)
        #fn的所有命名关键字参数
        self._named_kw_arg = get_named_kw_args(fn)
        #fn的所有未指定默认值的命名关键字参数
        self._required_kw_args = get_required_kw_args(fn)

    async def __call__(self, request):
        #kw理解成fn参数对应的待处理信息
        kw = None
        #如果fn有关键字参数或者命名关键字参数
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
            if request.method == 'POST':
                #content_type是request提交的消息主体类型
                if not request.content_type:
                    return web.HTTPBadRequest('Missing Content-Type.')
                #ct是消息主体类型小写
                ct = request.content_type.lower()
                ##如果消息主体类型开头为application/json，则说明消息主体是个json对象
                if ct.startswith('application/json'):
                    #用json方法读取消息到kw
                    params = await request.json()
                    if not isinstance(params, dict):
                        return web.HTTPBadRequest('JSON body must be object.')
                    kw =  params
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    #浏览器表单信息用post方法读取到kw
                    params = await request.post()
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest('Unsupported Content-Type: %s' % request.content_type)
            if request.method == 'GET':
                #获取请求字符串到qs
                qs = request.query_string
                #解析字符串，解析结果存入kw
                if qs:
                    kw = dict()
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]
        if kw is None:
            kw = dict(**request.match_info)
        else:
            #fn没有关键字参数但有命名关键字参数
            if not self._has_var_kw_arg and self._named_kw_arg:
                # remove all unamed kw:
                copy = dict()
                #提取request消息kw中与fn命名关键字参数重复的部分
                for name in self._named_kw_arg:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            # check named arg:
            #不明白
            for k, v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
        #如果fn有request参数
        if self._has_request_arg:
            kw['request'] = request
        # check required kw:
        if self._required_kw_args:
            #kw必须包含全部未指定默认值的命名关键字参数
            for name in self._required_kw_args:
                if not name in kw:
                    return web.HTTPBadRequest('Missing arument: %s' % name)
        logging.info('call with args: %s' % str(kw))
        try:
            r = await self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)

#向app中添加静态文件目录
def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))

#把URL函数注册到app
def add_route(app, fn):
    #获取fn的__method__属性和__route__属性
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.' % str(fn))
    #如果fn既不是协程，也不是生成器，就把fn转变成协程
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)' % (method, path, fn.__name__, ', '.join(inspect.signature(fn).parameters.keys())))
    #RequestHandler(app, fn)是封装后的fn函数
    app.router.add_route(method, path, RequestHandler(app, fn))

#将模块module_name中的所有URL函数注册到app
def add_routes(app, module_name):
    #如果handlers在当前目录下，module_name就为handlers
    #如果handlers在handler目录下，module_name就为handler.handlers
    #找出module_name中'.'的索引位置
    n = module_name.rfind('.')
    #module_name中没找到'.'，说明handlers在当前目录下，直接导入
    if n == (-1):
        mod = __import__(module_name, globals(), locals())
    else:
        name = module_name[n+1:] #从handler.handlers中提取handlers到name
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
    #遍历mod中的所有属性
    for attr in dir(mod):
        #跳过私有属性
        if attr.startswith('_'):
            continue
        #如果attr是函数，赋值给fn
        fn = getattr(mod, attr)
        if callable(fn):
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                add_route(app, fn)
