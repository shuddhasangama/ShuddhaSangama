import sys, time, uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import update, select, func
from app import create_app, phone
from models import Base, Investor, LoginSession, Admin, Challenge, Section

SID='VE'+'a'*32

class Fake:
    def __init__(self, sid=SID): self.sent=[]; self.checked=[]; self.sid=sid
    def send(self,number): self.sent.append(number); return self.sid
    def verify(self,sid,code,number=None): self.checked.append(number); return sid==self.sid and code=='123456'

def build(tmp_path, provider, number='+12025550123'):
    app=create_app(dict(TESTING=True,APP_ENV='development',SECRET_KEY='s'*48,LOOKUP_KEY='l'*48,DATA_ENCRYPTION_KEY=Fernet.generate_key().decode(),DATABASE_URL='sqlite:///'+str(tmp_path/'test.db'),PRIVATE_STORAGE=str(tmp_path/'documents'),OTP_PROVIDER=provider))
    ex=app.extensions; Base.metadata.create_all(ex['engine']); iid=str(uuid.uuid4())
    with ex['db'].begin() as db:
        db.add(Investor(id=iid,email_hash=ex['digest']('friend@example.com'),phone_hash=ex['digest']('phone:'+number),details=ex['enc'](dict(name='Friend',email='friend@example.com',phone=number,organisation='Company',city='Boston')),expires=int(time.time())+3600,created=int(time.time()),response=ex['enc']({}),notes=ex['enc']('')))
    return app,iid

@pytest.fixture
def env(tmp_path):
    provider=Fake()
    app,iid=build(tmp_path,provider)
    yield app,app.test_client(),provider,iid
    app.extensions['engine'].dispose()

def post(c,path,fields):
    c.get('/login')
    with c.session_transaction() as s: csrf=s['csrf']
    return c.post(path,data=dict(csrf=csrf,**fields))

def login(c,number='+1 (202) 555-0123'):
    post(c,'/login',{'phone':number})
    post(c,'/verify',{'otp':'123456'})
    post(c,'/consent',{'accept':'yes'})

def code(c,path):
    response=c.get(path)
    try: return response.status_code
    finally: response.close()

def admin_session(app,c):
    ex=app.extensions
    with ex['db'].begin() as db:
        db.add(Admin(id='owner',password_hash='unused',totp_secret=ex['enc']('test')))
        db.add(LoginSession(id=ex['digest']('admin-token'),subject='owner',role='admin',expires=int(time.time())+3600))
    c.get('/login')
    with c.session_transaction() as s: s['auth']='admin-token'

def test_protected_resources_and_login(env):
    app,c,p,i=env
    for path in ['/investors/','/investors/assets/room.js','/investors/assets/DhaShu-financial-plan.xlsx']:
        assert c.get(path).status_code==302
    login(c)
    assert p.sent==['+12025550123'] and p.checked==['+12025550123']
    assert code(c,'/investors/')==200
    assert code(c,'/investors/assets/room.js')==200
    assert code(c,'/investors/assets/DhaShu-financial-plan.xlsx')==200
    assert code(c,'/investor_backend/app.py')==404
    assert code(c,'/investors/assets/../../investor_backend/app.py')==404
    response=c.get('/investors/'); assert b'NO SIGN-IN' not in response.data; response.close()

def test_unapproved_csrf_and_attempt_limit(env):
    app,c,p,i=env
    assert c.post('/login',data={'phone':'+12025550123'}).status_code==400
    post(c,'/login',{'phone':'+919812345678'})
    post(c,'/verify',{'otp':'123456'})
    assert not p.sent and code(c,'/investors/')==302
    post(c,'/login',{'phone':'+12025550123'})
    for _ in range(5): post(c,'/verify',{'otp':'000000'})
    post(c,'/verify',{'otp':'123456'})
    assert code(c,'/investors/')==302

def test_email_is_not_a_login_identity(env):
    app,c,p,i=env
    post(c,'/login',{'phone':'friend@example.com'})
    post(c,'/verify',{'otp':'123456'})
    assert not p.sent and code(c,'/investors/')==302

def test_revocation_and_expiry(env):
    app,c,p,i=env; login(c)
    with app.extensions['db'].begin() as db: db.execute(update(Investor).values(status='revoked'))
    assert code(c,'/investors/assets/room.js')==302

