from __future__ import annotations

import base64
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    SettingsConfigDict,
)
from sqlalchemy import URL


# =============================================================================
# PROJECT PATHS
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


# =============================================================================
# SHARED PYDANTIC SETTINGS CONFIGURATION
# =============================================================================
_BASE_SETTINGS_CONFIG = SettingsConfigDict(
    env_file=ENV_FILE,
    env_file_encoding="utf-8",
    case_sensitive=False,
    extra="ignore",
    validate_default=True,
    frozen=True,
)


# =============================================================================
# ENUMS
# =============================================================================
class Environment(str, Enum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

class StorageMode(str, Enum):
    LOCAL = "local"
    R2 = "r2"


# =============================================================================
# APPLICATION
# =============================================================================
class AppSettings(BaseSettings):
    model_config = _BASE_SETTINGS_CONFIG | SettingsConfigDict( env_prefix="APP_",)    
    name: str = "Learning Management System"
    version: str = "0.1.0"
    environment: Environment = Environment.LOCAL
    debug: bool = False    

    @property
    def is_local(self) -> bool:
        return self.environment == Environment.LOCAL  

    @property
    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT

    @property
    def is_staging(self) -> bool:
        return self.environment == Environment.STAGING

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def is_deployed(self) -> bool:
        """
        Environments where production-grade secrets should be mandatory.
        """
        return self.environment in {
            Environment.STAGING,
            Environment.PRODUCTION,
        }

# =============================================================================
# HTTP SERVER
# =============================================================================

class ServerSettings(BaseSettings):
    model_config = (
        _BASE_SETTINGS_CONFIG
        | SettingsConfigDict(
            env_prefix="SERVER_",
        )
    )

    host: str = "0.0.0.0"
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
    )

    # IPs / CIDRs trusted by the ASGI server/reverse-proxy integration.
    forwarded_allow_ips: str = "127.0.0.1"

# =============================================================================
# API
# =============================================================================
class APISettings(BaseSettings):
    model_config = (
        _BASE_SETTINGS_CONFIG
        | SettingsConfigDict(
            env_prefix="API_",
        )
    )

    prefix: str = "/api/v1"

    # We deliberately accept:
    #
    # API_CORS_ORIGINS=https://a.com,https://b.com
    #
    # rather than forcing JSON arrays into environment variables.
    cors_origins: Annotated[
        list[str],
        NoDecode,
    ] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
        ]
    )

    trusted_hosts: Annotated[
        list[str],
        NoDecode,
    ] = Field(
        default_factory=lambda: [
            "localhost",
            "127.0.0.1",
        ]
    )

    request_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
    )

    @field_validator("prefix")
    @classmethod
    def validate_prefix(
        cls,
        value: str,
    ) -> str:
        value = value.strip()

        if not value.startswith("/"):
            raise ValueError(
                "API_PREFIX must start with '/'"
            )

        return value.rstrip("/") or "/"

    @field_validator(
        "cors_origins",
        "trusted_hosts",
        mode="before",
    )
    @classmethod
    def split_csv(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, str):
            return [
                item.strip()
                for item in value.split(",")
                if item.strip()
            ]

        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(
        cls,
        origins: list[str],
    ) -> list[str]:
        for origin in origins:

            if origin == "*":
                continue

            if not origin.startswith(
                (
                    "http://",
                    "https://",
                )
            ):
                raise ValueError(
                    f"Invalid CORS origin {origin!r}; "
                    "expected http:// or https://"
                )

        return origins


# =============================================================================
# DATABASE
# =============================================================================
DatabaseSSLMode = Literal[
    "disable",
    "allow",
    "prefer",
    "require",
    "verify-ca",
    "verify-full",
]


