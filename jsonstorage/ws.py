"""JSON Storage webservice
"""

__author__ = "Rogier Steehouder"
__date__ = "2022-01-30"
__version__ = "2.0"

import contextlib
import datetime
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from loguru import logger
from starlette import status
from starlite import (
    Controller,
    Parameter,
    Body,
    get,
    post,
    put,
    patch,
    delete,
    HTTPException,
    NotFoundException,
)

try:
    import orjson as json
except ImportError:
    import json

# Optional for patch operation
try:
    import jsonpatch
except:
    jsonpatch = None


from .config import cfg


class NotImplementedException(HTTPException):
    status_code = status.HTTP_501_NOT_IMPLEMENTED


class JSONDatabase:
    """JSON storage database"""

    sql_get_item = "select s.content from storage s where s.name = :p and effdt <= :d and not exists (select 1 from storage where name = s.name and effdt > s.effdt and effdt <= :d) and s.status = 'A'"
    sql_insert_item = "insert into storage values(:p, :d, :s, :c)"

    def __init__(self):
        self.logger = logger.bind(logtype="jsonstorage.database")

        self._db_file = Path(cfg.get("server.directory", ".")) / cfg.get(
            "database.filename", "jsonstorage.sqlite"
        )
        if not self._db_file.exists():
            self.logger.debug("New database file {}", self._db_file)
            self._db_init()

    @contextlib.contextmanager
    def _db_connect(self) -> sqlite3.Connection:
        """Connect to the sqlite3 database"""
        conn = sqlite3.connect(self._db_file)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except:
            # re-raise exceptions
            raise
        else:
            # no exceptions
            conn.commit()
        finally:
            # always
            conn.close()

    def _db_init(self):
        """Initialize the database"""
        with self._db_connect() as conn:
            conn.executescript(
                """
                create table storage (name text, effdt datetime, status text, content text);
                create unique index idx_storage on storage (name, effdt);
                """
            )

    @staticmethod
    def datetime_todb(d: datetime.datetime) -> str:
        return d.isoformat(sep=" ", timespec="seconds")

    @staticmethod
    def datetime_fromdb(s: str) -> datetime.datetime:
        return datetime.datetime.fromisoformat(s)

    def cleanup(self):
        """Clean up old versions of items"""
        self.logger.info("Cleanup: removing old inactive items from the database")
        with self._db_connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "with old_stuff as (select s.name, s.effdt from storage s where s.effdt < datetime('now', '-1 years') and (s.status = 'I' or exists (select 1 from storage where name = s.name and effdt > s.effdt))) delete from storage where exists (select 1 from old_stuff where name = storage.name and effdt = storage.effdt)"
            )
            cur.close()

    def get_list(self, like: str = None, glob: str = None) -> list:
        """List of item ids"""
        criteria = []
        if like is not None:
            criteria.append("s.name like :l")
        if glob is not None:
            criteria.append("s.name glob :g")
        crit = ""
        if criteria:
            crit = "and {}".format(" and ".join(criteria))

        with self._db_connect() as conn:
            cur = conn.cursor()
            self.logger.debug("List for items like {} or {}", like, glob)
            cur.execute(
                "select s.name from storage s where effdt <= :d and not exists (select 1 from storage where name = s.name and effdt > s.effdt and effdt <= :d) and s.status = 'A' {} order by s.name".format(
                    crit
                ),
                {
                    "l": like,
                    "g": glob,
                    "d": self.datetime_todb(datetime.datetime.utcnow()),
                },
            )
            items = [row["name"] for row in cur.fetchall()]
            cur.close()

        return items

    def get_list_hist(self, like: str = None, glob: str = None) -> list:
        """List of item ids"""
        criteria = []
        if like is not None:
            criteria.append("s.name like :l")
        if glob is not None:
            criteria.append("s.name glob :g")
        crit = ""
        if criteria:
            crit = "and {}".format(" and ".join(criteria))

        with self._db_connect() as conn:
            cur = conn.cursor()
            self.logger.debug("History list for items like {} or {}", like, glob)
            cur.execute(
                "select s.name, s.effdt, s.status from storage s where 1=1 {} order by s.name, s.effdt".format(
                    crit
                ),
                {"l": like, "g": glob},
            )
            items = [
                {
                    "name": row["name"],
                    "effdt": self.datetime_fromdb(row["effdt"]),
                    "status": row["status"],
                }
                for row in cur.fetchall()
            ]
            cur.close()

        return items

    def get_item(self, id: str, effdt: datetime.datetime = None) -> Any:
        if effdt is None:
            effdt = datetime.datetime.utcnow()
        self.logger.debug("Retrieve item {} on {}", id, effdt)

        with self._db_connect() as conn:
            cur = conn.cursor()
            cur.execute(self.sql_get_item, {"p": id, "d": self.datetime_todb(effdt)})
            row = cur.fetchone()
            cur.close()
        if row is None:
            return None

        return json.loads(row["content"])

    def put_item(self, content: Any, id: str, effdt: datetime.datetime = None):
        if effdt is None:
            effdt = datetime.datetime.utcnow()
        self.logger.debug("Store item {} on {}", id, effdt)

        with self._db_connect() as conn:
            cur = conn.cursor()
            if content is None:
                cur.execute(
                    self.sql_insert_item,
                    {"p": id, "d": self.datetime_todb(effdt), "s": "I", "c": ""},
                )
            else:
                cur.execute(
                    self.sql_insert_item,
                    {
                        "p": id,
                        "d": self.datetime_todb(effdt),
                        "s": "A",
                        "c": json.dumps(content),
                    },
                )
            cur.close()