def test_admin_directory(env):
    app,c,p,i=env; admin_session(app,c)
    assert b'Boston' in c.get('/admin').data
    assert post(c,'/admin/investors',dict(email='new@example.com',phone='+44 20 1234 5678',name='New',organisation='Work',city='London',days='30')).status_code==302
    assert b'London' in c.get('/admin').data
    assert post(c,'/admin/investors/'+i,dict(action='profile',name='Friend',phone='+12025550123',organisation='Updated',city='Seattle')).status_code==302
    assert b'Seattle' in c.get('/admin').data

def test_new_investor_can_log_in_with_their_number(env):
    app,c,p,i=env; admin_session(app,c)
    post(c,'/admin/investors',dict(email='dubai@example.com',phone='+971 50 123 4567',name='Dubai',days='30'))
    other=app.test_client()
    post(other,'/login',{'phone':'+971501234567'})
    assert p.sent==['+971501234567']

def test_changing_number_moves_login_and_clears_old_codes(env):
    app,c,p,i=env
    post(c,'/login',{'phone':'+12025550123'})
    admin=app.test_client(); admin_session(app,admin)
    assert post(admin,'/admin/investors/'+i,dict(action='profile',name='Friend',phone='+442012345678')).status_code==302
    with app.extensions['db']() as db:
        assert db.scalar(select(func.count()).select_from(Challenge).where(Challenge.used==0,Challenge.investor_id==i))==0
    old=app.test_client(); post(old,'/login',{'phone':'+12025550123'}); post(old,'/verify',{'otp':'123456'})
    assert code(old,'/investors/')==302
    new=app.test_client(); post(new,'/login',{'phone':'+442012345678'}); post(new,'/verify',{'otp':'123456'})
    assert p.sent[-1]=='+442012345678'

def test_number_cannot_be_shared_between_investors(env):
    app,c,p,i=env; admin_session(app,c)
    post(c,'/admin/investors',dict(email='second@example.com',phone='+919812345678',name='Second',days='30'))
    with app.extensions['db']() as db: second=db.scalars(select(Investor).where(Investor.id!=i)).one().id
    assert post(c,'/admin/investors/'+second,dict(action='profile',name='Second',phone='+12025550123')).status_code==400
    post(c,'/admin/investors',dict(email='third@example.com',phone='+1 202 555 0123',name='Third',days='30'))
    with app.extensions['db']() as db: assert db.scalar(select(func.count()).select_from(Investor))==2

def test_expired_challenge_and_rate_limit(env):
    app,c,p,i=env
    post(c,'/login',{'phone':'+12025550123'})
    assert post(c,'/login',{'phone':'+1 202 555 0123'}).status_code==429
    with app.extensions['db'].begin() as db: db.execute(update(Challenge).values(expires=0))
    post(c,'/verify',{'otp':'123456'})
    assert code(c,'/investors/')==302

def test_provider_failure_never_grants_access(env):
    from provider import ProviderUnavailable
    app,c,p,i=env
    def unavailable(number): raise ProviderUnavailable('test')
    p.send=unavailable
    post(c,'/login',{'phone':'+12025550123'})
    post(c,'/verify',{'otp':'123456'})
    assert code(c,'/investors/')==302

def test_admin_preview_and_duplicate(env):
    app,c,p,i=env; admin_session(app,c)
    assert code(c,'/investors/')==200
    assert code(c,'/investors/assets/room.js')==200
    post(c,'/admin/investors',dict(email='FRIEND@example.com',phone='+919812345678',name='Duplicate email',days='30'))
    post(c,'/admin/investors',dict(email='other@example.com',phone='+12025550123',name='Duplicate number',days='30'))
    post(c,'/admin/investors',dict(email='nophone@example.com',name='No phone',days='30'))
    with app.extensions['db']() as db: assert db.scalar(select(func.count()).select_from(Investor))==1

@pytest.mark.parametrize('raw,expected',[
    ('+91 98123 45678','+919812345678'),('0091-98123-45678','+919812345678'),
    ('+1 (202) 555-0123','+12025550123'),('+971 50 123 4567','+971501234567'),('+44 20 1234 5678','+442012345678')])
def test_phone_numbers_are_normalised(raw,expected):
    assert phone(raw)==expected

@pytest.mark.parametrize('raw',['','98123 45678','+0 123456789','+91 12345 67890','+91 98123','+1 2025','friend@example.com','+12025550123456789'])
def test_bad_phone_numbers_are_rejected(raw):
    with pytest.raises(ValueError): phone(raw)

