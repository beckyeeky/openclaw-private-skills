const assert = require('assert');
const extract = require('../scripts/extract.js');
function link(id,n) { return {href:`https://x.com/u/status/${id}/photo/${n}`,querySelector:()=>null}; }
function photo(id,n,key) { const a=link(id,n); return {closest:()=>a,querySelector:()=>({src:`https://pbs.twimg.com/media/${key}?format=jpg&name=small`})}; }
function article(id, items, video=false) { return {querySelectorAll:s=>s==='a[href]'?[{href:`https://x.com/u/status/${id}`,querySelector:()=>({})}]:items,querySelector:()=>video?{}:null}; }
function root(articles) { return {querySelectorAll:()=>articles}; }
const fixture=root([article('123',[photo('123',2,'B'),photo('999',1,'QUOTE'),photo('123',1,'A'),photo('123',2,'B'),photo('123',3,'B')]),article('456',[photo('456',1,'REPLY')])]);
const result=extract(fixture,'123');
assert.deepStrictEqual(result.photos.map(p=>p.index),[1,2]);
assert(result.photos.every(p=>p.url.includes('name=orig')));
assert(result.contiguous);
assert(!extract(root([]),'123').found);
assert(!extract(root([article('123',[photo('123',2,'B')])]),'123').contiguous);
assert(extract(root([article('123',[],true)]),'123').video);
assert.strictEqual(extract(root([article('123',[])]),'123').photos.length,0);
const modern = link('123',1);
modern.closest=()=>modern;
modern.querySelector=()=>({src:'https://pbs.twimg.com/media/MODERN?format=webp&name=large'});
assert(extract(root([article('123',[modern])]),'123').photos[0].url.includes('format=jpg'));
console.log('PASS extraction: modern anchors/WebP, order, duplicates, quotes, replies, absent target, gap, video/no photos');
