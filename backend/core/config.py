from __future__ import annotations

import base64
import re
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
class GoogleSettings(BaseSettings):
    """Google Calendar. Calendar only: no Classroom, Meet or YouTube scopes are requested.

    `GOOGLE_EMAIL`, `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` come from `.env`.
    The LMS acts as **one organisation account** (`GOOGLE_EMAIL`): a Super Admin signs
    in once, and batch calendars are created in that account and shared with admins.
    """

    model_config = _BASE_SETTINGS_CONFIG | SettingsConfigDict(env_prefix="GOOGLE_")

    email: str = ""
    client_id: str = ""
    client_secret: SecretStr = SecretStr("")

    @field_validator("client_id", mode="before")
    @classmethod
    def _tidy_client_id(cls, value: object) -> object:
        """Accept the ID as it is commonly pasted: with quotes, or as a link (`http://<id>/`).

        A client ID is a public identifier (it is in every consent URL), and after removing a
        scheme and slashes what remains is either a valid ID or is rejected by
        `configuration_problem`, so this cannot turn a wrong value into an accepted one.
        """
        if not isinstance(value, str):
            return value
        text = value.strip().strip("\"'").strip()
        text = re.sub(r"^https?://", "", text, flags=re.I)
        return text.strip("/ ")

    # Must be registered as an "Authorized redirect URI" on the OAuth client in Google Cloud.
    redirect_uri: str = "http://localhost:3000/integrations/google/callback"

    # `calendar.app.created` is the narrowest scope that can create secondary calendars and
    # manage the events on them; it cannot read or touch the account's other calendars.
    # `calendar.acls` lets the LMS share a batch calendar with administrators.
    scopes: tuple[str, ...] = (
        "https://www.googleapis.com/auth/calendar.app.created",
        "https://www.googleapis.com/auth/calendar.acls",
        # Non-sensitive identity scopes: they let the LMS check WHICH Google account signed in,
        # so connecting the wrong one is refused instead of quietly writing to it.
        "openid",
        "email",
    )
    calendar_timezone: str = "Europe/London"
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    # Who is put on an event. Guests see the event on their own calendar, which is the
    # point ("tutors and students can see their schedule") -- but it means real people.
    invite_attendees: bool = True
    # "none": guests get the event without an email. "all" emails every change.
    send_updates: Literal["none", "externalOnly", "all"] = "none"
    share_with_admins: bool = True
    # Who may create, move and delete events from Google. Google cannot say who made an edit, so
    # write access to the calendar IS the authorisation: Super Admins write, Administrators view.
    admins_can_edit: bool = False
    # A change made to a session's time in Google is applied back to the LMS.
    pull_session_times: bool = True
    sync_interval_seconds: int = Field(default=300, ge=30)
    # Batches that ended longer ago than this are left alone (unless already mirrored).
    sync_past_days: int = Field(default=30, ge=0)
    # Google allows a bounded number of guests per event.
    max_attendees_per_event: int = Field(default=200, ge=1, le=200)

    @property
    def configuration_problem(self) -> str | None:
        """Why Google sign-in cannot work with these settings, in words an administrator can act on.

        A wrongly-pasted client ID does not fail here: Google answers with an "invalid_client"
        page in the browser. Catching the shape locally turns that dead end into an instruction.
        """
        client_id = self.client_id.strip()
        if not client_id:
            return "GOOGLE_CLIENT_ID is not set."
        if not self.client_secret.get_secret_value().strip():
            return "GOOGLE_CLIENT_SECRET is not set."
        if not re.fullmatch(r"\d{6,}-[A-Za-z0-9_-]{10,}\.apps\.googleusercontent\.com", client_id):
            return (
                "GOOGLE_CLIENT_ID does not look like a Google OAuth client ID. It should look like "
                "123456789012-abc...xyz.apps.googleusercontent.com. Copy it from Google Cloud Console > "
                "APIs & Services > Credentials > your Web application client."
            )
        return None

    @property
    def is_configured(self) -> bool:
        return self.configuration_problem is None


class LaitSettings(BaseSettings):
    """The external LAIT system users are synchronised from.

    `LAIT_API_BASE_URL` and `LAIT_API_KEY` already exist in `.env`; the rest
    have defaults that describe how the LAIT API was observed to behave.
    """

    model_config = (
        _BASE_SETTINGS_CONFIG
        | SettingsConfigDict(
            env_prefix="LAIT_",
        )
    )

    api_base_url: str = "https://api.londonacademyofit.co.uk"
    api_key: SecretStr = SecretStr("")
    # Verified against the live API: `Authorization: Bearer` is refused with
    # 401, `X-API-Key` is accepted. Configurable in case that changes.
    api_key_header: str = "X-API-Key"
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    # LAIT emits `RegistrationDate` as a naive local timestamp ("2026-09-17T
    # 15:10:20.987", no offset). It is UK time; the database stores UTC.
    source_timezone: str = "Europe/London"

    # Every synced account starts with this password, hashed with Argon2id
    # like any other. It is only safe because a synced account also starts
    # with `can_login = false`: the password cannot be used until a Super
    # Admin opens the account. Kept out of the source by living here, and a
    # SecretStr so it is never printed by accident.
    default_password: SecretStr = SecretStr("123456")

    # Whose id goes in `created_by` / `updated_by` for a *scheduled* run,
    # when no person clicked anything. Looked up by username at run time; the
    # run fails loudly if the account is missing rather than writing NULLs.
    sync_actor_username: str = "superadmin"

    # Seconds between passes when the worker runs with `--interval`.
    sync_interval_seconds: int = Field(default=900, ge=30)

    # A `RUNNING` row older than this is a process that died mid-run, not a
    # sync still in progress, and stops blocking new runs.
    stale_run_minutes: int = Field(default=30, ge=1)

    # Course pages are scraped for level, duration, prerequisites and category.
    # The URL comes from an external payload, so it is only ever fetched when it
    # is https and its host is one of these (or a subdomain of one).
    course_page_hosts: tuple[str, ...] = ("londonacademyofit.co.uk",)
    course_page_timeout_seconds: int = Field(default=20, ge=1)
    default_batch_capacity: int = Field(default=25, ge=1)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_base_url and self.api_key.get_secret_value())


