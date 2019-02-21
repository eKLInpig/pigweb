from .web import PigWeb
import json

def jsonify(**kwargs):
    content = json.dumps(kwargs)
    response = PigWeb.Response()
    response.content_type = "application/json"
    response.body = "{}".format(content).encode()
    return response
