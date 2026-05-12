"""AppSetting — admin-managed deployment-wide config, stored encrypted.

Single-tenant by design. The current consumers are:
  - "anthropic_api_key": the LLM key, settable from the Settings page so
    self-hosters don't have to edit .env to get started.
"""

from sqlalchemy import Column, String, Text, DateTime, func

from app.core.database import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value_encrypted = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