class _DatabaseBaseSettings(BaseSettings):
    """
    Shared PostgreSQL connection configuration.
    This class contains no role-specific credentials.
    Runtime credentials and migration credentials live in separate subclasses.
    """
    model_config = (
        _BASE_SETTINGS_CONFIG
        | SettingsConfigDict(
            env_prefix="DATABASE_",
        )
    )

    host: str = "localhost"
    port: int = Field(default=5432,ge=1,le=65535,)
    name: str = "lms_platform_db"
    connect_timeout_seconds: int = Field( default=10,ge=1,le=300,)
    ssl_mode: DatabaseSSLMode = "disable"

    def _build_url(
        self,
        *,
        username: str,
        password: SecretStr,
        application_name: str,
    ) -> URL:
        """
        Create a SQLAlchemy PostgreSQL URL safely.

        SQLAlchemy URL.create() handles special characters in usernames and
        passwords correctly, avoiding manual URL quoting/encoding.
        """

        query: dict[str, str] = {
            "application_name": application_name,
            "connect_timeout": str(
                self.connect_timeout_seconds
            ),
            "sslmode": self.ssl_mode,
        }

        return URL.create(
            drivername="postgresql+psycopg",
            username=username,
            password=password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
            query=query,
        )


# =============================================================================
# FASTAPI RUNTIME DATABASE SETTINGS
# =============================================================================
class RuntimeDatabaseSettings(
    _DatabaseBaseSettings
):
    """
    Database configuration used by the running application.

    The runtime PostgreSQL role should normally have only the minimum DML
    privileges needed by the application.

    It should NOT be the schema owner and should NOT normally have DDL
    permissions.
    """

    runtime_username: str = "lms_runtime"
    runtime_password: SecretStr = SecretStr("")
    runtime_application_name: str = "lms-api"

    # -------------------------------------------------------------------------
    # SQLAlchemy QueuePool tuning
    # -------------------------------------------------------------------------
    pool_size: int = Field( default=10, ge=1, le=500, )
    max_overflow: int = Field( default=20, ge=0, le=1000,)
    pool_timeout_seconds: float = Field(default=30.0,gt=0, )
    pool_recycle_seconds: int = Field(default=1800,  ge=0,)
    pool_pre_ping: bool = True
    echo_sql: bool = False

    # -------------------------------------------------------------------------
    # Postgres session-level hardening (set via `connect_args={"options": ...}`
    # on the engine, not query parameters -- these are session GUCs, applied
    # to every connection the pool opens). A request whose query runs away
    # must not be able to hold a connection, and therefore a slot in a
    # bounded pool, forever.
    # -------------------------------------------------------------------------
    statement_timeout_ms: int = Field(default=30_000, ge=0, description="0 disables the timeout")
    lock_timeout_ms: int = Field(default=10_000, ge=0)
    idle_in_transaction_timeout_ms: int = Field(default=60_000, ge=0)

    def url(self) -> URL:
        """
        SQLAlchemy URL for FastAPI runtime database access.
        Use this with create_async_engine().
        """
        return self._build_url(
            username=self.runtime_username,
            password=self.runtime_password,
            application_name=self.runtime_application_name,
        )


# =============================================================================
# ALEMBIC MIGRATION DATABASE SETTINGS
# =============================================================================
class MigrationDatabaseSettings(
    _DatabaseBaseSettings
):
    """
    Database configuration used exclusively by Alembic / deployment jobs.
    This PostgreSQL role may have the DDL permissions required to perform
    schema migrations.
    These credentials should not normally be injected into the FastAPI
    application container/process.
    """

    migration_username: str = "lms_migrator"
    migration_password: SecretStr = SecretStr("")
    migration_application_name: str = ("lms-alembic")

    def url(self) -> URL:
        """
        SQLAlchemy URL for Alembic.
        Use this with sqlalchemy.create_engine().
        """

        return self._build_url(
            username=self.migration_username,
            password=self.migration_password,
            application_name=(
                self.migration_application_name
            ),
        )

