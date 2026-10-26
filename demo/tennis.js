/* Same getAI → aiExtract → openAI flow as foregate-page-demo-price.html. */
const T={
 zh:{fab:'AI 預測',loading:'模型計算中…',pick:'模型傾向',reason:'依據',unsupported:'暫不支持該項結果預測',close:'關閉',retry:'重試',go:'開始使用',
 note:'本地交互驗證：以下是合成對陣，不是真實賽程或 Poly 交易盤。概率由本地模型即時計算，仍屬研究輸出。',
 intro:'延續原有 AI 懸浮球和玩法浮層。一次請求整場概率，按盤號、盤口線和球員方向精確匹配；切換 ATP／WTA 或盤口時重新匹配。',
 discl:'本內容為盤前（賽前）機率估計，比賽開始後不應再作為參考。所有預測僅供參考，不構成任何投注建議，請理性判斷。',
 scope:'研究概率 · 正常完賽條件；是否完賽使用歷史整體基線',
 names:['賽事勝負','讓盤','大小盤','全場大小局','是否完賽','首盤勝者','首盤大小局','第2盤勝者','第2盤大小局','讓局','精確盤分 2–0'],over:'大',under:'小',yes:'是',no:'否'},
 en:{fab:'AI Prediction',loading:'Modeling…',pick:'Model pick',reason:'Why',unsupported:"This market isn't supported for prediction yet",close:'Close',retry:'Retry',go:'Start',
 note:'Local interaction test: synthetic matchups, not actual fixtures or tradable Poly markets. Probabilities are computed by the local research model.',
 intro:'The existing floating AI button and market sheet flow. One request fetches match probabilities; each sheet matches its exact set, line and player direction.',
 discl:'This is a pre-match probability estimate and should not be relied on once the match starts. Predictions are for reference only, not betting advice.',
 scope:'Research probabilities conditional on normal completion; completion uses a historical population rate.',
 names:['Moneyline','Set Handicap','Total Sets','Total Games','Completed Match','Set 1 Winner','Set 1 Total Games','Set 2 Winner','Set 2 Total Games','Game Handicap','Exact Set Score 2–0'],over:'Over',under:'Under',yes:'Yes',no:'No'},
 vi:{fab:'Dự đoán AI',loading:'Đang tính toán…',pick:'Mô hình nghiêng',reason:'Lý do',unsupported:'Chưa hỗ trợ dự đoán kết quả này',close:'Đóng',retry:'Thử lại',go:'Bắt đầu',
 note:'Kiểm tra tương tác cục bộ: cặp đấu giả định, không phải lịch thi đấu hoặc thị trường Poly thực. Xác suất được tính bằng mô hình nghiên cứu cục bộ.',
 intro:'Giữ nút AI nổi và bảng từng kèo. Một yêu cầu lấy xác suất cả trận; khớp đúng set, mức kèo và hướng người chơi.',
 discl:'Đây là xác suất trước trận; không nên dùng sau khi trận bắt đầu. Chỉ để tham khảo, không phải lời khuyên cá cược.',
 scope:'Xác suất nghiên cứu với điều kiện hoàn tất bình thường; tỷ lệ hoàn tất là mức chung trong lịch sử.',
 names:['Thắng trận','Chấp set','Tổng set','Tổng game','Hoàn tất trận','Thắng set 1','Tổng game set 1','Thắng set 2','Tổng game set 2','Chấp game','Tỷ số set 2–0'],over:'Tài',under:'Xỉu',yes:'Có',no:'Không'}
};
const MATCH={atp:{eventSlug:'demo-atp',a:'Jannik Sinner',b:'Carlos Alcaraz'},wta:{eventSlug:'demo-wta',a:'Aryna Sabalenka',b:'Iga Swiatek'}};
let tour='atp',lang='zh',openIndex=null,generation=0;
const aiCache=new Map(),$=id=>document.getElementById(id),esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let specs=[{market_type:'moneyline'},{market_type:'tennis_set_handicap',line:-1.5,selection:'a'},
 {market_type:'tennis_set_totals',line:2.5},{market_type:'tennis_match_totals',line:21.5},
 {market_type:'tennis_completed_match'}, {market_type:'tennis_first_set_winner'},
 {market_type:'tennis_first_set_totals',line:8.5},{market_type:'tennis_set_winner',set_number:2},
 {market_type:'tennis_set_games_totals',set_number:2,line:8.5},{market_type:'tennis_game_handicap',line:-2.5,selection:'a'},
 {market_type:'tennis_exact_score',score:'2-0'}];
function query(){return new URLSearchParams({type:'tennis',tour,...MATCH[tour],lang,markets:JSON.stringify(specs)});}
function keyFor(s){const p={};if(s.line!==undefined)p.line=s.line;if(s.selection==='b')p.selection='b';if(['tennis_set_winner','tennis_set_games_totals'].includes(s.market_type))p.set_number=s.set_number;
 if(s.market_type==='tennis_exact_score')return s.market_type+':'+s.score;
 const keys=Object.keys(p).sort();return s.market_type+(keys.length?':{'+keys.map(k=>JSON.stringify(k)+': '+JSON.stringify(p[k])).join(', ')+'}':'');}