def test_twilio_adapter_binds_approval_to_sid(monkeypatch):
    from provider import TwilioSms, ProviderUnavailable
    p=TwilioSms(); seen=[]
    def fake(resource,data): seen.append((resource,data)); return {'sid':'VE'+'b'*32,'status':'approved'}
    monkeypatch.setattr(p,'call',fake)
    assert not p.verify(SID,'123456')
    monkeypatch.setattr(p,'call',lambda resource,data: {'sid':SID,'status':'pending'})
    assert not p.verify(SID,'123456')
    assert p.send('+12025550123')==SID
    monkeypatch.setattr(p,'call',lambda resource,data: {'sid':SID,'status':'approved'})
    assert p.verify(SID,'123456')
    assert not p.verify('M91-abc','123456')
    with pytest.raises(ProviderUnavailable): p.send('+12025550123')
    def pending(resource,data): seen.append((resource,data)); return {'sid':SID,'status':'pending'}
    monkeypatch.setattr(p,'call',pending); p.send('+12025550123')
    assert seen[-1]==('Verifications',{'To':'+12025550123','Channel':'sms'})

def test_twilio_not_configured_fails_closed(monkeypatch):
    from provider import TwilioSms, ProviderUnavailable
    for key in ['TWILIO_ACCOUNT_SID','TWILIO_AUTH_TOKEN','TWILIO_VERIFY_SERVICE_SID']: monkeypatch.delenv(key,raising=False)
    with pytest.raises(ProviderUnavailable): TwilioSms().send('+12025550123')

class FakeResponse:
    def __init__(self,payload,status=200): self.payload=payload; self.status_code=status
    def json(self): return self.payload

def test_msg91_adapter_requests_and_results(monkeypatch):
    import provider
    from provider import Msg91Sms, ProviderUnavailable
    monkeypatch.setenv('MSG91_AUTH_KEY','K'*24); monkeypatch.setenv('MSG91_TEMPLATE_ID','6afe818d3d9bb415b50fd153')
    calls=[]; replies=[{'type':'success','request_id':'abc123XYZ'},{'type':'success','message':'OTP verified success'}]
    def fake_request(method,url,**kw): calls.append((method,url,kw)); return FakeResponse(replies.pop(0))
    monkeypatch.setattr(provider.requests,'request',fake_request)
    m=Msg91Sms(); sid=m.send('+919812345678')
    assert sid=='M91-abc123XYZ'
    method,url,kw=calls[0]
    assert method=='POST' and url=='https://control.msg91.com/api/v5/otp'
    assert kw['params']=={'template_id':'6afe818d3d9bb415b50fd153','mobile':'919812345678','otp_length':6,'otp_expiry':5}
    assert kw['headers']['authkey']=='K'*24 and 'K'*24 not in url and kw['allow_redirects'] is False
    assert m.verify(sid,'123456','+919812345678')
    method,url,kw=calls[1]
    assert method=='GET' and url.endswith('/otp/verify') and kw['params']=={'mobile':'919812345678','otp':'123456'}

def test_msg91_failures_never_approve(monkeypatch):
    import provider
    from provider import Msg91Sms, ProviderUnavailable
    monkeypatch.setenv('MSG91_AUTH_KEY','K'*24); monkeypatch.setenv('MSG91_TEMPLATE_ID','6afe818d3d9bb415b50fd153')
    m=Msg91Sms()
    monkeypatch.setattr(provider.requests,'request',lambda *a,**k: FakeResponse({'type':'error','message':'OTP not match'}))
    assert not m.verify('M91-abc','000000','+919812345678')
    with pytest.raises(ProviderUnavailable): m.send('+919812345678')
    monkeypatch.setattr(provider.requests,'request',lambda *a,**k: FakeResponse({'type':'success'},status=500))
    with pytest.raises(ProviderUnavailable): m.verify('M91-abc','123456','+919812345678')
    monkeypatch.setattr(provider.requests,'request',lambda *a,**k: FakeResponse({'type':'success'}))
    assert not m.verify('VE'+'a'*32,'123456','+919812345678')
    assert not m.verify('M91-abc','123456',None)
    monkeypatch.delenv('MSG91_AUTH_KEY')
    with pytest.raises(ProviderUnavailable): m.send('+919812345678')

def test_router_sends_each_country_through_the_right_provider(monkeypatch):
    from provider import SmsRouter
    monkeypatch.delenv('MSG91_COUNTRY_CODES',raising=False)
    msg91,twilio=Fake('M91-x'),Fake()
    r=SmsRouter(msg91,twilio)
    for number in ['+919812345678']: assert r.route(number) is msg91
    for number in ['+12025550123','+971501234567','+442012345678','+4915112345678','+14165550123']: assert r.route(number) is twilio
    monkeypatch.setenv('MSG91_COUNTRY_CODES','91,1')
    assert r.route('+12025550123') is msg91 and r.route('+14165550123') is msg91 and r.route('+971501234567') is twilio
    monkeypatch.setenv('MSG91_COUNTRY_CODES','bad,,0')
    assert r.route('+919812345678') is twilio