class LocaleSettings(BaseSettings):
    """Working out where a signed-in person is, and so which time zone to show them.

    The person's public IP address is looked up once at sign-in and remembered against the account; it is looked
    up again only when the address changes (checked at every sign-in, and periodically while they are using the
    console). **This sends the person's IP address to a third-party service** (`LOCALE_LOOKUP_URL`, ipapi.co by
    default); set `LOCALE_ENABLED=false` to turn it off, and the browser's own time zone is used instead.
    """

    model_config = _BASE_SETTINGS_CONFIG | SettingsConfigDict(env_prefix="LOCALE_")

    enabled: bool = True
    # `{ip}` is replaced by a validated IP address (never free text), so the URL cannot be steered elsewhere.
    lookup_url: str = "https://ipapi.co/{ip}/json/"
    # Asked for the *server's* public address, used only when the caller's own address is private (local
    # development, where the browser and the API are on one machine, so it is also the person's address).
    public_ip_url: str = "https://icanhazip.com"
    use_server_ip_fallback: bool = True
    timeout_seconds: float = Field(default=3.0, gt=0, le=15)
    # How long a lookup result is reused for the same address, across all accounts.
    cache_ttl_seconds: int = Field(default=86_400, ge=60)
    # After a failed lookup (rate limit, outage), do not ask again for this long.
    failure_backoff_seconds: int = Field(default=600, ge=10)


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
    # Where the console lives (e.g. https://lms.example.com), for the "reply in the LMS" link in an email. Optional.
    app_url: str = ""
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
# =============================================================================
# REALTIME
# =============================================================================


class RealtimeBackend(str, Enum):
    """Where events are fanned out.

    `memory` is correct for exactly one process and is refused in a deployed
    environment -- see `backend/realtime/bus.py` for why that failure mode is
    worse than no realtime at all.
    """

    MEMORY = "memory"
    REDIS = "redis"


class RealtimeSettings(BaseSettings):
    model_config = _BASE_SETTINGS_CONFIG | SettingsConfigDict(env_prefix="REALTIME_")

    enabled: bool = True
    backend: RealtimeBackend = RealtimeBackend.MEMORY
    redis_url: str = ""

    # Long-lived connections die quietly: a proxy, a load balancer or a laptop
    # lid closing severs them with nothing sent either way. A comment frame on
    # this interval keeps the connection warm and, more usefully, is what makes
    # a dead one detectable from the server side.
    heartbeat_seconds: int = Field(default=25, ge=5, le=300)

    # A cap on how long one stream may run before the client is asked to
    # reconnect. Bounds the damage from a subscriber leak and gives rolling
    # deploys a point at which connections naturally move to new workers.
    max_stream_seconds: int = Field(default=60 * 30, ge=60)

    # One person, several tabs, is ordinary. One person with two hundred open
    # streams is a bug or an attack, and each one holds a task and a queue.
    max_streams_per_user: int = Field(default=8, ge=1, le=64)


# =============================================================================
# WEB PUSH
# =============================================================================


class PushSettings(BaseSettings):
    """Keys for notifying a browser that is not open.

    VAPID is an identity, not a secret shared with the push service: the public
    key is handed to the browser at subscribe time and the private key signs
    each send, which is how Mozilla or Google can tell that the message really
    came from this deployment. Generate a pair with:

        python -m backend.cli.generate_vapid_keys

    It prints `PUSH_VAPID_PUBLIC_KEY` / `PUSH_VAPID_PRIVATE_KEY` -- one
    underscore, matching every other group here. Two would be silently ignored
    and the feature would stay off with nothing saying why.

    Unset keys mean the feature is off, and off is honest: a Subscribe button
    that succeeds and then never delivers anything is worse than one that is
    not offered.
    """

    model_config = _BASE_SETTINGS_CONFIG | SettingsConfigDict(env_prefix="PUSH_")

    vapid_public_key: str = ""
    vapid_private_key: str = ""

    # Required by the spec so a push service has somebody to contact about a
    # misbehaving sender. `mailto:` or an https URL.
    subject: str = "mailto:admin@example.com"

    # How long a push service may hold an undelivered message for a device that
    # is offline. A day-old "you have a new message" is noise, not news.
    ttl_seconds: int = Field(default=60 * 60 * 12, ge=0, le=60 * 60 * 24 * 28)

    # One person on a laptop, a phone and a tablet is ordinary; thirty stale
    # subscriptions is a browser that keeps re-registering, and each one is a
    # network call on every notification.
    max_devices_per_user: int = Field(default=10, ge=1, le=50)

    @property
    def configured(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)


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

    realtime: RealtimeSettings = Field(default_factory=RealtimeSettings)
    push: PushSettings = Field(default_factory=PushSettings)
    google: GoogleSettings = Field(default_factory=GoogleSettings)
    locale: LocaleSettings = Field(default_factory=LocaleSettings)
    lait: LaitSettings = Field(
        default_factory=LaitSettings,
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