class JSONStorage(Controller):
    """Simple JSON storage webservice"""

    path = "/storage"
    tags = ["Storage"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logger.bind(logtype="jsonstorage.storage")
        self._db = JSONDatabase()

    @get(
        path="/",
        status_code=status.HTTP_200_OK,
        operation_id="list",
        summary="List available JSON items",
        tags=["Storage"],
    )
    async def get_list(
        self,
        like: str = Parameter(
            required=False, default=None, description="Filter with sql 'like' syntax"
        ),
        glob: str = Parameter(
            required=False, default=None, description="Filter with 'glob' syntax"
        ),
    ) -> list:
        return self._db.get_list()

    @post(
        path="/",
        status_code=status.HTTP_201_CREATED,
        operation_id="new",
        summary="Store a new JSON item (id is generated)",
        tags=["Storage"],
    )
    async def post_json(
        self,
        data: Any = Body(),
        prefix: str = Parameter(
            default="", description="Add prefix to the generated id"
        ),
    ) -> dict:
        id = "{}{}".format(prefix, uuid.uuid1())
        self.logger.debug("Post: new item id {}", id)
        self._db.put_item(data, id)
        return {"id": id, "content": data}

    @get(
        path="/{id:str}",
        status_code=status.HTTP_200_OK,
        operation_id="get",
        summary="Retrieve a JSON item by id",
        tags=["Storage"],
        raises=[NotFoundException],
    )
    async def get_json(self, id: str) -> Any:
        self.logger.debug("Get item {}", id)
        item = self._db.get_item(id)
        if item is None:
            raise NotFoundException(extra=id)
        return item

    @put(
        path="/{id:str}",
        status_code=status.HTTP_200_OK,
        operation_id="put",
        summary="Store a JSON item by id",
        tags=["Storage"],
    )
    async def put_json(self, id: str, data: Any = Body()) -> Any:
        self.logger.debug("Put item {}", id)
        self._db.put_item(data, id)
        return data

    @patch(
        path="/{id:str}",
        status_code=status.HTTP_200_OK,
        operation_id="patch",
        summary="Change a stored JSON item (see JSON Patch standard)",
        tags=["Storage"],
        raises=[NotFoundException, NotImplementedException],
    )
    async def patch_json(self, id: str, data: list = Body()) -> Any:
        if jsonpatch is None:
            raise NotImplementedException()

        self.logger.debug("Patch item {}", id)
        item = self._db.get_item(id)
        if item is None:
            raise NotFoundException(extra=id)
        item_new = jsonpatch.apply_patch(item, data)
        self._db.put_item(item_new, id)

        return item_new

    @delete(
        path="/{id:str}",
        status_code=status.HTTP_204_NO_CONTENT,
        operation_id="delete",
        summary="Delete a JSON item",
        description="The item is not really deleted, but marked inactive.",
        tags=["Storage"],
        raises=[NotFoundException],
    )
    async def delete_json(self, id: str) -> None:
        self.logger.debug("Delete item {}", id)
        item = self._db.get_item(id)
        if item is None:
            raise NotFoundException(extra=id)
        self._db.put_item(None, id)

    @delete(
        path="/",
        status_code=status.HTTP_204_NO_CONTENT,
        operation_id="cleanup",
        summary="Permanently remove old (more than 1 year) versions of JSON items",
        tags=["Storage"],
    )
    async def cleanup(self) -> None:
        self._db.cleanup()


class JSONStorageHistory(Controller):
    """JSON storage webservice with history"""

    path = "/history"
    tags = ["History"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logger.bind(logtype="jsonstorage.history")
        self._db = JSONDatabase()

    @get(
        path="/",
        status_code=status.HTTP_200_OK,
        operation_id="list",
        summary="List available JSON items",
        tags=["History"],
    )
    async def get_list(
        self,
        like: str = Parameter(
            required=False, default=None, description="Filter with sql 'like' syntax"
        ),
        glob: str = Parameter(
            required=False, default=None, description="Filter with 'glob' syntax"
        ),
    ) -> list:
        return self._db.get_list_hist()

    @post(
        path="/",
        status_code=status.HTTP_201_CREATED,
        operation_id="new",
        summary="Store a new JSON item (id is generated)",
        tags=["History"],
    )
    async def post_json(
        self,
        data: Any = Body(),
        prefix: str = Parameter(
            default="", description="Add prefix to the generated id"
        ),
        effdt: datetime.datetime = Parameter(
            default=datetime.datetime.utcnow(), description="Use this date/time."
        ),
    ) -> dict:
        id = "{}{}".format(prefix, uuid.uuid1())
        self.logger.debug("Post: new item id {} on {}", id, effdt)
        self._db.put_item(data, id, effdt)
        return {"id": id, "content": data}

    @get(
        path="/{id:str}",
        status_code=status.HTTP_200_OK,
        operation_id="get",
        summary="Retrieve a JSON item by id",
        tags=["History"],
        raises=[NotFoundException],
    )
    async def get_json(
        self,
        id: str,
        effdt: datetime.datetime = Parameter(
            default=datetime.datetime.utcnow(), description="Use this date/time."
        ),
    ) -> Any:
        self.logger.debug("Get item {} on {}", id, effdt)
        item = self._db.get_item(id, effdt)
        if item is None:
            raise NotFoundException(extra=id)
        return item

    @put(
        path="/{id:str}",
        status_code=status.HTTP_200_OK,
        operation_id="put",
        summary="Store a JSON item by id",
        tags=["History"],
    )
    async def put_json(
        self,
        id: str,
        data: Any = Body(),
        effdt: datetime.datetime = Parameter(
            default=datetime.datetime.utcnow(), description="Use this date/time."
        ),
    ) -> Any:
        self.logger.debug("Put item {} on {}", id, effdt)
        self._db.put_item(data, id, effdt)
        return data

    @patch(
        path="/{id:str}",
        status_code=status.HTTP_200_OK,
        operation_id="patch",
        summary="Change a stored JSON item (see JSON Patch standard)",
        tags=["History"],
        raises=[NotFoundException, NotImplementedException],
    )
    async def patch_json(
        self,
        id: str,
        data: list = Body(),
        effdt: datetime.datetime = Parameter(
            default=datetime.datetime.utcnow(), description="Use this date/time."
        ),
    ) -> Any:
        if jsonpatch is None:
            raise NotImplementedException()

        self.logger.debug("Patch item {} on {}", id, effdt)
        item = self._db.get_item(id, effdt)
        if item is None:
            raise NotFoundException(extra=id)
        item_new = jsonpatch.apply_patch(item, data)
        self._db.put_item(item_new, id, effdt)

        return item_new

    @delete(
        path="/{id:str}",
        status_code=status.HTTP_204_NO_CONTENT,
        operation_id="delete",
        summary="Delete a JSON item",
        description="The item is not really deleted, but marked inactive. It will no longer shop up here, but may still be accessed using the history API.",
        tags=["History"],
        raises=[NotFoundException],
    )
    async def delete_json(
        self,
        id: str,
        effdt: datetime.datetime = Parameter(
            default=datetime.datetime.utcnow(), description="Use this date/time."
        ),
    ) -> None:
        self.logger.debug("Delete item {} on {}", id, effdt)
        item = self._db.get_item(id, effdt)
        if item is None:
            raise NotFoundException(extra=id)
        self._db.put_item(None, id, effdt)

    @delete(
        path="/",
        status_code=status.HTTP_204_NO_CONTENT,
        operation_id="cleanup",
        summary="Permanently remove old (more than 1 year) versions of JSON items",
        tags=["History"],
    )
    async def cleanup(self) -> None:
        self._db.cleanup()
