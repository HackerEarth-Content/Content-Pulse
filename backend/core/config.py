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
    SLACK_WRITES_ENABLED: bool
    SLACK_BOT_TOKEN: str = ""
    # Tagged on every plan-filed message and the daily update digest, same as
    # a manager cc'd on every status mail. Resolved to a Slack mention via the
    # member row with this email, same as JIRA_EMAIL identifies a person.
    SLACK_PLAN_MENTION_EMAIL: str = "sreejith@hackerearth.com"

    # Gmail SMTP for the daily plan reminder. EMAIL_ENABLED is the same guard as
    # the Jira and Slack flags — off unless you mean it.
    EMAIL_ENABLED: bool = False
    GMAIL_SMTP_USER: str = ""
    GMAIL_SMTP_APP_PASSWORD: str = ""
    SUPPORT_EMAIL: str = ""
    # When the nudge goes out, in the team's timezone.
    PLAN_REMINDER_HOUR: int = 11
    SLACK_CHANNEL: str = "ai-initiatives"

    # Reports run Mon-Sun; flip to 6 for Sun-Sat.
    WEEK_START: int = 0
    TIMEZONE: str = "Asia/Kolkata"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def superadmins(self) -> set[str]:
        return {
            e.strip().lower() for e in self.SUPERADMIN_EMAILS.split(",") if e.strip()
        }

    @property
    def sqlalchemy_url(self) -> str:
        return self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")


settings = Settings()
