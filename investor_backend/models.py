"""Dedicated database. No dependencies on the DhaShu user database."""
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, Integer, ForeignKey

class Base(DeclarativeBase): pass

class Investor(Base):
    __tablename__ = 'investors'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email_hash: Mapped[str] = mapped_column(String(64), unique=True)
    phone_hash: Mapped[str] = mapped_column(String(64), unique=True)
    details: Mapped[str] = mapped_column(Text)  # encrypted name, phone, email, organisation
    status: Mapped[str] = mapped_column(String(20), default='approved')
    expires: Mapped[int] = mapped_column(Integer)
    created: Mapped[int] = mapped_column(Integer)
    accepted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    terms_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    interest: Mapped[str] = mapped_column(String(30), default='reviewing')
    response: Mapped[str] = mapped_column(Text)  # encrypted amount, decision time, questions
    notes: Mapped[str] = mapped_column(Text)

class Admin(Base):
    __tablename__ = 'admins'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    totp_secret: Mapped[str] = mapped_column(Text)
    last_totp: Mapped[int] = mapped_column(Integer, default=0)

class LoginSession(Base):
    __tablename__ = 'login_sessions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(12))
    expires: Mapped[int] = mapped_column(Integer)

class Challenge(Base):
    __tablename__ = 'challenges'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    investor_id: Mapped[str | None] = mapped_column(ForeignKey('investors.id'), nullable=True)
    provider_sid: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expires: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[int] = mapped_column(Integer, default=0)

class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investor_id: Mapped[str | None] = mapped_column(ForeignKey('investors.id'), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(60))
    actor: Mapped[str] = mapped_column(String(80))
    at: Mapped[int] = mapped_column(Integer, index=True)
    detail: Mapped[str] = mapped_column(Text)  # encrypted metadata; no OTP / auth key

class Rate(Base):
    __tablename__ = 'rates'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    expires: Mapped[int] = mapped_column(Integer, index=True)

class Document(Base):
    __tablename__ = 'documents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    filename: Mapped[str] = mapped_column(String(180))
    active: Mapped[int] = mapped_column(Integer, default=1)

class Section(Base):
    __tablename__ = 'sections'
    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)  # encrypted; rendered as text, never raw HTML
