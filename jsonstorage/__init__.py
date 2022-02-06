"""JSON storage webservice

Provides REST webservices to store and retrieve json objects.
"""

__author__  = 'Rogier Steehouder'
__date__    = '2022-01-29'
__version__ = '2.0'

import os

from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlite import Starlite, OpenAPIConfig, OpenAPIController
from openapi_schema_pydantic import Tag

from .auth import BasicAuthBackend, on_auth_error
from .config import cfg
from .ws import JSONStorage, JSONStorageHistory


class DocController(OpenAPIController):
    path = '/docs'

def make_app():
    return Starlite(
        route_handlers = [
            JSONStorage,
            JSONStorageHistory
        ],
        middleware = [
            Middleware(AuthenticationMiddleware, backend=BasicAuthBackend(), on_error=on_auth_error)
        ],
        openapi_config = OpenAPIConfig(
            title = 'JSONStorage',
            version = __version__,
            tags = [
                Tag(name='Storage', description='Store and retrieve JSON.'),
                Tag(name='History', description='Store and retrieve JSON, with the option of using specific dates.')
            ],
            openapi_controller = DocController
        )
    )