def test_login_end_to_end_uses_msg91_for_india_and_twilio_for_abroad(tmp_path):
    from provider import SmsRouter
    msg91,twilio=Fake('M91-x'),Fake()
    app,iid=build(tmp_path,SmsRouter(msg91,twilio),number='+919812345678')
    try:
        c=app.test_client(); login(c,'+91 98123 45678')
        assert msg91.sent==['+919812345678'] and msg91.checked==['+919812345678']
        assert not twilio.sent and code(c,'/investors/')==200
        admin=app.test_client(); admin_session(app,admin)
        post(admin,'/admin/investors',dict(email='us@example.com',phone='+1 202 555 0199',name='US',days='30'))
        us=app.test_client(); post(us,'/login',{'phone':'+12025550199'}); post(us,'/verify',{'otp':'123456'})
        assert twilio.sent==['+12025550199'] and twilio.checked==['+12025550199']
    finally:
        app.extensions['engine'].dispose()

def test_session_length_is_configurable(tmp_path,monkeypatch):
    monkeypatch.setenv('INVESTOR_SESSION_HOURS','24')
    p=Fake(); app,iid=build(tmp_path,p)
    try:
        c=app.test_client(); login(c)
        with app.extensions['db']() as db: record=db.scalar(select(LoginSession).where(LoginSession.role=='investor'))
        assert 23*3600 < record.expires-int(time.time()) <= 24*3600
    finally:
        app.extensions['engine'].dispose()


TERMS_JSON='{"raising":{"value":"TEST-RAISE","note":"test cap note"},"price":{"value":"TEST-PRICE-777","note":"test price note"},"valuation":{"value":"TEST-VALUE","note":"after the money"},"shareholder_note":"You become a shareholder of record.","holdings":[["TEST-ROW-A","TEST-SHARES-9","TEST-PCT"]],"terms":[["Instrument","Equity shares, issued directly"]]}'

def seed_terms(app):
    ex=app.extensions
    with ex['db'].begin() as db: db.add(Section(id='terms_data',title='Round terms data',body=ex['enc']('{}')))

def page(c,path):
    response=c.get(path)
    try: return response.status_code,response.get_data(as_text=True)
    finally: response.close()

def test_round_terms_reach_signed_in_investors_only(env):
    app,c,p,i=env; seed_terms(app)
    admin=app.test_client(); admin_session(app,admin)
    assert post(admin,'/admin/content/terms_data',{'body':TERMS_JSON}).status_code==302
    assert page(c,'/investors/')[0]==302
    login(c)
    status,html=page(c,'/investors/')
    assert status==200 and 'id="private-terms"' in html and 'TEST-PRICE-777' in html and 'test cap note' in html
    assert page(c,'/room/terms_data')[0]==404
    with app.extensions['db']() as db: stored=db.get(Section,'terms_data').body
    assert 'TEST-PRICE-777' not in stored

def test_round_terms_cannot_break_out_of_the_page(env):
    app,c,p,i=env; seed_terms(app)
    admin=app.test_client(); admin_session(app,admin)
    evil='{"raising":{"value":"x","note":"</script><img src=x onerror=alert(1)>"},"price":{"value":"y","note":""},"valuation":{"value":"z","note":""}}'
    assert post(admin,'/admin/content/terms_data',{'body':evil}).status_code==302
    login(c)
    status,html=page(c,'/investors/')
    assert '</script><img' not in html and '\\u003c/script\\u003e' in html

@pytest.mark.parametrize('body',['not json','[]','{"price":{"value":5,"note":""}}','{"surprise":1}','{"holdings":[["a","b"]]}','{"terms":[["a","b","c"]]}','{"holdings":'+str([["a","b","c"]]*21).replace("'",'"')+'}','{"raising":{"value":"x","note":"y","extra":"z"}}'])
def test_bad_round_terms_are_refused_and_not_saved(env,body):
    app,c,p,i=env; seed_terms(app)
    admin=app.test_client(); admin_session(app,admin)
    assert post(admin,'/admin/content/terms_data',{'body':body}).status_code==400
    login(c); status,html=page(c,'/investors/')
    assert status==200 and 'id="private-terms"' not in html

def test_page_without_round_terms_has_no_data_block(env):
    app,c,p,i=env; seed_terms(app); login(c)
    status,html=page(c,'/investors/')
    assert status==200 and 'private-terms' not in html
