#!usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'Liuyzh'

import asyncio, logging

import aiomysql

#输出sql操作信息
def log(sql, args=()):
    logging.info('SQL: %s' % sql)

#创建全局连接池变量__pool
#需要连接数据库时直接从__pool中获取连接
async def create_pool(loop, **kw):
    logging.info('create database connection pool...')
    #声明为全局变量
    global __pool
    __pool = await aiomysql.create_pool(
        host=kw.get('host', 'localhost'),
        port=kw.get('port', 3306),
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf8'),
        autocommit=kw.get('autocommit', True),
        maxsize=kw.get('maxsize', 10),
        minsize=kw.get('minsize', 1),
        loop=loop
     )

#将执行sql的代码封装进select函数中，调用只需要传入sql语句和参数
async def select(sql, args, size=None):
    log(sql, args)
    global __pool
    #从__pool中获取一个数据库连接
    async with __pool.get() as conn:
        #创建游标
        async with conn.cursor(aiomysql.DictCursor) as cur:
            #执行sql命令，传入sql参数，包括目标表等
            await cur.execute(sql.replace('?', '%s'), args or ())
            #size是需要返回的结果数，默认返回所有查询结果
            if size:
                rs = await cur.fetchmany(size)
            else:
                rs = await cur.fetchall()
        logging.info('row returned: %s' % len(rs))
        return rs

#由于insert，update，delete需要相同的参数，而且都返回一个整数表示影响的行数
#定义一个通用函数execute包含以上三种sql
async def execute(sql, args, autocommit=True):
    log(sql)
    async with __pool.get() as conn:
        if not autocommit:
            await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?', '%s'), args)
                #受影响的行数
                affected = cur.rowcount
            if not autocommit:
                await conn.commit()
        except BaseException as e:
            if not autocommit:
                await conn.rollback()
            raise
        return affected

#创建一定数量的占位符
def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    #假如L=['?', '?', '?']，则返回字符串'?, ?, ?'
    return ', '.join(L)

#定义字段基类
class Field(object):

    def __init__(self, name, column_type, primary_key, default):
        #字段名
        self.name = name
        #字段类型
        self.colume_type = column_type
        #是否是主键
        self.primary_key = primary_key
        #默认值
        self.default = default
    #打印相关
    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.colume_type, self.name)

class StringField(Field):

    #ddl意为数据定义语言(data definition languages)
    #默认值为可变字符串'varchar(100)'
    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)

class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)

class InterField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)

class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)

class TextField(Field):

    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)

#通过ModelMetaclass.__new__()创建类
#元类的作用: 
#添加类属性__table__，存储类对应的表名
#添加类属性__mappings__，存储类中所有Field类属性
#添加类属性__fields__，存储类中除了主键字段外的Field类属性
#添加类属性__primary_key__，存储主键字段名
#添加类属性__select__、__insert__、__update__、__delete__
class ModelMetaclass(type):

    #cls: 当前准备创建的类的对象
    #name: 类的名字
    #bases: 父类集合
    #attrs: 类的属性方法集合
    def __new__(cls, name, bases, attrs):
        #创建Model类时不使用元类
        if name=='Model':
            return type.__new__(cls, name, bases, attrs)
        #默认表名是类名
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))
        mappings = dict()
        fields = []
        primaryKey = None
        #遍历类的所有属性
        for k, v in attrs.items():
            #属性类型是不是Field
            if isinstance(v, Field):
                logging.info('  found mappings: %s ==> %s' % (k, v))
                mappings[k] = v
                if v.primary_key:
                    # 找到主键，且主键应该唯一
                    if primaryKey:
                        raise StandardError('Duplicate primary key for field: %s' % k)
                    #主键赋值
                    primaryKey = k
                else:
                    fields.append(k)
        #没找到主键
        if not primaryKey:
            raise StandardError('Primary key not found.')
        #删除类中被mappings包含了的属性
        for k in mappings.keys():
            attrs.pop(k)
        #对fields中的字符串元素进行处理
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))
        #把mappings存入attrs
        attrs['__mappings__'] = mappings
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey
        attrs['__fields__'] = fields
        #生成select，insert，update，delete四个sql语句，存入attrs
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)

#Model类继承自dict类
#元类的作用: 
#添加类属性__table__，存储类对应的表名
#添加类属性__mappings__，存储类中所有Field类属性
#添加类属性__fields__，存储类中除了主键字段外的Field类属性
#添加类属性__primary_key__，存储主键字段名
#添加属性__select__、__insert__、__update__、__delete__
class Model(dict, metaclass=ModelMetaclass):

    def __init__(self, **kw):
        #调用 Model 父类 dict 的初始化方法
        #传入的关键字参数存入自身dict中
        #如user = User(id = 1)
        #user['id'] = 1
        super(Model, self).__init__(**kw)
    
    #获取dict的值
    #user.id 等价于 user['id']
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    #设置dict的值
    #通过d.k=v的方式实现赋值d['k']=v
    def __setattr__(self, key, value):
        self[key] = value

    #获取当前实例的属性值
    #如user.id或user.name
    def getValue(self, key):
        return getattr(self, key, None)

    #若当前实例没有名为key的属性值
    #如user.name
    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            #到__mappings__中寻找key
            field = self.__mappings__[key]
            #若属性key具有default属性
            if field.default is not None:
                #如果default是方法则返回default()，如果是具体值则返回default
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s: %s' % (key, str(values)))
                setattr(self, key, value)
        return value

    #类方法装饰器
    #不用创建实例就可以调用
    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        ' find objects by where clause. '
        #'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where. '
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    @classmethod
    async def find(cls, pk):
        ' find object by primary key. '
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])
    
    #save、updat、delete三个方法需要创建实例后调用
    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        #'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        rows = await execute(self.__insert__, args)
        if row != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        #'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        #'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)