# =============================================================================
# SECURITY
# =============================================================================
class SecuritySettings(BaseSettings):
    model_config = (
        _BASE_SETTINGS_CONFIG
        | SettingsConfigDict(
            env_prefix="SECURITY_",
        )
    )

    # -------------------------------------------------------------------------
    # JWT
    # -------------------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr("")
    jwt_algorithm: Literal[
        "HS256",
        "HS384",
        "HS512",
    ] = "HS256"
    jwt_issuer: str = "lms-api"
    jwt_audience: str = "lms-clients"
    access_token_ttl_seconds: int = Field(default=900, gt=0,)
    refresh_token_ttl_seconds: int = Field(default=1_209_600,gt=0,)

    # "Remember me" (spec §3) -- a deliberately longer refresh lifetime for
    # a trusted personal device. Separate from the default so raising one
    # doesn't silently raise the other.
    remember_me_refresh_token_ttl_seconds: int = Field(default=2_592_000, gt=0)

    # -------------------------------------------------------------------------
    # Brute-force protection (spec §20)
    # -------------------------------------------------------------------------
    # A temporary lockout, not a permanent one: permanent lockouts turn a
    # guessable username into a denial-of-service against that account, and
    # generate support load for the legitimate owner.
    max_failed_login_attempts: int = Field(default=5, ge=1, le=100)
    lockout_duration_seconds: int = Field(default=900, gt=0)

    # -------------------------------------------------------------------------
    # Envelope Encryption
    # -------------------------------------------------------------------------
    master_encryption_key: SecretStr = ( SecretStr(""))

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(
        cls,
        value: SecretStr,
    ) -> SecretStr:

        raw = value.get_secret_value()

        if (
            raw
            and len(
                raw.encode("utf-8")
            )
            < 32
        ):
            raise ValueError(
                "SECURITY_JWT_SECRET must "
                "be at least 32 bytes"
            )

        return value

    @field_validator(
        "master_encryption_key"
    )
    @classmethod
    def validate_master_encryption_key(
        cls,
        value: SecretStr,
    ) -> SecretStr:

        raw = value.get_secret_value()

        if not raw:
            return value

        try:
            decoded = base64.b64decode(
                raw,
                validate=True,
            )

        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                "SECURITY_MASTER_ENCRYPTION_KEY "
                "must be valid Base64"
            ) from exc

        if len(decoded) != 32:
            raise ValueError(
                "SECURITY_MASTER_ENCRYPTION_KEY "
                "must decode to exactly 32 bytes"
            )

        return value

    def master_key_bytes(self) -> bytes:
        """
        Return the decoded 32-byte master encryption key.

        Secret values should only be unwrapped at the point where they are
        actually required.
        """

        raw = (
            self.master_encryption_key
            .get_secret_value()
        )

        if not raw:
            raise RuntimeError(
                "SECURITY_MASTER_ENCRYPTION_KEY "
                "is not configured"
            )

        return base64.b64decode(
            raw,
            validate=True,
        )

# =============================================================================
# CONNECTION ORCHESTRATOR
# =============================================================================
class ConnectionSettings(BaseSettings):
    """
    Settings for live target-database sessions.

    Remove this class if the LMS does not provide target-database connectivity.
    """

    model_config = (
        _BASE_SETTINGS_CONFIG
        | SettingsConfigDict(
            env_prefix="CONN_",
        )
    )

    max_sessions_per_user: int = Field(
        default=10,
        ge=1,
    )

    session_idle_ttl_seconds: int = Field(
        default=1800,
        gt=0,
    )

    reaper_interval_seconds: int = Field(
        default=60,
        gt=0,
    )

    connect_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
    )

    session_pool_min_size: int = Field(
        default=1,
        ge=1,
    )

    session_pool_max_size: int = Field(
        default=5,
        ge=1,
    )

    @model_validator(mode="after")
    def validate_pool_bounds(
        self,
    ) -> "ConnectionSettings":

        if (
            self.session_pool_max_size
            < self.session_pool_min_size
        ):
            raise ValueError(
                "CONN_SESSION_POOL_MAX_SIZE "
                "must be >= "
                "CONN_SESSION_POOL_MIN_SIZE"
            )

        return self

