import os, re, json, time, secrets, hashlib, hmac, uuid, io
from pathlib import Path
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, session, g, render_template, redirect, url_for, abort, flash, send_file
from sqlalchemy import create_engine, select, update, delete, func
from sqlalchemy.orm import sessionmaker
from cryptography.fernet import Fernet
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import pyotp
from models import Base, Investor, Admin, LoginSession, Challenge, Event, Rate, Document, Section
from provider import SmsRouter, ProviderUnavailable

TERMS = '2026-11-v1'
TERMS_ID = 'terms_data'  # private round figures (JSON) for the Ask chapter; stored encrypted, never in Git
INTERESTS = {'reviewing':'Still reviewing', 'liked':'I like the idea', 'not_for_me':'Not for me',
             'discussion':'I would like a discussion', 'invest':'I would like to invest'}
SECTIONS = {'idea':'The idea', 'product':'Product and progress', 'market':'Market and launch plan',
            'financials':'Revenue and operating plan', 'ask':'Investment ask and use of funds', 'team':'Team and roadmap'}
def now(): return int(time.time())
def phone(value):
    value = re.sub(r'[\s()\-.]', '', value.strip())
    if value.startswith('00'): value = '+' + value[2:]
    if not re.fullmatch(r'\+[1-9]\d{7,14}', value):
        raise ValueError('Enter the mobile number with its country code, for example +91 98xxxxxxxx or +1 202 555 0123.')
    if value.startswith('+91') and not re.fullmatch(r'\+91[6-9]\d{9}', value):
        raise ValueError('Indian mobile numbers use +91 followed by 10 digits.')
    return value

def clean_terms(raw):
    """Validate the private round terms so only plain text reaches the Investor Room page."""
    if not isinstance(raw, dict): raise ValueError('Round terms must be a JSON object.')
    def text(value, limit=300):
        if not isinstance(value, str) or len(value) > limit: raise ValueError(f'Each value must be text of at most {limit} characters.')
        return value.strip()
    out = {}
    for key in ('raising', 'price', 'valuation'):
        if key in raw:
            item = raw[key]
            if not isinstance(item, dict) or set(item) - {'value', 'note'}: raise ValueError(f'"{key}" needs only "value" and "note".')
            out[key] = {'value': text(item.get('value', ''), 60), 'note': text(item.get('note', ''), 120)}
    for key in ('shareholder_note', 'holdings_note'):
        if key in raw: out[key] = text(raw[key], 600)
    for key, width in (('holdings', 3), ('terms', 2)):
        if key in raw:
            rows = raw[key]
            if not isinstance(rows, list) or len(rows) > 20: raise ValueError(f'"{key}" must be a list of up to 20 rows.')
            out[key] = []
            for row in rows:
                if not isinstance(row, list) or len(row) != width: raise ValueError(f'Each "{key}" row needs exactly {width} values.')
                out[key].append([text(cell) for cell in row])
    unknown = set(raw) - set(out)
    if unknown: raise ValueError('Unknown field: ' + ', '.join(sorted(map(str, unknown))))
    return out

def email(value):
    value=value.strip().lower()
    if len(value)>254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",value):
        raise ValueError('Enter a valid email address.')
    return value

