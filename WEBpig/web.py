from webob import Response, Request, dec, exc
import re


class Context(dict):  # app
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError('Attribute {} Not Found'.format(item))

    def __setattr__(self, key, value):
        self[key] = value


class NestedContext(Context):  # route
    def __init__(self, globalcontext: Context = None):
        super().__init__()
        self.relate(globalcontext)

    def relate(self, globalcontext: Context = None):
        self.globalcontext = globalcontext

    def __getattr__(self, item):
        if item in self.keys():
            return self[item]
        return self.globalcontext[item]


# 字典转属性
class DictObj:
    def __init__(self, d: dict):
        if isinstance(d, (dict,)):
            self.__dict__['_dict'] = d
        else:
            self.__dict__['_dict'] = {}

    def __getattr__(self, item):
        try:
            return self._dict[item]
        except KeyError:
            raise AttributeError('Attribute {} Not Found'.format(item))

    def __setattr__(self, key, value):
        # 不允许修改属性
        raise NotImplementedError


# 路由前缀类
class _Router:
    # 正则转换
    KVPATTERN = re.compile('/({[^{}:]+:?[^{}:]*})')

    TYPEPATTERNS = {
        'str': r'[^/]+',
        'word': r'\w+',
        'int': r'[+-]?\d+',
        'float': r'[+-]?\d+\.\d+',
        'any': r'.+'
    }

    TYPECAST = {
        'str': str,
        'word': str,
        'int': int,
        'float': float,
        'any': str
    }

    def transform(self, kv: str):
        # /{id:int} => /(?P<id>[+-}?\d+)
        name, _, type = kv.strip('/{}').partition(":")
        # 返回元组，(目标正则表达式，被替换部分类型有序列表)
        return '/(?P<{}>{})'.format(name, self.TYPEPATTERNS.get(type, '\w+')), name, self.TYPECAST.get(type, str)

    def parse(self, src: str):
        start = 0  # '/({[^{}:]+:?[^{}:]*})'
        result = ''  # '/student/{name:str}/xxx/{id:int}'  /prefix/{name}/{id}
        translator = {}  # id => int    name => str
        while True:
            matcher = self.KVPATTERN.search(src, start)
            if matcher:
                result += matcher.string[start:matcher.start()]
                tmp = self.transform(matcher.string[matcher.start():matcher.end()])
                result += tmp[0]
                translator[tmp[1]] = tmp[2]
                start = matcher.end()
            else:
                break
                # 没有任何匹配应该原样返回字符串
        if result:
            return result, translator
        else:
            return src, translator

    def __init__(self, prefix: str = '/'):
        self.__prefix = prefix.rstrip('/\\')

        self.__routetable = []

        self.ctx = NestedContext()  # 未绑定全局的上下文

        self.preinterceptor = []
        self.postinterceptor = []

    def reg_preinterceptor(self, fn):
        self.preinterceptor.append(fn)
        return fn

    def reg_postinterceptor(self, fn):
        self.postinterceptor.append(fn)
        return fn

    @property
    def prefix(self):
        return self.__prefix

    def route(self, rule, *methods):
        def wrapper(handler):
            pattern, translator = self.parse(rule)
            self.__routetable.append((methods, re.compile(pattern), translator, handler))
            return handler

        return wrapper

    def get(self, pattern):
        return self.route(pattern, 'GET')

    def post(self, pattern):
        return self.route(pattern, 'POST')

    def head(self, pattern):
        return self.route(pattern, 'HEAD')

    def match(self, request: Request) -> Response:
        # 属于你管的prefix
        if not request.path.startswith(self.prefix):
            return

        for fn in self.preinterceptor:
            request = fn(self.ctx, request)

        for methods, pattern, translator, handler in self.__routetable:
            if not methods or request.method in methods:
                matcher = pattern.match(request.path.replace(self.prefix, "", 1))
                if matcher:
                    # request.args = matcher.group()  # 所有分组
                    # request.kwargs = DictObj(matcher.groupdict())  # 所有的命名的分组
                    newdict = {}
                    for k, v in matcher.groupdict().items():
                        newdict[k] = translator[k](v)
                    request.vars = DictObj(newdict)

                    response = handler(request)

                    for fn in self.postinterceptor:
                        response = fn(self.ctx, request, response)

                    return response
        # return None


# 主程序
class PigWeb:
    Router = _Router
    Request = Request
    Response = Response

    # 路由表
    ROUTERS = []

    # 上下文
    ctx = Context()

    # 拦截器列表
    PREINTERCEPTOR = []
    POSTINTERCEPTOR = []

    # 拦截器注册函数
    @classmethod
    def reg_preinterceptor(cls, fn):
        cls.PREINTERCEPTOR.append(fn)
        return fn

    @classmethod
    def reg_postinterceptor(cls, fn):
        cls.POSTINTERCEPTOR.append(fn)
        return fn

    def __init__(self, **kwargs):
        self.ctx.app = self
        for k, v in kwargs:
            self.ctx[k] = v

    @classmethod
    def register(cls, router: Router):
        router.ctx.relate(cls.ctx)
        router.ctx.router = router
        cls.ROUTERS.append(router)
        return router

    @dec.wsgify
    def __call__(self, request: Request) -> Response:
        # 拦截器一号
        for fn in self.PREINTERCEPTOR:
            request = fn(self.ctx, request)

        for router in self.ROUTERS:
            response = router.match(request)

            if response:
                # 拦截器二号
                for fn in self.POSTINTERCEPTOR:
                    response = fn(self.ctx, request, response)

                return response

        raise exc.HTTPNotFound("您访问的页面被python星人劫持了")

    @classmethod
    def extend(cls, name, ext):
        cls.ctx[name] = ext
