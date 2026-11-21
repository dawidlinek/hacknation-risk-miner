import re, html
from html.parser import HTMLParser
class _P(HTMLParser):
    BLOCK={'p','div','h1','h2','h3','h4','h5','h6','li','tr','br','table','section','ul','ol'}
    def __init__(self):
        super().__init__(); self.out=[]; self.skip=0
    def handle_starttag(self,t,a):
        if t in('style','script'): self.skip+=1
        if t in self.BLOCK: self.out.append('\n')
    def handle_endtag(self,t):
        if t in('style','script'): self.skip-=1
        if t in self.BLOCK: self.out.append('\n')
    def handle_data(self,d):
        if not self.skip: self.out.append(d)
def html2text(h):
    p=_P(); p.feed(h or ''); t=''.join(p.out)
    t=t.replace('\xa0',' ')
    t=re.sub(r'[ \t]+',' ',t); t=re.sub(r'\n\s*\n+','\n',t)
    return t.strip()
