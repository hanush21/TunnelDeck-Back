from types import SimpleNamespace

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.persistence.models import Base
from app.modules.security.service import SecurityService


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


def test_totp_verification_success(db_session: Session) -> None:
    key = Fernet.generate_key().decode("utf-8")
    settings = SimpleNamespace(TOTP_ENCRYPTION_KEY=key)
    service = SecurityService(settings)

    secret = pyotp.random_base32()
    service.set_user_totp_secret(db_session, email="admin@example.com", secret=secret)
    db_session.commit()

    code = pyotp.TOTP(secret).now()
    service.verify_user_totp(db_session, "admin@example.com", code)


def test_totp_verification_invalid_code(db_session: Session) -> None:
    key = Fernet.generate_key().decode("utf-8")
    settings = SimpleNamespace(TOTP_ENCRYPTION_KEY=key)
    service = SecurityService(settings)

    secret = pyotp.random_base32()
    service.set_user_totp_secret(db_session, email="admin@example.com", secret=secret)
    db_session.commit()

    with pytest.raises(HTTPException):
        service.verify_user_totp(db_session, "admin@example.com", "000000")
