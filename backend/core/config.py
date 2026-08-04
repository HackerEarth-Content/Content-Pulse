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
    # Comma-separated. Empty means any Google account may sign in.
    ALLOWED_EMAILS: str = ""

    INTAKE_TOKEN: str = ""

    JIRA_BASE_URL: str = "https://hackerearth.atlassian.net"
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""

    SLACK_BOT_TOKEN: str = ""
    SLACK_CHANNEL: str = "content-dashboard"

    # Reports run Mon-Sun; flip to 6 for Sun-Sat.
    WEEK_START: int = 0
    TIMEZONE: str = "Asia/Kolkata"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def sqlalchemy_url(self) -> str:
        return self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")


settings = Settings()
