from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Any '#' or '@' in the password must be percent-encoded or the URL
    # silently truncates at that character.
    DATABASE_URL: str
    ENVIRONMENT: str = "development"

    USER_SECRET: str
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    FRONTEND_URL: str = "http://localhost:5173"
    API_BASE_URL: str = "http://localhost:8000"
    # Always resolve to an admin member, creating one if missing. Sourced from
    # env so a bad database edit can never lock every administrator out.
    SUPERADMIN_EMAILS: str = ""

    INTAKE_TOKEN: str = ""

    # Off by default. Reads are always allowed; creating and transitioning
    # issues requires opting in, so a test run or a stray background task can
    # never mint tickets in a live project.
    JIRA_WRITES_ENABLED: bool = False
    JIRA_BASE_URL: str = "https://hackerearth.atlassian.net"
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""

    # Same reasoning as JIRA_WRITES_ENABLED: posting to a team channel is
    # outward-facing and must be opted into, never a side effect of a test.
    SLACK_WRITES_ENABLED: bool = False
    SLACK_BOT_TOKEN: str = ""
    SLACK_CHANNEL: str = "content-dashboard"

    # Reports run Mon-Sun; flip to 6 for Sun-Sat.
    WEEK_START: int = 0
    TIMEZONE: str = "Asia/Kolkata"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def superadmins(self) -> set[str]:
        return {e.strip().lower() for e in self.SUPERADMIN_EMAILS.split(",") if e.strip()}

    @property
    def sqlalchemy_url(self) -> str:
        return self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")


settings = Settings()
