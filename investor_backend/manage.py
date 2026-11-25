"""Operator commands; run in the application's environment, never a public endpoint."""
import argparse, getpass, secrets, json
from datetime import datetime, timezone
import pyotp
from cryptography.fernet import Fernet
from sqlalchemy import select, delete
from werkzeug.security import generate_password_hash

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('command',choices=['keys','init-db','admin','cleanup'])
    args=parser.parse_args()
    if args.command=='keys':
        print('PRIVATE: store securely; never paste into chat or commit.')
        print('SECRET_KEY='+secrets.token_urlsafe(48)); print('LOOKUP_KEY='+secrets.token_urlsafe(48))
        print('DATA_ENCRYPTION_KEY='+Fernet.generate_key().decode()); return
    from app import create_app, SECTIONS, now
    from models import Base, Admin, Section, Challenge, LoginSession, Rate
    app=create_app(); ext=app.extensions
    if args.command=='init-db':
        Base.metadata.create_all(ext['engine'])
        with ext['db'].begin() as db:
            for slug,title in SECTIONS.items():
                if not db.get(Section,slug):
                    db.add(Section(id=slug,title=title,body=ext['enc']('The founder will publish the approved material here.')))
        print('Dedicated Investor Room schema ready. Existing data preserved.'); return
    if args.command=='admin':
        user=input('Admin username: ').strip()
        if not user or len(user)>80: raise SystemExit('Invalid username')
        password=getpass.getpass('New password (at least 14 characters): ')
        if len(password)<14 or password!=getpass.getpass('Repeat password: '): raise SystemExit('Password validation failed')
        secret=pyotp.random_base32(); totp=pyotp.TOTP(secret)
        print('PRIVATE authenticator setup key:',secret)
        print('Enter this key in your authenticator app for ShuddhaSangama Investor Room.')
        if not totp.verify(getpass.getpass('Current authenticator code: ')): raise SystemExit('Authenticator validation failed')
        with ext['db'].begin() as db:
            a=db.get(Admin,user)
            if a:
                if input('Replace this admin credential? Type REPLACE: ')!='REPLACE': raise SystemExit('Cancelled')
                a.password_hash=generate_password_hash(password); a.totp_secret=ext['enc'](secret); a.last_totp=0
                db.execute(delete(LoginSession).where(LoginSession.role=='admin',LoginSession.subject==user))
            else: db.add(Admin(id=user,password_hash=generate_password_hash(password),totp_secret=ext['enc'](secret)))
        print('Admin ready. Credentials and setup keys are never committed.'); return
    if args.command=='cleanup':
        with ext['db'].begin() as db:
            for model in [Challenge,LoginSession,Rate]: db.execute(delete(model).where(model.expires<now()))
        print('Expired authentication records removed; investor activity preserved.')

if __name__=='__main__': main()