# =============================================================================
# QUERY ENGINE
# =============================================================================
class QuerySettings(BaseSettings):
    model_config = (
        _BASE_SETTINGS_CONFIG
        | SettingsConfigDict(
            env_prefix="QUERY_",
        )
    )

    default_max_rows: int = Field(
        default=1000,
        ge=1,
    )

    max_rows_limit: int = Field(
        default=100_000,
        ge=1,
    )

    stream_batch_size: int = Field(
        default=500,
        ge=1,
    )

    statement_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
    )

    @model_validator(mode="after")
    def validate_row_limits(
        self,
    ) -> "QuerySettings":

        if (
            self.default_max_rows
            > self.max_rows_limit
        ):
            raise ValueError(
                "QUERY_DEFAULT_MAX_ROWS must "
                "be <= QUERY_MAX_ROWS_LIMIT"
            )

        return self

# =============================================================================
# STORAGE
# =============================================================================
class StorageSettings(BaseSettings):
    model_config = (
        _BASE_SETTINGS_CONFIG
        | SettingsConfigDict(
            env_prefix="STORAGE_",
        )
    )

    mode: StorageMode = StorageMode.LOCAL

    local_path: Path = (
        PROJECT_ROOT
        / "var"
        / "storage"
    )

    # -------------------------------------------------------------------------
    # Cloudflare R2
    # -------------------------------------------------------------------------

    r2_account_id: str = ""

    r2_bucket: str = ""

    r2_access_key_id: str = ""

    r2_secret_access_key: SecretStr = (
        SecretStr("")
    )

    # Seconds a presigned R2 download link stays valid. Short by default:
    # the link carries its own authorisation, so anyone it is forwarded to
    # can use it until it expires, regardless of the LMS's own permissions.
    r2_presign_expiry_seconds: int = Field(default=300, ge=30, le=86_400)

    # -------------------------------------------------------------------------
    # Upload limits and validation (spec §20 "File validation")
    # -------------------------------------------------------------------------

    max_upload_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)

    # Allowlist, not a blocklist. A blocklist of "dangerous" extensions is
    # unbounded and always one new format behind; an allowlist fails closed
    # on anything unanticipated. Empty means "allow any content type", which
    # is deliberately NOT the default.
    allowed_mime_types: Annotated[
        list[str],
        NoDecode,
    ] = Field(
        default_factory=lambda: [
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/zip",
            "text/plain",
            "text/csv",
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "video/mp4",
            "video/webm",
            "audio/mpeg",
            "audio/wav",
            "audio/ogg",
        ]
    )

    @field_validator(
        "allowed_mime_types",
        mode="before",
    )
    @classmethod
    def split_mime_csv(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, str):
            return [
                item.strip().lower()
                for item in value.split(",")
                if item.strip()
            ]
        return value

    @model_validator(mode="after")
    def validate_backend(
        self,
    ) -> "StorageSettings":

        if self.mode != StorageMode.R2:
            return self

        missing: list[str] = []

        if not self.r2_account_id:
            missing.append(
                "STORAGE_R2_ACCOUNT_ID"
            )

        if not self.r2_bucket:
            missing.append(
                "STORAGE_R2_BUCKET"
            )

        if not self.r2_access_key_id:
            missing.append(
                "STORAGE_R2_ACCESS_KEY_ID"
            )

        if not (
            self.r2_secret_access_key
            .get_secret_value()
        ):
            missing.append(
                "STORAGE_R2_SECRET_ACCESS_KEY"
            )

        if missing:
            raise ValueError(
                "R2 storage is enabled but "
                "the following settings are missing: "
                + ", ".join(missing)
            )

        return self

    @property
    def r2_endpoint_url(self) -> str:
        if not self.r2_account_id:
            raise RuntimeError(
                "STORAGE_R2_ACCOUNT_ID "
                "is not configured"
            )

        return (
            "https://"
            f"{self.r2_account_id}"
            ".r2.cloudflarestorage.com"
        )