async function getAI(){const q=query(),cacheKey=q.toString(),saved=aiCache.get(cacheKey),now=Date.now();
 if(saved&&now-saved.at<60000&&Date.parse(saved.data.matchStartTime)>now)return saved.data;
 const response=await fetch('/predict?'+q,{cache:'no-store'});if(!response.ok)throw Error('Request failed');
 const data=await response.json();if(data.ready)aiCache.set(cacheKey,{at:now,data});return data;
}
function aiExtract(spec,data){const kind=spec.market_type,value=data.platform_markets?.[kind];if(!value)return null;
 const entries=Array.isArray(value)?value:[value];return entries.find(x=>x.key===keyFor(spec))||null;}
function head(title){return `<div class="wb-head"><span id="sheet-title">✨ ${esc(title)}</span><button class="wb-x" aria-label="${esc(T[lang].close)}">×</button></div>`;}
function finishSheet(){document.querySelector('.wb-x').onclick=closeMask;$('mask').classList.add('show');document.querySelector('.wb-x').focus();}
function closeMask(){generation++;openIndex=null;$('mask').classList.remove('show');}
function renderUnsupported(title){$('sheet').innerHTML=head(title)+`<div class="empty">${esc(T[lang].unsupported)}</div><button id="retry" class="primary">${esc(T[lang].retry)}</button>`;finishSheet();$('retry').onclick=()=>{aiCache.clear();if(openIndex!==null)openAI(openIndex);};}
async function openAI(index){openIndex=index;const current=++generation,title=T[lang].names[index];$('sheet').innerHTML=head(title)+`<div class="loading">${esc(T[lang].loading)}</div>`;finishSheet();
 try{const data=await getAI();if(current!==generation)return;const row=aiExtract(specs[index],data);if(!row){renderUnsupported(title);return;}
  const pairs=row.pairs,max=Math.max(...pairs.map(x=>x[1])),winner=pairs.find(x=>x[1]===max);
  const bars=pairs.map(([name,p])=>`<div class="wb-row"><span class="wb-name">${esc(name)}</span><span class="wb-bar ${p===max?'win':''}"><i style="width:${(p*100).toFixed(1)}%"></i></span><span class="wb-pct">${(p*100).toFixed(1)}%</span></div>`).join('');
  const reasons=data.reasons?.[row.key]||[];
  $('sheet').innerHTML=head(title)+`<div class="wb-sub">${esc(data.A)} vs ${esc(data.B)}</div>${bars}<div class="wb-pick">${esc(T[lang].pick)}: <b>${esc(winner[0])}</b> · ${(winner[1]*100).toFixed(1)}%</div>`+
   (reasons.length?`<div class="wb-reasons"><b>${esc(T[lang].reason)}</b><ul>${reasons.map(x=>'<li>'+esc(x)+'</li>').join('')}</ul></div>`:'')+`<div class="muted">${esc(T[lang].scope)}</div><div class="wb-reasons wb-warn">${esc(T[lang].discl)}</div>`;finishSheet();
 }catch{if(current===generation)renderUnsupported(title);}
}
function introModal(){$('sheet').innerHTML=head(T[lang].fab)+`<p>${esc(T[lang].intro)}</p><p class="muted">${esc(T[lang].note)}</p><button id="start" class="primary">${esc(T[lang].go)}</button>`;finishSheet();$('start').onclick=closeMask;}
function render(){const t=T[lang];document.documentElement.lang=lang;$('demo-note').textContent=t.note;$('match-title').textContent=MATCH[tour].a+' vs '+MATCH[tour].b;$('match-meta').textContent=tour.toUpperCase()+' · '+t.scope;$('intro').textContent=t.fab;
 $('markets').innerHTML=specs.map((s,i)=>{let choices=null;if(s.market_type==='tennis_match_totals')choices=[21.5,22.5,23.5];if(['tennis_first_set_totals','tennis_set_games_totals'].includes(s.market_type))choices=[8.5,9.5,10.5];
  return `<div class="market"><span class="market-title">${esc(t.names[i])}<button class="ai-badge" data-index="${i}">✨AI</button></span>`+(choices?`<select data-line="${i}" aria-label="${esc(t.names[i])}">${choices.map(v=>`<option value="${v}" ${v===s.line?'selected':''}>${v}</option>`).join('')}</select>`:s.line!==undefined?`<span class="muted">${s.line}</span>`:'')+'</div>';}).join('');
 document.querySelectorAll('.ai-badge').forEach(b=>b.onclick=()=>openAI(Number(b.dataset.index)));
 document.querySelectorAll('[data-line]').forEach(s=>s.onchange=()=>{generation++;specs[Number(s.dataset.line)].line=Number(s.value);aiCache.clear();});}
$('tour').onchange=()=>{tour=$('tour').value;closeMask();aiCache.clear();render();};$('lang').onchange=()=>{const index=openIndex;lang=$('lang').value;closeMask();render();if(index!==null)openAI(index);};$('intro').onclick=introModal;
$('mask').onclick=e=>{if(e.target===$('mask'))closeMask();};document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMask();});
const fab=$('wb-fab');let drag=null;fab.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,left:fab.offsetLeft,top:fab.offsetTop,moved:false};fab.setPointerCapture(e.pointerId);};
fab.onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>5)drag.moved=true;if(drag.moved){fab.style.right='auto';fab.style.bottom='auto';fab.style.left=Math.max(4,Math.min(innerWidth-70,drag.left+dx))+'px';fab.style.top=Math.max(4,Math.min(innerHeight-70,drag.top+dy))+'px';}};
fab.onpointerup=()=>{if(drag&&!drag.moved){document.body.classList.toggle('wb-on');fab.classList.toggle('on');if(document.body.classList.contains('wb-on'))introModal();}drag=null;};
render();
