#!/usr/bin/env python3
"""
Database & Storage Tools
=========================
Tools for database operations and cloud storage

Tools:
- mysql_query: Execute SQL on an outside MySQL database (never the substrate's own)
- postgres_query: Execute SQL on an outside PostgreSQL database (never the substrate's own)
- redis_get: Get Redis key value
- redis_set: Set Redis key value
- r2_upload: Upload file to Cloudflare R2 storage
- r2_download: Download file from R2 storage

The other database tools (MySQL table info, backup and restore, connection pool,
transactions, migrations, row-level access, the safe query executors) ran on the
substrate's own database and were archived 2026-09-30:
archive/superseded_database_tools_2026-09-30/.

Author: Lyric AI Team
"""

import logging
import os
import ipaddress
import socket
from typing import Any, List, Optional, Tuple
from pathlib import Path

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata, RiskLevel


logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# OUTSIDE DATABASES
# ══════════════════════════════════════════════════════════════════════════
#
# A database tool works on a database OUTSIDE the substrate: the one it is given.
# Never the substrate's own. Its own data is reached through its authorities (the
# memory agent, the belief system, the queue), and a tool run on it would go
# around them -- circumventing the safety mechanisms and bypassing the oversight
# Law 5 preserves. So a connection to the substrate's own database server is
# refused before anything connects.


class OutsideDatabaseRefused(Exception):
    """A database tool was asked to work where it may not."""


def _machine_addresses() -> set:
    try:
        return set(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        return set()


def _addresses(host: Optional[str]) -> set:
    """Where `host` is, as addresses; any address of this machine reads as "local"."""
    if not host or str(host).startswith("/"):
        return {"local"}
    try:
        infos = socket.getaddrinfo(str(host), None)
    except socket.gaierror:
        return {str(host).lower()}
    here = _machine_addresses()
    out = set()
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        out.add("local" if ip.is_loopback or str(ip) in here else str(ip))
    return out


def _is_own_server(host: Optional[str], port: Any) -> bool:
    """Whether host:port is the substrate's own database server."""
    from core.database.postgres_config import PostgresConfig
    own = PostgresConfig.resolve()
    if int(port or 5432) != int(own.port):
        return False
    return bool(_addresses(host) & _addresses(own.host))


async def _outside_postgres(host: str, port: int, database: str, user: str, password: str):
    """A connection to an outside PostgreSQL database, or OutsideDatabaseRefused
    when it is the substrate's own server (refused before connecting)."""
    if _is_own_server(host, port):
        raise OutsideDatabaseRefused(
            "that is the substrate's own database server; its own data is reached through its "
            "authorities, never through a tool (Law 5: never around its safety mechanisms)")
    import asyncpg
    return await asyncpg.connect(host=host, port=int(port), database=database, user=user,
                                 password=password)


async def _outside_mysql(host: str, port: int, database: str, user: str, password: str):
    """A connection to an outside MySQL database, or OutsideDatabaseRefused when
    it is the substrate's own server (refused before connecting)."""
    if _is_own_server(host, port):
        raise OutsideDatabaseRefused(
            "that is the substrate's own database server; its own data is reached through its "
            "authorities, never through a tool (Law 5: never around its safety mechanisms)")
    import aiomysql
    return await aiomysql.connect(host=host, port=int(port), db=database, user=user,
                                  password=password, autocommit=True)


class MySQLQueryTool(Tool):
    """Execute SQL on an outside MySQL database."""

    def __init__(self):
        super().__init__()
        self.name = "mysql_query"
        self.description = ("Execute SQL on an outside MySQL database, given its address and login "
                            "(SELECT, INSERT, UPDATE, DELETE). Never the substrate's own database.")
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(name="query", type="string",
                          description="SQL query to execute (use %s placeholders for parameters)",
                          required=True),
            ToolParameter(name="params", type="array",
                          description="Query parameters for parameterized queries", required=False),
            ToolParameter(name="host", type="string", description="Database server host", required=True),
            ToolParameter(name="port", type="integer", description="Database server port",
                          required=False, default=3306),
            ToolParameter(name="database", type="string", description="Database name", required=True),
            ToolParameter(name="user", type="string", description="Login user", required=True),
            ToolParameter(name="password", type="string", description="Login password", required=False,
                          default=""),
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="mysql_query",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.QUERY_DATABASE,
                    description="Execute SQL queries on an outside MySQL database"
                ),
                CapabilityMetadata(
                    capability=Capability.MODIFY_DATABASE,
                    description="Modify an outside MySQL database via INSERT/UPDATE/DELETE",
                    input_types=["sql", "params"],
                    output_types=["affected_rows"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=8
                )
            ]
        )

    async def execute(self, query: str, host: str, database: str, user: str, password: str = "",
                      port: int = 3306, params: List = None) -> ToolResult:
        try:
            conn = await _outside_mysql(host, port, database, user, password)
        except OutsideDatabaseRefused as refused:
            return ToolResult(success=False, output=None, error=str(refused))
        except Exception as e:
            logger.error(f"MySQL connection error ({host}:{port}/{database}): {e}")
            return ToolResult(success=False, output=None, error=str(e))
        try:
            import aiomysql
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, tuple(params or ()))
                if cursor.description is not None:
                    rows = [dict(row) for row in await cursor.fetchall()]
                    return ToolResult(success=True, output={"query": query, "database": database,
                                                            "rows": rows, "count": len(rows)})
                return ToolResult(success=True, output={"query": query, "database": database,
                                                        "affected_rows": cursor.rowcount,
                                                        "last_insert_id": cursor.lastrowid})
        except Exception as e:
            logger.error(f"MySQL query error ({host}:{port}/{database}): {e}")
            return ToolResult(success=False, output=None, error=str(e))
        finally:
            conn.close()