# =============================================================================
# MAIL
# =============================================================================
class MailSettings(BaseSettings):
    model_config = (
        _BASE_SETTINGS_CONFIG
        | SettingsConfigDict(
            env_prefix="MAIL_",
        )
    )

    enabled: bool = False
    username: str = ""
    password: SecretStr = SecretStr("")
    # Preserve existing MAIL_FROM environment variable naming.
    from_email: str = Field(
        default="",
        validation_alias="MAIL_FROM",
    )

    from_name: str = "LMS"
    server: str = ""
    port: int = Field(
        default=587,
        ge=1,
        le=65535,
    )
    tls: bool = True
    ssl: bool = False
    suppress_send: bool = False
    template_dir: Path = (
        PROJECT_ROOT
        / "templates"
        / "email"
    )

    @model_validator(mode="after")
    def validate_mail(
        self,
    ) -> "MailSettings":

        if self.tls and self.ssl:
            raise ValueError(
                "MAIL_TLS and MAIL_SSL "
                "cannot both be true"
            )

        if not self.enabled:
            return self

        missing: list[str] = []

        if not self.server:
            missing.append(
                "MAIL_SERVER"
            )

        if not self.from_email:
            missing.append(
                "MAIL_FROM"
            )

        username_set = bool(
            self.username
        )

        password_set = bool(
            self.password.get_secret_value()
        )

        if username_set != password_set:
            raise ValueError(
                "MAIL_USERNAME and MAIL_PASSWORD "
                "must either both be configured "
                "or both be empty"
            )

        if missing:
            raise ValueError(
                "Mail is enabled but the following "
                "settings are missing: "
                + ", ".join(missing)
            )

        return self

# =============================================================================
# LOGGING
# =============================================================================
class LoggingSettings(BaseSettings):
    model_config = (
        _BASE_SETTINGS_CONFIG
        | SettingsConfigDict(
            env_prefix="LOG_",
        )
    )

    level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "INFO"

    format: Literal[
        "json",
        "console",
    ] = "json"

