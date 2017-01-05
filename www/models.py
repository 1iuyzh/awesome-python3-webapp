#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
Models for user. blog, comment.
'''

__author__ = 'Liuyzh'

import time, uuid

from orm import Model, StringField, BooleanField, FloatField, TextField

#生成一个和当前时间有关的id
def next_id():
    return '%015d%s000' % (int(time.time() * 1000), uuid.uuid4().hex)

class User(Model):
    #定义表名
    __table__ = 'users'

    #定义id为主键，调用next_id方法后获得默认值
    id = StringField(primary_key=True, default=next_id, ddl='varchar(50)')
    #邮箱
    email = StringField(ddl='varchar(50)')
    #密码
    passwd = StringField(ddl='varchar(50)')
    #管理员身份
    admin = BooleanField()
    #名字
    name = StringField(ddl='varchar(50)')
    #头像
    image = StringField(ddl='varchar(500)')
    #创建时间
    created_at = FloatField(default=time.time)

class Blog(Model):
    __table__ = 'blogs'

    id = StringField(primary_key=True, default=next_id, ddl='varchar(50)')
    #作者id
    user_id = StringField(ddl='varchar(50)')
    #作者名
    user_name = StringField(ddl='varchar(50)')
    #作者上传的图片
    user_image = StringField(ddl='varchar(500)')
    #文章名
    name = StringField(ddl='varchar(50)')
    #文章概要
    summary = StringField(ddl='varchar(200)')
    #文章正文
    content = TextField()
    #创建时间
    created_at = FloatField(default=time.time)

class Comment(Model):
    __table__ = 'comments'

    id = StringField(primary_key=True, default=next_id, ddl='varchar(50)')
    #博客id
    blog_id = StringField(ddl='varchar(50)')
    #评论者id
    user_id = StringField(ddl='varchar(50)')
    #评论者名字
    user_name = StringField(ddl='varchar(50)')
    #评论者上传的图片
    user_image = StringField(ddl='varchar(500)')
    #评论内容
    content = TextField()
    created_at = FloatField(default=time.time)