class RedisGetTool(Tool):
    """Get Redis key value"""

    def __init__(self):
        super().__init__()
        self.name = "redis_get"
        self.description = "Get value from Redis cache"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="key",
                type="string",
                description="Redis key to retrieve",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="redis_get",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    description="Read data from Redis cache"
                ),
                CapabilityMetadata(
                    capability=Capability.RECEIVE_MESSAGE,
                    description="Receive messages and data from Redis pub/sub",
                    input_types=["key"],
                    output_types=["value"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ]
        )

    async def execute(self, key: str) -> ToolResult:
        try:
            import redis.asyncio as redis

            # Connect to Redis
            r = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379)),
                db=0,
                decode_responses=True
            )

            value = await r.get(key)
            await r.close()

            return ToolResult(
                success=True,
                output={
                    'key': key,
                    'value': value,
                    'exists': value is not None
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class RedisSetTool(Tool):
    """Set Redis key value"""

    def __init__(self):
        super().__init__()
        self.name = "redis_set"
        self.description = "Set value in Redis cache with optional TTL"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="key",
                type="string",
                description="Redis key to set",
                required=True
            ),
            ToolParameter(
                name="value",
                type="string",
                description="Value to store",
                required=True
            ),
            ToolParameter(
                name="ttl_seconds",
                type="number",
                description="Time to live in seconds (optional)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="redis_set",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.WRITE_DATA,
                    description="Write data to Redis cache"
                )
            ]
        )

    async def execute(self, key: str, value: str, ttl_seconds: int = None) -> ToolResult:
        try:
            import redis.asyncio as redis

            r = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379)),
                db=0,
                decode_responses=True
            )

            if ttl_seconds:
                await r.setex(key, ttl_seconds, value)
            else:
                await r.set(key, value)

            await r.close()

            return ToolResult(
                success=True,
                output={
                    'key': key,
                    'set': True,
                    'ttl': ttl_seconds
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class R2UploadTool(Tool):
    """Upload file to Cloudflare R2 storage"""

    def __init__(self):
        super().__init__()
        self.name = "r2_upload"
        self.description = "Upload file to Cloudflare R2 object storage"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Local file path to upload",
                required=True
            ),
            ToolParameter(
                name="object_key",
                type="string",
                description="Object key in R2 (destination path)",
                required=True
            ),
            ToolParameter(
                name="bucket",
                type="string",
                description="R2 bucket name",
                required=False,
                default="torinai-system-data",
                enum=["torinai-system-data", "torinai-short-term-memory", "torinai-ml-models", "dominion-labs-data"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="r2_upload",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.UPLOAD,
                    description="Upload files to Cloudflare R2 storage"
                )
            ]
        )

    async def execute(self, file_path: str, object_key: str, bucket: str = "torinai-system-data") -> ToolResult:
        try:
            import boto3

            file = Path(file_path).expanduser().resolve()
            if not file.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {file}")

            # Initialize R2 client
            s3_client = boto3.client(
                's3',
                endpoint_url=os.getenv('R2_ENDPOINT'),
                aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY')
            )

            # Upload file
            s3_client.upload_file(str(file), bucket, object_key)

            return ToolResult(
                success=True,
                output={
                    'file_path': str(file),
                    'bucket': bucket,
                    'object_key': object_key,
                    'uploaded': True,
                    'size_bytes': file.stat().st_size
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class R2DownloadTool(Tool):
    """Download file from Cloudflare R2 storage"""

    def __init__(self):
        super().__init__()
        self.name = "r2_download"
        self.description = "Download file from Cloudflare R2 object storage"
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="object_key",
                type="string",
                description="Object key in R2 (source path)",
                required=True
            ),
            ToolParameter(
                name="file_path",
                type="string",
                description="Local destination file path",
                required=True
            ),
            ToolParameter(
                name="bucket",
                type="string",
                description="R2 bucket name",
                required=False,
                default="torinai-system-data",
                enum=["torinai-system-data", "torinai-short-term-memory", "torinai-ml-models", "dominion-labs-data"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="r2_download",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOWNLOAD,
                    description="Download files from Cloudflare R2 storage"
                )
            ]
        )

    async def execute(self, object_key: str, file_path: str, bucket: str = "torinai-system-data") -> ToolResult:
        try:
            import boto3

            dest = Path(file_path).expanduser().resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Initialize R2 client
            s3_client = boto3.client(
                's3',
                endpoint_url=os.getenv('R2_ENDPOINT'),
                aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY')
            )

            # Download file
            s3_client.download_file(bucket, object_key, str(dest))

            return ToolResult(
                success=True,
                output={
                    'object_key': object_key,
                    'bucket': bucket,
                    'file_path': str(dest),
                    'downloaded': True,
                    'size_bytes': dest.stat().st_size
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class PostgresQueryTool(Tool):
    """Execute SQL on an outside PostgreSQL database."""

    def __init__(self):
        super().__init__()
        self.name = "postgres_query"
        self.description = ("Execute SQL on an outside PostgreSQL database, given its address and login "
                            "(SELECT, INSERT, UPDATE, DELETE). Never the substrate's own database.")
        self.category = ToolCategory.DATABASE
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(name="query", type="string",
                          description="SQL query to execute (use $1, $2 placeholders for parameters)",
                          required=True),
            ToolParameter(name="params", type="array",
                          description="Query parameters for parameterized queries", required=False),
            ToolParameter(name="host", type="string", description="Database server host", required=True),
            ToolParameter(name="port", type="integer", description="Database server port",
                          required=False, default=5432),
            ToolParameter(name="database", type="string", description="Database name", required=True),
            ToolParameter(name="user", type="string", description="Login user", required=True),
            ToolParameter(name="password", type="string", description="Login password", required=False,
                          default=""),
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="postgres_query",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.QUERY_DATABASE,
                    description="Execute SQL queries on an outside PostgreSQL database"
                ),
                CapabilityMetadata(
                    capability=Capability.MODIFY_DATABASE,
                    description="Modify an outside PostgreSQL database via INSERT/UPDATE/DELETE",
                    input_types=["sql", "params"],
                    output_types=["affected_rows"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=8
                )
            ]
        )

    async def execute(self, query: str, host: str, database: str, user: str, password: str = "",
                      port: int = 5432, params: List = None) -> ToolResult:
        try:
            conn = await _outside_postgres(host, port, database, user, password)
        except OutsideDatabaseRefused as refused:
            return ToolResult(success=False, output=None, error=str(refused))
        except Exception as e:
            logger.error(f"PostgreSQL connection error ({host}:{port}/{database}): {e}")
            return ToolResult(success=False, output=None, error=str(e))
        try:
            query_upper = query.strip().upper()
            is_select = query_upper.startswith("SELECT") or query_upper.startswith("WITH")
            params_tuple: Tuple = tuple(params or ())
            if is_select:
                rows = [dict(row) for row in await conn.fetch(query, *params_tuple)]
                return ToolResult(success=True, output={"query": query, "database": database,
                                                        "rows": rows, "count": len(rows)})
            status = await conn.execute(query, *params_tuple)
            affected_rows: Optional[int] = None
            if status:
                # asyncpg status examples: "INSERT 0 1", "UPDATE 3"
                parts = status.split()
                if parts and parts[-1].isdigit():
                    affected_rows = int(parts[-1])
            return ToolResult(success=True, output={"query": query, "database": database,
                                                    "status": status, "affected_rows": affected_rows})
        except Exception as e:
            logger.error(f"PostgreSQL query error ({host}:{port}/{database}): {e}")
            return ToolResult(success=False, output=None, error=str(e))
        finally:
            await conn.close()


