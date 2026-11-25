import sys, time, uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import update
from app import create_app
from models import Base, Investor, LoginSession, Admin, Challenge

class Fake:
    def __init__(self): self.sent=[]
    def send(self,email): self.sent.append(email); return 'VE'+'a'*32
    def verify(self,sid,code): return sid=='VE'+'a'*32 and code=='123456'

@pytest.fixture
def env(tmp_path):
    provider=Fake()
    app=create_app(dict(TESTING=True,APP_ENV='development',SECRET_KEY='s'*48,LOOKUP_KEY='l'*48,DATA_ENCRYPTION_KEY=Fernet.generate_key().decode(),DATABASE_URL='sqlite:///'+str(tmp_path/'test.db'),PRIVATE_STORAGE=str(tmp_path/'documents'),OTP_PROVIDER=provider))
    ex=app.extensions; Base.metadata.create_all(ex['engine']); iid=str(uuid.uuid4())
    with ex['db'].begin() as db:
        db.add(Investor(id=iid,email_hash=ex['digest']('friend@example.com'),phone_hash=ex['digest']('email:friend@example.com'),details=ex['enc'](dict(name='Friend',email='friend@example.com',phone='+12025550123',organisation='Company',city='Boston')),expires=int(time.time())+3600,created=int(time.time()),response=ex['enc']({}),notes=ex['enc']('')))
    yield app,app.test_client(),provider,iid
    ex['engine'].dispose()

def post(c,path,fields):
    c.get('/login')
    with c.session_transaction() as s: csrf=s['csrf']
    return c.post(path,data=dict(csrf=csrf,**fields))

def login(c):
    post(c,'/login',{'email':'FRIEND@example.com'})
    post(c,'/verify',{'otp':'123456'})
    post(c,'/consent',{'accept':'yes'})

def test_protected_resources_and_login(env):
    app,c,p,i=env
    for path in ['/investors/','/investors/assets/room.js','/investors/assets/DhaShu-financial-plan.xlsx']:
        assert c.get(path).status_code==302
    login(c)
    assert p.sent==['friend@example.com']
    assert c.get('/investors/').status_code==200
    assert c.get('/investors/assets/room.js').status_code==200
    assert c.get('/investors/assets/DhaShu-financial-plan.xlsx').status_code==200
    assert c.get('/investor_backend/app.py').status_code==404
    assert c.get('/investors/assets/../../investor_backend/app.py').status_code==404
    assert b'NO SIGN-IN' not in c.get('/investors/').data

def test_unapproved_csrf_and_attempt_limit(env):
    app,c,p,i=env
    assert c.post('/login',data={'email':'friend@example.com'}).status_code==400
    post(c,'/login',{'email':'unknown@example.com'})
    post(c,'/verify',{'otp':'123456'})
    assert not p.sent and c.get('/investors/').status_code==302
    post(c,'/login',{'email':'friend@example.com'})
    for _ in range(5): post(c,'/verify',{'otp':'000000'})
    post(c,'/verify',{'otp':'123456'})
    assert c.get('/investors/').status_code==302

def test_revocation_and_expiry(env):
    app,c,p,i=env; login(c)
    with app.extensions['db'].begin() as db: db.execute(update(Investor).values(status='revoked'))
    assert c.get('/investors/assets/room.js').status_code==302

def test_admin_directory(env):
    app,c,p,i=env; ex=app.extensions
    with ex['db'].begin() as db:
        db.add(Admin(id='owner',password_hash='unused',totp_secret=ex['enc']('test')))
        db.add(LoginSession(id=ex['digest']('admin-token'),subject='owner',role='admin',expires=int(time.time())+3600))
    c.get('/login')
    with c.session_transaction() as s: s['auth']='admin-token'
    assert b'Boston' in c.get('/admin').data
    assert post(c,'/admin/investors',dict(email='new@example.com',phone='+442012345678',name='New',organisation='Work',city='London',days='30')).status_code==302
    assert b'London' in c.get('/admin').data
    assert post(c,'/admin/investors/'+i,dict(action='profile',name='Friend',phone='+12025550123',organisation='Updated',city='Seattle')).status_code==302
    assert b'Seattle' in c.get('/admin').data

def test_expired_challenge_and_rate_limit(env):
    app,c,p,i=env
    post(c,'/login',{'email':'friend@example.com'})
    assert post(c,'/login',{'email':'friend@example.com'}).status_code==429
    with app.extensions['db'].begin() as db: db.execute(update(Challenge).values(expires=0))
    post(c,'/verify',{'otp':'123456'})
    assert c.get('/investors/').status_code==302


def test_twilio_adapter_binds_approval_to_sid(monkeypatch):
    from provider import TwilioEmail, ProviderUnavailable
    p=TwilioEmail()
    monkeypatch.setattr(p,'call',lambda resource,data: {'sid':'VE'+'b'*32,'status':'approved'})
    assert not p.verify('VE'+'a'*32,'123456')
    monkeypatch.setattr(p,'call',lambda resource,data: {'sid':'VE'+'a'*32,'status':'pending'})
    assert not p.verify('VE'+'a'*32,'123456')
    assert p.send('friend@example.com')=='VE'+'a'*32
    monkeypatch.setattr(p,'call',lambda resource,data: {'sid':'VE'+'a'*32,'status':'approved'})
    assert p.verify('VE'+'a'*32,'123456')
    with pytest.raises(ProviderUnavailable): p.send('friend@example.com')

def test_provider_failure_never_grants_access(env):
    from provider import ProviderUnavailable
    app,c,p,i=env
    def unavailable(email): raise ProviderUnavailable('test')
    p.send=unavailable
    post(c,'/login',{'email':'friend@example.com'})
    post(c,'/verify',{'otp':'123456'})
    assert c.get('/investors/').status_code==302

def test_admin_preview_and_email_duplicate(env):
    app,c,p,i=env; ex=app.extensions
    with ex['db'].begin() as db:
        db.add(Admin(id='owner',password_hash='unused',totp_secret=ex['enc']('test')))
        db.add(LoginSession(id=ex['digest']('admin-token'),subject='owner',role='admin',expires=int(time.time())+3600))
    c.get('/login')
    with c.session_transaction() as s: s['auth']='admin-token'
    assert c.get('/investors/').status_code==200
    assert c.get('/investors/assets/room.js').status_code==200
    post(c,'/admin/investors',dict(email='FRIEND@example.com',name='Duplicate',days='30'))
    from sqlalchemy import select,func
    with ex['db']() as db: assert db.scalar(select(func.count()).select_from(Investor))==1
