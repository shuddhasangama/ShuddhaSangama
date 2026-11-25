"""Import a locally supplied proposal into encrypted DB storage, never source control."""
import argparse
from html.parser import HTMLParser
from pathlib import Path
from app import create_app
from models import Section


class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.output=[]; self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script', 'head'): self.skip+=1
        if not self.skip and tag in ('p','h1','h2','h3','tr','li','section'): self.output.append('\n')
    def handle_endtag(self, tag):
        if tag in ('style', 'script', 'head'): self.skip-=1
        if not self.skip and tag in ('td','th'): self.output.append(' | ')
    def handle_data(self, text):
        if not self.skip: self.output.append(text)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('file'); args=parser.parse_args()
    parsed=Text(); parsed.feed(Path(args.file).read_text(encoding='utf-8'))
    text='\n'.join(line.strip() for line in ''.join(parsed.output).splitlines() if line.strip())
    app=create_app(); ex=app.extensions
    with ex['db'].begin() as db:
        section=db.get(Section,'ask')
        if not section: section=Section(id='ask',title='Detailed proposal & terms, plainly',body=''); db.add(section)
        section.title='Detailed proposal & terms, plainly'
        section.body=ex['enc']('SOURCE PROPOSAL — 25 November 2026. Proposed terms, not a completed offer. The roadmap in the Investor Room is the current operating plan; the source proposal contains an earlier, slower rollout. Holdings in this proposal assume a ₹50 lakh close; the ₹60 lakh cap requires a revised cap table.\n\n'+text)
    print('Proposal saved in encrypted storage. Available only after approved investor login.')
