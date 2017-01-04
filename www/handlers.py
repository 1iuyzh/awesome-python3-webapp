#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'Liuyzh'

' url handlers '

import re, time, json, logging, hashlib, base64, asyncio

from coroweb import get, post

from models import User, Comment, Blog, next_id

@get('/')
async def indec(request):
    users = await User.findAll()
    return{
        '__template__': 'test.html',
        'user': users
    }