def create_app(config=None):
    app = Flask(__name__)
    app.config.update(APP_ENV=os.getenv('APP_ENV','production'), SECRET_KEY=os.getenv('SECRET_KEY'),
        DATA_ENCRYPTION_KEY=os.getenv('DATA_ENCRYPTION_KEY'), LOOKUP_KEY=os.getenv('LOOKUP_KEY'),
        DATABASE_URL=os.getenv('DATABASE_URL','sqlite:///private/investors.db'),
        PRIVATE_STORAGE=os.getenv('PRIVATE_STORAGE','private/documents'),
        PUBLIC_URL=os.getenv('PUBLIC_URL','http://localhost:8080'),
        MAX_CONTENT_LENGTH=12*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_NAME='investor_room', MSG91_AUTH_KEY=os.getenv('MSG91_AUTH_KEY'),
        MSG91_TEMPLATE_ID=os.getenv('MSG91_TEMPLATE_ID'))
    app.config.update(config or {})
    for key in ['SECRET_KEY','LOOKUP_KEY','DATA_ENCRYPTION_KEY']:
        if not app.config.get(key) or len(app.config[key]) < 32:
            raise RuntimeError('Set independent SECRET_KEY, LOOKUP_KEY and DATA_ENCRYPTION_KEY first.')
    if app.config['SECRET_KEY'] == app.config['LOOKUP_KEY']:
        raise RuntimeError('Secrets must be independent.')
    prod = app.config['APP_ENV'] == 'production'
    try: session_hours = min(72, max(1, int(os.getenv('INVESTOR_SESSION_HOURS', '8'))))
    except ValueError: session_hours = 8
    app.config['SESSION_COOKIE_SECURE'] = prod
    if prod and (not app.config['PUBLIC_URL'].startswith('https://') or not app.config['DATABASE_URL'].startswith(('postgresql','postgres:'))):
        raise RuntimeError('Production requires HTTPS and dedicated PostgreSQL.')
    if os.getenv('TRUST_PROXY') == '1':
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    storage = Path(app.config['PRIVATE_STORAGE']).resolve(); storage.mkdir(parents=True,exist_ok=True)
    Path('private').mkdir(exist_ok=True)
    fernet = Fernet(app.config['DATA_ENCRYPTION_KEY'].encode())
    def enc(value): return fernet.encrypt(json.dumps(value).encode()).decode()
    def dec(value): return json.loads(fernet.decrypt(value.encode()))
    def digest(value): return hmac.new(app.config['LOOKUP_KEY'].encode(),value.encode(),hashlib.sha256).hexdigest()
    dburl = app.config['DATABASE_URL'].replace('postgres://','postgresql+psycopg://',1)
    if dburl.startswith('postgresql://'): dburl=dburl.replace('postgresql://','postgresql+psycopg://',1)
    engine=create_engine(dburl,pool_pre_ping=True)
    factory=sessionmaker(engine,expire_on_commit=False)
    provider=app.config.get('OTP_PROVIDER') or SmsRouter()
    app.extensions.update(db=factory,engine=engine,enc=enc,dec=dec,digest=digest,fernet=fernet,storage=storage)
    def event(db,kind,iid=None,detail=None):
        db.add(Event(investor_id=iid,kind=kind,actor=getattr(g,'subject','anonymous'),at=now(),detail=enc(detail or {})))
    def limited(key,limit,period):
        bucket=now()//period; rid=digest(key)+':'+str(bucket)
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sq_insert
        ins=pg_insert if engine.dialect.name=='postgresql' else sq_insert
        with factory.begin() as db:
            stmt=ins(Rate).values(id=rid,count=1,expires=(bucket+2)*period)
            count=db.execute(stmt.on_conflict_do_update(index_elements=['id'],set_={'count':Rate.count+1}).returning(Rate.count)).scalar_one()
        if count>limit: abort(429,description='Too many attempts. Please wait and try again.')
    def active(i): return i is not None and i.status=='approved' and i.expires>now()
    def require(role):
        def deco(fn):
            @wraps(fn)
            def inner(*a,**kw):
                if role=='investor' and g.role=='admin' and request.endpoint in {'investor_site','investor_asset','content','document'}:
                    return fn(*a,**kw)
                if g.role!=role: return redirect(url_for('admin_login' if role=='admin' else 'login'))
                if role=='investor' and not g.investor.accepted and request.endpoint!='consent':
                    return redirect(url_for('consent'))
                return fn(*a,**kw)
            return inner
        return deco
    def login_as(db,subject,role):
        old=session.get('auth')
        if old: db.execute(delete(LoginSession).where(LoginSession.id==digest(old)))
        session.clear(); token=secrets.token_urlsafe(32)
        session['auth']=token; session['csrf']=secrets.token_urlsafe(32)
        db.add(LoginSession(id=digest(token),subject=subject,role=role,expires=now()+ (3600 if role=='admin' else session_hours*3600)))

    @app.before_request
    def setup():
        g.role=None; g.subject='anonymous'; g.investor=None
        session.setdefault('csrf',secrets.token_urlsafe(32))
        if request.method=='POST' and not hmac.compare_digest(str(session['csrf']),request.form.get('csrf','')):
            abort(400,description='Form expired. Refresh the page and try again.')
        with factory() as db:
            record=db.get(LoginSession,digest(session['auth'])) if session.get('auth') else None
            if record and record.expires>now():
                if record.role=='admin' and db.get(Admin,record.subject): g.role='admin'
                elif record.role=='investor':
                    investor=db.get(Investor,record.subject)
                    if active(investor): g.role='investor'; g.investor=investor
                if g.role: g.subject=record.subject

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store, private','X-Content-Type-Options':'nosniff',
            'X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow',
            'Content-Security-Policy':"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; media-src 'self' https://dhashu.com; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        if prod: response.headers['Strict-Transport-Security']='max-age=31536000'
        return response

    @app.context_processor
    def context(): return dict(csrf=session['csrf'],interests=INTERESTS,sections=SECTIONS,dec=dec)
    @app.template_filter('date')
    def date(value): return datetime.fromtimestamp(value,timezone.utc).strftime('%d %b %Y %H:%M UTC') if value else 'â€”'
    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def error(exc): return render_template('message.html',title='Request could not be completed',message=exc.description),exc.code

    @app.get('/health')
    def health():
        with factory() as db: db.execute(select(Investor.id).limit(1))
        return {'status':'ok'}
    site=Path(__file__).resolve().parent.parent
    @app.get('/')
    def index(): return send_file(site/'index.html')
    @app.get('/<filename>')
    def corporate(filename):
        if filename not in {'about.html','contact.html','cost-to-earth.html','index.html','privacy.html','styles.css','ventures.html','videos.html','writing.html'}: abort(404)
        return send_file(site/filename)
    @app.get('/investors')
    def investors_redirect(): return redirect('/investors/')
    @app.get('/investors/')
    @require('investor')
    def investor_site():
        with factory.begin() as db: event(db,'room_visit',g.subject if g.role=='investor' else None)
        html=(site/'investors/index.html').read_text(encoding='utf-8')
        html=html.replace('OPEN PREVIEW · NO SIGN-IN REQUIRED','APPROVED INVESTOR ACCESS')
        html=html.replace('</header>', '<a href="/room">Account &amp; private terms</a></header>')
        with factory() as db: stored=db.get(Section,TERMS_ID)
        try: terms=clean_terms(json.loads(dec(stored.body))) if stored else {}
        except (ValueError, TypeError): terms={}
        if terms:
            data=json.dumps(terms,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
            html=html.replace('</body>','<script type="application/json" id="private-terms">'+data+'</script></body>')
        return html
    @app.get('/investors/assets/<path:filename>')
    @require('investor')
    def investor_asset(filename):
        from flask import send_from_directory
        return send_from_directory(site/'investors/assets',filename)

    @app.route('/login',methods=['GET','POST'])
    def login():
        if request.method=='POST':
            limited('send-ip:'+str(request.remote_addr),15,3600)
            try: mobile=phone(request.form.get('phone',''))
            except ValueError as ex: flash(str(ex)); return redirect(url_for('login'))
            ph=digest('phone:'+mobile); limited('send-phone:'+ph,1,60); limited('send-day:'+ph,8,86400)
            cid=secrets.token_urlsafe(32)
            with factory.begin() as db:
                i=db.scalar(select(Investor).where(Investor.phone_hash==ph).with_for_update())
                iid=i.id if active(i) else None
                request_id=None
                if iid:
                    db.execute(update(Challenge).where(Challenge.investor_id==iid).values(used=1))
                    try:
                        request_id=provider.send(mobile)
                        event(db,'otp_provider_accepted',iid,{'request_id':request_id})
                    except ProviderUnavailable:
                        event(db,'otp_send_failed',iid); iid=None
                db.add(Challenge(id=digest(cid),investor_id=iid,expires=now()+300,attempts=0,used=0,provider_sid=request_id))
            session['challenge']=cid
            flash('If this number has active access and delivery is available, a code has been requested by SMS. It expires in 5 minutes.')
            return redirect(url_for('verify'))
        return render_template('login.html')

    @app.route('/verify',methods=['GET','POST'])
    def verify():
        if not session.get('challenge'): return redirect(url_for('login'))
        if request.method=='POST':
            limited('verify-ip:'+str(request.remote_addr),30,3600)
            otp=request.form.get('otp',''); success=False
            with factory.begin() as db:
                ch=db.scalar(select(Challenge).where(Challenge.id==digest(session['challenge'])).with_for_update())
                if ch and not ch.used and ch.expires>now() and ch.attempts<5:
                    # Consume attempt before provider interaction; row lock serialises production requests.
                    ch.attempts+=1
                    i=db.get(Investor,ch.investor_id) if ch.investor_id else None
                    number=dec(i.details).get('phone','') if i else ''
                    if active(i) and number and re.fullmatch(r'\d{6}',otp):
                        try: success=provider.verify(ch.provider_sid,otp,number)
                        except ProviderUnavailable: success=False
                        if success:
                            ch.used=1; login_as(db,i.id,'investor'); event(db,'login',i.id)
                    if not success and ch.attempts>=5: ch.used=1
            if success: return redirect(url_for('investor_site'))
            flash('Code could not be verified. Check the code and expiry, or request a new one.')
        return render_template('verify.html')

    @app.post('/logout')
    def logout():
        with factory.begin() as db:
            if session.get('auth'): db.execute(delete(LoginSession).where(LoginSession.id==digest(session['auth'])))
        session.clear(); return redirect(url_for('login'))

    @app.route('/consent',methods=['GET','POST'])
    @require('investor')
    def consent():
        if request.method=='POST':
            if request.form.get('accept')!='yes': abort(400,description='Please acknowledge the access terms.')
            with factory.begin() as db:
                i=db.get(Investor,g.subject); i.accepted=now(); i.terms_version=TERMS; event(db,'terms_accepted',i.id,{'version':TERMS})
            return redirect(url_for('investor_site'))
        return render_template('consent.html')

    @app.get('/room')
    @require('investor')
    def room():
        with factory.begin() as db:
            event(db,'room_visit',g.subject)
            docs=db.scalars(select(Document).where(Document.active==1)).all()
        return render_template('room.html',docs=docs,investor=g.investor,response=dec(g.investor.response))

    @app.get('/room/<slug>')
    @require('investor')
    def content(slug):
        with factory.begin() as db:
            section=db.get(Section,slug)
            if not section or slug==TERMS_ID: abort(404)
            event(db,'section_view',g.subject,{'section':slug})
        return render_template('content.html',section=section)

    @app.post('/response')
    @require('investor')
    def response():
        interest=request.form.get('interest')
        if interest not in INTERESTS: abort(400)
        amount=request.form.get('amount','').strip(); decision=request.form.get('decision','').strip()
        if amount and (not amount.isdigit() or len(amount)>12): abort(400,description='Enter a whole INR amount, up to 12 digits.')
        if decision:
            try: datetime.strptime(decision,'%Y-%m-%dT%H:%M')
            except ValueError: abort(400,description='Enter a valid date and time in IST.')
        payload={'amount_inr':int(amount) if amount else None,'decision_ist':decision,'questions':request.form.get('questions','')[:2000]}
        with factory.begin() as db:
            i=db.get(Investor,g.subject); i.interest=interest; i.response=enc(payload)
            event(db,'interest_updated',i.id,{'interest':interest,**payload})
        flash('Response saved. Your interest is non-binding; no payment or investment commitment has been made.')
        return redirect(url_for('room'))

    @app.get('/documents/<did>')
    @require('investor')
    def document(did):
        with factory.begin() as db:
            doc=db.get(Document,did)
            if not doc or not doc.active: abort(404)
            path=storage/(doc.id+'.enc')
            if not path.is_file(): abort(404)
            data=fernet.decrypt(path.read_bytes()); event(db,'document_download',g.subject,{'document':did})
        return send_file(io.BytesIO(data),mimetype='application/pdf',as_attachment=True,download_name=doc.filename)

    @app.route('/admin/login',methods=['GET','POST'])
    def admin_login():
        if request.method=='POST':
            limited('admin-ip:'+str(request.remote_addr),10,3600)
            username=request.form.get('username','')[:80]; limited('admin-user:'+username,10,3600)
            ok=False
            with factory.begin() as db:
                a=db.scalar(select(Admin).where(Admin.id==username).with_for_update())
                if a and check_password_hash(a.password_hash,request.form.get('password','')):
                    t=pyotp.TOTP(dec(a.totp_secret)); step=now()//30
                    if step>a.last_totp and t.verify(request.form.get('totp',''),valid_window=0):
                        a.last_totp=step; login_as(db,a.id,'admin'); event(db,'admin_login'); ok=True
            if ok: return redirect(url_for('admin'))
            flash('Login failed. Check your password and current authenticator code.')
        return render_template('admin_login.html')

    @app.get('/admin')
    @require('admin')
    def admin():
        with factory() as db:
            investors=db.scalars(select(Investor).order_by(Investor.created.desc())).all()
            events=db.scalars(select(Event).order_by(Event.at.desc(),Event.id.desc()).limit(100)).all()
            content=db.scalars(select(Section)).all(); docs=db.scalars(select(Document)).all()
            stats={kind:count for kind,count in db.execute(select(Event.kind,func.count(func.distinct(Event.investor_id))).group_by(Event.kind))}
            visits={iid:{'count':count,'first':first,'last':last} for iid,count,first,last in db.execute(
                select(Event.investor_id,func.count(Event.id),func.min(Event.at),func.max(Event.at)).where(Event.kind=='room_visit').group_by(Event.investor_id))}
        return render_template('admin.html',investors=investors,events=events,content=content,docs=docs,stats=stats,visits=visits,now=now(),public_url=app.config['PUBLIC_URL'])

    @app.post('/admin/investors')
    @require('admin')
    def add_investor():
        try: mail=email(request.form.get('email','')); number=phone(request.form.get('phone','')); days=int(request.form.get('days','30'))
        except ValueError as ex: abort(400,description=str(ex))
        if not 1<=days<=365 or not request.form.get('name','').strip(): abort(400)
        with factory.begin() as db:
            if db.scalar(select(Investor).where((Investor.phone_hash==digest('phone:'+number))|(Investor.email_hash==digest(mail)))):
                flash('This number or email is already listed. Update the existing access.'); return redirect(url_for('admin'))
            iid=str(uuid.uuid4())
            db.add(Investor(id=iid,phone_hash=digest('phone:'+number),email_hash=digest(mail),details=enc({'phone':number,'name':request.form['name'][:100],
                'email':mail,'organisation':request.form.get('organisation','')[:150],'city':request.form.get('city','')[:100]}),
                status='approved',expires=now()+days*86400,created=now(),response=enc({}),notes=enc('')))
            db.flush(); event(db,'access_approved',iid)
        flash('Investor added. Share the Investor Room link manually; no invitation has been sent.')
        return redirect(url_for('admin'))

    @app.post('/admin/investors/<iid>')
    @require('admin')
    def edit_investor(iid):
        action=request.form.get('action')
        with factory.begin() as db:
            i=db.get(Investor,iid)
            if not i: abort(404)
            if action=='revoke':
                i.status='revoked'; db.execute(delete(LoginSession).where(LoginSession.subject==iid))
                db.execute(update(Challenge).where(Challenge.investor_id==iid).values(used=1))
            elif action=='renew': i.status='approved'; i.expires=now()+30*86400
            elif action=='profile':
                person=dec(i.details)
                try: number=phone(request.form.get('phone',''))
                except ValueError as ex: abort(400,description=str(ex))
                taken=db.scalar(select(Investor).where(Investor.phone_hash==digest('phone:'+number),Investor.id!=iid))
                if taken: abort(400,description='This number already belongs to another investor.')
                for field,limit in [('name',100),('organisation',150),('city',100)]:
                    person[field]=request.form.get(field,'').strip()[:limit]
                if not person['name']: abort(400)
                if number!=person.get('phone'):
                    db.execute(update(Challenge).where(Challenge.investor_id==iid).values(used=1))
                person['phone']=number; i.phone_hash=digest('phone:'+number)
                i.details=enc(person)
            elif action=='note': i.notes=enc(request.form.get('notes','')[:4000])
            elif action=='invitation_shared':
                if request.form.get('channel') not in ['email','whatsapp','other']: abort(400)
            else: abort(400)
            event(db,action,iid,{'channel':request.form.get('channel',''),'note':request.form.get('message','')[:1000]})
        flash('Saved.'); return redirect(url_for('admin'))

    @app.post('/admin/content/<slug>')
    @require('admin')
    def edit_content(slug):
        with factory.begin() as db:
            c=db.get(Section,slug)
            if not c: abort(404)
            body=request.form.get('body','')[:30000]
            if slug==TERMS_ID:
                try: body=json.dumps(clean_terms(json.loads(body or '{}')),ensure_ascii=False,indent=1)
                except (ValueError, TypeError) as ex: abort(400,description='Round terms were not saved: '+str(ex))
            c.body=enc(body); event(db,'content_updated',detail={'section':slug})
        flash('Content saved.'); return redirect(url_for('admin'))

    @app.post('/admin/documents')
    @require('admin')
    def upload():
        f=request.files.get('document'); title=request.form.get('title','').strip()[:150]
        if not f or not title: abort(400)
        data=f.read(); filename=secure_filename(f.filename or '')
        if not filename.lower().endswith('.pdf') or not data.startswith(b'%PDF-'): abort(400,description='Upload a PDF file only.')
        did=str(uuid.uuid4()); target=storage/(did+'.enc')
        target.write_bytes(fernet.encrypt(data))
        try:
            with factory.begin() as db:
                db.add(Document(id=did,title=title,filename=filename,active=1)); event(db,'document_uploaded',detail={'document':did})
        except Exception:
            target.unlink(missing_ok=True); raise
        flash('Private PDF uploaded. Approved investors can download it.'); return redirect(url_for('admin'))

    @app.post('/admin/documents/<did>/retire')
    @require('admin')
    def retire(did):
        with factory.begin() as db:
            doc=db.get(Document,did)
            if not doc: abort(404)
            doc.active=0; event(db,'document_retired',detail={'document':did})
        return redirect(url_for('admin'))
    return app
