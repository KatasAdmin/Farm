#!/usr/bin/env node
/* Localization coverage audit. Run: node scripts/audit-localization.cjs
   This audit intentionally reports gaps without changing gameplay or claiming complete localization. */
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const files=['index.html','assets/game.js','assets/fields.js','assets/monetag-rewards.js'];
const locale=fs.readFileSync(path.join(root,'assets/localization.js'),'utf8');
const dictionaryKeys=new Set([...locale.matchAll(/dictionary\[("(?:[^"\\]|\\.)*")\]=/g)].map(x=>JSON.parse(x[1])));
const initial=locale.match(/const dictionary=(\{.*?\});\n/s);
if(initial){for(const key of Object.keys(JSON.parse(initial[1])))dictionaryKeys.add(key);}
let total=0,untranslated=0;
for(const file of files){
 const source=fs.readFileSync(path.join(root,file),'utf8');
 const matches=file.endsWith('.html')
  ?[...source.matchAll(/>([^<>\n]*[А-Яа-яЁё][^<>\n]*)</g)].map(m=>m[1].trim())
  :[...source.matchAll(/(["'`])([^"'\n`]*[А-Яа-яЁё][^"'\n`]*)\1/g)].map(m=>m[2].trim());
 const unique=[...new Set(matches.filter(x=>x.length>2&&!x.includes('<')&&!x.includes('=>')))];
 const missing=unique.filter(x=>!dictionaryKeys.has(x));
 total+=unique.length;untranslated+=missing.length;
 console.log('\n'+file+': '+(unique.length-missing.length)+'/'+unique.length+' exact source strings translated');
 for(const value of missing.slice(0,35))console.log('  MISSING '+value.slice(0,130));
 if(missing.length>35)console.log('  ... and '+(missing.length-35)+' more');
}
console.log('\nExact-phrase coverage: '+(total-untranslated)+'/'+total+'; remaining: '+untranslated);
if(untranslated)process.exitCode=1;