# =============================================================================
# ROOT APPLICATION SETTINGS
# =============================================================================
class Settings(BaseModel):
    """
    Configuration required by the running FastAPI application.

    IMPORTANT:

    MigrationDatabaseSettings is deliberately NOT included here.

    Therefore:

        get_settings()

    does not load or expose Alembic's migration password.

    Alembic should explicitly use:

        get_migration_database_settings()
    """

    model_config = ConfigDict(
        frozen=True,
    )

    app: AppSettings = Field(
        default_factory=AppSettings,
    )

    server: ServerSettings = Field(
        default_factory=ServerSettings,
    )

    api: APISettings = Field(
        default_factory=APISettings,
    )

    database: RuntimeDatabaseSettings = Field(
        default_factory=RuntimeDatabaseSettings,
    )

    security: SecuritySettings = Field(
        default_factory=SecuritySettings,
    )

    connections: ConnectionSettings = Field(
        default_factory=ConnectionSettings,
    )

    query: QuerySettings = Field(
        default_factory=QuerySettings,
    )

    storage: StorageSettings = Field(
        default_factory=StorageSettings,
    )

    mail: MailSettings = Field(
        default_factory=MailSettings,
    )

    logging: LoggingSettings = Field(
        default_factory=LoggingSettings,
    )

    # =========================================================================
    # CROSS-SECTION DEPLOYMENT VALIDATION
    # =========================================================================

    @model_validator(mode="after")
    def validate_deployment_safety(
        self,
    ) -> "Settings":

        # ---------------------------------------------------------------------
        # Staging + Production
        # ---------------------------------------------------------------------

        if not self.app.is_deployed:
            return self

        missing: list[str] = []

        if not (
            self.database.runtime_password
            .get_secret_value()
        ):
            missing.append(
                "DATABASE_RUNTIME_PASSWORD"
            )

        if not (
            self.security.jwt_secret
            .get_secret_value()
        ):
            missing.append(
                "SECURITY_JWT_SECRET"
            )

        if not (
            self.security
            .master_encryption_key
            .get_secret_value()
        ):
            missing.append(
                "SECURITY_MASTER_ENCRYPTION_KEY"
            )

        if missing:
            raise ValueError(
                "Missing required secrets for "
                f"{self.app.environment.value}: "
                + ", ".join(missing)
            )

        # ---------------------------------------------------------------------
        # Production-only hardening
        # ---------------------------------------------------------------------

        if self.app.is_production:

            errors: list[str] = []

            # -----------------------------------------------------------------
            # Debug
            # -----------------------------------------------------------------

            if self.app.debug:
                errors.append(
                    "APP_DEBUG must be false "
                    "in production"
                )

            # -----------------------------------------------------------------
            # SQL logging
            # -----------------------------------------------------------------

            if self.database.echo_sql:
                errors.append(
                    "DATABASE_ECHO_SQL must be false "
                    "in production"
                )

            # -----------------------------------------------------------------
            # PostgreSQL TLS
            # -----------------------------------------------------------------

            if self.database.ssl_mode in {
                "disable",
                "allow",
                "prefer",
            }:
                errors.append(
                    "DATABASE_SSL_MODE must be "
                    "require, verify-ca, or verify-full "
                    "in production"
                )

            # -----------------------------------------------------------------
            # CORS
            # -----------------------------------------------------------------

            if "*" in self.api.cors_origins:
                errors.append(
                    "API_CORS_ORIGINS cannot contain "
                    "'*' in production"
                )

            if any(
                (
                    "localhost" in origin
                    or "127.0.0.1" in origin
                )
                for origin
                in self.api.cors_origins
            ):
                errors.append(
                    "API_CORS_ORIGINS cannot use "
                    "localhost in production"
                )

            # -----------------------------------------------------------------
            # Trusted hosts
            # -----------------------------------------------------------------

            if "*" in self.api.trusted_hosts:
                errors.append(
                    "API_TRUSTED_HOSTS cannot contain "
                    "'*' in production"
                )

            # -----------------------------------------------------------------
            # Reverse proxy trust
            # -----------------------------------------------------------------

            if (
                self.server
                .forwarded_allow_ips
                .strip()
                == "*"
            ):
                errors.append(
                    "SERVER_FORWARDED_ALLOW_IPS "
                    "cannot be '*' in production"
                )

            # -----------------------------------------------------------------
            # Mail
            # -----------------------------------------------------------------

            if (
                self.mail.enabled
                and self.mail.suppress_send
            ):
                errors.append(
                    "MAIL_SUPPRESS_SEND must be false "
                    "when mail is enabled in production"
                )

            # -----------------------------------------------------------------
            # Final production validation
            # -----------------------------------------------------------------

            if errors:
                raise ValueError(
                    "Unsafe production configuration: "
                    + "; ".join(errors)
                )

        return self

# =============================================================================
# SETTINGS FACTORIES
# =============================================================================
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the process-wide application settings.

    Intended usage:

        from backend.core.config import get_settings

        settings = get_settings()
    """

    return Settings()

@lru_cache(maxsize=1)
def get_runtime_database_settings(
) -> RuntimeDatabaseSettings:
    """
    Load only FastAPI runtime database configuration.

    Useful in database bootstrap modules that do not need all application
    configuration.
    """

    return RuntimeDatabaseSettings()

@lru_cache(maxsize=1)
def get_migration_database_settings(
) -> MigrationDatabaseSettings:
    """
    Load only Alembic migration database configuration.

    This deliberately avoids loading:

        SECURITY_JWT_SECRET
        SECURITY_MASTER_ENCRYPTION_KEY
        DATABASE_RUNTIME_PASSWORD
        MAIL_PASSWORD
        STORAGE_R2_SECRET_ACCESS_KEY

    This separation is important for CI/CD and least-privilege deployment
    architecture.
    """

    settings = MigrationDatabaseSettings()

    if not (
        settings.migration_password
        .get_secret_value()
    ):
        raise ValueError(
            "DATABASE_MIGRATION_PASSWORD "
            "must be configured for Alembic"
        )

    return settings