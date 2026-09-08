(function(){const e=document.createElement("link").relList;if(e&&e.supports&&e.supports("modulepreload"))return;for(const i of document.querySelectorAll('link[rel="modulepreload"]'))n(i);new MutationObserver(i=>{for(const r of i)if(r.type==="childList")for(const a of r.addedNodes)a.tagName==="LINK"&&a.rel==="modulepreload"&&n(a)}).observe(document,{childList:!0,subtree:!0});function t(i){const r={};return i.integrity&&(r.integrity=i.integrity),i.referrerPolicy&&(r.referrerPolicy=i.referrerPolicy),i.crossOrigin==="use-credentials"?r.credentials="include":i.crossOrigin==="anonymous"?r.credentials="omit":r.credentials="same-origin",r}function n(i){if(i.ep)return;i.ep=!0;const r=t(i);fetch(i.href,r)}})();var Cd=["0","1","2","3","4","5","6","7","8","9"],Us=new Map,Pd=/[\u0590-\u08ff\u200e\u200f\u202a-\u202e\u2066-\u2069\ufb1d-\ufeff]/u;function Dd(s={}){let e=Intl.getCanonicalLocales(s.locales),t=Object.fromEntries(Object.entries(s.format??{}).sort(([r],[a])=>r.localeCompare(a))),n=JSON.stringify([e,t]),i=Us.get(n);if(!i){i=new Intl.NumberFormat(e,t);let r=Us.keys().next().value;Us.size>=64&&r!==void 0&&Us.delete(r),Us.set(n,i)}return i}function Ld(s,e={}){let t=Dd(e),n=t.formatToParts(s),i=n.map(g=>g.value).join(""),r=t.resolvedOptions(),a=r.numberingSystem==="latn"&&r.notation==="standard"&&!Pd.test(i)&&!n.some(g=>g.type==="nan"||g.type==="infinity"),o=JSON.stringify(r);if(!a)return{text:i,tokens:[],rollable:a,signature:o,magnitude:""};let l=n.filter(g=>g.type==="integer").reduce((g,x)=>g+x.value.length,0),c=-1,h=new Map,u=[],d="",f="";for(let g of n)if(g.type==="integer"||g.type==="fraction"){g.type==="integer"?d+=g.value:f+=g.value;for(let x of g.value){let p=`digit:${g.type==="integer"?--l:c--}`;u.push({key:p,identity:p,text:x,wheel:Cd,index:Number(x)})}}else if(g.type==="group"){let x=`group:${l}`;u.push({key:`${x}:${g.value}`,identity:x,text:g.value})}else{let x=h.get(g.type)??0;h.set(g.type,x+1);let p=g.type==="plusSign"||g.type==="minusSign"?"sign":g.type;u.push({key:`${g.type}:${x}:${g.value}`,identity:`${p}:${x}`,text:g.value})}return{text:i,tokens:u,rollable:a,signature:o,magnitude:`${d.replace(/^0+(?=\d)/u,"")}.${f}`}}function Id(s,e){let[t="",n=""]=s.magnitude.split("."),[i="",r=""]=e.magnitude.split(".");if(t.length!==i.length)return i.length>t.length?1:-1;if(t!==i)return i>t?1:-1;let a=Math.max(n.length,r.length),o=n.padEnd(a,"0"),l=r.padEnd(a,"0");return l===o?0:l>o?1:-1}function Nd(s,e,t=.14){return{target:0,duration:e,points:Array.from({length:49},(n,i)=>{if(i===48)return 0;let r=Math.max(0,Math.min(1,(i/48-t)/(1-t)));return s*(1+10*r)*Math.exp(-10*r)})}}function hr(s,e){if(e<=0||s.duration<=0)return s;let t=s.duration+e,n=Math.round((s.points.length-1)*t/s.duration)+1,i=s.points[0]??s.target;return{target:s.target,duration:t,points:Array.from({length:n},(r,a)=>{if(a===n-1)return s.target;let o=a/(n-1)*t-e;return o<=0?i:lu(s,o).position})}}function ni(s,e,t,n){if(n<=0)return{points:[e,e],duration:0,target:e};let i=n/1e3,r=s-e,a=Math.max(Math.abs(r),1)*12/i,o=Math.max(-a,Math.min(a,t))*i;return{points:Array.from({length:49},(l,c)=>{if(c===48)return e;let h=c/48;return e+(r+(o+10*r)*h)*Math.exp(-10*h)}),duration:n,target:e}}function Ud(s,e=0,t=24){if(s.duration<=0)return{points:[0,0],duration:0,target:0};let n=s.duration/(s.points.length-1)/1e3;return{duration:s.duration,target:0,points:s.points.map((i,r,a)=>{if(r===0)return Math.max(0,Math.min(1,e));if(r===a.length-1)return 0;let o=Math.abs((a[r+1]-a[r-1])/(2*n)),l=t/6;return Math.max(0,Math.min(1,(o-l)/(t-l)))})}}function lu(s,e){if(e>=s.duration||s.duration===0)return{position:s.target,velocity:0};let t=Math.max(0,e)/s.duration*(s.points.length-1),n=Math.min(Math.floor(t),s.points.length-2),i=s.points[n]??s.target,r=s.points[n+1]??s.target;return{position:i+(r-i)*(t-n),velocity:(r-i)*(s.points.length-1)*1e3/s.duration}}function yc(s,e,t,n=10){let i=Math.floor(s/n)*n+e;return t>0&&i<s-.001?i+=n:t<0&&i>s+.001?i-=n:t===0&&(i+=Math.round((s-i)/n)*n),i}var ta=(s,e)=>s[(e%s.length+s.length)%s.length];function Fd(s,e,t){let n=Math.floor(e),i=e-n,r=[ta(s,n)];return i>1e-5&&r.push(ta(s,n+1)),r.at(-1)!==t&&r.push(t),{wheel:r,from:i,target:r.length-1}}function Od(s,e="outward"){if(e!=="outward"){let i=s.map((a,o)=>a?-1:o).filter(a=>a>=0);e==="end"&&i.reverse();let r=s.map(a=>a?0:1);return e!=="none"&&i.forEach((a,o)=>{r[a]=o+1}),r}let t=s.map((i,r)=>i?0:r+1);if(!s.includes(!0))return t;let n=-1/0;for(let i=0;i<s.length;i++)s[i]?n=i:t[i]=i-n;n=1/0;for(let i=s.length-1;i>=0;i--)s[i]?n=i:t[i]=Math.min(t[i],n-i);return t}function Sc(s,e){let t=new Map,n=[],i=0;for(let r of s){let a=e.get(r);if(!a){n.push(r);continue}for(let o of n)t.set(o,a.x);n.length=0,i=a.x+a.width}for(let r of n)t.set(r,i);return t}var Aa=new WeakMap;class Dl{view;media;members=new Set;pending=new Set;sizes=new WeakMap;intersections=new WeakMap;resize;intersection;frame=0;static for(e){let t=Aa.get(e);return t||(t=new Dl(e),Aa.set(e,t)),t}constructor(e){this.view=e,this.media=e.matchMedia("(prefers-reduced-motion: reduce)"),this.media.addEventListener("change",this.refresh),e.document.addEventListener("visibilitychange",this.refresh),e.document.fonts?.addEventListener("loadingdone",this.refresh),e.document.fonts?.ready.then(this.refresh),e.ResizeObserver&&(this.resize=new e.ResizeObserver(t=>{for(let n of t){let i=this.sizes.get(n.target);i?.sizeChanged(n.target,n.contentRect.width,n.contentRect.height)&&i.refresh()}})),e.IntersectionObserver&&(this.intersection=new e.IntersectionObserver(t=>{for(let n of t)this.intersections.get(n.target)?.visibility(n.isIntersecting)},{rootMargin:"64px"}))}refresh=()=>{for(let e of this.members)e.refresh()};add(e,t){this.members.add(e),this.intersections.set(t,e),this.intersection?.observe(t)}watch(e,t){this.sizes.set(e,t),this.resize?.observe(e)}unwatch(e){this.resize?.unobserve(e),this.sizes.delete(e)}enqueue(e){this.pending.add(e),!this.frame&&(this.frame=this.view.requestAnimationFrame(()=>{this.frame=0;let t=[...this.pending];this.pending.clear();let n=t.map(r=>r.stage());for(let r of n)r?.();let i=t.map(r=>r.measure());for(let r of i)r?.()}))}remove(e,t){this.pending.delete(e),this.members.delete(e),this.intersection?.unobserve(t),this.intersections.delete(t),!this.members.size&&(this.view.cancelAnimationFrame(this.frame),this.resize?.disconnect(),this.intersection?.disconnect(),this.media.removeEventListener("change",this.refresh),this.view.document.removeEventListener("visibilitychange",this.refresh),this.view.document.fonts?.removeEventListener("loadingdone",this.refresh),Aa.delete(this.view))}}var bc=new WeakMap;function rs(s,e,t){let n=s.animate(e,t),i=s.ownerDocument.timeline?.currentTime;return typeof i=="number"&&n.playState==="running"&&(n.startTime=i),n}function Ec(s){let e=s.ownerDocument.defaultView;if(!e)return!1;let t=bc.get(e);return t===void 0&&(t=e.CSS?.supports("animation-timing-function","linear(0, 1)")??!1,bc.set(e,t)),t}class as{element;property;animation;motion;value=0;constructor(e,t){this.element=e,this.property=t}read(){let e=this.animation?.currentTime;return this.animation&&this.motion?lu(this.motion,typeof e=="number"?e:0):{position:this.value,velocity:0}}set(e,t){this.cancel(),this.value=e,this.element.style.setProperty(this.property,t(e))}play(e,t,n){if(this.cancel(),this.value=e.target,this.element.style.setProperty(this.property,t(e.target)),!e.duration||e.points.every(u=>u===e.target)){n?.();return}let i=e.points[0]??e.target,r=e.target-i,a=this.property==="opacity"&&Ec(this.element),o=this.property==="transform"&&Math.abs(r)>1e-5&&Ec(this.element),l=a?[{opacity:0},{opacity:1}]:o?[{[this.property]:t(i)},{[this.property]:t(e.target)}]:e.points.map(u=>({[this.property]:t(u)})),c=a?`linear(${e.points.map(t).join(",")})`:o?`linear(${e.points.map(u=>Number(((u-i)/r).toFixed(6))).join(",")})`:"linear",h=rs(this.element,l,{duration:e.duration,easing:c});this.animation=h,this.motion=e,h.onfinish=()=>{this.animation===h&&(this.animation=void 0,this.motion=void 0,h.onfinish=null,h.cancel(),n?.())}}cancel(){this.animation&&(this.animation.onfinish=null,this.animation.cancel(),this.animation=void 0),this.motion=void 0}}var wa="http://www.w3.org/2000/svg",Bd=0;class Ra{host;layers=new Map;filter;intensity=1;constructor(e){this.host=e}filterUrl(e){if(!this.filter){let n=this.host.ownerDocument,i=n.createElementNS(wa,"svg");i.classList.add("rn-blur-defs"),i.setAttribute("aria-hidden","true"),i.setAttribute("focusable","false");let r=n.createElementNS(wa,"filter"),a;do a=`rn-vertical-blur-${++Bd}`;while(n.getElementById(a));r.id=a,r.setAttribute("x","-15%"),r.setAttribute("width","130%"),r.setAttribute("color-interpolation-filters","sRGB");let o=n.createElementNS(wa,"feGaussianBlur");r.append(o),i.append(r),this.host.append(i),this.filter={svg:i,blur:o,id:a,height:0}}let t=e*.035*this.intensity;return this.filter.height!==t&&(this.filter.blur.setAttribute("stdDeviation",`0 ${t}`),this.filter.height=t),`url("#${this.filter.id}")`}apply(e,t,n,i,r="roll"){let a=Ud(t,i,r==="entry"?6:24);if(a.points.every(u=>u===0))return!1;let o=this.host.ownerDocument.createElement("span");o.className="rn-sharp",o.append(...e.childNodes);let l=o.cloneNode(!0);l.className="rn-smear",l.style.filter=this.filterUrl(n),e.append(o,l);let c=new as(o,"opacity"),h=new as(l,"opacity");return this.layers.set(e,{sharp:o,sharpOpacity:c,smearOpacity:h}),c.play(a,u=>String(1-u)),h.play(a,String),!0}remove(e){let t=this.layers.get(e);if(!t)return 0;let n=t.smearOpacity.read().position;return t.sharpOpacity.cancel(),t.smearOpacity.cancel(),e.replaceChildren(...t.sharp.childNodes),this.layers.delete(e),n}destroy(){for(let e of this.layers.keys())this.remove(e);this.filter?.svg.remove(),this.filter=void 0}}function kd(s){return Math.max(45,Math.min(110,s/7))}function Vd(s,e,t){let n=Math.abs(e-s);return{points:[s,e],target:e,duration:n*t}}function zd(s){let e=Array.from({length:s+1},(i,r)=>({"--rn-flap-step":String(r),offset:r/s,easing:"steps(1, end)"})),t=[],n=[];for(let i=0;i<s;i++){let r=i/s,a=(i+.5)/s,o=(i+1)/s;t.push({transform:"perspective(5em) rotateX(0deg)",filter:"brightness(1)",offset:r,easing:"cubic-bezier(.6, 0, 1, .5)"},{transform:"perspective(5em) rotateX(-90deg)",filter:"brightness(.45)",offset:a},{transform:"perspective(5em) rotateX(-90deg)",filter:"brightness(.45)",offset:o}),n.push({transform:"perspective(5em) rotateX(90deg)",filter:"brightness(.45)",offset:r},{transform:"perspective(5em) rotateX(90deg)",filter:"brightness(.45)",offset:a,easing:"linear(0, 0.58, 0.9, 1, 1.045 78%, 1)"},{transform:"perspective(5em) rotateX(0deg)",filter:"brightness(1)",offset:o})}return{index:e,falls:t,lands:n}}function Hd(s){for(let e of s.querySelectorAll(".rn-flap-smear")){for(let t of e.getAnimations())t.cancel();e.remove()}for(let e of s.querySelectorAll(".rn-flap-sharp")){for(let t of e.getAnimations())t.cancel();e.classList.remove("rn-flap-sharp")}}function Gd(s,e,t,n,i,r,a,o){let l=s.ownerDocument,c=Math.abs(n-t),h=n>=t?1:-1;if(!c){s.replaceChildren();return}let u=zd(c),d=Array.from({length:c+1},(E,w)=>ta(e,t+w*h)),f=[...d.slice(1),d.at(-1)],g=d.some(E=>/[\r\n\f\u2028\u2029]/u.test(E)),x=l.createElement("span");x.style.cssText=`display:block;position:relative;height:${i}px`,rs(x,u.index,{delay:a,duration:c*r,fill:"both"});let p=(E,w)=>{let C=l.createElement("span");C.className=`rn-face rn-flap rn-flap-${E}`,C.style.height=`${i}px`,C.style.overflow="hidden";let v=l.createElement("span");v.style.cssText=`display:block;white-space:pre;line-height:${i}px`;let b=w?f:d;if(g)for(let D of b){let R=l.createElement("span");R.style.cssText=`display:block;height:${i}px`,R.textContent=D,v.append(R)}else v.textContent=b.join(`
`);return C.append(v),v.style.transform=`translateY(calc(var(--rn-flap-step) * ${-i}px))`,C},m=p("bottom",!1),S=p("top",!0),T=p("top",!1),M=p("bottom",!0);if(o){let E=(w,C)=>{let v=w.firstElementChild,b=v.cloneNode(!0);v.classList.add("rn-flap-sharp");let D=l.createElement("span");D.className="rn-flap-smear",D.style.cssText="display:block;position:absolute;inset:0;overflow:hidden",D.style.filter=o,D.append(b),w.append(D);let R=C.map(O=>({offset:O.offset,easing:O.easing??"linear",opacity:O.filter==="brightness(1)"?0:1})),F={delay:a,duration:c*r,fill:"both"};rs(D,R,F),rs(v,R.map(O=>({...O,opacity:1-O.opacity})),F)};E(T,u.falls),E(M,u.lands)}T.style.transform="perspective(5em) rotateX(-90deg)",rs(T,u.falls,{delay:a,duration:c*r,fill:"backwards"}),M.style.transform="perspective(5em) rotateX(90deg)",rs(M,u.lands,{delay:a,duration:c*r,fill:"forwards"}),s.style.height=`${i}px`,x.append(m,S,M,T),s.replaceChildren(x)}var Wd=new WeakMap,wo=new WeakSet,Ca=s=>`translateX(${s}px)`,Pa=s=>`scale(${s})`,Da=s=>String(Math.max(0,Math.min(1,s))),La=s=>"transition"in s&&s.transition==="direct";function Xd(s){if(s.duration!==void 0&&(!Number.isFinite(s.duration)||s.duration<0||s.duration>1e4))throw RangeError("duration must be between 0 and 10000 milliseconds");if(s.flipDuration!==void 0&&(!Number.isFinite(s.flipDuration)||s.flipDuration<1||s.flipDuration>1e4))throw RangeError("flipDuration must be between 1 and 10000 milliseconds")}var Yd={validate(s){if(typeof s.value!="number"&&typeof s.value!="bigint")throw TypeError("value must be a number or bigint");Xd(s)},model:s=>Ld(s.value,s),direction:Id};class qd{host;source;options;target;displayed;semantic;measurement;visual;measures=new Map;columns=new Map;sizes=new Map;scheduler;enhanced=!1;destroyed=!1;visible=!0;reset=!0;measurementPending=!1;hadClass;previousLeft;blur;blurIntensity=1;constructor(e,t,n){this.host=e,this.source=n,n.validate(t),this.options={...t},this.target=this.displayed=n.model(t);let i=e.ownerDocument,r=o=>{let l=i.createElement("span");return l.className=o,l};this.semantic=r("rn-value"),this.measurement=r("rn-measure"),this.visual=r("rn-visual"),this.measurement.setAttribute("aria-hidden","true"),this.visual.setAttribute("aria-hidden","true"),this.semantic.textContent=this.target.text,this.hadClass=e.classList.contains("rn-root"),e.classList.add("rn-root"),e.replaceChildren(this.semantic,this.measurement,this.visual);let a=i.defaultView;a&&typeof a.matchMedia=="function"&&typeof a.requestAnimationFrame=="function"&&typeof e.animate=="function"&&(this.scheduler=Dl.for(a),this.scheduler.add(this,e),this.scheduler.watch(this.measurement,this)),this.prepare()}canAnimate(){return!!this.scheduler&&this.options.animated!==!1&&(this.options.duration??500)>0&&!this.scheduler.media.matches&&!this.host.ownerDocument.hidden&&(this.visible||this.options.pauseOffscreen===!1)&&this.target.rollable&&this.host.isConnected}update(e){if(this.destroyed)return;let t={...this.options,...e};this.source.validate(t);let n=this.source.model(t),i=n.text===this.target.text&&n.signature===this.target.signature;if(this.options.motionBlur&&!t.motionBlur&&(this.blur?.destroy(),this.blur=void 0,Hd(this.visual)),La(this.options)!==La(t)&&(this.reset=!0),this.options=t,this.target=n,!this.canAnimate()){this.finish();return}i&&this.enhanced&&!this.reset||(this.semantic.textContent=n.text,this.prepare())}prepare(){if(!this.canAnimate()){this.finish();return}this.measurementPending=!0,this.scheduler?.enqueue(this)}stage(){if(!this.destroyed)return this.canAnimate()?(this.previousLeft=this.enhanced&&!this.reset?this.measurement.getBoundingClientRect().left:void 0,()=>this.stageMeasurement()):()=>this.finish()}stageMeasurement(){let e=new Set(this.target.tokens.map(n=>n.key));for(let[n,i]of this.measures)e.has(n)||(this.scheduler?.unwatch(i),this.sizes.delete(i),i.remove(),this.measures.delete(n));let t=null;for(let n of this.target.tokens){let i=this.measures.get(n.key);i||(i=this.host.ownerDocument.createElement("span"),i.className="rn-token",this.measures.set(n.key,i),this.scheduler?.watch(i,this)),i.textContent!==n.text&&(i.textContent=n.text);let r=t?t.nextSibling:this.measurement.firstChild;i!==r&&this.measurement.insertBefore(i,r),t=i}this.host.dataset.rnMeasuring=""}measure(){if(this.destroyed)return;if(!this.canAnimate())return()=>this.finish();let e=this.measurement.getBoundingClientRect(),t=this.host.ownerDocument.defaultView;if(!t)return()=>this.finish();let n=t.getComputedStyle(this.measurement);if(n.direction==="rtl")return()=>this.finish();let i=parseFloat(n.width),r=parseFloat(n.height);if(!i||!r||!e.width||!e.height)return()=>this.finish();let a=e.width/i,o=e.height/r,l=parseFloat(n.getPropertyValue("--rn-blur"));this.blurIntensity=Number.isFinite(l)?Math.max(0,l):1,this.sizes.set(this.measurement,{width:i,height:r});let c=new Map;for(let[u,d]of this.measures){let f=d.getBoundingClientRect(),g={width:f.width/a,height:f.height/o};this.sizes.set(d,g),c.set(u,{...g,x:(f.left-e.left)/a,y:(f.top-e.top)/o})}let h=this.previousLeft===void 0?0:(this.previousLeft-e.left)/a;return()=>this.commit(c,h)}makeColumn(e){let t=this.host.ownerDocument.createElement("span");t.className="rn-slot",t.dataset.rnKey=e.key,e.index!==void 0&&(t.dataset.rnWheel=""),this.options.mode==="flap"&&(t.dataset.rnFlap="");let n=this.host.ownerDocument.createElement("span");return n.className="rn-reel",t.append(n),this.visual.append(t),{token:e,element:t,reel:n,x:new as(t,"transform"),opacity:new as(t,"opacity"),roll:new as(n,"transform"),exiting:!1,height:0,width:0}}face(e,t){let n=this.host.ownerDocument.createElement("span");n.className="rn-face",n.textContent=t,n.style.height=`${e.height}px`;let i=e.reel.children.length;n.style.position="absolute",n.style.top="0",n.style.left="0",n.style.width="100%",n.style.transform=`translateY(${i*e.height}px)`,e.reel.style.height=`${(i+1)*e.height}px`,e.reel.append(n)}rest(e){this.blur?.remove(e.reel),e.reel.replaceChildren(),e.reel.style.removeProperty("height"),this.face(e,e.token.text),this.wrapInk(e),e.token.index===void 0?e.roll.set(1,Pa):e.roll.set(e.token.index,()=>"translateY(0px)")}wrapInk(e){if(this.options.mode==="flap")return;let t=this.host.ownerDocument.createElement("span");t.className="rn-ink",t.append(...e.reel.childNodes),e.reel.append(t)}finishEntry(e){e.entry&&(e.entry.blurred&&this.blur?.remove(e.reel),e.entry.track.cancel(),e.entry.element.replaceWith(e.reel),e.entry=void 0)}enter(e,t,n,i){let r=this.host.ownerDocument.createElement("span");r.className="rn-enter",e.reel.replaceWith(r),r.append(e.reel);let a=new as(r,"transform");e.entry={element:r,track:a,blurred:!1};let o=hr(Nd(e.height*(i?.entryDistance??1),i?.entryDuration??t,i?.entryHold),n);if(this.options.motionBlur&&e.token.text.trim()){this.blur??=new Ra(this.host),this.blur.intensity=this.blurIntensity;let l={...o,points:o.points.map(c=>c/e.height)};e.entry.blurred=this.blur.apply(e.reel,l,e.height,0,"entry")}a.play(o,l=>`translateY(${l}px)`,()=>this.finishEntry(e))}commit(e,t){if(this.destroyed)return;this.measurementPending=!1;let n=this.enhanced&&!this.reset,i=n?this.options.duration??500:0,r=Wd.get(this.host),a=i?r?.widthDuration??i:0,o=this.options.mode==="flap",l=this.options.direction==="up"?1:this.options.direction==="down"?-1:this.source.direction(this.displayed,this.target);this.target.text!==this.displayed.text&&(this.host.dataset.rnTrend=l>0?"up":l<0?"down":"none");let c=new Map([...this.columns].map(([M,E])=>{let w=E.x.read();return[M,{...w,x:w.position,width:E.width}]})),h=Sc(this.target.tokens.map(M=>M.key),c),u=[...c.keys()].sort((M,E)=>c.get(M).x-c.get(E).x),d=Sc(u,e),f=new Map(this.displayed.tokens.filter(M=>M.index===void 0).map(M=>[M.identity,M.key])),g=new Map(this.target.tokens.filter(M=>M.index===void 0).map(M=>[M.identity,M.key])),x=this.options.stagger==="start"||this.options.stagger==="end",p=this.target.tokens.map(M=>{let E=this.columns.get(M.key);return!E||E.exiting||x&&M.index!==void 0&&E.token.text!==M.text}),m=Od(this.target.tokens.map((M,E)=>M.index!==void 0&&!p[E]),this.options.stagger),S=Math.max(0,...this.target.tokens.map((M,E)=>p[E]?m[E]-1:0)),T=Math.min(i*.045,i*.3/Math.max(1,S));for(let[M,E]of this.target.tokens.entries()){let w=e.get(E.key);if(!w)continue;let C=Math.max(0,m[M]-1)*T,v=f.get(E.identity),b=v!==void 0&&v!==E.key?c.get(v):void 0,D=this.columns.get(E.key),R=!D;if(!D){D=this.makeColumn(E),this.columns.set(E.key,D);let k=(b?.x??h.get(E.key)??w.x)+t;D.x.set(n?k+(w.x-k)*(b?0:r?.entryOrigin??0):w.x,Ca),D.opacity.set(n?0:1,Da)}let F=D.token.text!==E.text,O=Math.abs(D.height-w.height)>.1,X=D.exiting;D.exiting=!1,D.element.style.width=`${w.width}px`,D.element.style.height=`${w.height}px`,D.element.style.top=`${w.y}px`;let V=c.get(E.key);if(D.x.play(ni(V?V.position+t:D.x.read().position,w.x,V?.velocity??0,a),Ca),R||X||!n){let k=D.opacity.read(),U=ni(k.position,1,k.velocity,E.index===void 0?Math.min(i,180):i?r?.fadeDuration??i:0),Q=!o&&E.identity.startsWith("group:")&&!b?(r?.entryDuration??i)*(r?.entryHold??.14):0;D.opacity.play(R?hr(U,C+Q):U,Da)}if(D.height=w.height,D.width=w.width,(!n||O)&&this.finishEntry(D),R&&o&&E.wheel&&i&&D.roll.set(Math.max(0,E.wheel.indexOf(" ")),()=>"translateY(0px)"),o&&!O&&(F||R)&&E.index!==void 0&&E.wheel&&i&&D.roll.read().position!==E.index){let k=D.roll.read(),U=Math.round(k.position),Q=yc(U,E.index,l,E.wheel.length),K=this.options.flipDuration??kd(i);this.blur?.remove(D.reel);let se;this.options.motionBlur&&this.blurIntensity>0&&(this.blur??=new Ra(this.host),this.blur.intensity=this.blurIntensity,se=this.blur.filterUrl(w.height)),Gd(D.reel,E.wheel,U,Q,w.height,K,C,se),D.token=E;let he=D;D.roll.play(hr(Vd(U,Q,K),C),()=>"translateY(0px)",()=>this.rest(he))}else if(!R&&!O&&F&&E.index!==void 0&&E.wheel&&D.token.index!==void 0&&i){let k=D.roll.read(),U=La(this.options)?Fd(D.token.wheel,k.position,E.text):void 0,Q=U?.from??k.position,K=U?.target??yc(k.position,E.index,l,E.wheel.length),se=U?.wheel??E.wheel,he=U?Math.min(Math.max(0,k.velocity),(K-Q)*1e4/i):k.velocity,le=x?hr(ni(Q,K,he,i),C):ni(Q,K,he,i),$=Math.floor(Math.min(...le.points)),ce=Math.ceil(Math.max(...le.points));D.entry&&(D.entry.blurred=!1);let Re=this.blur?.remove(D.reel)??0;D.reel.replaceChildren();for(let Z=$;Z<=ce;Z++)this.face(D,ta(se,Z));this.wrapInk(D),this.options.motionBlur&&(this.blur??=new Ra(this.host),this.blur.intensity=this.blurIntensity,this.blur.apply(D.reel,le,w.height,Re)),D.token=U?{...E,wheel:se,index:K}:E;let G=D;D.roll.play(le,Z=>`translateY(${($-Z)*w.height}px)`,()=>this.rest(G))}else(R||O||F||!n)&&(D.token=E,this.rest(D));if(R&&i&&E.index!==void 0&&!o&&this.enter(D,i,C,r),b&&i&&(R||X)){let k=D.roll.read(),U=D;D.roll.play(ni(R?.96:k.position,1,k.velocity,Math.min(i,180)),Pa,()=>this.rest(U))}}for(let[M,E]of this.columns){if(e.has(M))continue;let w=c.get(M),C=g.get(E.token.identity),v=C?e.get(C):void 0;if(E.x.play(ni(w.position+t,v?.x??d.get(M)??w.position,w.velocity,a),Ca),E.exiting)continue;if(E.exiting=!0,v&&i){let D=E.roll.read();E.roll.play(ni(D.position,1.04,D.velocity,Math.min(i,180)),Pa)}let b=E.opacity.read();E.opacity.play(ni(b.position,0,b.velocity,E.token.index===void 0?Math.min(i,180):i*.65),Da,()=>{E.exiting&&(this.removeColumn(E),this.columns.delete(M))})}this.enhanced=!0,this.reset=!1,this.displayed=this.target,this.host.dataset.rnReady=""}removeColumn(e){this.blur?.remove(e.reel),this.finishEntry(e),e.x.cancel(),e.roll.cancel(),e.opacity.cancel(),e.element.remove()}refresh(){this.destroyed||(this.reset=!0,this.prepare())}sizeChanged(e,t,n){if(this.measurementPending||!this.host.hasAttribute("data-rn-measuring"))return!1;let i=this.sizes.get(e);return!i||Math.abs(i.width-t)>.2||Math.abs(i.height-n)>.2}visibility(e){this.visible!==e&&(this.visible=e,(e||this.options.pauseOffscreen!==!1)&&this.refresh())}finish(){if(!this.destroyed){this.measurementPending=!1;for(let e of this.columns.values())this.removeColumn(e);this.columns.clear(),this.blur?.destroy(),this.blur=void 0,this.semantic.textContent=this.target.text,delete this.host.dataset.rnReady,delete this.host.dataset.rnMeasuring,delete this.host.dataset.rnTrend,this.enhanced=!1,this.reset=!0,this.displayed=this.target}}destroy(){if(!this.destroyed){this.finish(),this.destroyed=!0;for(let e of this.measures.values())this.scheduler?.unwatch(e);this.scheduler?.unwatch(this.measurement),this.scheduler?.remove(this,this.host),this.host.replaceChildren(this.host.ownerDocument.createTextNode(this.target.text)),!this.hadClass&&this.host.classList.remove("rn-root"),wo.delete(this.host)}}}function fa(s,e){if(wo.has(s))throw Error("A rolling number is already mounted on this element");let t=new qd(s,e,Yd);return wo.add(s),t}const Ll="183",ls={ROTATE:0,DOLLY:1,PAN:2},os={ROTATE:0,PAN:1,DOLLY_PAN:2,DOLLY_ROTATE:3},jd=0,Tc=1,Kd=2,qr=1,cu=2,Ys=3,Zn=0,qt=1,Pn=2,Bt=0,cs=1,Ac=2,wc=3,Rc=4,hu=5,qn=100,$d=101,Zd=102,Jd=103,Qd=104,Ro=200,ef=201,tf=202,nf=203,Co=204,Po=205,uu=206,sf=207,du=208,rf=209,af=210,of=211,lf=212,cf=213,hf=214,Do=0,Lo=1,Io=2,gs=3,No=4,Uo=5,Fo=6,Oo=7,Il=0,uf=1,df=2,Un=0,Nl=1,Ul=2,Fl=3,ar=4,Ol=5,Bl=6,kl=7,Cc="attached",ff="detached",fu=300,Di=301,_s=302,Ia=303,Na=304,pa=306,vi=1e3,Dn=1001,na=1002,xt=1003,pu=1004,qs=1005,Ct=1006,jr=1007,jn=1008,nn=1009,mu=1010,gu=1011,Qs=1012,Vl=1013,Fn=1014,sn=1015,on=1016,zl=1017,Hl=1018,vs=1020,_u=35902,vu=35899,xu=1021,Mu=1022,un=1023,Jn=1026,pi=1027,ma=1028,Gl=1029,xs=1030,Wl=1031,Xl=1033,Kr=33776,$r=33777,Zr=33778,Jr=33779,Bo=35840,ko=35841,Vo=35842,zo=35843,Ho=36196,Go=37492,Wo=37496,Xo=37488,Yo=37489,qo=37490,jo=37491,Ko=37808,$o=37809,Zo=37810,Jo=37811,Qo=37812,el=37813,tl=37814,nl=37815,il=37816,sl=37817,rl=37818,al=37819,ol=37820,ll=37821,cl=36492,hl=36494,ul=36495,dl=36283,fl=36284,pl=36285,ml=36286,er=2300,tr=2301,Ua=2302,Pc=2303,Dc=2400,Lc=2401,Ic=2402,pf=2500,mf=0,yu=1,gl=2,gf=3200,_f=3201,ga=0,vf=1,di="",wt="srgb",Kt="srgb-linear",ia="linear",tt="srgb",Vi=7680,Nc=519,xf=512,Mf=513,yf=514,Yl=515,Sf=516,bf=517,ql=518,Ef=519,_l=35044,Tf=35048,Uc="300 es",Ln=2e3,nr=2001;function Af(s){for(let e=s.length-1;e>=0;--e)if(s[e]>=65535)return!0;return!1}function wf(s){return ArrayBuffer.isView(s)&&!(s instanceof DataView)}function ir(s){return document.createElementNS("http://www.w3.org/1999/xhtml",s)}function Rf(){const s=ir("canvas");return s.style.display="block",s}const Fc={};function sa(...s){const e="THREE."+s.shift();console.log(e,...s)}function Su(s){const e=s[0];if(typeof e=="string"&&e.startsWith("TSL:")){const t=s[1];t&&t.isStackTrace?s[0]+=" "+t.getLocation():s[1]='Stack trace not available. Enable "THREE.Node.captureStackTrace" to capture stack traces.'}return s}function Pe(...s){s=Su(s);const e="THREE."+s.shift();{const t=s[0];t&&t.isStackTrace?console.warn(t.getError(e)):console.warn(e,...s)}}function Ue(...s){s=Su(s);const e="THREE."+s.shift();{const t=s[0];t&&t.isStackTrace?console.error(t.getError(e)):console.error(e,...s)}}function ra(...s){const e=s.join(" ");e in Fc||(Fc[e]=!0,Pe(...s))}function Cf(s,e,t){return new Promise(function(n,i){function r(){switch(s.clientWaitSync(e,s.SYNC_FLUSH_COMMANDS_BIT,0)){case s.WAIT_FAILED:i();break;case s.TIMEOUT_EXPIRED:setTimeout(r,t);break;default:n()}}setTimeout(r,t)})}const Pf={[Do]:Lo,[Io]:Fo,[No]:Oo,[gs]:Uo,[Lo]:Do,[Fo]:Io,[Oo]:No,[Uo]:gs};class Ni{addEventListener(e,t){this._listeners===void 0&&(this._listeners={});const n=this._listeners;n[e]===void 0&&(n[e]=[]),n[e].indexOf(t)===-1&&n[e].push(t)}hasEventListener(e,t){const n=this._listeners;return n===void 0?!1:n[e]!==void 0&&n[e].indexOf(t)!==-1}removeEventListener(e,t){const n=this._listeners;if(n===void 0)return;const i=n[e];if(i!==void 0){const r=i.indexOf(t);r!==-1&&i.splice(r,1)}}dispatchEvent(e){const t=this._listeners;if(t===void 0)return;const n=t[e.type];if(n!==void 0){e.target=this;const i=n.slice(0);for(let r=0,a=i.length;r<a;r++)i[r].call(this,e);e.target=null}}}const Ht=["00","01","02","03","04","05","06","07","08","09","0a","0b","0c","0d","0e","0f","10","11","12","13","14","15","16","17","18","19","1a","1b","1c","1d","1e","1f","20","21","22","23","24","25","26","27","28","29","2a","2b","2c","2d","2e","2f","30","31","32","33","34","35","36","37","38","39","3a","3b","3c","3d","3e","3f","40","41","42","43","44","45","46","47","48","49","4a","4b","4c","4d","4e","4f","50","51","52","53","54","55","56","57","58","59","5a","5b","5c","5d","5e","5f","60","61","62","63","64","65","66","67","68","69","6a","6b","6c","6d","6e","6f","70","71","72","73","74","75","76","77","78","79","7a","7b","7c","7d","7e","7f","80","81","82","83","84","85","86","87","88","89","8a","8b","8c","8d","8e","8f","90","91","92","93","94","95","96","97","98","99","9a","9b","9c","9d","9e","9f","a0","a1","a2","a3","a4","a5","a6","a7","a8","a9","aa","ab","ac","ad","ae","af","b0","b1","b2","b3","b4","b5","b6","b7","b8","b9","ba","bb","bc","bd","be","bf","c0","c1","c2","c3","c4","c5","c6","c7","c8","c9","ca","cb","cc","cd","ce","cf","d0","d1","d2","d3","d4","d5","d6","d7","d8","d9","da","db","dc","dd","de","df","e0","e1","e2","e3","e4","e5","e6","e7","e8","e9","ea","eb","ec","ed","ee","ef","f0","f1","f2","f3","f4","f5","f6","f7","f8","f9","fa","fb","fc","fd","fe","ff"];let Oc=1234567;const $s=Math.PI/180,Ms=180/Math.PI;function Mn(){const s=Math.random()*4294967295|0,e=Math.random()*4294967295|0,t=Math.random()*4294967295|0,n=Math.random()*4294967295|0;return(Ht[s&255]+Ht[s>>8&255]+Ht[s>>16&255]+Ht[s>>24&255]+"-"+Ht[e&255]+Ht[e>>8&255]+"-"+Ht[e>>16&15|64]+Ht[e>>24&255]+"-"+Ht[t&63|128]+Ht[t>>8&255]+"-"+Ht[t>>16&255]+Ht[t>>24&255]+Ht[n&255]+Ht[n>>8&255]+Ht[n>>16&255]+Ht[n>>24&255]).toLowerCase()}function Xe(s,e,t){return Math.max(e,Math.min(t,s))}function jl(s,e){return(s%e+e)%e}function Df(s,e,t,n,i){return n+(s-e)*(i-n)/(t-e)}function Lf(s,e,t){return s!==e?(t-s)/(e-s):0}function Zs(s,e,t){return(1-t)*s+t*e}function If(s,e,t,n){return Zs(s,e,1-Math.exp(-t*n))}function Nf(s,e=1){return e-Math.abs(jl(s,e*2)-e)}function Uf(s,e,t){return s<=e?0:s>=t?1:(s=(s-e)/(t-e),s*s*(3-2*s))}function Ff(s,e,t){return s<=e?0:s>=t?1:(s=(s-e)/(t-e),s*s*s*(s*(s*6-15)+10))}function Of(s,e){return s+Math.floor(Math.random()*(e-s+1))}function Bf(s,e){return s+Math.random()*(e-s)}function kf(s){return s*(.5-Math.random())}function Vf(s){s!==void 0&&(Oc=s);let e=Oc+=1831565813;return e=Math.imul(e^e>>>15,e|1),e^=e+Math.imul(e^e>>>7,e|61),((e^e>>>14)>>>0)/4294967296}function zf(s){return s*$s}function Hf(s){return s*Ms}function Gf(s){return(s&s-1)===0&&s!==0}function Wf(s){return Math.pow(2,Math.ceil(Math.log(s)/Math.LN2))}function Xf(s){return Math.pow(2,Math.floor(Math.log(s)/Math.LN2))}function Yf(s,e,t,n,i){const r=Math.cos,a=Math.sin,o=r(t/2),l=a(t/2),c=r((e+n)/2),h=a((e+n)/2),u=r((e-n)/2),d=a((e-n)/2),f=r((n-e)/2),g=a((n-e)/2);switch(i){case"XYX":s.set(o*h,l*u,l*d,o*c);break;case"YZY":s.set(l*d,o*h,l*u,o*c);break;case"ZXZ":s.set(l*u,l*d,o*h,o*c);break;case"XZX":s.set(o*h,l*g,l*f,o*c);break;case"YXY":s.set(l*f,o*h,l*g,o*c);break;case"ZYZ":s.set(l*g,l*f,o*h,o*c);break;default:Pe("MathUtils: .setQuaternionFromProperEuler() encountered an unknown order: "+i)}}function _n(s,e){switch(e.constructor){case Float32Array:return s;case Uint32Array:return s/4294967295;case Uint16Array:return s/65535;case Uint8Array:return s/255;case Int32Array:return Math.max(s/2147483647,-1);case Int16Array:return Math.max(s/32767,-1);case Int8Array:return Math.max(s/127,-1);default:throw new Error("Invalid component type.")}}function it(s,e){switch(e.constructor){case Float32Array:return s;case Uint32Array:return Math.round(s*4294967295);case Uint16Array:return Math.round(s*65535);case Uint8Array:return Math.round(s*255);case Int32Array:return Math.round(s*2147483647);case Int16Array:return Math.round(s*32767);case Int8Array:return Math.round(s*127);default:throw new Error("Invalid component type.")}}const je={DEG2RAD:$s,RAD2DEG:Ms,generateUUID:Mn,clamp:Xe,euclideanModulo:jl,mapLinear:Df,inverseLerp:Lf,lerp:Zs,damp:If,pingpong:Nf,smoothstep:Uf,smootherstep:Ff,randInt:Of,randFloat:Bf,randFloatSpread:kf,seededRandom:Vf,degToRad:zf,radToDeg:Hf,isPowerOfTwo:Gf,ceilPowerOfTwo:Wf,floorPowerOfTwo:Xf,setQuaternionFromProperEuler:Yf,normalize:it,denormalize:_n};class Le{constructor(e=0,t=0){Le.prototype.isVector2=!0,this.x=e,this.y=t}get width(){return this.x}set width(e){this.x=e}get height(){return this.y}set height(e){this.y=e}set(e,t){return this.x=e,this.y=t,this}setScalar(e){return this.x=e,this.y=e,this}setX(e){return this.x=e,this}setY(e){return this.y=e,this}setComponent(e,t){switch(e){case 0:this.x=t;break;case 1:this.y=t;break;default:throw new Error("index is out of range: "+e)}return this}getComponent(e){switch(e){case 0:return this.x;case 1:return this.y;default:throw new Error("index is out of range: "+e)}}clone(){return new this.constructor(this.x,this.y)}copy(e){return this.x=e.x,this.y=e.y,this}add(e){return this.x+=e.x,this.y+=e.y,this}addScalar(e){return this.x+=e,this.y+=e,this}addVectors(e,t){return this.x=e.x+t.x,this.y=e.y+t.y,this}addScaledVector(e,t){return this.x+=e.x*t,this.y+=e.y*t,this}sub(e){return this.x-=e.x,this.y-=e.y,this}subScalar(e){return this.x-=e,this.y-=e,this}subVectors(e,t){return this.x=e.x-t.x,this.y=e.y-t.y,this}multiply(e){return this.x*=e.x,this.y*=e.y,this}multiplyScalar(e){return this.x*=e,this.y*=e,this}divide(e){return this.x/=e.x,this.y/=e.y,this}divideScalar(e){return this.multiplyScalar(1/e)}applyMatrix3(e){const t=this.x,n=this.y,i=e.elements;return this.x=i[0]*t+i[3]*n+i[6],this.y=i[1]*t+i[4]*n+i[7],this}min(e){return this.x=Math.min(this.x,e.x),this.y=Math.min(this.y,e.y),this}max(e){return this.x=Math.max(this.x,e.x),this.y=Math.max(this.y,e.y),this}clamp(e,t){return this.x=Xe(this.x,e.x,t.x),this.y=Xe(this.y,e.y,t.y),this}clampScalar(e,t){return this.x=Xe(this.x,e,t),this.y=Xe(this.y,e,t),this}clampLength(e,t){const n=this.length();return this.divideScalar(n||1).multiplyScalar(Xe(n,e,t))}floor(){return this.x=Math.floor(this.x),this.y=Math.floor(this.y),this}ceil(){return this.x=Math.ceil(this.x),this.y=Math.ceil(this.y),this}round(){return this.x=Math.round(this.x),this.y=Math.round(this.y),this}roundToZero(){return this.x=Math.trunc(this.x),this.y=Math.trunc(this.y),this}negate(){return this.x=-this.x,this.y=-this.y,this}dot(e){return this.x*e.x+this.y*e.y}cross(e){return this.x*e.y-this.y*e.x}lengthSq(){return this.x*this.x+this.y*this.y}length(){return Math.sqrt(this.x*this.x+this.y*this.y)}manhattanLength(){return Math.abs(this.x)+Math.abs(this.y)}normalize(){return this.divideScalar(this.length()||1)}angle(){return Math.atan2(-this.y,-this.x)+Math.PI}angleTo(e){const t=Math.sqrt(this.lengthSq()*e.lengthSq());if(t===0)return Math.PI/2;const n=this.dot(e)/t;return Math.acos(Xe(n,-1,1))}distanceTo(e){return Math.sqrt(this.distanceToSquared(e))}distanceToSquared(e){const t=this.x-e.x,n=this.y-e.y;return t*t+n*n}manhattanDistanceTo(e){return Math.abs(this.x-e.x)+Math.abs(this.y-e.y)}setLength(e){return this.normalize().multiplyScalar(e)}lerp(e,t){return this.x+=(e.x-this.x)*t,this.y+=(e.y-this.y)*t,this}lerpVectors(e,t,n){return this.x=e.x+(t.x-e.x)*n,this.y=e.y+(t.y-e.y)*n,this}equals(e){return e.x===this.x&&e.y===this.y}fromArray(e,t=0){return this.x=e[t],this.y=e[t+1],this}toArray(e=[],t=0){return e[t]=this.x,e[t+1]=this.y,e}fromBufferAttribute(e,t){return this.x=e.getX(t),this.y=e.getY(t),this}rotateAround(e,t){const n=Math.cos(t),i=Math.sin(t),r=this.x-e.x,a=this.y-e.y;return this.x=r*n-a*i+e.x,this.y=r*i+a*n+e.y,this}random(){return this.x=Math.random(),this.y=Math.random(),this}*[Symbol.iterator](){yield this.x,yield this.y}}class yn{constructor(e=0,t=0,n=0,i=1){this.isQuaternion=!0,this._x=e,this._y=t,this._z=n,this._w=i}static slerpFlat(e,t,n,i,r,a,o){let l=n[i+0],c=n[i+1],h=n[i+2],u=n[i+3],d=r[a+0],f=r[a+1],g=r[a+2],x=r[a+3];if(u!==x||l!==d||c!==f||h!==g){let p=l*d+c*f+h*g+u*x;p<0&&(d=-d,f=-f,g=-g,x=-x,p=-p);let m=1-o;if(p<.9995){const S=Math.acos(p),T=Math.sin(S);m=Math.sin(m*S)/T,o=Math.sin(o*S)/T,l=l*m+d*o,c=c*m+f*o,h=h*m+g*o,u=u*m+x*o}else{l=l*m+d*o,c=c*m+f*o,h=h*m+g*o,u=u*m+x*o;const S=1/Math.sqrt(l*l+c*c+h*h+u*u);l*=S,c*=S,h*=S,u*=S}}e[t]=l,e[t+1]=c,e[t+2]=h,e[t+3]=u}static multiplyQuaternionsFlat(e,t,n,i,r,a){const o=n[i],l=n[i+1],c=n[i+2],h=n[i+3],u=r[a],d=r[a+1],f=r[a+2],g=r[a+3];return e[t]=o*g+h*u+l*f-c*d,e[t+1]=l*g+h*d+c*u-o*f,e[t+2]=c*g+h*f+o*d-l*u,e[t+3]=h*g-o*u-l*d-c*f,e}get x(){return this._x}set x(e){this._x=e,this._onChangeCallback()}get y(){return this._y}set y(e){this._y=e,this._onChangeCallback()}get z(){return this._z}set z(e){this._z=e,this._onChangeCallback()}get w(){return this._w}set w(e){this._w=e,this._onChangeCallback()}set(e,t,n,i){return this._x=e,this._y=t,this._z=n,this._w=i,this._onChangeCallback(),this}clone(){return new this.constructor(this._x,this._y,this._z,this._w)}copy(e){return this._x=e.x,this._y=e.y,this._z=e.z,this._w=e.w,this._onChangeCallback(),this}setFromEuler(e,t=!0){const n=e._x,i=e._y,r=e._z,a=e._order,o=Math.cos,l=Math.sin,c=o(n/2),h=o(i/2),u=o(r/2),d=l(n/2),f=l(i/2),g=l(r/2);switch(a){case"XYZ":this._x=d*h*u+c*f*g,this._y=c*f*u-d*h*g,this._z=c*h*g+d*f*u,this._w=c*h*u-d*f*g;break;case"YXZ":this._x=d*h*u+c*f*g,this._y=c*f*u-d*h*g,this._z=c*h*g-d*f*u,this._w=c*h*u+d*f*g;break;case"ZXY":this._x=d*h*u-c*f*g,this._y=c*f*u+d*h*g,this._z=c*h*g+d*f*u,this._w=c*h*u-d*f*g;break;case"ZYX":this._x=d*h*u-c*f*g,this._y=c*f*u+d*h*g,this._z=c*h*g-d*f*u,this._w=c*h*u+d*f*g;break;case"YZX":this._x=d*h*u+c*f*g,this._y=c*f*u+d*h*g,this._z=c*h*g-d*f*u,this._w=c*h*u-d*f*g;break;case"XZY":this._x=d*h*u-c*f*g,this._y=c*f*u-d*h*g,this._z=c*h*g+d*f*u,this._w=c*h*u+d*f*g;break;default:Pe("Quaternion: .setFromEuler() encountered an unknown order: "+a)}return t===!0&&this._onChangeCallback(),this}setFromAxisAngle(e,t){const n=t/2,i=Math.sin(n);return this._x=e.x*i,this._y=e.y*i,this._z=e.z*i,this._w=Math.cos(n),this._onChangeCallback(),this}setFromRotationMatrix(e){const t=e.elements,n=t[0],i=t[4],r=t[8],a=t[1],o=t[5],l=t[9],c=t[2],h=t[6],u=t[10],d=n+o+u;if(d>0){const f=.5/Math.sqrt(d+1);this._w=.25/f,this._x=(h-l)*f,this._y=(r-c)*f,this._z=(a-i)*f}else if(n>o&&n>u){const f=2*Math.sqrt(1+n-o-u);this._w=(h-l)/f,this._x=.25*f,this._y=(i+a)/f,this._z=(r+c)/f}else if(o>u){const f=2*Math.sqrt(1+o-n-u);this._w=(r-c)/f,this._x=(i+a)/f,this._y=.25*f,this._z=(l+h)/f}else{const f=2*Math.sqrt(1+u-n-o);this._w=(a-i)/f,this._x=(r+c)/f,this._y=(l+h)/f,this._z=.25*f}return this._onChangeCallback(),this}setFromUnitVectors(e,t){let n=e.dot(t)+1;return n<1e-8?(n=0,Math.abs(e.x)>Math.abs(e.z)?(this._x=-e.y,this._y=e.x,this._z=0,this._w=n):(this._x=0,this._y=-e.z,this._z=e.y,this._w=n)):(this._x=e.y*t.z-e.z*t.y,this._y=e.z*t.x-e.x*t.z,this._z=e.x*t.y-e.y*t.x,this._w=n),this.normalize()}angleTo(e){return 2*Math.acos(Math.abs(Xe(this.dot(e),-1,1)))}rotateTowards(e,t){const n=this.angleTo(e);if(n===0)return this;const i=Math.min(1,t/n);return this.slerp(e,i),this}identity(){return this.set(0,0,0,1)}invert(){return this.conjugate()}conjugate(){return this._x*=-1,this._y*=-1,this._z*=-1,this._onChangeCallback(),this}dot(e){return this._x*e._x+this._y*e._y+this._z*e._z+this._w*e._w}lengthSq(){return this._x*this._x+this._y*this._y+this._z*this._z+this._w*this._w}length(){return Math.sqrt(this._x*this._x+this._y*this._y+this._z*this._z+this._w*this._w)}normalize(){let e=this.length();return e===0?(this._x=0,this._y=0,this._z=0,this._w=1):(e=1/e,this._x=this._x*e,this._y=this._y*e,this._z=this._z*e,this._w=this._w*e),this._onChangeCallback(),this}multiply(e){return this.multiplyQuaternions(this,e)}premultiply(e){return this.multiplyQuaternions(e,this)}multiplyQuaternions(e,t){const n=e._x,i=e._y,r=e._z,a=e._w,o=t._x,l=t._y,c=t._z,h=t._w;return this._x=n*h+a*o+i*c-r*l,this._y=i*h+a*l+r*o-n*c,this._z=r*h+a*c+n*l-i*o,this._w=a*h-n*o-i*l-r*c,this._onChangeCallback(),this}slerp(e,t){let n=e._x,i=e._y,r=e._z,a=e._w,o=this.dot(e);o<0&&(n=-n,i=-i,r=-r,a=-a,o=-o);let l=1-t;if(o<.9995){const c=Math.acos(o),h=Math.sin(c);l=Math.sin(l*c)/h,t=Math.sin(t*c)/h,this._x=this._x*l+n*t,this._y=this._y*l+i*t,this._z=this._z*l+r*t,this._w=this._w*l+a*t,this._onChangeCallback()}else this._x=this._x*l+n*t,this._y=this._y*l+i*t,this._z=this._z*l+r*t,this._w=this._w*l+a*t,this.normalize();return this}slerpQuaternions(e,t,n){return this.copy(e).slerp(t,n)}random(){const e=2*Math.PI*Math.random(),t=2*Math.PI*Math.random(),n=Math.random(),i=Math.sqrt(1-n),r=Math.sqrt(n);return this.set(i*Math.sin(e),i*Math.cos(e),r*Math.sin(t),r*Math.cos(t))}equals(e){return e._x===this._x&&e._y===this._y&&e._z===this._z&&e._w===this._w}fromArray(e,t=0){return this._x=e[t],this._y=e[t+1],this._z=e[t+2],this._w=e[t+3],this._onChangeCallback(),this}toArray(e=[],t=0){return e[t]=this._x,e[t+1]=this._y,e[t+2]=this._z,e[t+3]=this._w,e}fromBufferAttribute(e,t){return this._x=e.getX(t),this._y=e.getY(t),this._z=e.getZ(t),this._w=e.getW(t),this._onChangeCallback(),this}toJSON(){return this.toArray()}_onChange(e){return this._onChangeCallback=e,this}_onChangeCallback(){}*[Symbol.iterator](){yield this._x,yield this._y,yield this._z,yield this._w}}class L{constructor(e=0,t=0,n=0){L.prototype.isVector3=!0,this.x=e,this.y=t,this.z=n}set(e,t,n){return n===void 0&&(n=this.z),this.x=e,this.y=t,this.z=n,this}setScalar(e){return this.x=e,this.y=e,this.z=e,this}setX(e){return this.x=e,this}setY(e){return this.y=e,this}setZ(e){return this.z=e,this}setComponent(e,t){switch(e){case 0:this.x=t;break;case 1:this.y=t;break;case 2:this.z=t;break;default:throw new Error("index is out of range: "+e)}return this}getComponent(e){switch(e){case 0:return this.x;case 1:return this.y;case 2:return this.z;default:throw new Error("index is out of range: "+e)}}clone(){return new this.constructor(this.x,this.y,this.z)}copy(e){return this.x=e.x,this.y=e.y,this.z=e.z,this}add(e){return this.x+=e.x,this.y+=e.y,this.z+=e.z,this}addScalar(e){return this.x+=e,this.y+=e,this.z+=e,this}addVectors(e,t){return this.x=e.x+t.x,this.y=e.y+t.y,this.z=e.z+t.z,this}addScaledVector(e,t){return this.x+=e.x*t,this.y+=e.y*t,this.z+=e.z*t,this}sub(e){return this.x-=e.x,this.y-=e.y,this.z-=e.z,this}subScalar(e){return this.x-=e,this.y-=e,this.z-=e,this}subVectors(e,t){return this.x=e.x-t.x,this.y=e.y-t.y,this.z=e.z-t.z,this}multiply(e){return this.x*=e.x,this.y*=e.y,this.z*=e.z,this}multiplyScalar(e){return this.x*=e,this.y*=e,this.z*=e,this}multiplyVectors(e,t){return this.x=e.x*t.x,this.y=e.y*t.y,this.z=e.z*t.z,this}applyEuler(e){return this.applyQuaternion(Bc.setFromEuler(e))}applyAxisAngle(e,t){return this.applyQuaternion(Bc.setFromAxisAngle(e,t))}applyMatrix3(e){const t=this.x,n=this.y,i=this.z,r=e.elements;return this.x=r[0]*t+r[3]*n+r[6]*i,this.y=r[1]*t+r[4]*n+r[7]*i,this.z=r[2]*t+r[5]*n+r[8]*i,this}applyNormalMatrix(e){return this.applyMatrix3(e).normalize()}applyMatrix4(e){const t=this.x,n=this.y,i=this.z,r=e.elements,a=1/(r[3]*t+r[7]*n+r[11]*i+r[15]);return this.x=(r[0]*t+r[4]*n+r[8]*i+r[12])*a,this.y=(r[1]*t+r[5]*n+r[9]*i+r[13])*a,this.z=(r[2]*t+r[6]*n+r[10]*i+r[14])*a,this}applyQuaternion(e){const t=this.x,n=this.y,i=this.z,r=e.x,a=e.y,o=e.z,l=e.w,c=2*(a*i-o*n),h=2*(o*t-r*i),u=2*(r*n-a*t);return this.x=t+l*c+a*u-o*h,this.y=n+l*h+o*c-r*u,this.z=i+l*u+r*h-a*c,this}project(e){return this.applyMatrix4(e.matrixWorldInverse).applyMatrix4(e.projectionMatrix)}unproject(e){return this.applyMatrix4(e.projectionMatrixInverse).applyMatrix4(e.matrixWorld)}transformDirection(e){const t=this.x,n=this.y,i=this.z,r=e.elements;return this.x=r[0]*t+r[4]*n+r[8]*i,this.y=r[1]*t+r[5]*n+r[9]*i,this.z=r[2]*t+r[6]*n+r[10]*i,this.normalize()}divide(e){return this.x/=e.x,this.y/=e.y,this.z/=e.z,this}divideScalar(e){return this.multiplyScalar(1/e)}min(e){return this.x=Math.min(this.x,e.x),this.y=Math.min(this.y,e.y),this.z=Math.min(this.z,e.z),this}max(e){return this.x=Math.max(this.x,e.x),this.y=Math.max(this.y,e.y),this.z=Math.max(this.z,e.z),this}clamp(e,t){return this.x=Xe(this.x,e.x,t.x),this.y=Xe(this.y,e.y,t.y),this.z=Xe(this.z,e.z,t.z),this}clampScalar(e,t){return this.x=Xe(this.x,e,t),this.y=Xe(this.y,e,t),this.z=Xe(this.z,e,t),this}clampLength(e,t){const n=this.length();return this.divideScalar(n||1).multiplyScalar(Xe(n,e,t))}floor(){return this.x=Math.floor(this.x),this.y=Math.floor(this.y),this.z=Math.floor(this.z),this}ceil(){return this.x=Math.ceil(this.x),this.y=Math.ceil(this.y),this.z=Math.ceil(this.z),this}round(){return this.x=Math.round(this.x),this.y=Math.round(this.y),this.z=Math.round(this.z),this}roundToZero(){return this.x=Math.trunc(this.x),this.y=Math.trunc(this.y),this.z=Math.trunc(this.z),this}negate(){return this.x=-this.x,this.y=-this.y,this.z=-this.z,this}dot(e){return this.x*e.x+this.y*e.y+this.z*e.z}lengthSq(){return this.x*this.x+this.y*this.y+this.z*this.z}length(){return Math.sqrt(this.x*this.x+this.y*this.y+this.z*this.z)}manhattanLength(){return Math.abs(this.x)+Math.abs(this.y)+Math.abs(this.z)}normalize(){return this.divideScalar(this.length()||1)}setLength(e){return this.normalize().multiplyScalar(e)}lerp(e,t){return this.x+=(e.x-this.x)*t,this.y+=(e.y-this.y)*t,this.z+=(e.z-this.z)*t,this}lerpVectors(e,t,n){return this.x=e.x+(t.x-e.x)*n,this.y=e.y+(t.y-e.y)*n,this.z=e.z+(t.z-e.z)*n,this}cross(e){return this.crossVectors(this,e)}crossVectors(e,t){const n=e.x,i=e.y,r=e.z,a=t.x,o=t.y,l=t.z;return this.x=i*l-r*o,this.y=r*a-n*l,this.z=n*o-i*a,this}projectOnVector(e){const t=e.lengthSq();if(t===0)return this.set(0,0,0);const n=e.dot(this)/t;return this.copy(e).multiplyScalar(n)}projectOnPlane(e){return Fa.copy(this).projectOnVector(e),this.sub(Fa)}reflect(e){return this.sub(Fa.copy(e).multiplyScalar(2*this.dot(e)))}angleTo(e){const t=Math.sqrt(this.lengthSq()*e.lengthSq());if(t===0)return Math.PI/2;const n=this.dot(e)/t;return Math.acos(Xe(n,-1,1))}distanceTo(e){return Math.sqrt(this.distanceToSquared(e))}distanceToSquared(e){const t=this.x-e.x,n=this.y-e.y,i=this.z-e.z;return t*t+n*n+i*i}manhattanDistanceTo(e){return Math.abs(this.x-e.x)+Math.abs(this.y-e.y)+Math.abs(this.z-e.z)}setFromSpherical(e){return this.setFromSphericalCoords(e.radius,e.phi,e.theta)}setFromSphericalCoords(e,t,n){const i=Math.sin(t)*e;return this.x=i*Math.sin(n),this.y=Math.cos(t)*e,this.z=i*Math.cos(n),this}setFromCylindrical(e){return this.setFromCylindricalCoords(e.radius,e.theta,e.y)}setFromCylindricalCoords(e,t,n){return this.x=e*Math.sin(t),this.y=n,this.z=e*Math.cos(t),this}setFromMatrixPosition(e){const t=e.elements;return this.x=t[12],this.y=t[13],this.z=t[14],this}setFromMatrixScale(e){const t=this.setFromMatrixColumn(e,0).length(),n=this.setFromMatrixColumn(e,1).length(),i=this.setFromMatrixColumn(e,2).length();return this.x=t,this.y=n,this.z=i,this}setFromMatrixColumn(e,t){return this.fromArray(e.elements,t*4)}setFromMatrix3Column(e,t){return this.fromArray(e.elements,t*3)}setFromEuler(e){return this.x=e._x,this.y=e._y,this.z=e._z,this}setFromColor(e){return this.x=e.r,this.y=e.g,this.z=e.b,this}equals(e){return e.x===this.x&&e.y===this.y&&e.z===this.z}fromArray(e,t=0){return this.x=e[t],this.y=e[t+1],this.z=e[t+2],this}toArray(e=[],t=0){return e[t]=this.x,e[t+1]=this.y,e[t+2]=this.z,e}fromBufferAttribute(e,t){return this.x=e.getX(t),this.y=e.getY(t),this.z=e.getZ(t),this}random(){return this.x=Math.random(),this.y=Math.random(),this.z=Math.random(),this}randomDirection(){const e=Math.random()*Math.PI*2,t=Math.random()*2-1,n=Math.sqrt(1-t*t);return this.x=n*Math.cos(e),this.y=t,this.z=n*Math.sin(e),this}*[Symbol.iterator](){yield this.x,yield this.y,yield this.z}}const Fa=new L,Bc=new yn;class He{constructor(e,t,n,i,r,a,o,l,c){He.prototype.isMatrix3=!0,this.elements=[1,0,0,0,1,0,0,0,1],e!==void 0&&this.set(e,t,n,i,r,a,o,l,c)}set(e,t,n,i,r,a,o,l,c){const h=this.elements;return h[0]=e,h[1]=i,h[2]=o,h[3]=t,h[4]=r,h[5]=l,h[6]=n,h[7]=a,h[8]=c,this}identity(){return this.set(1,0,0,0,1,0,0,0,1),this}copy(e){const t=this.elements,n=e.elements;return t[0]=n[0],t[1]=n[1],t[2]=n[2],t[3]=n[3],t[4]=n[4],t[5]=n[5],t[6]=n[6],t[7]=n[7],t[8]=n[8],this}extractBasis(e,t,n){return e.setFromMatrix3Column(this,0),t.setFromMatrix3Column(this,1),n.setFromMatrix3Column(this,2),this}setFromMatrix4(e){const t=e.elements;return this.set(t[0],t[4],t[8],t[1],t[5],t[9],t[2],t[6],t[10]),this}multiply(e){return this.multiplyMatrices(this,e)}premultiply(e){return this.multiplyMatrices(e,this)}multiplyMatrices(e,t){const n=e.elements,i=t.elements,r=this.elements,a=n[0],o=n[3],l=n[6],c=n[1],h=n[4],u=n[7],d=n[2],f=n[5],g=n[8],x=i[0],p=i[3],m=i[6],S=i[1],T=i[4],M=i[7],E=i[2],w=i[5],C=i[8];return r[0]=a*x+o*S+l*E,r[3]=a*p+o*T+l*w,r[6]=a*m+o*M+l*C,r[1]=c*x+h*S+u*E,r[4]=c*p+h*T+u*w,r[7]=c*m+h*M+u*C,r[2]=d*x+f*S+g*E,r[5]=d*p+f*T+g*w,r[8]=d*m+f*M+g*C,this}multiplyScalar(e){const t=this.elements;return t[0]*=e,t[3]*=e,t[6]*=e,t[1]*=e,t[4]*=e,t[7]*=e,t[2]*=e,t[5]*=e,t[8]*=e,this}determinant(){const e=this.elements,t=e[0],n=e[1],i=e[2],r=e[3],a=e[4],o=e[5],l=e[6],c=e[7],h=e[8];return t*a*h-t*o*c-n*r*h+n*o*l+i*r*c-i*a*l}invert(){const e=this.elements,t=e[0],n=e[1],i=e[2],r=e[3],a=e[4],o=e[5],l=e[6],c=e[7],h=e[8],u=h*a-o*c,d=o*l-h*r,f=c*r-a*l,g=t*u+n*d+i*f;if(g===0)return this.set(0,0,0,0,0,0,0,0,0);const x=1/g;return e[0]=u*x,e[1]=(i*c-h*n)*x,e[2]=(o*n-i*a)*x,e[3]=d*x,e[4]=(h*t-i*l)*x,e[5]=(i*r-o*t)*x,e[6]=f*x,e[7]=(n*l-c*t)*x,e[8]=(a*t-n*r)*x,this}transpose(){let e;const t=this.elements;return e=t[1],t[1]=t[3],t[3]=e,e=t[2],t[2]=t[6],t[6]=e,e=t[5],t[5]=t[7],t[7]=e,this}getNormalMatrix(e){return this.setFromMatrix4(e).invert().transpose()}transposeIntoArray(e){const t=this.elements;return e[0]=t[0],e[1]=t[3],e[2]=t[6],e[3]=t[1],e[4]=t[4],e[5]=t[7],e[6]=t[2],e[7]=t[5],e[8]=t[8],this}setUvTransform(e,t,n,i,r,a,o){const l=Math.cos(r),c=Math.sin(r);return this.set(n*l,n*c,-n*(l*a+c*o)+a+e,-i*c,i*l,-i*(-c*a+l*o)+o+t,0,0,1),this}scale(e,t){return this.premultiply(Oa.makeScale(e,t)),this}rotate(e){return this.premultiply(Oa.makeRotation(-e)),this}translate(e,t){return this.premultiply(Oa.makeTranslation(e,t)),this}makeTranslation(e,t){return e.isVector2?this.set(1,0,e.x,0,1,e.y,0,0,1):this.set(1,0,e,0,1,t,0,0,1),this}makeRotation(e){const t=Math.cos(e),n=Math.sin(e);return this.set(t,-n,0,n,t,0,0,0,1),this}makeScale(e,t){return this.set(e,0,0,0,t,0,0,0,1),this}equals(e){const t=this.elements,n=e.elements;for(let i=0;i<9;i++)if(t[i]!==n[i])return!1;return!0}fromArray(e,t=0){for(let n=0;n<9;n++)this.elements[n]=e[n+t];return this}toArray(e=[],t=0){const n=this.elements;return e[t]=n[0],e[t+1]=n[1],e[t+2]=n[2],e[t+3]=n[3],e[t+4]=n[4],e[t+5]=n[5],e[t+6]=n[6],e[t+7]=n[7],e[t+8]=n[8],e}clone(){return new this.constructor().fromArray(this.elements)}}const Oa=new He,kc=new He().set(.4123908,.3575843,.1804808,.212639,.7151687,.0721923,.0193308,.1191948,.9505322),Vc=new He().set(3.2409699,-1.5373832,-.4986108,-.9692436,1.8759675,.0415551,.0556301,-.203977,1.0569715);function qf(){const s={enabled:!0,workingColorSpace:Kt,spaces:{},convert:function(i,r,a){return this.enabled===!1||r===a||!r||!a||(this.spaces[r].transfer===tt&&(i.r=$n(i.r),i.g=$n(i.g),i.b=$n(i.b)),this.spaces[r].primaries!==this.spaces[a].primaries&&(i.applyMatrix3(this.spaces[r].toXYZ),i.applyMatrix3(this.spaces[a].fromXYZ)),this.spaces[a].transfer===tt&&(i.r=hs(i.r),i.g=hs(i.g),i.b=hs(i.b))),i},workingToColorSpace:function(i,r){return this.convert(i,this.workingColorSpace,r)},colorSpaceToWorking:function(i,r){return this.convert(i,r,this.workingColorSpace)},getPrimaries:function(i){return this.spaces[i].primaries},getTransfer:function(i){return i===di?ia:this.spaces[i].transfer},getToneMappingMode:function(i){return this.spaces[i].outputColorSpaceConfig.toneMappingMode||"standard"},getLuminanceCoefficients:function(i,r=this.workingColorSpace){return i.fromArray(this.spaces[r].luminanceCoefficients)},define:function(i){Object.assign(this.spaces,i)},_getMatrix:function(i,r,a){return i.copy(this.spaces[r].toXYZ).multiply(this.spaces[a].fromXYZ)},_getDrawingBufferColorSpace:function(i){return this.spaces[i].outputColorSpaceConfig.drawingBufferColorSpace},_getUnpackColorSpace:function(i=this.workingColorSpace){return this.spaces[i].workingColorSpaceConfig.unpackColorSpace},fromWorkingColorSpace:function(i,r){return ra("ColorManagement: .fromWorkingColorSpace() has been renamed to .workingToColorSpace()."),s.workingToColorSpace(i,r)},toWorkingColorSpace:function(i,r){return ra("ColorManagement: .toWorkingColorSpace() has been renamed to .colorSpaceToWorking()."),s.colorSpaceToWorking(i,r)}},e=[.64,.33,.3,.6,.15,.06],t=[.2126,.7152,.0722],n=[.3127,.329];return s.define({[Kt]:{primaries:e,whitePoint:n,transfer:ia,toXYZ:kc,fromXYZ:Vc,luminanceCoefficients:t,workingColorSpaceConfig:{unpackColorSpace:wt},outputColorSpaceConfig:{drawingBufferColorSpace:wt}},[wt]:{primaries:e,whitePoint:n,transfer:tt,toXYZ:kc,fromXYZ:Vc,luminanceCoefficients:t,outputColorSpaceConfig:{drawingBufferColorSpace:wt}}}),s}const Ke=qf();function $n(s){return s<.04045?s*.0773993808:Math.pow(s*.9478672986+.0521327014,2.4)}function hs(s){return s<.0031308?s*12.92:1.055*Math.pow(s,.41666)-.055}let zi;class jf{static getDataURL(e,t="image/png"){if(/^data:/i.test(e.src)||typeof HTMLCanvasElement>"u")return e.src;let n;if(e instanceof HTMLCanvasElement)n=e;else{zi===void 0&&(zi=ir("canvas")),zi.width=e.width,zi.height=e.height;const i=zi.getContext("2d");e instanceof ImageData?i.putImageData(e,0,0):i.drawImage(e,0,0,e.width,e.height),n=zi}return n.toDataURL(t)}static sRGBToLinear(e){if(typeof HTMLImageElement<"u"&&e instanceof HTMLImageElement||typeof HTMLCanvasElement<"u"&&e instanceof HTMLCanvasElement||typeof ImageBitmap<"u"&&e instanceof ImageBitmap){const t=ir("canvas");t.width=e.width,t.height=e.height;const n=t.getContext("2d");n.drawImage(e,0,0,e.width,e.height);const i=n.getImageData(0,0,e.width,e.height),r=i.data;for(let a=0;a<r.length;a++)r[a]=$n(r[a]/255)*255;return n.putImageData(i,0,0),t}else if(e.data){const t=e.data.slice(0);for(let n=0;n<t.length;n++)t instanceof Uint8Array||t instanceof Uint8ClampedArray?t[n]=Math.floor($n(t[n]/255)*255):t[n]=$n(t[n]);return{data:t,width:e.width,height:e.height}}else return Pe("ImageUtils.sRGBToLinear(): Unsupported image type. No color space conversion applied."),e}}let Kf=0;class Kl{constructor(e=null){this.isSource=!0,Object.defineProperty(this,"id",{value:Kf++}),this.uuid=Mn(),this.data=e,this.dataReady=!0,this.version=0}getSize(e){const t=this.data;return typeof HTMLVideoElement<"u"&&t instanceof HTMLVideoElement?e.set(t.videoWidth,t.videoHeight,0):typeof VideoFrame<"u"&&t instanceof VideoFrame?e.set(t.displayHeight,t.displayWidth,0):t!==null?e.set(t.width,t.height,t.depth||0):e.set(0,0,0),e}set needsUpdate(e){e===!0&&this.version++}toJSON(e){const t=e===void 0||typeof e=="string";if(!t&&e.images[this.uuid]!==void 0)return e.images[this.uuid];const n={uuid:this.uuid,url:""},i=this.data;if(i!==null){let r;if(Array.isArray(i)){r=[];for(let a=0,o=i.length;a<o;a++)i[a].isDataTexture?r.push(Ba(i[a].image)):r.push(Ba(i[a]))}else r=Ba(i);n.url=r}return t||(e.images[this.uuid]=n),n}}function Ba(s){return typeof HTMLImageElement<"u"&&s instanceof HTMLImageElement||typeof HTMLCanvasElement<"u"&&s instanceof HTMLCanvasElement||typeof ImageBitmap<"u"&&s instanceof ImageBitmap?jf.getDataURL(s):s.data?{data:Array.from(s.data),width:s.width,height:s.height,type:s.data.constructor.name}:(Pe("Texture: Unable to serialize Texture."),{})}let $f=0;const ka=new L;class Pt extends Ni{constructor(e=Pt.DEFAULT_IMAGE,t=Pt.DEFAULT_MAPPING,n=Dn,i=Dn,r=Ct,a=jn,o=un,l=nn,c=Pt.DEFAULT_ANISOTROPY,h=di){super(),this.isTexture=!0,Object.defineProperty(this,"id",{value:$f++}),this.uuid=Mn(),this.name="",this.source=new Kl(e),this.mipmaps=[],this.mapping=t,this.channel=0,this.wrapS=n,this.wrapT=i,this.magFilter=r,this.minFilter=a,this.anisotropy=c,this.format=o,this.internalFormat=null,this.type=l,this.offset=new Le(0,0),this.repeat=new Le(1,1),this.center=new Le(0,0),this.rotation=0,this.matrixAutoUpdate=!0,this.matrix=new He,this.generateMipmaps=!0,this.premultiplyAlpha=!1,this.flipY=!0,this.unpackAlignment=4,this.colorSpace=h,this.userData={},this.updateRanges=[],this.version=0,this.onUpdate=null,this.renderTarget=null,this.isRenderTargetTexture=!1,this.isArrayTexture=!!(e&&e.depth&&e.depth>1),this.pmremVersion=0}get width(){return this.source.getSize(ka).x}get height(){return this.source.getSize(ka).y}get depth(){return this.source.getSize(ka).z}get image(){return this.source.data}set image(e=null){this.source.data=e}updateMatrix(){this.matrix.setUvTransform(this.offset.x,this.offset.y,this.repeat.x,this.repeat.y,this.rotation,this.center.x,this.center.y)}addUpdateRange(e,t){this.updateRanges.push({start:e,count:t})}clearUpdateRanges(){this.updateRanges.length=0}clone(){return new this.constructor().copy(this)}copy(e){return this.name=e.name,this.source=e.source,this.mipmaps=e.mipmaps.slice(0),this.mapping=e.mapping,this.channel=e.channel,this.wrapS=e.wrapS,this.wrapT=e.wrapT,this.magFilter=e.magFilter,this.minFilter=e.minFilter,this.anisotropy=e.anisotropy,this.format=e.format,this.internalFormat=e.internalFormat,this.type=e.type,this.offset.copy(e.offset),this.repeat.copy(e.repeat),this.center.copy(e.center),this.rotation=e.rotation,this.matrixAutoUpdate=e.matrixAutoUpdate,this.matrix.copy(e.matrix),this.generateMipmaps=e.generateMipmaps,this.premultiplyAlpha=e.premultiplyAlpha,this.flipY=e.flipY,this.unpackAlignment=e.unpackAlignment,this.colorSpace=e.colorSpace,this.renderTarget=e.renderTarget,this.isRenderTargetTexture=e.isRenderTargetTexture,this.isArrayTexture=e.isArrayTexture,this.userData=JSON.parse(JSON.stringify(e.userData)),this.needsUpdate=!0,this}setValues(e){for(const t in e){const n=e[t];if(n===void 0){Pe(`Texture.setValues(): parameter '${t}' has value of undefined.`);continue}const i=this[t];if(i===void 0){Pe(`Texture.setValues(): property '${t}' does not exist.`);continue}i&&n&&i.isVector2&&n.isVector2||i&&n&&i.isVector3&&n.isVector3||i&&n&&i.isMatrix3&&n.isMatrix3?i.copy(n):this[t]=n}}toJSON(e){const t=e===void 0||typeof e=="string";if(!t&&e.textures[this.uuid]!==void 0)return e.textures[this.uuid];const n={metadata:{version:4.7,type:"Texture",generator:"Texture.toJSON"},uuid:this.uuid,name:this.name,image:this.source.toJSON(e).uuid,mapping:this.mapping,channel:this.channel,repeat:[this.repeat.x,this.repeat.y],offset:[this.offset.x,this.offset.y],center:[this.center.x,this.center.y],rotation:this.rotation,wrap:[this.wrapS,this.wrapT],format:this.format,internalFormat:this.internalFormat,type:this.type,colorSpace:this.colorSpace,minFilter:this.minFilter,magFilter:this.magFilter,anisotropy:this.anisotropy,flipY:this.flipY,generateMipmaps:this.generateMipmaps,premultiplyAlpha:this.premultiplyAlpha,unpackAlignment:this.unpackAlignment};return Object.keys(this.userData).length>0&&(n.userData=this.userData),t||(e.textures[this.uuid]=n),n}dispose(){this.dispatchEvent({type:"dispose"})}transformUv(e){if(this.mapping!==fu)return e;if(e.applyMatrix3(this.matrix),e.x<0||e.x>1)switch(this.wrapS){case vi:e.x=e.x-Math.floor(e.x);break;case Dn:e.x=e.x<0?0:1;break;case na:Math.abs(Math.floor(e.x)%2)===1?e.x=Math.ceil(e.x)-e.x:e.x=e.x-Math.floor(e.x);break}if(e.y<0||e.y>1)switch(this.wrapT){case vi:e.y=e.y-Math.floor(e.y);break;case Dn:e.y=e.y<0?0:1;break;case na:Math.abs(Math.floor(e.y)%2)===1?e.y=Math.ceil(e.y)-e.y:e.y=e.y-Math.floor(e.y);break}return this.flipY&&(e.y=1-e.y),e}set needsUpdate(e){e===!0&&(this.version++,this.source.needsUpdate=!0)}set needsPMREMUpdate(e){e===!0&&this.pmremVersion++}}Pt.DEFAULT_IMAGE=null;Pt.DEFAULT_MAPPING=fu;Pt.DEFAULT_ANISOTROPY=1;class mt{constructor(e=0,t=0,n=0,i=1){mt.prototype.isVector4=!0,this.x=e,this.y=t,this.z=n,this.w=i}get width(){return this.z}set width(e){this.z=e}get height(){return this.w}set height(e){this.w=e}set(e,t,n,i){return this.x=e,this.y=t,this.z=n,this.w=i,this}setScalar(e){return this.x=e,this.y=e,this.z=e,this.w=e,this}setX(e){return this.x=e,this}setY(e){return this.y=e,this}setZ(e){return this.z=e,this}setW(e){return this.w=e,this}setComponent(e,t){switch(e){case 0:this.x=t;break;case 1:this.y=t;break;case 2:this.z=t;break;case 3:this.w=t;break;default:throw new Error("index is out of range: "+e)}return this}getComponent(e){switch(e){case 0:return this.x;case 1:return this.y;case 2:return this.z;case 3:return this.w;default:throw new Error("index is out of range: "+e)}}clone(){return new this.constructor(this.x,this.y,this.z,this.w)}copy(e){return this.x=e.x,this.y=e.y,this.z=e.z,this.w=e.w!==void 0?e.w:1,this}add(e){return this.x+=e.x,this.y+=e.y,this.z+=e.z,this.w+=e.w,this}addScalar(e){return this.x+=e,this.y+=e,this.z+=e,this.w+=e,this}addVectors(e,t){return this.x=e.x+t.x,this.y=e.y+t.y,this.z=e.z+t.z,this.w=e.w+t.w,this}addScaledVector(e,t){return this.x+=e.x*t,this.y+=e.y*t,this.z+=e.z*t,this.w+=e.w*t,this}sub(e){return this.x-=e.x,this.y-=e.y,this.z-=e.z,this.w-=e.w,this}subScalar(e){return this.x-=e,this.y-=e,this.z-=e,this.w-=e,this}subVectors(e,t){return this.x=e.x-t.x,this.y=e.y-t.y,this.z=e.z-t.z,this.w=e.w-t.w,this}multiply(e){return this.x*=e.x,this.y*=e.y,this.z*=e.z,this.w*=e.w,this}multiplyScalar(e){return this.x*=e,this.y*=e,this.z*=e,this.w*=e,this}applyMatrix4(e){const t=this.x,n=this.y,i=this.z,r=this.w,a=e.elements;return this.x=a[0]*t+a[4]*n+a[8]*i+a[12]*r,this.y=a[1]*t+a[5]*n+a[9]*i+a[13]*r,this.z=a[2]*t+a[6]*n+a[10]*i+a[14]*r,this.w=a[3]*t+a[7]*n+a[11]*i+a[15]*r,this}divide(e){return this.x/=e.x,this.y/=e.y,this.z/=e.z,this.w/=e.w,this}divideScalar(e){return this.multiplyScalar(1/e)}setAxisAngleFromQuaternion(e){this.w=2*Math.acos(e.w);const t=Math.sqrt(1-e.w*e.w);return t<1e-4?(this.x=1,this.y=0,this.z=0):(this.x=e.x/t,this.y=e.y/t,this.z=e.z/t),this}setAxisAngleFromRotationMatrix(e){let t,n,i,r;const l=e.elements,c=l[0],h=l[4],u=l[8],d=l[1],f=l[5],g=l[9],x=l[2],p=l[6],m=l[10];if(Math.abs(h-d)<.01&&Math.abs(u-x)<.01&&Math.abs(g-p)<.01){if(Math.abs(h+d)<.1&&Math.abs(u+x)<.1&&Math.abs(g+p)<.1&&Math.abs(c+f+m-3)<.1)return this.set(1,0,0,0),this;t=Math.PI;const T=(c+1)/2,M=(f+1)/2,E=(m+1)/2,w=(h+d)/4,C=(u+x)/4,v=(g+p)/4;return T>M&&T>E?T<.01?(n=0,i=.707106781,r=.707106781):(n=Math.sqrt(T),i=w/n,r=C/n):M>E?M<.01?(n=.707106781,i=0,r=.707106781):(i=Math.sqrt(M),n=w/i,r=v/i):E<.01?(n=.707106781,i=.707106781,r=0):(r=Math.sqrt(E),n=C/r,i=v/r),this.set(n,i,r,t),this}let S=Math.sqrt((p-g)*(p-g)+(u-x)*(u-x)+(d-h)*(d-h));return Math.abs(S)<.001&&(S=1),this.x=(p-g)/S,this.y=(u-x)/S,this.z=(d-h)/S,this.w=Math.acos((c+f+m-1)/2),this}setFromMatrixPosition(e){const t=e.elements;return this.x=t[12],this.y=t[13],this.z=t[14],this.w=t[15],this}min(e){return this.x=Math.min(this.x,e.x),this.y=Math.min(this.y,e.y),this.z=Math.min(this.z,e.z),this.w=Math.min(this.w,e.w),this}max(e){return this.x=Math.max(this.x,e.x),this.y=Math.max(this.y,e.y),this.z=Math.max(this.z,e.z),this.w=Math.max(this.w,e.w),this}clamp(e,t){return this.x=Xe(this.x,e.x,t.x),this.y=Xe(this.y,e.y,t.y),this.z=Xe(this.z,e.z,t.z),this.w=Xe(this.w,e.w,t.w),this}clampScalar(e,t){return this.x=Xe(this.x,e,t),this.y=Xe(this.y,e,t),this.z=Xe(this.z,e,t),this.w=Xe(this.w,e,t),this}clampLength(e,t){const n=this.length();return this.divideScalar(n||1).multiplyScalar(Xe(n,e,t))}floor(){return this.x=Math.floor(this.x),this.y=Math.floor(this.y),this.z=Math.floor(this.z),this.w=Math.floor(this.w),this}ceil(){return this.x=Math.ceil(this.x),this.y=Math.ceil(this.y),this.z=Math.ceil(this.z),this.w=Math.ceil(this.w),this}round(){return this.x=Math.round(this.x),this.y=Math.round(this.y),this.z=Math.round(this.z),this.w=Math.round(this.w),this}roundToZero(){return this.x=Math.trunc(this.x),this.y=Math.trunc(this.y),this.z=Math.trunc(this.z),this.w=Math.trunc(this.w),this}negate(){return this.x=-this.x,this.y=-this.y,this.z=-this.z,this.w=-this.w,this}dot(e){return this.x*e.x+this.y*e.y+this.z*e.z+this.w*e.w}lengthSq(){return this.x*this.x+this.y*this.y+this.z*this.z+this.w*this.w}length(){return Math.sqrt(this.x*this.x+this.y*this.y+this.z*this.z+this.w*this.w)}manhattanLength(){return Math.abs(this.x)+Math.abs(this.y)+Math.abs(this.z)+Math.abs(this.w)}normalize(){return this.divideScalar(this.length()||1)}setLength(e){return this.normalize().multiplyScalar(e)}lerp(e,t){return this.x+=(e.x-this.x)*t,this.y+=(e.y-this.y)*t,this.z+=(e.z-this.z)*t,this.w+=(e.w-this.w)*t,this}lerpVectors(e,t,n){return this.x=e.x+(t.x-e.x)*n,this.y=e.y+(t.y-e.y)*n,this.z=e.z+(t.z-e.z)*n,this.w=e.w+(t.w-e.w)*n,this}equals(e){return e.x===this.x&&e.y===this.y&&e.z===this.z&&e.w===this.w}fromArray(e,t=0){return this.x=e[t],this.y=e[t+1],this.z=e[t+2],this.w=e[t+3],this}toArray(e=[],t=0){return e[t]=this.x,e[t+1]=this.y,e[t+2]=this.z,e[t+3]=this.w,e}fromBufferAttribute(e,t){return this.x=e.getX(t),this.y=e.getY(t),this.z=e.getZ(t),this.w=e.getW(t),this}random(){return this.x=Math.random(),this.y=Math.random(),this.z=Math.random(),this.w=Math.random(),this}*[Symbol.iterator](){yield this.x,yield this.y,yield this.z,yield this.w}}class Zf extends Ni{constructor(e=1,t=1,n={}){super(),n=Object.assign({generateMipmaps:!1,internalFormat:null,minFilter:Ct,depthBuffer:!0,stencilBuffer:!1,resolveDepthBuffer:!0,resolveStencilBuffer:!0,depthTexture:null,samples:0,count:1,depth:1,multiview:!1},n),this.isRenderTarget=!0,this.width=e,this.height=t,this.depth=n.depth,this.scissor=new mt(0,0,e,t),this.scissorTest=!1,this.viewport=new mt(0,0,e,t),this.textures=[];const i={width:e,height:t,depth:n.depth},r=new Pt(i),a=n.count;for(let o=0;o<a;o++)this.textures[o]=r.clone(),this.textures[o].isRenderTargetTexture=!0,this.textures[o].renderTarget=this;this._setTextureOptions(n),this.depthBuffer=n.depthBuffer,this.stencilBuffer=n.stencilBuffer,this.resolveDepthBuffer=n.resolveDepthBuffer,this.resolveStencilBuffer=n.resolveStencilBuffer,this._depthTexture=null,this.depthTexture=n.depthTexture,this.samples=n.samples,this.multiview=n.multiview}_setTextureOptions(e={}){const t={minFilter:Ct,generateMipmaps:!1,flipY:!1,internalFormat:null};e.mapping!==void 0&&(t.mapping=e.mapping),e.wrapS!==void 0&&(t.wrapS=e.wrapS),e.wrapT!==void 0&&(t.wrapT=e.wrapT),e.wrapR!==void 0&&(t.wrapR=e.wrapR),e.magFilter!==void 0&&(t.magFilter=e.magFilter),e.minFilter!==void 0&&(t.minFilter=e.minFilter),e.format!==void 0&&(t.format=e.format),e.type!==void 0&&(t.type=e.type),e.anisotropy!==void 0&&(t.anisotropy=e.anisotropy),e.colorSpace!==void 0&&(t.colorSpace=e.colorSpace),e.flipY!==void 0&&(t.flipY=e.flipY),e.generateMipmaps!==void 0&&(t.generateMipmaps=e.generateMipmaps),e.internalFormat!==void 0&&(t.internalFormat=e.internalFormat);for(let n=0;n<this.textures.length;n++)this.textures[n].setValues(t)}get texture(){return this.textures[0]}set texture(e){this.textures[0]=e}set depthTexture(e){this._depthTexture!==null&&(this._depthTexture.renderTarget=null),e!==null&&(e.renderTarget=this),this._depthTexture=e}get depthTexture(){return this._depthTexture}setSize(e,t,n=1){if(this.width!==e||this.height!==t||this.depth!==n){this.width=e,this.height=t,this.depth=n;for(let i=0,r=this.textures.length;i<r;i++)this.textures[i].image.width=e,this.textures[i].image.height=t,this.textures[i].image.depth=n,this.textures[i].isData3DTexture!==!0&&(this.textures[i].isArrayTexture=this.textures[i].image.depth>1);this.dispose()}this.viewport.set(0,0,e,t),this.scissor.set(0,0,e,t)}clone(){return new this.constructor().copy(this)}copy(e){this.width=e.width,this.height=e.height,this.depth=e.depth,this.scissor.copy(e.scissor),this.scissorTest=e.scissorTest,this.viewport.copy(e.viewport),this.textures.length=0;for(let t=0,n=e.textures.length;t<n;t++){this.textures[t]=e.textures[t].clone(),this.textures[t].isRenderTargetTexture=!0,this.textures[t].renderTarget=this;const i=Object.assign({},e.textures[t].image);this.textures[t].source=new Kl(i)}return this.depthBuffer=e.depthBuffer,this.stencilBuffer=e.stencilBuffer,this.resolveDepthBuffer=e.resolveDepthBuffer,this.resolveStencilBuffer=e.resolveStencilBuffer,e.depthTexture!==null&&(this.depthTexture=e.depthTexture.clone()),this.samples=e.samples,this}dispose(){this.dispatchEvent({type:"dispose"})}}class Jt extends Zf{constructor(e=1,t=1,n={}){super(e,t,n),this.isWebGLRenderTarget=!0}}class bu extends Pt{constructor(e=null,t=1,n=1,i=1){super(null),this.isDataArrayTexture=!0,this.image={data:e,width:t,height:n,depth:i},this.magFilter=xt,this.minFilter=xt,this.wrapR=Dn,this.generateMipmaps=!1,this.flipY=!1,this.unpackAlignment=1,this.layerUpdates=new Set}addLayerUpdate(e){this.layerUpdates.add(e)}clearLayerUpdates(){this.layerUpdates.clear()}}class Jf extends Pt{constructor(e=null,t=1,n=1,i=1){super(null),this.isData3DTexture=!0,this.image={data:e,width:t,height:n,depth:i},this.magFilter=xt,this.minFilter=xt,this.wrapR=Dn,this.generateMipmaps=!1,this.flipY=!1,this.unpackAlignment=1}}class Ve{constructor(e,t,n,i,r,a,o,l,c,h,u,d,f,g,x,p){Ve.prototype.isMatrix4=!0,this.elements=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],e!==void 0&&this.set(e,t,n,i,r,a,o,l,c,h,u,d,f,g,x,p)}set(e,t,n,i,r,a,o,l,c,h,u,d,f,g,x,p){const m=this.elements;return m[0]=e,m[4]=t,m[8]=n,m[12]=i,m[1]=r,m[5]=a,m[9]=o,m[13]=l,m[2]=c,m[6]=h,m[10]=u,m[14]=d,m[3]=f,m[7]=g,m[11]=x,m[15]=p,this}identity(){return this.set(1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1),this}clone(){return new Ve().fromArray(this.elements)}copy(e){const t=this.elements,n=e.elements;return t[0]=n[0],t[1]=n[1],t[2]=n[2],t[3]=n[3],t[4]=n[4],t[5]=n[5],t[6]=n[6],t[7]=n[7],t[8]=n[8],t[9]=n[9],t[10]=n[10],t[11]=n[11],t[12]=n[12],t[13]=n[13],t[14]=n[14],t[15]=n[15],this}copyPosition(e){const t=this.elements,n=e.elements;return t[12]=n[12],t[13]=n[13],t[14]=n[14],this}setFromMatrix3(e){const t=e.elements;return this.set(t[0],t[3],t[6],0,t[1],t[4],t[7],0,t[2],t[5],t[8],0,0,0,0,1),this}extractBasis(e,t,n){return this.determinant()===0?(e.set(1,0,0),t.set(0,1,0),n.set(0,0,1),this):(e.setFromMatrixColumn(this,0),t.setFromMatrixColumn(this,1),n.setFromMatrixColumn(this,2),this)}makeBasis(e,t,n){return this.set(e.x,t.x,n.x,0,e.y,t.y,n.y,0,e.z,t.z,n.z,0,0,0,0,1),this}extractRotation(e){if(e.determinant()===0)return this.identity();const t=this.elements,n=e.elements,i=1/Hi.setFromMatrixColumn(e,0).length(),r=1/Hi.setFromMatrixColumn(e,1).length(),a=1/Hi.setFromMatrixColumn(e,2).length();return t[0]=n[0]*i,t[1]=n[1]*i,t[2]=n[2]*i,t[3]=0,t[4]=n[4]*r,t[5]=n[5]*r,t[6]=n[6]*r,t[7]=0,t[8]=n[8]*a,t[9]=n[9]*a,t[10]=n[10]*a,t[11]=0,t[12]=0,t[13]=0,t[14]=0,t[15]=1,this}makeRotationFromEuler(e){const t=this.elements,n=e.x,i=e.y,r=e.z,a=Math.cos(n),o=Math.sin(n),l=Math.cos(i),c=Math.sin(i),h=Math.cos(r),u=Math.sin(r);if(e.order==="XYZ"){const d=a*h,f=a*u,g=o*h,x=o*u;t[0]=l*h,t[4]=-l*u,t[8]=c,t[1]=f+g*c,t[5]=d-x*c,t[9]=-o*l,t[2]=x-d*c,t[6]=g+f*c,t[10]=a*l}else if(e.order==="YXZ"){const d=l*h,f=l*u,g=c*h,x=c*u;t[0]=d+x*o,t[4]=g*o-f,t[8]=a*c,t[1]=a*u,t[5]=a*h,t[9]=-o,t[2]=f*o-g,t[6]=x+d*o,t[10]=a*l}else if(e.order==="ZXY"){const d=l*h,f=l*u,g=c*h,x=c*u;t[0]=d-x*o,t[4]=-a*u,t[8]=g+f*o,t[1]=f+g*o,t[5]=a*h,t[9]=x-d*o,t[2]=-a*c,t[6]=o,t[10]=a*l}else if(e.order==="ZYX"){const d=a*h,f=a*u,g=o*h,x=o*u;t[0]=l*h,t[4]=g*c-f,t[8]=d*c+x,t[1]=l*u,t[5]=x*c+d,t[9]=f*c-g,t[2]=-c,t[6]=o*l,t[10]=a*l}else if(e.order==="YZX"){const d=a*l,f=a*c,g=o*l,x=o*c;t[0]=l*h,t[4]=x-d*u,t[8]=g*u+f,t[1]=u,t[5]=a*h,t[9]=-o*h,t[2]=-c*h,t[6]=f*u+g,t[10]=d-x*u}else if(e.order==="XZY"){const d=a*l,f=a*c,g=o*l,x=o*c;t[0]=l*h,t[4]=-u,t[8]=c*h,t[1]=d*u+x,t[5]=a*h,t[9]=f*u-g,t[2]=g*u-f,t[6]=o*h,t[10]=x*u+d}return t[3]=0,t[7]=0,t[11]=0,t[12]=0,t[13]=0,t[14]=0,t[15]=1,this}makeRotationFromQuaternion(e){return this.compose(Qf,e,ep)}lookAt(e,t,n){const i=this.elements;return en.subVectors(e,t),en.lengthSq()===0&&(en.z=1),en.normalize(),ii.crossVectors(n,en),ii.lengthSq()===0&&(Math.abs(n.z)===1?en.x+=1e-4:en.z+=1e-4,en.normalize(),ii.crossVectors(n,en)),ii.normalize(),ur.crossVectors(en,ii),i[0]=ii.x,i[4]=ur.x,i[8]=en.x,i[1]=ii.y,i[5]=ur.y,i[9]=en.y,i[2]=ii.z,i[6]=ur.z,i[10]=en.z,this}multiply(e){return this.multiplyMatrices(this,e)}premultiply(e){return this.multiplyMatrices(e,this)}multiplyMatrices(e,t){const n=e.elements,i=t.elements,r=this.elements,a=n[0],o=n[4],l=n[8],c=n[12],h=n[1],u=n[5],d=n[9],f=n[13],g=n[2],x=n[6],p=n[10],m=n[14],S=n[3],T=n[7],M=n[11],E=n[15],w=i[0],C=i[4],v=i[8],b=i[12],D=i[1],R=i[5],F=i[9],O=i[13],X=i[2],V=i[6],k=i[10],U=i[14],Q=i[3],K=i[7],se=i[11],he=i[15];return r[0]=a*w+o*D+l*X+c*Q,r[4]=a*C+o*R+l*V+c*K,r[8]=a*v+o*F+l*k+c*se,r[12]=a*b+o*O+l*U+c*he,r[1]=h*w+u*D+d*X+f*Q,r[5]=h*C+u*R+d*V+f*K,r[9]=h*v+u*F+d*k+f*se,r[13]=h*b+u*O+d*U+f*he,r[2]=g*w+x*D+p*X+m*Q,r[6]=g*C+x*R+p*V+m*K,r[10]=g*v+x*F+p*k+m*se,r[14]=g*b+x*O+p*U+m*he,r[3]=S*w+T*D+M*X+E*Q,r[7]=S*C+T*R+M*V+E*K,r[11]=S*v+T*F+M*k+E*se,r[15]=S*b+T*O+M*U+E*he,this}multiplyScalar(e){const t=this.elements;return t[0]*=e,t[4]*=e,t[8]*=e,t[12]*=e,t[1]*=e,t[5]*=e,t[9]*=e,t[13]*=e,t[2]*=e,t[6]*=e,t[10]*=e,t[14]*=e,t[3]*=e,t[7]*=e,t[11]*=e,t[15]*=e,this}determinant(){const e=this.elements,t=e[0],n=e[4],i=e[8],r=e[12],a=e[1],o=e[5],l=e[9],c=e[13],h=e[2],u=e[6],d=e[10],f=e[14],g=e[3],x=e[7],p=e[11],m=e[15],S=l*f-c*d,T=o*f-c*u,M=o*d-l*u,E=a*f-c*h,w=a*d-l*h,C=a*u-o*h;return t*(x*S-p*T+m*M)-n*(g*S-p*E+m*w)+i*(g*T-x*E+m*C)-r*(g*M-x*w+p*C)}transpose(){const e=this.elements;let t;return t=e[1],e[1]=e[4],e[4]=t,t=e[2],e[2]=e[8],e[8]=t,t=e[6],e[6]=e[9],e[9]=t,t=e[3],e[3]=e[12],e[12]=t,t=e[7],e[7]=e[13],e[13]=t,t=e[11],e[11]=e[14],e[14]=t,this}setPosition(e,t,n){const i=this.elements;return e.isVector3?(i[12]=e.x,i[13]=e.y,i[14]=e.z):(i[12]=e,i[13]=t,i[14]=n),this}invert(){const e=this.elements,t=e[0],n=e[1],i=e[2],r=e[3],a=e[4],o=e[5],l=e[6],c=e[7],h=e[8],u=e[9],d=e[10],f=e[11],g=e[12],x=e[13],p=e[14],m=e[15],S=t*o-n*a,T=t*l-i*a,M=t*c-r*a,E=n*l-i*o,w=n*c-r*o,C=i*c-r*l,v=h*x-u*g,b=h*p-d*g,D=h*m-f*g,R=u*p-d*x,F=u*m-f*x,O=d*m-f*p,X=S*O-T*F+M*R+E*D-w*b+C*v;if(X===0)return this.set(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0);const V=1/X;return e[0]=(o*O-l*F+c*R)*V,e[1]=(i*F-n*O-r*R)*V,e[2]=(x*C-p*w+m*E)*V,e[3]=(d*w-u*C-f*E)*V,e[4]=(l*D-a*O-c*b)*V,e[5]=(t*O-i*D+r*b)*V,e[6]=(p*M-g*C-m*T)*V,e[7]=(h*C-d*M+f*T)*V,e[8]=(a*F-o*D+c*v)*V,e[9]=(n*D-t*F-r*v)*V,e[10]=(g*w-x*M+m*S)*V,e[11]=(u*M-h*w-f*S)*V,e[12]=(o*b-a*R-l*v)*V,e[13]=(t*R-n*b+i*v)*V,e[14]=(x*T-g*E-p*S)*V,e[15]=(h*E-u*T+d*S)*V,this}scale(e){const t=this.elements,n=e.x,i=e.y,r=e.z;return t[0]*=n,t[4]*=i,t[8]*=r,t[1]*=n,t[5]*=i,t[9]*=r,t[2]*=n,t[6]*=i,t[10]*=r,t[3]*=n,t[7]*=i,t[11]*=r,this}getMaxScaleOnAxis(){const e=this.elements,t=e[0]*e[0]+e[1]*e[1]+e[2]*e[2],n=e[4]*e[4]+e[5]*e[5]+e[6]*e[6],i=e[8]*e[8]+e[9]*e[9]+e[10]*e[10];return Math.sqrt(Math.max(t,n,i))}makeTranslation(e,t,n){return e.isVector3?this.set(1,0,0,e.x,0,1,0,e.y,0,0,1,e.z,0,0,0,1):this.set(1,0,0,e,0,1,0,t,0,0,1,n,0,0,0,1),this}makeRotationX(e){const t=Math.cos(e),n=Math.sin(e);return this.set(1,0,0,0,0,t,-n,0,0,n,t,0,0,0,0,1),this}makeRotationY(e){const t=Math.cos(e),n=Math.sin(e);return this.set(t,0,n,0,0,1,0,0,-n,0,t,0,0,0,0,1),this}makeRotationZ(e){const t=Math.cos(e),n=Math.sin(e);return this.set(t,-n,0,0,n,t,0,0,0,0,1,0,0,0,0,1),this}makeRotationAxis(e,t){const n=Math.cos(t),i=Math.sin(t),r=1-n,a=e.x,o=e.y,l=e.z,c=r*a,h=r*o;return this.set(c*a+n,c*o-i*l,c*l+i*o,0,c*o+i*l,h*o+n,h*l-i*a,0,c*l-i*o,h*l+i*a,r*l*l+n,0,0,0,0,1),this}makeScale(e,t,n){return this.set(e,0,0,0,0,t,0,0,0,0,n,0,0,0,0,1),this}makeShear(e,t,n,i,r,a){return this.set(1,n,r,0,e,1,a,0,t,i,1,0,0,0,0,1),this}compose(e,t,n){const i=this.elements,r=t._x,a=t._y,o=t._z,l=t._w,c=r+r,h=a+a,u=o+o,d=r*c,f=r*h,g=r*u,x=a*h,p=a*u,m=o*u,S=l*c,T=l*h,M=l*u,E=n.x,w=n.y,C=n.z;return i[0]=(1-(x+m))*E,i[1]=(f+M)*E,i[2]=(g-T)*E,i[3]=0,i[4]=(f-M)*w,i[5]=(1-(d+m))*w,i[6]=(p+S)*w,i[7]=0,i[8]=(g+T)*C,i[9]=(p-S)*C,i[10]=(1-(d+x))*C,i[11]=0,i[12]=e.x,i[13]=e.y,i[14]=e.z,i[15]=1,this}decompose(e,t,n){const i=this.elements;e.x=i[12],e.y=i[13],e.z=i[14];const r=this.determinant();if(r===0)return n.set(1,1,1),t.identity(),this;let a=Hi.set(i[0],i[1],i[2]).length();const o=Hi.set(i[4],i[5],i[6]).length(),l=Hi.set(i[8],i[9],i[10]).length();r<0&&(a=-a),pn.copy(this);const c=1/a,h=1/o,u=1/l;return pn.elements[0]*=c,pn.elements[1]*=c,pn.elements[2]*=c,pn.elements[4]*=h,pn.elements[5]*=h,pn.elements[6]*=h,pn.elements[8]*=u,pn.elements[9]*=u,pn.elements[10]*=u,t.setFromRotationMatrix(pn),n.x=a,n.y=o,n.z=l,this}makePerspective(e,t,n,i,r,a,o=Ln,l=!1){const c=this.elements,h=2*r/(t-e),u=2*r/(n-i),d=(t+e)/(t-e),f=(n+i)/(n-i);let g,x;if(l)g=r/(a-r),x=a*r/(a-r);else if(o===Ln)g=-(a+r)/(a-r),x=-2*a*r/(a-r);else if(o===nr)g=-a/(a-r),x=-a*r/(a-r);else throw new Error("THREE.Matrix4.makePerspective(): Invalid coordinate system: "+o);return c[0]=h,c[4]=0,c[8]=d,c[12]=0,c[1]=0,c[5]=u,c[9]=f,c[13]=0,c[2]=0,c[6]=0,c[10]=g,c[14]=x,c[3]=0,c[7]=0,c[11]=-1,c[15]=0,this}makeOrthographic(e,t,n,i,r,a,o=Ln,l=!1){const c=this.elements,h=2/(t-e),u=2/(n-i),d=-(t+e)/(t-e),f=-(n+i)/(n-i);let g,x;if(l)g=1/(a-r),x=a/(a-r);else if(o===Ln)g=-2/(a-r),x=-(a+r)/(a-r);else if(o===nr)g=-1/(a-r),x=-r/(a-r);else throw new Error("THREE.Matrix4.makeOrthographic(): Invalid coordinate system: "+o);return c[0]=h,c[4]=0,c[8]=0,c[12]=d,c[1]=0,c[5]=u,c[9]=0,c[13]=f,c[2]=0,c[6]=0,c[10]=g,c[14]=x,c[3]=0,c[7]=0,c[11]=0,c[15]=1,this}equals(e){const t=this.elements,n=e.elements;for(let i=0;i<16;i++)if(t[i]!==n[i])return!1;return!0}fromArray(e,t=0){for(let n=0;n<16;n++)this.elements[n]=e[n+t];return this}toArray(e=[],t=0){const n=this.elements;return e[t]=n[0],e[t+1]=n[1],e[t+2]=n[2],e[t+3]=n[3],e[t+4]=n[4],e[t+5]=n[5],e[t+6]=n[6],e[t+7]=n[7],e[t+8]=n[8],e[t+9]=n[9],e[t+10]=n[10],e[t+11]=n[11],e[t+12]=n[12],e[t+13]=n[13],e[t+14]=n[14],e[t+15]=n[15],e}}const Hi=new L,pn=new Ve,Qf=new L(0,0,0),ep=new L(1,1,1),ii=new L,ur=new L,en=new L,zc=new Ve,Hc=new yn;class Sn{constructor(e=0,t=0,n=0,i=Sn.DEFAULT_ORDER){this.isEuler=!0,this._x=e,this._y=t,this._z=n,this._order=i}get x(){return this._x}set x(e){this._x=e,this._onChangeCallback()}get y(){return this._y}set y(e){this._y=e,this._onChangeCallback()}get z(){return this._z}set z(e){this._z=e,this._onChangeCallback()}get order(){return this._order}set order(e){this._order=e,this._onChangeCallback()}set(e,t,n,i=this._order){return this._x=e,this._y=t,this._z=n,this._order=i,this._onChangeCallback(),this}clone(){return new this.constructor(this._x,this._y,this._z,this._order)}copy(e){return this._x=e._x,this._y=e._y,this._z=e._z,this._order=e._order,this._onChangeCallback(),this}setFromRotationMatrix(e,t=this._order,n=!0){const i=e.elements,r=i[0],a=i[4],o=i[8],l=i[1],c=i[5],h=i[9],u=i[2],d=i[6],f=i[10];switch(t){case"XYZ":this._y=Math.asin(Xe(o,-1,1)),Math.abs(o)<.9999999?(this._x=Math.atan2(-h,f),this._z=Math.atan2(-a,r)):(this._x=Math.atan2(d,c),this._z=0);break;case"YXZ":this._x=Math.asin(-Xe(h,-1,1)),Math.abs(h)<.9999999?(this._y=Math.atan2(o,f),this._z=Math.atan2(l,c)):(this._y=Math.atan2(-u,r),this._z=0);break;case"ZXY":this._x=Math.asin(Xe(d,-1,1)),Math.abs(d)<.9999999?(this._y=Math.atan2(-u,f),this._z=Math.atan2(-a,c)):(this._y=0,this._z=Math.atan2(l,r));break;case"ZYX":this._y=Math.asin(-Xe(u,-1,1)),Math.abs(u)<.9999999?(this._x=Math.atan2(d,f),this._z=Math.atan2(l,r)):(this._x=0,this._z=Math.atan2(-a,c));break;case"YZX":this._z=Math.asin(Xe(l,-1,1)),Math.abs(l)<.9999999?(this._x=Math.atan2(-h,c),this._y=Math.atan2(-u,r)):(this._x=0,this._y=Math.atan2(o,f));break;case"XZY":this._z=Math.asin(-Xe(a,-1,1)),Math.abs(a)<.9999999?(this._x=Math.atan2(d,c),this._y=Math.atan2(o,r)):(this._x=Math.atan2(-h,f),this._y=0);break;default:Pe("Euler: .setFromRotationMatrix() encountered an unknown order: "+t)}return this._order=t,n===!0&&this._onChangeCallback(),this}setFromQuaternion(e,t,n){return zc.makeRotationFromQuaternion(e),this.setFromRotationMatrix(zc,t,n)}setFromVector3(e,t=this._order){return this.set(e.x,e.y,e.z,t)}reorder(e){return Hc.setFromEuler(this),this.setFromQuaternion(Hc,e)}equals(e){return e._x===this._x&&e._y===this._y&&e._z===this._z&&e._order===this._order}fromArray(e){return this._x=e[0],this._y=e[1],this._z=e[2],e[3]!==void 0&&(this._order=e[3]),this._onChangeCallback(),this}toArray(e=[],t=0){return e[t]=this._x,e[t+1]=this._y,e[t+2]=this._z,e[t+3]=this._order,e}_onChange(e){return this._onChangeCallback=e,this}_onChangeCallback(){}*[Symbol.iterator](){yield this._x,yield this._y,yield this._z,yield this._order}}Sn.DEFAULT_ORDER="XYZ";class $l{constructor(){this.mask=1}set(e){this.mask=(1<<e|0)>>>0}enable(e){this.mask|=1<<e|0}enableAll(){this.mask=-1}toggle(e){this.mask^=1<<e|0}disable(e){this.mask&=~(1<<e|0)}disableAll(){this.mask=0}test(e){return(this.mask&e.mask)!==0}isEnabled(e){return(this.mask&(1<<e|0))!==0}}let tp=0;const Gc=new L,Gi=new yn,zn=new Ve,dr=new L,Fs=new L,np=new L,ip=new yn,Wc=new L(1,0,0),Xc=new L(0,1,0),Yc=new L(0,0,1),qc={type:"added"},sp={type:"removed"},Wi={type:"childadded",child:null},Va={type:"childremoved",child:null};class ft extends Ni{constructor(){super(),this.isObject3D=!0,Object.defineProperty(this,"id",{value:tp++}),this.uuid=Mn(),this.name="",this.type="Object3D",this.parent=null,this.children=[],this.up=ft.DEFAULT_UP.clone();const e=new L,t=new Sn,n=new yn,i=new L(1,1,1);function r(){n.setFromEuler(t,!1)}function a(){t.setFromQuaternion(n,void 0,!1)}t._onChange(r),n._onChange(a),Object.defineProperties(this,{position:{configurable:!0,enumerable:!0,value:e},rotation:{configurable:!0,enumerable:!0,value:t},quaternion:{configurable:!0,enumerable:!0,value:n},scale:{configurable:!0,enumerable:!0,value:i},modelViewMatrix:{value:new Ve},normalMatrix:{value:new He}}),this.matrix=new Ve,this.matrixWorld=new Ve,this.matrixAutoUpdate=ft.DEFAULT_MATRIX_AUTO_UPDATE,this.matrixWorldAutoUpdate=ft.DEFAULT_MATRIX_WORLD_AUTO_UPDATE,this.matrixWorldNeedsUpdate=!1,this.layers=new $l,this.visible=!0,this.castShadow=!1,this.receiveShadow=!1,this.frustumCulled=!0,this.renderOrder=0,this.animations=[],this.customDepthMaterial=void 0,this.customDistanceMaterial=void 0,this.static=!1,this.userData={},this.pivot=null}onBeforeShadow(){}onAfterShadow(){}onBeforeRender(){}onAfterRender(){}applyMatrix4(e){this.matrixAutoUpdate&&this.updateMatrix(),this.matrix.premultiply(e),this.matrix.decompose(this.position,this.quaternion,this.scale)}applyQuaternion(e){return this.quaternion.premultiply(e),this}setRotationFromAxisAngle(e,t){this.quaternion.setFromAxisAngle(e,t)}setRotationFromEuler(e){this.quaternion.setFromEuler(e,!0)}setRotationFromMatrix(e){this.quaternion.setFromRotationMatrix(e)}setRotationFromQuaternion(e){this.quaternion.copy(e)}rotateOnAxis(e,t){return Gi.setFromAxisAngle(e,t),this.quaternion.multiply(Gi),this}rotateOnWorldAxis(e,t){return Gi.setFromAxisAngle(e,t),this.quaternion.premultiply(Gi),this}rotateX(e){return this.rotateOnAxis(Wc,e)}rotateY(e){return this.rotateOnAxis(Xc,e)}rotateZ(e){return this.rotateOnAxis(Yc,e)}translateOnAxis(e,t){return Gc.copy(e).applyQuaternion(this.quaternion),this.position.add(Gc.multiplyScalar(t)),this}translateX(e){return this.translateOnAxis(Wc,e)}translateY(e){return this.translateOnAxis(Xc,e)}translateZ(e){return this.translateOnAxis(Yc,e)}localToWorld(e){return this.updateWorldMatrix(!0,!1),e.applyMatrix4(this.matrixWorld)}worldToLocal(e){return this.updateWorldMatrix(!0,!1),e.applyMatrix4(zn.copy(this.matrixWorld).invert())}lookAt(e,t,n){e.isVector3?dr.copy(e):dr.set(e,t,n);const i=this.parent;this.updateWorldMatrix(!0,!1),Fs.setFromMatrixPosition(this.matrixWorld),this.isCamera||this.isLight?zn.lookAt(Fs,dr,this.up):zn.lookAt(dr,Fs,this.up),this.quaternion.setFromRotationMatrix(zn),i&&(zn.extractRotation(i.matrixWorld),Gi.setFromRotationMatrix(zn),this.quaternion.premultiply(Gi.invert()))}add(e){if(arguments.length>1){for(let t=0;t<arguments.length;t++)this.add(arguments[t]);return this}return e===this?(Ue("Object3D.add: object can't be added as a child of itself.",e),this):(e&&e.isObject3D?(e.removeFromParent(),e.parent=this,this.children.push(e),e.dispatchEvent(qc),Wi.child=e,this.dispatchEvent(Wi),Wi.child=null):Ue("Object3D.add: object not an instance of THREE.Object3D.",e),this)}remove(e){if(arguments.length>1){for(let n=0;n<arguments.length;n++)this.remove(arguments[n]);return this}const t=this.children.indexOf(e);return t!==-1&&(e.parent=null,this.children.splice(t,1),e.dispatchEvent(sp),Va.child=e,this.dispatchEvent(Va),Va.child=null),this}removeFromParent(){const e=this.parent;return e!==null&&e.remove(this),this}clear(){return this.remove(...this.children)}attach(e){return this.updateWorldMatrix(!0,!1),zn.copy(this.matrixWorld).invert(),e.parent!==null&&(e.parent.updateWorldMatrix(!0,!1),zn.multiply(e.parent.matrixWorld)),e.applyMatrix4(zn),e.removeFromParent(),e.parent=this,this.children.push(e),e.updateWorldMatrix(!1,!0),e.dispatchEvent(qc),Wi.child=e,this.dispatchEvent(Wi),Wi.child=null,this}getObjectById(e){return this.getObjectByProperty("id",e)}getObjectByName(e){return this.getObjectByProperty("name",e)}getObjectByProperty(e,t){if(this[e]===t)return this;for(let n=0,i=this.children.length;n<i;n++){const a=this.children[n].getObjectByProperty(e,t);if(a!==void 0)return a}}getObjectsByProperty(e,t,n=[]){this[e]===t&&n.push(this);const i=this.children;for(let r=0,a=i.length;r<a;r++)i[r].getObjectsByProperty(e,t,n);return n}getWorldPosition(e){return this.updateWorldMatrix(!0,!1),e.setFromMatrixPosition(this.matrixWorld)}getWorldQuaternion(e){return this.updateWorldMatrix(!0,!1),this.matrixWorld.decompose(Fs,e,np),e}getWorldScale(e){return this.updateWorldMatrix(!0,!1),this.matrixWorld.decompose(Fs,ip,e),e}getWorldDirection(e){this.updateWorldMatrix(!0,!1);const t=this.matrixWorld.elements;return e.set(t[8],t[9],t[10]).normalize()}raycast(){}traverse(e){e(this);const t=this.children;for(let n=0,i=t.length;n<i;n++)t[n].traverse(e)}traverseVisible(e){if(this.visible===!1)return;e(this);const t=this.children;for(let n=0,i=t.length;n<i;n++)t[n].traverseVisible(e)}traverseAncestors(e){const t=this.parent;t!==null&&(e(t),t.traverseAncestors(e))}updateMatrix(){this.matrix.compose(this.position,this.quaternion,this.scale);const e=this.pivot;if(e!==null){const t=e.x,n=e.y,i=e.z,r=this.matrix.elements;r[12]+=t-r[0]*t-r[4]*n-r[8]*i,r[13]+=n-r[1]*t-r[5]*n-r[9]*i,r[14]+=i-r[2]*t-r[6]*n-r[10]*i}this.matrixWorldNeedsUpdate=!0}updateMatrixWorld(e){this.matrixAutoUpdate&&this.updateMatrix(),(this.matrixWorldNeedsUpdate||e)&&(this.matrixWorldAutoUpdate===!0&&(this.parent===null?this.matrixWorld.copy(this.matrix):this.matrixWorld.multiplyMatrices(this.parent.matrixWorld,this.matrix)),this.matrixWorldNeedsUpdate=!1,e=!0);const t=this.children;for(let n=0,i=t.length;n<i;n++)t[n].updateMatrixWorld(e)}updateWorldMatrix(e,t){const n=this.parent;if(e===!0&&n!==null&&n.updateWorldMatrix(!0,!1),this.matrixAutoUpdate&&this.updateMatrix(),this.matrixWorldAutoUpdate===!0&&(this.parent===null?this.matrixWorld.copy(this.matrix):this.matrixWorld.multiplyMatrices(this.parent.matrixWorld,this.matrix)),t===!0){const i=this.children;for(let r=0,a=i.length;r<a;r++)i[r].updateWorldMatrix(!1,!0)}}toJSON(e){const t=e===void 0||typeof e=="string",n={};t&&(e={geometries:{},materials:{},textures:{},images:{},shapes:{},skeletons:{},animations:{},nodes:{}},n.metadata={version:4.7,type:"Object",generator:"Object3D.toJSON"});const i={};i.uuid=this.uuid,i.type=this.type,this.name!==""&&(i.name=this.name),this.castShadow===!0&&(i.castShadow=!0),this.receiveShadow===!0&&(i.receiveShadow=!0),this.visible===!1&&(i.visible=!1),this.frustumCulled===!1&&(i.frustumCulled=!1),this.renderOrder!==0&&(i.renderOrder=this.renderOrder),this.static!==!1&&(i.static=this.static),Object.keys(this.userData).length>0&&(i.userData=this.userData),i.layers=this.layers.mask,i.matrix=this.matrix.toArray(),i.up=this.up.toArray(),this.pivot!==null&&(i.pivot=this.pivot.toArray()),this.matrixAutoUpdate===!1&&(i.matrixAutoUpdate=!1),this.morphTargetDictionary!==void 0&&(i.morphTargetDictionary=Object.assign({},this.morphTargetDictionary)),this.morphTargetInfluences!==void 0&&(i.morphTargetInfluences=this.morphTargetInfluences.slice()),this.isInstancedMesh&&(i.type="InstancedMesh",i.count=this.count,i.instanceMatrix=this.instanceMatrix.toJSON(),this.instanceColor!==null&&(i.instanceColor=this.instanceColor.toJSON())),this.isBatchedMesh&&(i.type="BatchedMesh",i.perObjectFrustumCulled=this.perObjectFrustumCulled,i.sortObjects=this.sortObjects,i.drawRanges=this._drawRanges,i.reservedRanges=this._reservedRanges,i.geometryInfo=this._geometryInfo.map(o=>({...o,boundingBox:o.boundingBox?o.boundingBox.toJSON():void 0,boundingSphere:o.boundingSphere?o.boundingSphere.toJSON():void 0})),i.instanceInfo=this._instanceInfo.map(o=>({...o})),i.availableInstanceIds=this._availableInstanceIds.slice(),i.availableGeometryIds=this._availableGeometryIds.slice(),i.nextIndexStart=this._nextIndexStart,i.nextVertexStart=this._nextVertexStart,i.geometryCount=this._geometryCount,i.maxInstanceCount=this._maxInstanceCount,i.maxVertexCount=this._maxVertexCount,i.maxIndexCount=this._maxIndexCount,i.geometryInitialized=this._geometryInitialized,i.matricesTexture=this._matricesTexture.toJSON(e),i.indirectTexture=this._indirectTexture.toJSON(e),this._colorsTexture!==null&&(i.colorsTexture=this._colorsTexture.toJSON(e)),this.boundingSphere!==null&&(i.boundingSphere=this.boundingSphere.toJSON()),this.boundingBox!==null&&(i.boundingBox=this.boundingBox.toJSON()));function r(o,l){return o[l.uuid]===void 0&&(o[l.uuid]=l.toJSON(e)),l.uuid}if(this.isScene)this.background&&(this.background.isColor?i.background=this.background.toJSON():this.background.isTexture&&(i.background=this.background.toJSON(e).uuid)),this.environment&&this.environment.isTexture&&this.environment.isRenderTargetTexture!==!0&&(i.environment=this.environment.toJSON(e).uuid);else if(this.isMesh||this.isLine||this.isPoints){i.geometry=r(e.geometries,this.geometry);const o=this.geometry.parameters;if(o!==void 0&&o.shapes!==void 0){const l=o.shapes;if(Array.isArray(l))for(let c=0,h=l.length;c<h;c++){const u=l[c];r(e.shapes,u)}else r(e.shapes,l)}}if(this.isSkinnedMesh&&(i.bindMode=this.bindMode,i.bindMatrix=this.bindMatrix.toArray(),this.skeleton!==void 0&&(r(e.skeletons,this.skeleton),i.skeleton=this.skeleton.uuid)),this.material!==void 0)if(Array.isArray(this.material)){const o=[];for(let l=0,c=this.material.length;l<c;l++)o.push(r(e.materials,this.material[l]));i.material=o}else i.material=r(e.materials,this.material);if(this.children.length>0){i.children=[];for(let o=0;o<this.children.length;o++)i.children.push(this.children[o].toJSON(e).object)}if(this.animations.length>0){i.animations=[];for(let o=0;o<this.animations.length;o++){const l=this.animations[o];i.animations.push(r(e.animations,l))}}if(t){const o=a(e.geometries),l=a(e.materials),c=a(e.textures),h=a(e.images),u=a(e.shapes),d=a(e.skeletons),f=a(e.animations),g=a(e.nodes);o.length>0&&(n.geometries=o),l.length>0&&(n.materials=l),c.length>0&&(n.textures=c),h.length>0&&(n.images=h),u.length>0&&(n.shapes=u),d.length>0&&(n.skeletons=d),f.length>0&&(n.animations=f),g.length>0&&(n.nodes=g)}return n.object=i,n;function a(o){const l=[];for(const c in o){const h=o[c];delete h.metadata,l.push(h)}return l}}clone(e){return new this.constructor().copy(this,e)}copy(e,t=!0){if(this.name=e.name,this.up.copy(e.up),this.position.copy(e.position),this.rotation.order=e.rotation.order,this.quaternion.copy(e.quaternion),this.scale.copy(e.scale),e.pivot!==null&&(this.pivot=e.pivot.clone()),this.matrix.copy(e.matrix),this.matrixWorld.copy(e.matrixWorld),this.matrixAutoUpdate=e.matrixAutoUpdate,this.matrixWorldAutoUpdate=e.matrixWorldAutoUpdate,this.matrixWorldNeedsUpdate=e.matrixWorldNeedsUpdate,this.layers.mask=e.layers.mask,this.visible=e.visible,this.castShadow=e.castShadow,this.receiveShadow=e.receiveShadow,this.frustumCulled=e.frustumCulled,this.renderOrder=e.renderOrder,this.static=e.static,this.animations=e.animations.slice(),this.userData=JSON.parse(JSON.stringify(e.userData)),t===!0)for(let n=0;n<e.children.length;n++){const i=e.children[n];this.add(i.clone())}return this}}ft.DEFAULT_UP=new L(0,1,0);ft.DEFAULT_MATRIX_AUTO_UPDATE=!0;ft.DEFAULT_MATRIX_WORLD_AUTO_UPDATE=!0;class In extends ft{constructor(){super(),this.isGroup=!0,this.type="Group"}}const rp={type:"move"};class za{constructor(){this._targetRay=null,this._grip=null,this._hand=null}getHandSpace(){return this._hand===null&&(this._hand=new In,this._hand.matrixAutoUpdate=!1,this._hand.visible=!1,this._hand.joints={},this._hand.inputState={pinching:!1}),this._hand}getTargetRaySpace(){return this._targetRay===null&&(this._targetRay=new In,this._targetRay.matrixAutoUpdate=!1,this._targetRay.visible=!1,this._targetRay.hasLinearVelocity=!1,this._targetRay.linearVelocity=new L,this._targetRay.hasAngularVelocity=!1,this._targetRay.angularVelocity=new L),this._targetRay}getGripSpace(){return this._grip===null&&(this._grip=new In,this._grip.matrixAutoUpdate=!1,this._grip.visible=!1,this._grip.hasLinearVelocity=!1,this._grip.linearVelocity=new L,this._grip.hasAngularVelocity=!1,this._grip.angularVelocity=new L),this._grip}dispatchEvent(e){return this._targetRay!==null&&this._targetRay.dispatchEvent(e),this._grip!==null&&this._grip.dispatchEvent(e),this._hand!==null&&this._hand.dispatchEvent(e),this}connect(e){if(e&&e.hand){const t=this._hand;if(t)for(const n of e.hand.values())this._getHandJoint(t,n)}return this.dispatchEvent({type:"connected",data:e}),this}disconnect(e){return this.dispatchEvent({type:"disconnected",data:e}),this._targetRay!==null&&(this._targetRay.visible=!1),this._grip!==null&&(this._grip.visible=!1),this._hand!==null&&(this._hand.visible=!1),this}update(e,t,n){let i=null,r=null,a=null;const o=this._targetRay,l=this._grip,c=this._hand;if(e&&t.session.visibilityState!=="visible-blurred"){if(c&&e.hand){a=!0;for(const x of e.hand.values()){const p=t.getJointPose(x,n),m=this._getHandJoint(c,x);p!==null&&(m.matrix.fromArray(p.transform.matrix),m.matrix.decompose(m.position,m.rotation,m.scale),m.matrixWorldNeedsUpdate=!0,m.jointRadius=p.radius),m.visible=p!==null}const h=c.joints["index-finger-tip"],u=c.joints["thumb-tip"],d=h.position.distanceTo(u.position),f=.02,g=.005;c.inputState.pinching&&d>f+g?(c.inputState.pinching=!1,this.dispatchEvent({type:"pinchend",handedness:e.handedness,target:this})):!c.inputState.pinching&&d<=f-g&&(c.inputState.pinching=!0,this.dispatchEvent({type:"pinchstart",handedness:e.handedness,target:this}))}else l!==null&&e.gripSpace&&(r=t.getPose(e.gripSpace,n),r!==null&&(l.matrix.fromArray(r.transform.matrix),l.matrix.decompose(l.position,l.rotation,l.scale),l.matrixWorldNeedsUpdate=!0,r.linearVelocity?(l.hasLinearVelocity=!0,l.linearVelocity.copy(r.linearVelocity)):l.hasLinearVelocity=!1,r.angularVelocity?(l.hasAngularVelocity=!0,l.angularVelocity.copy(r.angularVelocity)):l.hasAngularVelocity=!1));o!==null&&(i=t.getPose(e.targetRaySpace,n),i===null&&r!==null&&(i=r),i!==null&&(o.matrix.fromArray(i.transform.matrix),o.matrix.decompose(o.position,o.rotation,o.scale),o.matrixWorldNeedsUpdate=!0,i.linearVelocity?(o.hasLinearVelocity=!0,o.linearVelocity.copy(i.linearVelocity)):o.hasLinearVelocity=!1,i.angularVelocity?(o.hasAngularVelocity=!0,o.angularVelocity.copy(i.angularVelocity)):o.hasAngularVelocity=!1,this.dispatchEvent(rp)))}return o!==null&&(o.visible=i!==null),l!==null&&(l.visible=r!==null),c!==null&&(c.visible=a!==null),this}_getHandJoint(e,t){if(e.joints[t.jointName]===void 0){const n=new In;n.matrixAutoUpdate=!1,n.visible=!1,e.joints[t.jointName]=n,e.add(n)}return e.joints[t.jointName]}}const Eu={aliceblue:15792383,antiquewhite:16444375,aqua:65535,aquamarine:8388564,azure:15794175,beige:16119260,bisque:16770244,black:0,blanchedalmond:16772045,blue:255,blueviolet:9055202,brown:10824234,burlywood:14596231,cadetblue:6266528,chartreuse:8388352,chocolate:13789470,coral:16744272,cornflowerblue:6591981,cornsilk:16775388,crimson:14423100,cyan:65535,darkblue:139,darkcyan:35723,darkgoldenrod:12092939,darkgray:11119017,darkgreen:25600,darkgrey:11119017,darkkhaki:12433259,darkmagenta:9109643,darkolivegreen:5597999,darkorange:16747520,darkorchid:10040012,darkred:9109504,darksalmon:15308410,darkseagreen:9419919,darkslateblue:4734347,darkslategray:3100495,darkslategrey:3100495,darkturquoise:52945,darkviolet:9699539,deeppink:16716947,deepskyblue:49151,dimgray:6908265,dimgrey:6908265,dodgerblue:2003199,firebrick:11674146,floralwhite:16775920,forestgreen:2263842,fuchsia:16711935,gainsboro:14474460,ghostwhite:16316671,gold:16766720,goldenrod:14329120,gray:8421504,green:32768,greenyellow:11403055,grey:8421504,honeydew:15794160,hotpink:16738740,indianred:13458524,indigo:4915330,ivory:16777200,khaki:15787660,lavender:15132410,lavenderblush:16773365,lawngreen:8190976,lemonchiffon:16775885,lightblue:11393254,lightcoral:15761536,lightcyan:14745599,lightgoldenrodyellow:16448210,lightgray:13882323,lightgreen:9498256,lightgrey:13882323,lightpink:16758465,lightsalmon:16752762,lightseagreen:2142890,lightskyblue:8900346,lightslategray:7833753,lightslategrey:7833753,lightsteelblue:11584734,lightyellow:16777184,lime:65280,limegreen:3329330,linen:16445670,magenta:16711935,maroon:8388608,mediumaquamarine:6737322,mediumblue:205,mediumorchid:12211667,mediumpurple:9662683,mediumseagreen:3978097,mediumslateblue:8087790,mediumspringgreen:64154,mediumturquoise:4772300,mediumvioletred:13047173,midnightblue:1644912,mintcream:16121850,mistyrose:16770273,moccasin:16770229,navajowhite:16768685,navy:128,oldlace:16643558,olive:8421376,olivedrab:7048739,orange:16753920,orangered:16729344,orchid:14315734,palegoldenrod:15657130,palegreen:10025880,paleturquoise:11529966,palevioletred:14381203,papayawhip:16773077,peachpuff:16767673,peru:13468991,pink:16761035,plum:14524637,powderblue:11591910,purple:8388736,rebeccapurple:6697881,red:16711680,rosybrown:12357519,royalblue:4286945,saddlebrown:9127187,salmon:16416882,sandybrown:16032864,seagreen:3050327,seashell:16774638,sienna:10506797,silver:12632256,skyblue:8900331,slateblue:6970061,slategray:7372944,slategrey:7372944,snow:16775930,springgreen:65407,steelblue:4620980,tan:13808780,teal:32896,thistle:14204888,tomato:16737095,turquoise:4251856,violet:15631086,wheat:16113331,white:16777215,whitesmoke:16119285,yellow:16776960,yellowgreen:10145074},si={h:0,s:0,l:0},fr={h:0,s:0,l:0};function Ha(s,e,t){return t<0&&(t+=1),t>1&&(t-=1),t<1/6?s+(e-s)*6*t:t<1/2?e:t<2/3?s+(e-s)*6*(2/3-t):s}class Ie{constructor(e,t,n){return this.isColor=!0,this.r=1,this.g=1,this.b=1,this.set(e,t,n)}set(e,t,n){if(t===void 0&&n===void 0){const i=e;i&&i.isColor?this.copy(i):typeof i=="number"?this.setHex(i):typeof i=="string"&&this.setStyle(i)}else this.setRGB(e,t,n);return this}setScalar(e){return this.r=e,this.g=e,this.b=e,this}setHex(e,t=wt){return e=Math.floor(e),this.r=(e>>16&255)/255,this.g=(e>>8&255)/255,this.b=(e&255)/255,Ke.colorSpaceToWorking(this,t),this}setRGB(e,t,n,i=Ke.workingColorSpace){return this.r=e,this.g=t,this.b=n,Ke.colorSpaceToWorking(this,i),this}setHSL(e,t,n,i=Ke.workingColorSpace){if(e=jl(e,1),t=Xe(t,0,1),n=Xe(n,0,1),t===0)this.r=this.g=this.b=n;else{const r=n<=.5?n*(1+t):n+t-n*t,a=2*n-r;this.r=Ha(a,r,e+1/3),this.g=Ha(a,r,e),this.b=Ha(a,r,e-1/3)}return Ke.colorSpaceToWorking(this,i),this}setStyle(e,t=wt){function n(r){r!==void 0&&parseFloat(r)<1&&Pe("Color: Alpha component of "+e+" will be ignored.")}let i;if(i=/^(\w+)\(([^\)]*)\)/.exec(e)){let r;const a=i[1],o=i[2];switch(a){case"rgb":case"rgba":if(r=/^\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*(\d*\.?\d+)\s*)?$/.exec(o))return n(r[4]),this.setRGB(Math.min(255,parseInt(r[1],10))/255,Math.min(255,parseInt(r[2],10))/255,Math.min(255,parseInt(r[3],10))/255,t);if(r=/^\s*(\d+)\%\s*,\s*(\d+)\%\s*,\s*(\d+)\%\s*(?:,\s*(\d*\.?\d+)\s*)?$/.exec(o))return n(r[4]),this.setRGB(Math.min(100,parseInt(r[1],10))/100,Math.min(100,parseInt(r[2],10))/100,Math.min(100,parseInt(r[3],10))/100,t);break;case"hsl":case"hsla":if(r=/^\s*(\d*\.?\d+)\s*,\s*(\d*\.?\d+)\%\s*,\s*(\d*\.?\d+)\%\s*(?:,\s*(\d*\.?\d+)\s*)?$/.exec(o))return n(r[4]),this.setHSL(parseFloat(r[1])/360,parseFloat(r[2])/100,parseFloat(r[3])/100,t);break;default:Pe("Color: Unknown color model "+e)}}else if(i=/^\#([A-Fa-f\d]+)$/.exec(e)){const r=i[1],a=r.length;if(a===3)return this.setRGB(parseInt(r.charAt(0),16)/15,parseInt(r.charAt(1),16)/15,parseInt(r.charAt(2),16)/15,t);if(a===6)return this.setHex(parseInt(r,16),t);Pe("Color: Invalid hex color "+e)}else if(e&&e.length>0)return this.setColorName(e,t);return this}setColorName(e,t=wt){const n=Eu[e.toLowerCase()];return n!==void 0?this.setHex(n,t):Pe("Color: Unknown color "+e),this}clone(){return new this.constructor(this.r,this.g,this.b)}copy(e){return this.r=e.r,this.g=e.g,this.b=e.b,this}copySRGBToLinear(e){return this.r=$n(e.r),this.g=$n(e.g),this.b=$n(e.b),this}copyLinearToSRGB(e){return this.r=hs(e.r),this.g=hs(e.g),this.b=hs(e.b),this}convertSRGBToLinear(){return this.copySRGBToLinear(this),this}convertLinearToSRGB(){return this.copyLinearToSRGB(this),this}getHex(e=wt){return Ke.workingToColorSpace(Gt.copy(this),e),Math.round(Xe(Gt.r*255,0,255))*65536+Math.round(Xe(Gt.g*255,0,255))*256+Math.round(Xe(Gt.b*255,0,255))}getHexString(e=wt){return("000000"+this.getHex(e).toString(16)).slice(-6)}getHSL(e,t=Ke.workingColorSpace){Ke.workingToColorSpace(Gt.copy(this),t);const n=Gt.r,i=Gt.g,r=Gt.b,a=Math.max(n,i,r),o=Math.min(n,i,r);let l,c;const h=(o+a)/2;if(o===a)l=0,c=0;else{const u=a-o;switch(c=h<=.5?u/(a+o):u/(2-a-o),a){case n:l=(i-r)/u+(i<r?6:0);break;case i:l=(r-n)/u+2;break;case r:l=(n-i)/u+4;break}l/=6}return e.h=l,e.s=c,e.l=h,e}getRGB(e,t=Ke.workingColorSpace){return Ke.workingToColorSpace(Gt.copy(this),t),e.r=Gt.r,e.g=Gt.g,e.b=Gt.b,e}getStyle(e=wt){Ke.workingToColorSpace(Gt.copy(this),e);const t=Gt.r,n=Gt.g,i=Gt.b;return e!==wt?`color(${e} ${t.toFixed(3)} ${n.toFixed(3)} ${i.toFixed(3)})`:`rgb(${Math.round(t*255)},${Math.round(n*255)},${Math.round(i*255)})`}offsetHSL(e,t,n){return this.getHSL(si),this.setHSL(si.h+e,si.s+t,si.l+n)}add(e){return this.r+=e.r,this.g+=e.g,this.b+=e.b,this}addColors(e,t){return this.r=e.r+t.r,this.g=e.g+t.g,this.b=e.b+t.b,this}addScalar(e){return this.r+=e,this.g+=e,this.b+=e,this}sub(e){return this.r=Math.max(0,this.r-e.r),this.g=Math.max(0,this.g-e.g),this.b=Math.max(0,this.b-e.b),this}multiply(e){return this.r*=e.r,this.g*=e.g,this.b*=e.b,this}multiplyScalar(e){return this.r*=e,this.g*=e,this.b*=e,this}lerp(e,t){return this.r+=(e.r-this.r)*t,this.g+=(e.g-this.g)*t,this.b+=(e.b-this.b)*t,this}lerpColors(e,t,n){return this.r=e.r+(t.r-e.r)*n,this.g=e.g+(t.g-e.g)*n,this.b=e.b+(t.b-e.b)*n,this}lerpHSL(e,t){this.getHSL(si),e.getHSL(fr);const n=Zs(si.h,fr.h,t),i=Zs(si.s,fr.s,t),r=Zs(si.l,fr.l,t);return this.setHSL(n,i,r),this}setFromVector3(e){return this.r=e.x,this.g=e.y,this.b=e.z,this}applyMatrix3(e){const t=this.r,n=this.g,i=this.b,r=e.elements;return this.r=r[0]*t+r[3]*n+r[6]*i,this.g=r[1]*t+r[4]*n+r[7]*i,this.b=r[2]*t+r[5]*n+r[8]*i,this}equals(e){return e.r===this.r&&e.g===this.g&&e.b===this.b}fromArray(e,t=0){return this.r=e[t],this.g=e[t+1],this.b=e[t+2],this}toArray(e=[],t=0){return e[t]=this.r,e[t+1]=this.g,e[t+2]=this.b,e}fromBufferAttribute(e,t){return this.r=e.getX(t),this.g=e.getY(t),this.b=e.getZ(t),this}toJSON(){return this.getHex()}*[Symbol.iterator](){yield this.r,yield this.g,yield this.b}}const Gt=new Ie;Ie.NAMES=Eu;class _a{constructor(e,t=1,n=1e3){this.isFog=!0,this.name="",this.color=new Ie(e),this.near=t,this.far=n}clone(){return new _a(this.color,this.near,this.far)}toJSON(){return{type:"Fog",name:this.name,color:this.color.getHex(),near:this.near,far:this.far}}}class Zl extends ft{constructor(){super(),this.isScene=!0,this.type="Scene",this.background=null,this.environment=null,this.fog=null,this.backgroundBlurriness=0,this.backgroundIntensity=1,this.backgroundRotation=new Sn,this.environmentIntensity=1,this.environmentRotation=new Sn,this.overrideMaterial=null,typeof __THREE_DEVTOOLS__<"u"&&__THREE_DEVTOOLS__.dispatchEvent(new CustomEvent("observe",{detail:this}))}copy(e,t){return super.copy(e,t),e.background!==null&&(this.background=e.background.clone()),e.environment!==null&&(this.environment=e.environment.clone()),e.fog!==null&&(this.fog=e.fog.clone()),this.backgroundBlurriness=e.backgroundBlurriness,this.backgroundIntensity=e.backgroundIntensity,this.backgroundRotation.copy(e.backgroundRotation),this.environmentIntensity=e.environmentIntensity,this.environmentRotation.copy(e.environmentRotation),e.overrideMaterial!==null&&(this.overrideMaterial=e.overrideMaterial.clone()),this.matrixAutoUpdate=e.matrixAutoUpdate,this}toJSON(e){const t=super.toJSON(e);return this.fog!==null&&(t.object.fog=this.fog.toJSON()),this.backgroundBlurriness>0&&(t.object.backgroundBlurriness=this.backgroundBlurriness),this.backgroundIntensity!==1&&(t.object.backgroundIntensity=this.backgroundIntensity),t.object.backgroundRotation=this.backgroundRotation.toArray(),this.environmentIntensity!==1&&(t.object.environmentIntensity=this.environmentIntensity),t.object.environmentRotation=this.environmentRotation.toArray(),t}}const mn=new L,Hn=new L,Ga=new L,Gn=new L,Xi=new L,Yi=new L,jc=new L,Wa=new L,Xa=new L,Ya=new L,qa=new mt,ja=new mt,Ka=new mt;class vn{constructor(e=new L,t=new L,n=new L){this.a=e,this.b=t,this.c=n}static getNormal(e,t,n,i){i.subVectors(n,t),mn.subVectors(e,t),i.cross(mn);const r=i.lengthSq();return r>0?i.multiplyScalar(1/Math.sqrt(r)):i.set(0,0,0)}static getBarycoord(e,t,n,i,r){mn.subVectors(i,t),Hn.subVectors(n,t),Ga.subVectors(e,t);const a=mn.dot(mn),o=mn.dot(Hn),l=mn.dot(Ga),c=Hn.dot(Hn),h=Hn.dot(Ga),u=a*c-o*o;if(u===0)return r.set(0,0,0),null;const d=1/u,f=(c*l-o*h)*d,g=(a*h-o*l)*d;return r.set(1-f-g,g,f)}static containsPoint(e,t,n,i){return this.getBarycoord(e,t,n,i,Gn)===null?!1:Gn.x>=0&&Gn.y>=0&&Gn.x+Gn.y<=1}static getInterpolation(e,t,n,i,r,a,o,l){return this.getBarycoord(e,t,n,i,Gn)===null?(l.x=0,l.y=0,"z"in l&&(l.z=0),"w"in l&&(l.w=0),null):(l.setScalar(0),l.addScaledVector(r,Gn.x),l.addScaledVector(a,Gn.y),l.addScaledVector(o,Gn.z),l)}static getInterpolatedAttribute(e,t,n,i,r,a){return qa.setScalar(0),ja.setScalar(0),Ka.setScalar(0),qa.fromBufferAttribute(e,t),ja.fromBufferAttribute(e,n),Ka.fromBufferAttribute(e,i),a.setScalar(0),a.addScaledVector(qa,r.x),a.addScaledVector(ja,r.y),a.addScaledVector(Ka,r.z),a}static isFrontFacing(e,t,n,i){return mn.subVectors(n,t),Hn.subVectors(e,t),mn.cross(Hn).dot(i)<0}set(e,t,n){return this.a.copy(e),this.b.copy(t),this.c.copy(n),this}setFromPointsAndIndices(e,t,n,i){return this.a.copy(e[t]),this.b.copy(e[n]),this.c.copy(e[i]),this}setFromAttributeAndIndices(e,t,n,i){return this.a.fromBufferAttribute(e,t),this.b.fromBufferAttribute(e,n),this.c.fromBufferAttribute(e,i),this}clone(){return new this.constructor().copy(this)}copy(e){return this.a.copy(e.a),this.b.copy(e.b),this.c.copy(e.c),this}getArea(){return mn.subVectors(this.c,this.b),Hn.subVectors(this.a,this.b),mn.cross(Hn).length()*.5}getMidpoint(e){return e.addVectors(this.a,this.b).add(this.c).multiplyScalar(1/3)}getNormal(e){return vn.getNormal(this.a,this.b,this.c,e)}getPlane(e){return e.setFromCoplanarPoints(this.a,this.b,this.c)}getBarycoord(e,t){return vn.getBarycoord(e,this.a,this.b,this.c,t)}getInterpolation(e,t,n,i,r){return vn.getInterpolation(e,this.a,this.b,this.c,t,n,i,r)}containsPoint(e){return vn.containsPoint(e,this.a,this.b,this.c)}isFrontFacing(e){return vn.isFrontFacing(this.a,this.b,this.c,e)}intersectsBox(e){return e.intersectsTriangle(this)}closestPointToPoint(e,t){const n=this.a,i=this.b,r=this.c;let a,o;Xi.subVectors(i,n),Yi.subVectors(r,n),Wa.subVectors(e,n);const l=Xi.dot(Wa),c=Yi.dot(Wa);if(l<=0&&c<=0)return t.copy(n);Xa.subVectors(e,i);const h=Xi.dot(Xa),u=Yi.dot(Xa);if(h>=0&&u<=h)return t.copy(i);const d=l*u-h*c;if(d<=0&&l>=0&&h<=0)return a=l/(l-h),t.copy(n).addScaledVector(Xi,a);Ya.subVectors(e,r);const f=Xi.dot(Ya),g=Yi.dot(Ya);if(g>=0&&f<=g)return t.copy(r);const x=f*c-l*g;if(x<=0&&c>=0&&g<=0)return o=c/(c-g),t.copy(n).addScaledVector(Yi,o);const p=h*g-f*u;if(p<=0&&u-h>=0&&f-g>=0)return jc.subVectors(r,i),o=(u-h)/(u-h+(f-g)),t.copy(i).addScaledVector(jc,o);const m=1/(p+x+d);return a=x*m,o=d*m,t.copy(n).addScaledVector(Xi,a).addScaledVector(Yi,o)}equals(e){return e.a.equals(this.a)&&e.b.equals(this.b)&&e.c.equals(this.c)}}class Qn{constructor(e=new L(1/0,1/0,1/0),t=new L(-1/0,-1/0,-1/0)){this.isBox3=!0,this.min=e,this.max=t}set(e,t){return this.min.copy(e),this.max.copy(t),this}setFromArray(e){this.makeEmpty();for(let t=0,n=e.length;t<n;t+=3)this.expandByPoint(gn.fromArray(e,t));return this}setFromBufferAttribute(e){this.makeEmpty();for(let t=0,n=e.count;t<n;t++)this.expandByPoint(gn.fromBufferAttribute(e,t));return this}setFromPoints(e){this.makeEmpty();for(let t=0,n=e.length;t<n;t++)this.expandByPoint(e[t]);return this}setFromCenterAndSize(e,t){const n=gn.copy(t).multiplyScalar(.5);return this.min.copy(e).sub(n),this.max.copy(e).add(n),this}setFromObject(e,t=!1){return this.makeEmpty(),this.expandByObject(e,t)}clone(){return new this.constructor().copy(this)}copy(e){return this.min.copy(e.min),this.max.copy(e.max),this}makeEmpty(){return this.min.x=this.min.y=this.min.z=1/0,this.max.x=this.max.y=this.max.z=-1/0,this}isEmpty(){return this.max.x<this.min.x||this.max.y<this.min.y||this.max.z<this.min.z}getCenter(e){return this.isEmpty()?e.set(0,0,0):e.addVectors(this.min,this.max).multiplyScalar(.5)}getSize(e){return this.isEmpty()?e.set(0,0,0):e.subVectors(this.max,this.min)}expandByPoint(e){return this.min.min(e),this.max.max(e),this}expandByVector(e){return this.min.sub(e),this.max.add(e),this}expandByScalar(e){return this.min.addScalar(-e),this.max.addScalar(e),this}expandByObject(e,t=!1){e.updateWorldMatrix(!1,!1);const n=e.geometry;if(n!==void 0){const r=n.getAttribute("position");if(t===!0&&r!==void 0&&e.isInstancedMesh!==!0)for(let a=0,o=r.count;a<o;a++)e.isMesh===!0?e.getVertexPosition(a,gn):gn.fromBufferAttribute(r,a),gn.applyMatrix4(e.matrixWorld),this.expandByPoint(gn);else e.boundingBox!==void 0?(e.boundingBox===null&&e.computeBoundingBox(),pr.copy(e.boundingBox)):(n.boundingBox===null&&n.computeBoundingBox(),pr.copy(n.boundingBox)),pr.applyMatrix4(e.matrixWorld),this.union(pr)}const i=e.children;for(let r=0,a=i.length;r<a;r++)this.expandByObject(i[r],t);return this}containsPoint(e){return e.x>=this.min.x&&e.x<=this.max.x&&e.y>=this.min.y&&e.y<=this.max.y&&e.z>=this.min.z&&e.z<=this.max.z}containsBox(e){return this.min.x<=e.min.x&&e.max.x<=this.max.x&&this.min.y<=e.min.y&&e.max.y<=this.max.y&&this.min.z<=e.min.z&&e.max.z<=this.max.z}getParameter(e,t){return t.set((e.x-this.min.x)/(this.max.x-this.min.x),(e.y-this.min.y)/(this.max.y-this.min.y),(e.z-this.min.z)/(this.max.z-this.min.z))}intersectsBox(e){return e.max.x>=this.min.x&&e.min.x<=this.max.x&&e.max.y>=this.min.y&&e.min.y<=this.max.y&&e.max.z>=this.min.z&&e.min.z<=this.max.z}intersectsSphere(e){return this.clampPoint(e.center,gn),gn.distanceToSquared(e.center)<=e.radius*e.radius}intersectsPlane(e){let t,n;return e.normal.x>0?(t=e.normal.x*this.min.x,n=e.normal.x*this.max.x):(t=e.normal.x*this.max.x,n=e.normal.x*this.min.x),e.normal.y>0?(t+=e.normal.y*this.min.y,n+=e.normal.y*this.max.y):(t+=e.normal.y*this.max.y,n+=e.normal.y*this.min.y),e.normal.z>0?(t+=e.normal.z*this.min.z,n+=e.normal.z*this.max.z):(t+=e.normal.z*this.max.z,n+=e.normal.z*this.min.z),t<=-e.constant&&n>=-e.constant}intersectsTriangle(e){if(this.isEmpty())return!1;this.getCenter(Os),mr.subVectors(this.max,Os),qi.subVectors(e.a,Os),ji.subVectors(e.b,Os),Ki.subVectors(e.c,Os),ri.subVectors(ji,qi),ai.subVectors(Ki,ji),yi.subVectors(qi,Ki);let t=[0,-ri.z,ri.y,0,-ai.z,ai.y,0,-yi.z,yi.y,ri.z,0,-ri.x,ai.z,0,-ai.x,yi.z,0,-yi.x,-ri.y,ri.x,0,-ai.y,ai.x,0,-yi.y,yi.x,0];return!$a(t,qi,ji,Ki,mr)||(t=[1,0,0,0,1,0,0,0,1],!$a(t,qi,ji,Ki,mr))?!1:(gr.crossVectors(ri,ai),t=[gr.x,gr.y,gr.z],$a(t,qi,ji,Ki,mr))}clampPoint(e,t){return t.copy(e).clamp(this.min,this.max)}distanceToPoint(e){return this.clampPoint(e,gn).distanceTo(e)}getBoundingSphere(e){return this.isEmpty()?e.makeEmpty():(this.getCenter(e.center),e.radius=this.getSize(gn).length()*.5),e}intersect(e){return this.min.max(e.min),this.max.min(e.max),this.isEmpty()&&this.makeEmpty(),this}union(e){return this.min.min(e.min),this.max.max(e.max),this}applyMatrix4(e){return this.isEmpty()?this:(Wn[0].set(this.min.x,this.min.y,this.min.z).applyMatrix4(e),Wn[1].set(this.min.x,this.min.y,this.max.z).applyMatrix4(e),Wn[2].set(this.min.x,this.max.y,this.min.z).applyMatrix4(e),Wn[3].set(this.min.x,this.max.y,this.max.z).applyMatrix4(e),Wn[4].set(this.max.x,this.min.y,this.min.z).applyMatrix4(e),Wn[5].set(this.max.x,this.min.y,this.max.z).applyMatrix4(e),Wn[6].set(this.max.x,this.max.y,this.min.z).applyMatrix4(e),Wn[7].set(this.max.x,this.max.y,this.max.z).applyMatrix4(e),this.setFromPoints(Wn),this)}translate(e){return this.min.add(e),this.max.add(e),this}equals(e){return e.min.equals(this.min)&&e.max.equals(this.max)}toJSON(){return{min:this.min.toArray(),max:this.max.toArray()}}fromJSON(e){return this.min.fromArray(e.min),this.max.fromArray(e.max),this}}const Wn=[new L,new L,new L,new L,new L,new L,new L,new L],gn=new L,pr=new Qn,qi=new L,ji=new L,Ki=new L,ri=new L,ai=new L,yi=new L,Os=new L,mr=new L,gr=new L,Si=new L;function $a(s,e,t,n,i){for(let r=0,a=s.length-3;r<=a;r+=3){Si.fromArray(s,r);const o=i.x*Math.abs(Si.x)+i.y*Math.abs(Si.y)+i.z*Math.abs(Si.z),l=e.dot(Si),c=t.dot(Si),h=n.dot(Si);if(Math.max(-Math.max(l,c,h),Math.min(l,c,h))>o)return!1}return!0}const Tt=new L,_r=new Le;let ap=0;class jt{constructor(e,t,n=!1){if(Array.isArray(e))throw new TypeError("THREE.BufferAttribute: array should be a Typed Array.");this.isBufferAttribute=!0,Object.defineProperty(this,"id",{value:ap++}),this.name="",this.array=e,this.itemSize=t,this.count=e!==void 0?e.length/t:0,this.normalized=n,this.usage=_l,this.updateRanges=[],this.gpuType=sn,this.version=0}onUploadCallback(){}set needsUpdate(e){e===!0&&this.version++}setUsage(e){return this.usage=e,this}addUpdateRange(e,t){this.updateRanges.push({start:e,count:t})}clearUpdateRanges(){this.updateRanges.length=0}copy(e){return this.name=e.name,this.array=new e.array.constructor(e.array),this.itemSize=e.itemSize,this.count=e.count,this.normalized=e.normalized,this.usage=e.usage,this.gpuType=e.gpuType,this}copyAt(e,t,n){e*=this.itemSize,n*=t.itemSize;for(let i=0,r=this.itemSize;i<r;i++)this.array[e+i]=t.array[n+i];return this}copyArray(e){return this.array.set(e),this}applyMatrix3(e){if(this.itemSize===2)for(let t=0,n=this.count;t<n;t++)_r.fromBufferAttribute(this,t),_r.applyMatrix3(e),this.setXY(t,_r.x,_r.y);else if(this.itemSize===3)for(let t=0,n=this.count;t<n;t++)Tt.fromBufferAttribute(this,t),Tt.applyMatrix3(e),this.setXYZ(t,Tt.x,Tt.y,Tt.z);return this}applyMatrix4(e){for(let t=0,n=this.count;t<n;t++)Tt.fromBufferAttribute(this,t),Tt.applyMatrix4(e),this.setXYZ(t,Tt.x,Tt.y,Tt.z);return this}applyNormalMatrix(e){for(let t=0,n=this.count;t<n;t++)Tt.fromBufferAttribute(this,t),Tt.applyNormalMatrix(e),this.setXYZ(t,Tt.x,Tt.y,Tt.z);return this}transformDirection(e){for(let t=0,n=this.count;t<n;t++)Tt.fromBufferAttribute(this,t),Tt.transformDirection(e),this.setXYZ(t,Tt.x,Tt.y,Tt.z);return this}set(e,t=0){return this.array.set(e,t),this}getComponent(e,t){let n=this.array[e*this.itemSize+t];return this.normalized&&(n=_n(n,this.array)),n}setComponent(e,t,n){return this.normalized&&(n=it(n,this.array)),this.array[e*this.itemSize+t]=n,this}getX(e){let t=this.array[e*this.itemSize];return this.normalized&&(t=_n(t,this.array)),t}setX(e,t){return this.normalized&&(t=it(t,this.array)),this.array[e*this.itemSize]=t,this}getY(e){let t=this.array[e*this.itemSize+1];return this.normalized&&(t=_n(t,this.array)),t}setY(e,t){return this.normalized&&(t=it(t,this.array)),this.array[e*this.itemSize+1]=t,this}getZ(e){let t=this.array[e*this.itemSize+2];return this.normalized&&(t=_n(t,this.array)),t}setZ(e,t){return this.normalized&&(t=it(t,this.array)),this.array[e*this.itemSize+2]=t,this}getW(e){let t=this.array[e*this.itemSize+3];return this.normalized&&(t=_n(t,this.array)),t}setW(e,t){return this.normalized&&(t=it(t,this.array)),this.array[e*this.itemSize+3]=t,this}setXY(e,t,n){return e*=this.itemSize,this.normalized&&(t=it(t,this.array),n=it(n,this.array)),this.array[e+0]=t,this.array[e+1]=n,this}setXYZ(e,t,n,i){return e*=this.itemSize,this.normalized&&(t=it(t,this.array),n=it(n,this.array),i=it(i,this.array)),this.array[e+0]=t,this.array[e+1]=n,this.array[e+2]=i,this}setXYZW(e,t,n,i,r){return e*=this.itemSize,this.normalized&&(t=it(t,this.array),n=it(n,this.array),i=it(i,this.array),r=it(r,this.array)),this.array[e+0]=t,this.array[e+1]=n,this.array[e+2]=i,this.array[e+3]=r,this}onUpload(e){return this.onUploadCallback=e,this}clone(){return new this.constructor(this.array,this.itemSize).copy(this)}toJSON(){const e={itemSize:this.itemSize,type:this.array.constructor.name,array:Array.from(this.array),normalized:this.normalized};return this.name!==""&&(e.name=this.name),this.usage!==_l&&(e.usage=this.usage),e}}class Tu extends jt{constructor(e,t,n){super(new Uint16Array(e),t,n)}}class Au extends jt{constructor(e,t,n){super(new Uint32Array(e),t,n)}}class an extends jt{constructor(e,t,n){super(new Float32Array(e),t,n)}}const op=new Qn,Bs=new L,Za=new L;class On{constructor(e=new L,t=-1){this.isSphere=!0,this.center=e,this.radius=t}set(e,t){return this.center.copy(e),this.radius=t,this}setFromPoints(e,t){const n=this.center;t!==void 0?n.copy(t):op.setFromPoints(e).getCenter(n);let i=0;for(let r=0,a=e.length;r<a;r++)i=Math.max(i,n.distanceToSquared(e[r]));return this.radius=Math.sqrt(i),this}copy(e){return this.center.copy(e.center),this.radius=e.radius,this}isEmpty(){return this.radius<0}makeEmpty(){return this.center.set(0,0,0),this.radius=-1,this}containsPoint(e){return e.distanceToSquared(this.center)<=this.radius*this.radius}distanceToPoint(e){return e.distanceTo(this.center)-this.radius}intersectsSphere(e){const t=this.radius+e.radius;return e.center.distanceToSquared(this.center)<=t*t}intersectsBox(e){return e.intersectsSphere(this)}intersectsPlane(e){return Math.abs(e.distanceToPoint(this.center))<=this.radius}clampPoint(e,t){const n=this.center.distanceToSquared(e);return t.copy(e),n>this.radius*this.radius&&(t.sub(this.center).normalize(),t.multiplyScalar(this.radius).add(this.center)),t}getBoundingBox(e){return this.isEmpty()?(e.makeEmpty(),e):(e.set(this.center,this.center),e.expandByScalar(this.radius),e)}applyMatrix4(e){return this.center.applyMatrix4(e),this.radius=this.radius*e.getMaxScaleOnAxis(),this}translate(e){return this.center.add(e),this}expandByPoint(e){if(this.isEmpty())return this.center.copy(e),this.radius=0,this;Bs.subVectors(e,this.center);const t=Bs.lengthSq();if(t>this.radius*this.radius){const n=Math.sqrt(t),i=(n-this.radius)*.5;this.center.addScaledVector(Bs,i/n),this.radius+=i}return this}union(e){return e.isEmpty()?this:this.isEmpty()?(this.copy(e),this):(this.center.equals(e.center)===!0?this.radius=Math.max(this.radius,e.radius):(Za.subVectors(e.center,this.center).setLength(e.radius),this.expandByPoint(Bs.copy(e.center).add(Za)),this.expandByPoint(Bs.copy(e.center).sub(Za))),this)}equals(e){return e.center.equals(this.center)&&e.radius===this.radius}clone(){return new this.constructor().copy(this)}toJSON(){return{radius:this.radius,center:this.center.toArray()}}fromJSON(e){return this.radius=e.radius,this.center.fromArray(e.center),this}}let lp=0;const cn=new Ve,Ja=new ft,$i=new L,tn=new Qn,ks=new Qn,Nt=new L;class ln extends Ni{constructor(){super(),this.isBufferGeometry=!0,Object.defineProperty(this,"id",{value:lp++}),this.uuid=Mn(),this.name="",this.type="BufferGeometry",this.index=null,this.indirect=null,this.indirectOffset=0,this.attributes={},this.morphAttributes={},this.morphTargetsRelative=!1,this.groups=[],this.boundingBox=null,this.boundingSphere=null,this.drawRange={start:0,count:1/0},this.userData={}}getIndex(){return this.index}setIndex(e){return Array.isArray(e)?this.index=new(Af(e)?Au:Tu)(e,1):this.index=e,this}setIndirect(e,t=0){return this.indirect=e,this.indirectOffset=t,this}getIndirect(){return this.indirect}getAttribute(e){return this.attributes[e]}setAttribute(e,t){return this.attributes[e]=t,this}deleteAttribute(e){return delete this.attributes[e],this}hasAttribute(e){return this.attributes[e]!==void 0}addGroup(e,t,n=0){this.groups.push({start:e,count:t,materialIndex:n})}clearGroups(){this.groups=[]}setDrawRange(e,t){this.drawRange.start=e,this.drawRange.count=t}applyMatrix4(e){const t=this.attributes.position;t!==void 0&&(t.applyMatrix4(e),t.needsUpdate=!0);const n=this.attributes.normal;if(n!==void 0){const r=new He().getNormalMatrix(e);n.applyNormalMatrix(r),n.needsUpdate=!0}const i=this.attributes.tangent;return i!==void 0&&(i.transformDirection(e),i.needsUpdate=!0),this.boundingBox!==null&&this.computeBoundingBox(),this.boundingSphere!==null&&this.computeBoundingSphere(),this}applyQuaternion(e){return cn.makeRotationFromQuaternion(e),this.applyMatrix4(cn),this}rotateX(e){return cn.makeRotationX(e),this.applyMatrix4(cn),this}rotateY(e){return cn.makeRotationY(e),this.applyMatrix4(cn),this}rotateZ(e){return cn.makeRotationZ(e),this.applyMatrix4(cn),this}translate(e,t,n){return cn.makeTranslation(e,t,n),this.applyMatrix4(cn),this}scale(e,t,n){return cn.makeScale(e,t,n),this.applyMatrix4(cn),this}lookAt(e){return Ja.lookAt(e),Ja.updateMatrix(),this.applyMatrix4(Ja.matrix),this}center(){return this.computeBoundingBox(),this.boundingBox.getCenter($i).negate(),this.translate($i.x,$i.y,$i.z),this}setFromPoints(e){const t=this.getAttribute("position");if(t===void 0){const n=[];for(let i=0,r=e.length;i<r;i++){const a=e[i];n.push(a.x,a.y,a.z||0)}this.setAttribute("position",new an(n,3))}else{const n=Math.min(e.length,t.count);for(let i=0;i<n;i++){const r=e[i];t.setXYZ(i,r.x,r.y,r.z||0)}e.length>t.count&&Pe("BufferGeometry: Buffer size too small for points data. Use .dispose() and create a new geometry."),t.needsUpdate=!0}return this}computeBoundingBox(){this.boundingBox===null&&(this.boundingBox=new Qn);const e=this.attributes.position,t=this.morphAttributes.position;if(e&&e.isGLBufferAttribute){Ue("BufferGeometry.computeBoundingBox(): GLBufferAttribute requires a manual bounding box.",this),this.boundingBox.set(new L(-1/0,-1/0,-1/0),new L(1/0,1/0,1/0));return}if(e!==void 0){if(this.boundingBox.setFromBufferAttribute(e),t)for(let n=0,i=t.length;n<i;n++){const r=t[n];tn.setFromBufferAttribute(r),this.morphTargetsRelative?(Nt.addVectors(this.boundingBox.min,tn.min),this.boundingBox.expandByPoint(Nt),Nt.addVectors(this.boundingBox.max,tn.max),this.boundingBox.expandByPoint(Nt)):(this.boundingBox.expandByPoint(tn.min),this.boundingBox.expandByPoint(tn.max))}}else this.boundingBox.makeEmpty();(isNaN(this.boundingBox.min.x)||isNaN(this.boundingBox.min.y)||isNaN(this.boundingBox.min.z))&&Ue('BufferGeometry.computeBoundingBox(): Computed min/max have NaN values. The "position" attribute is likely to have NaN values.',this)}computeBoundingSphere(){this.boundingSphere===null&&(this.boundingSphere=new On);const e=this.attributes.position,t=this.morphAttributes.position;if(e&&e.isGLBufferAttribute){Ue("BufferGeometry.computeBoundingSphere(): GLBufferAttribute requires a manual bounding sphere.",this),this.boundingSphere.set(new L,1/0);return}if(e){const n=this.boundingSphere.center;if(tn.setFromBufferAttribute(e),t)for(let r=0,a=t.length;r<a;r++){const o=t[r];ks.setFromBufferAttribute(o),this.morphTargetsRelative?(Nt.addVectors(tn.min,ks.min),tn.expandByPoint(Nt),Nt.addVectors(tn.max,ks.max),tn.expandByPoint(Nt)):(tn.expandByPoint(ks.min),tn.expandByPoint(ks.max))}tn.getCenter(n);let i=0;for(let r=0,a=e.count;r<a;r++)Nt.fromBufferAttribute(e,r),i=Math.max(i,n.distanceToSquared(Nt));if(t)for(let r=0,a=t.length;r<a;r++){const o=t[r],l=this.morphTargetsRelative;for(let c=0,h=o.count;c<h;c++)Nt.fromBufferAttribute(o,c),l&&($i.fromBufferAttribute(e,c),Nt.add($i)),i=Math.max(i,n.distanceToSquared(Nt))}this.boundingSphere.radius=Math.sqrt(i),isNaN(this.boundingSphere.radius)&&Ue('BufferGeometry.computeBoundingSphere(): Computed radius is NaN. The "position" attribute is likely to have NaN values.',this)}}computeTangents(){const e=this.index,t=this.attributes;if(e===null||t.position===void 0||t.normal===void 0||t.uv===void 0){Ue("BufferGeometry: .computeTangents() failed. Missing required attributes (index, position, normal or uv)");return}const n=t.position,i=t.normal,r=t.uv;this.hasAttribute("tangent")===!1&&this.setAttribute("tangent",new jt(new Float32Array(4*n.count),4));const a=this.getAttribute("tangent"),o=[],l=[];for(let v=0;v<n.count;v++)o[v]=new L,l[v]=new L;const c=new L,h=new L,u=new L,d=new Le,f=new Le,g=new Le,x=new L,p=new L;function m(v,b,D){c.fromBufferAttribute(n,v),h.fromBufferAttribute(n,b),u.fromBufferAttribute(n,D),d.fromBufferAttribute(r,v),f.fromBufferAttribute(r,b),g.fromBufferAttribute(r,D),h.sub(c),u.sub(c),f.sub(d),g.sub(d);const R=1/(f.x*g.y-g.x*f.y);isFinite(R)&&(x.copy(h).multiplyScalar(g.y).addScaledVector(u,-f.y).multiplyScalar(R),p.copy(u).multiplyScalar(f.x).addScaledVector(h,-g.x).multiplyScalar(R),o[v].add(x),o[b].add(x),o[D].add(x),l[v].add(p),l[b].add(p),l[D].add(p))}let S=this.groups;S.length===0&&(S=[{start:0,count:e.count}]);for(let v=0,b=S.length;v<b;++v){const D=S[v],R=D.start,F=D.count;for(let O=R,X=R+F;O<X;O+=3)m(e.getX(O+0),e.getX(O+1),e.getX(O+2))}const T=new L,M=new L,E=new L,w=new L;function C(v){E.fromBufferAttribute(i,v),w.copy(E);const b=o[v];T.copy(b),T.sub(E.multiplyScalar(E.dot(b))).normalize(),M.crossVectors(w,b);const R=M.dot(l[v])<0?-1:1;a.setXYZW(v,T.x,T.y,T.z,R)}for(let v=0,b=S.length;v<b;++v){const D=S[v],R=D.start,F=D.count;for(let O=R,X=R+F;O<X;O+=3)C(e.getX(O+0)),C(e.getX(O+1)),C(e.getX(O+2))}}computeVertexNormals(){const e=this.index,t=this.getAttribute("position");if(t!==void 0){let n=this.getAttribute("normal");if(n===void 0)n=new jt(new Float32Array(t.count*3),3),this.setAttribute("normal",n);else for(let d=0,f=n.count;d<f;d++)n.setXYZ(d,0,0,0);const i=new L,r=new L,a=new L,o=new L,l=new L,c=new L,h=new L,u=new L;if(e)for(let d=0,f=e.count;d<f;d+=3){const g=e.getX(d+0),x=e.getX(d+1),p=e.getX(d+2);i.fromBufferAttribute(t,g),r.fromBufferAttribute(t,x),a.fromBufferAttribute(t,p),h.subVectors(a,r),u.subVectors(i,r),h.cross(u),o.fromBufferAttribute(n,g),l.fromBufferAttribute(n,x),c.fromBufferAttribute(n,p),o.add(h),l.add(h),c.add(h),n.setXYZ(g,o.x,o.y,o.z),n.setXYZ(x,l.x,l.y,l.z),n.setXYZ(p,c.x,c.y,c.z)}else for(let d=0,f=t.count;d<f;d+=3)i.fromBufferAttribute(t,d+0),r.fromBufferAttribute(t,d+1),a.fromBufferAttribute(t,d+2),h.subVectors(a,r),u.subVectors(i,r),h.cross(u),n.setXYZ(d+0,h.x,h.y,h.z),n.setXYZ(d+1,h.x,h.y,h.z),n.setXYZ(d+2,h.x,h.y,h.z);this.normalizeNormals(),n.needsUpdate=!0}}normalizeNormals(){const e=this.attributes.normal;for(let t=0,n=e.count;t<n;t++)Nt.fromBufferAttribute(e,t),Nt.normalize(),e.setXYZ(t,Nt.x,Nt.y,Nt.z)}toNonIndexed(){function e(o,l){const c=o.array,h=o.itemSize,u=o.normalized,d=new c.constructor(l.length*h);let f=0,g=0;for(let x=0,p=l.length;x<p;x++){o.isInterleavedBufferAttribute?f=l[x]*o.data.stride+o.offset:f=l[x]*h;for(let m=0;m<h;m++)d[g++]=c[f++]}return new jt(d,h,u)}if(this.index===null)return Pe("BufferGeometry.toNonIndexed(): BufferGeometry is already non-indexed."),this;const t=new ln,n=this.index.array,i=this.attributes;for(const o in i){const l=i[o],c=e(l,n);t.setAttribute(o,c)}const r=this.morphAttributes;for(const o in r){const l=[],c=r[o];for(let h=0,u=c.length;h<u;h++){const d=c[h],f=e(d,n);l.push(f)}t.morphAttributes[o]=l}t.morphTargetsRelative=this.morphTargetsRelative;const a=this.groups;for(let o=0,l=a.length;o<l;o++){const c=a[o];t.addGroup(c.start,c.count,c.materialIndex)}return t}toJSON(){const e={metadata:{version:4.7,type:"BufferGeometry",generator:"BufferGeometry.toJSON"}};if(e.uuid=this.uuid,e.type=this.type,this.name!==""&&(e.name=this.name),Object.keys(this.userData).length>0&&(e.userData=this.userData),this.parameters!==void 0){const l=this.parameters;for(const c in l)l[c]!==void 0&&(e[c]=l[c]);return e}e.data={attributes:{}};const t=this.index;t!==null&&(e.data.index={type:t.array.constructor.name,array:Array.prototype.slice.call(t.array)});const n=this.attributes;for(const l in n){const c=n[l];e.data.attributes[l]=c.toJSON(e.data)}const i={};let r=!1;for(const l in this.morphAttributes){const c=this.morphAttributes[l],h=[];for(let u=0,d=c.length;u<d;u++){const f=c[u];h.push(f.toJSON(e.data))}h.length>0&&(i[l]=h,r=!0)}r&&(e.data.morphAttributes=i,e.data.morphTargetsRelative=this.morphTargetsRelative);const a=this.groups;a.length>0&&(e.data.groups=JSON.parse(JSON.stringify(a)));const o=this.boundingSphere;return o!==null&&(e.data.boundingSphere=o.toJSON()),e}clone(){return new this.constructor().copy(this)}copy(e){this.index=null,this.attributes={},this.morphAttributes={},this.groups=[],this.boundingBox=null,this.boundingSphere=null;const t={};this.name=e.name;const n=e.index;n!==null&&this.setIndex(n.clone());const i=e.attributes;for(const c in i){const h=i[c];this.setAttribute(c,h.clone(t))}const r=e.morphAttributes;for(const c in r){const h=[],u=r[c];for(let d=0,f=u.length;d<f;d++)h.push(u[d].clone(t));this.morphAttributes[c]=h}this.morphTargetsRelative=e.morphTargetsRelative;const a=e.groups;for(let c=0,h=a.length;c<h;c++){const u=a[c];this.addGroup(u.start,u.count,u.materialIndex)}const o=e.boundingBox;o!==null&&(this.boundingBox=o.clone());const l=e.boundingSphere;return l!==null&&(this.boundingSphere=l.clone()),this.drawRange.start=e.drawRange.start,this.drawRange.count=e.drawRange.count,this.userData=e.userData,this}dispose(){this.dispatchEvent({type:"dispose"})}}class cp{constructor(e,t){this.isInterleavedBuffer=!0,this.array=e,this.stride=t,this.count=e!==void 0?e.length/t:0,this.usage=_l,this.updateRanges=[],this.version=0,this.uuid=Mn()}onUploadCallback(){}set needsUpdate(e){e===!0&&this.version++}setUsage(e){return this.usage=e,this}addUpdateRange(e,t){this.updateRanges.push({start:e,count:t})}clearUpdateRanges(){this.updateRanges.length=0}copy(e){return this.array=new e.array.constructor(e.array),this.count=e.count,this.stride=e.stride,this.usage=e.usage,this}copyAt(e,t,n){e*=this.stride,n*=t.stride;for(let i=0,r=this.stride;i<r;i++)this.array[e+i]=t.array[n+i];return this}set(e,t=0){return this.array.set(e,t),this}clone(e){e.arrayBuffers===void 0&&(e.arrayBuffers={}),this.array.buffer._uuid===void 0&&(this.array.buffer._uuid=Mn()),e.arrayBuffers[this.array.buffer._uuid]===void 0&&(e.arrayBuffers[this.array.buffer._uuid]=this.array.slice(0).buffer);const t=new this.array.constructor(e.arrayBuffers[this.array.buffer._uuid]),n=new this.constructor(t,this.stride);return n.setUsage(this.usage),n}onUpload(e){return this.onUploadCallback=e,this}toJSON(e){return e.arrayBuffers===void 0&&(e.arrayBuffers={}),this.array.buffer._uuid===void 0&&(this.array.buffer._uuid=Mn()),e.arrayBuffers[this.array.buffer._uuid]===void 0&&(e.arrayBuffers[this.array.buffer._uuid]=Array.from(new Uint32Array(this.array.buffer))),{uuid:this.uuid,buffer:this.array.buffer._uuid,type:this.array.constructor.name,stride:this.stride}}}const Xt=new L;class Jl{constructor(e,t,n,i=!1){this.isInterleavedBufferAttribute=!0,this.name="",this.data=e,this.itemSize=t,this.offset=n,this.normalized=i}get count(){return this.data.count}get array(){return this.data.array}set needsUpdate(e){this.data.needsUpdate=e}applyMatrix4(e){for(let t=0,n=this.data.count;t<n;t++)Xt.fromBufferAttribute(this,t),Xt.applyMatrix4(e),this.setXYZ(t,Xt.x,Xt.y,Xt.z);return this}applyNormalMatrix(e){for(let t=0,n=this.count;t<n;t++)Xt.fromBufferAttribute(this,t),Xt.applyNormalMatrix(e),this.setXYZ(t,Xt.x,Xt.y,Xt.z);return this}transformDirection(e){for(let t=0,n=this.count;t<n;t++)Xt.fromBufferAttribute(this,t),Xt.transformDirection(e),this.setXYZ(t,Xt.x,Xt.y,Xt.z);return this}getComponent(e,t){let n=this.array[e*this.data.stride+this.offset+t];return this.normalized&&(n=_n(n,this.array)),n}setComponent(e,t,n){return this.normalized&&(n=it(n,this.array)),this.data.array[e*this.data.stride+this.offset+t]=n,this}setX(e,t){return this.normalized&&(t=it(t,this.array)),this.data.array[e*this.data.stride+this.offset]=t,this}setY(e,t){return this.normalized&&(t=it(t,this.array)),this.data.array[e*this.data.stride+this.offset+1]=t,this}setZ(e,t){return this.normalized&&(t=it(t,this.array)),this.data.array[e*this.data.stride+this.offset+2]=t,this}setW(e,t){return this.normalized&&(t=it(t,this.array)),this.data.array[e*this.data.stride+this.offset+3]=t,this}getX(e){let t=this.data.array[e*this.data.stride+this.offset];return this.normalized&&(t=_n(t,this.array)),t}getY(e){let t=this.data.array[e*this.data.stride+this.offset+1];return this.normalized&&(t=_n(t,this.array)),t}getZ(e){let t=this.data.array[e*this.data.stride+this.offset+2];return this.normalized&&(t=_n(t,this.array)),t}getW(e){let t=this.data.array[e*this.data.stride+this.offset+3];return this.normalized&&(t=_n(t,this.array)),t}setXY(e,t,n){return e=e*this.data.stride+this.offset,this.normalized&&(t=it(t,this.array),n=it(n,this.array)),this.data.array[e+0]=t,this.data.array[e+1]=n,this}setXYZ(e,t,n,i){return e=e*this.data.stride+this.offset,this.normalized&&(t=it(t,this.array),n=it(n,this.array),i=it(i,this.array)),this.data.array[e+0]=t,this.data.array[e+1]=n,this.data.array[e+2]=i,this}setXYZW(e,t,n,i,r){return e=e*this.data.stride+this.offset,this.normalized&&(t=it(t,this.array),n=it(n,this.array),i=it(i,this.array),r=it(r,this.array)),this.data.array[e+0]=t,this.data.array[e+1]=n,this.data.array[e+2]=i,this.data.array[e+3]=r,this}clone(e){if(e===void 0){sa("InterleavedBufferAttribute.clone(): Cloning an interleaved buffer attribute will de-interleave buffer data.");const t=[];for(let n=0;n<this.count;n++){const i=n*this.data.stride+this.offset;for(let r=0;r<this.itemSize;r++)t.push(this.data.array[i+r])}return new jt(new this.array.constructor(t),this.itemSize,this.normalized)}else return e.interleavedBuffers===void 0&&(e.interleavedBuffers={}),e.interleavedBuffers[this.data.uuid]===void 0&&(e.interleavedBuffers[this.data.uuid]=this.data.clone(e)),new Jl(e.interleavedBuffers[this.data.uuid],this.itemSize,this.offset,this.normalized)}toJSON(e){if(e===void 0){sa("InterleavedBufferAttribute.toJSON(): Serializing an interleaved buffer attribute will de-interleave buffer data.");const t=[];for(let n=0;n<this.count;n++){const i=n*this.data.stride+this.offset;for(let r=0;r<this.itemSize;r++)t.push(this.data.array[i+r])}return{itemSize:this.itemSize,type:this.array.constructor.name,array:t,normalized:this.normalized}}else return e.interleavedBuffers===void 0&&(e.interleavedBuffers={}),e.interleavedBuffers[this.data.uuid]===void 0&&(e.interleavedBuffers[this.data.uuid]=this.data.toJSON(e)),{isInterleavedBufferAttribute:!0,itemSize:this.itemSize,data:this.data.uuid,offset:this.offset,normalized:this.normalized}}}let hp=0;class dn extends Ni{constructor(){super(),this.isMaterial=!0,Object.defineProperty(this,"id",{value:hp++}),this.uuid=Mn(),this.name="",this.type="Material",this.blending=cs,this.side=Zn,this.vertexColors=!1,this.opacity=1,this.transparent=!1,this.alphaHash=!1,this.blendSrc=Co,this.blendDst=Po,this.blendEquation=qn,this.blendSrcAlpha=null,this.blendDstAlpha=null,this.blendEquationAlpha=null,this.blendColor=new Ie(0,0,0),this.blendAlpha=0,this.depthFunc=gs,this.depthTest=!0,this.depthWrite=!0,this.stencilWriteMask=255,this.stencilFunc=Nc,this.stencilRef=0,this.stencilFuncMask=255,this.stencilFail=Vi,this.stencilZFail=Vi,this.stencilZPass=Vi,this.stencilWrite=!1,this.clippingPlanes=null,this.clipIntersection=!1,this.clipShadows=!1,this.shadowSide=null,this.colorWrite=!0,this.precision=null,this.polygonOffset=!1,this.polygonOffsetFactor=0,this.polygonOffsetUnits=0,this.dithering=!1,this.alphaToCoverage=!1,this.premultipliedAlpha=!1,this.forceSinglePass=!1,this.allowOverride=!0,this.visible=!0,this.toneMapped=!0,this.userData={},this.version=0,this._alphaTest=0}get alphaTest(){return this._alphaTest}set alphaTest(e){this._alphaTest>0!=e>0&&this.version++,this._alphaTest=e}onBeforeRender(){}onBeforeCompile(){}customProgramCacheKey(){return this.onBeforeCompile.toString()}setValues(e){if(e!==void 0)for(const t in e){const n=e[t];if(n===void 0){Pe(`Material: parameter '${t}' has value of undefined.`);continue}const i=this[t];if(i===void 0){Pe(`Material: '${t}' is not a property of THREE.${this.type}.`);continue}i&&i.isColor?i.set(n):i&&i.isVector3&&n&&n.isVector3?i.copy(n):this[t]=n}}toJSON(e){const t=e===void 0||typeof e=="string";t&&(e={textures:{},images:{}});const n={metadata:{version:4.7,type:"Material",generator:"Material.toJSON"}};n.uuid=this.uuid,n.type=this.type,this.name!==""&&(n.name=this.name),this.color&&this.color.isColor&&(n.color=this.color.getHex()),this.roughness!==void 0&&(n.roughness=this.roughness),this.metalness!==void 0&&(n.metalness=this.metalness),this.sheen!==void 0&&(n.sheen=this.sheen),this.sheenColor&&this.sheenColor.isColor&&(n.sheenColor=this.sheenColor.getHex()),this.sheenRoughness!==void 0&&(n.sheenRoughness=this.sheenRoughness),this.emissive&&this.emissive.isColor&&(n.emissive=this.emissive.getHex()),this.emissiveIntensity!==void 0&&this.emissiveIntensity!==1&&(n.emissiveIntensity=this.emissiveIntensity),this.specular&&this.specular.isColor&&(n.specular=this.specular.getHex()),this.specularIntensity!==void 0&&(n.specularIntensity=this.specularIntensity),this.specularColor&&this.specularColor.isColor&&(n.specularColor=this.specularColor.getHex()),this.shininess!==void 0&&(n.shininess=this.shininess),this.clearcoat!==void 0&&(n.clearcoat=this.clearcoat),this.clearcoatRoughness!==void 0&&(n.clearcoatRoughness=this.clearcoatRoughness),this.clearcoatMap&&this.clearcoatMap.isTexture&&(n.clearcoatMap=this.clearcoatMap.toJSON(e).uuid),this.clearcoatRoughnessMap&&this.clearcoatRoughnessMap.isTexture&&(n.clearcoatRoughnessMap=this.clearcoatRoughnessMap.toJSON(e).uuid),this.clearcoatNormalMap&&this.clearcoatNormalMap.isTexture&&(n.clearcoatNormalMap=this.clearcoatNormalMap.toJSON(e).uuid,n.clearcoatNormalScale=this.clearcoatNormalScale.toArray()),this.sheenColorMap&&this.sheenColorMap.isTexture&&(n.sheenColorMap=this.sheenColorMap.toJSON(e).uuid),this.sheenRoughnessMap&&this.sheenRoughnessMap.isTexture&&(n.sheenRoughnessMap=this.sheenRoughnessMap.toJSON(e).uuid),this.dispersion!==void 0&&(n.dispersion=this.dispersion),this.iridescence!==void 0&&(n.iridescence=this.iridescence),this.iridescenceIOR!==void 0&&(n.iridescenceIOR=this.iridescenceIOR),this.iridescenceThicknessRange!==void 0&&(n.iridescenceThicknessRange=this.iridescenceThicknessRange),this.iridescenceMap&&this.iridescenceMap.isTexture&&(n.iridescenceMap=this.iridescenceMap.toJSON(e).uuid),this.iridescenceThicknessMap&&this.iridescenceThicknessMap.isTexture&&(n.iridescenceThicknessMap=this.iridescenceThicknessMap.toJSON(e).uuid),this.anisotropy!==void 0&&(n.anisotropy=this.anisotropy),this.anisotropyRotation!==void 0&&(n.anisotropyRotation=this.anisotropyRotation),this.anisotropyMap&&this.anisotropyMap.isTexture&&(n.anisotropyMap=this.anisotropyMap.toJSON(e).uuid),this.map&&this.map.isTexture&&(n.map=this.map.toJSON(e).uuid),this.matcap&&this.matcap.isTexture&&(n.matcap=this.matcap.toJSON(e).uuid),this.alphaMap&&this.alphaMap.isTexture&&(n.alphaMap=this.alphaMap.toJSON(e).uuid),this.lightMap&&this.lightMap.isTexture&&(n.lightMap=this.lightMap.toJSON(e).uuid,n.lightMapIntensity=this.lightMapIntensity),this.aoMap&&this.aoMap.isTexture&&(n.aoMap=this.aoMap.toJSON(e).uuid,n.aoMapIntensity=this.aoMapIntensity),this.bumpMap&&this.bumpMap.isTexture&&(n.bumpMap=this.bumpMap.toJSON(e).uuid,n.bumpScale=this.bumpScale),this.normalMap&&this.normalMap.isTexture&&(n.normalMap=this.normalMap.toJSON(e).uuid,n.normalMapType=this.normalMapType,n.normalScale=this.normalScale.toArray()),this.displacementMap&&this.displacementMap.isTexture&&(n.displacementMap=this.displacementMap.toJSON(e).uuid,n.displacementScale=this.displacementScale,n.displacementBias=this.displacementBias),this.roughnessMap&&this.roughnessMap.isTexture&&(n.roughnessMap=this.roughnessMap.toJSON(e).uuid),this.metalnessMap&&this.metalnessMap.isTexture&&(n.metalnessMap=this.metalnessMap.toJSON(e).uuid),this.emissiveMap&&this.emissiveMap.isTexture&&(n.emissiveMap=this.emissiveMap.toJSON(e).uuid),this.specularMap&&this.specularMap.isTexture&&(n.specularMap=this.specularMap.toJSON(e).uuid),this.specularIntensityMap&&this.specularIntensityMap.isTexture&&(n.specularIntensityMap=this.specularIntensityMap.toJSON(e).uuid),this.specularColorMap&&this.specularColorMap.isTexture&&(n.specularColorMap=this.specularColorMap.toJSON(e).uuid),this.envMap&&this.envMap.isTexture&&(n.envMap=this.envMap.toJSON(e).uuid,this.combine!==void 0&&(n.combine=this.combine)),this.envMapRotation!==void 0&&(n.envMapRotation=this.envMapRotation.toArray()),this.envMapIntensity!==void 0&&(n.envMapIntensity=this.envMapIntensity),this.reflectivity!==void 0&&(n.reflectivity=this.reflectivity),this.refractionRatio!==void 0&&(n.refractionRatio=this.refractionRatio),this.gradientMap&&this.gradientMap.isTexture&&(n.gradientMap=this.gradientMap.toJSON(e).uuid),this.transmission!==void 0&&(n.transmission=this.transmission),this.transmissionMap&&this.transmissionMap.isTexture&&(n.transmissionMap=this.transmissionMap.toJSON(e).uuid),this.thickness!==void 0&&(n.thickness=this.thickness),this.thicknessMap&&this.thicknessMap.isTexture&&(n.thicknessMap=this.thicknessMap.toJSON(e).uuid),this.attenuationDistance!==void 0&&this.attenuationDistance!==1/0&&(n.attenuationDistance=this.attenuationDistance),this.attenuationColor!==void 0&&(n.attenuationColor=this.attenuationColor.getHex()),this.size!==void 0&&(n.size=this.size),this.shadowSide!==null&&(n.shadowSide=this.shadowSide),this.sizeAttenuation!==void 0&&(n.sizeAttenuation=this.sizeAttenuation),this.blending!==cs&&(n.blending=this.blending),this.side!==Zn&&(n.side=this.side),this.vertexColors===!0&&(n.vertexColors=!0),this.opacity<1&&(n.opacity=this.opacity),this.transparent===!0&&(n.transparent=!0),this.blendSrc!==Co&&(n.blendSrc=this.blendSrc),this.blendDst!==Po&&(n.blendDst=this.blendDst),this.blendEquation!==qn&&(n.blendEquation=this.blendEquation),this.blendSrcAlpha!==null&&(n.blendSrcAlpha=this.blendSrcAlpha),this.blendDstAlpha!==null&&(n.blendDstAlpha=this.blendDstAlpha),this.blendEquationAlpha!==null&&(n.blendEquationAlpha=this.blendEquationAlpha),this.blendColor&&this.blendColor.isColor&&(n.blendColor=this.blendColor.getHex()),this.blendAlpha!==0&&(n.blendAlpha=this.blendAlpha),this.depthFunc!==gs&&(n.depthFunc=this.depthFunc),this.depthTest===!1&&(n.depthTest=this.depthTest),this.depthWrite===!1&&(n.depthWrite=this.depthWrite),this.colorWrite===!1&&(n.colorWrite=this.colorWrite),this.stencilWriteMask!==255&&(n.stencilWriteMask=this.stencilWriteMask),this.stencilFunc!==Nc&&(n.stencilFunc=this.stencilFunc),this.stencilRef!==0&&(n.stencilRef=this.stencilRef),this.stencilFuncMask!==255&&(n.stencilFuncMask=this.stencilFuncMask),this.stencilFail!==Vi&&(n.stencilFail=this.stencilFail),this.stencilZFail!==Vi&&(n.stencilZFail=this.stencilZFail),this.stencilZPass!==Vi&&(n.stencilZPass=this.stencilZPass),this.stencilWrite===!0&&(n.stencilWrite=this.stencilWrite),this.rotation!==void 0&&this.rotation!==0&&(n.rotation=this.rotation),this.polygonOffset===!0&&(n.polygonOffset=!0),this.polygonOffsetFactor!==0&&(n.polygonOffsetFactor=this.polygonOffsetFactor),this.polygonOffsetUnits!==0&&(n.polygonOffsetUnits=this.polygonOffsetUnits),this.linewidth!==void 0&&this.linewidth!==1&&(n.linewidth=this.linewidth),this.dashSize!==void 0&&(n.dashSize=this.dashSize),this.gapSize!==void 0&&(n.gapSize=this.gapSize),this.scale!==void 0&&(n.scale=this.scale),this.dithering===!0&&(n.dithering=!0),this.alphaTest>0&&(n.alphaTest=this.alphaTest),this.alphaHash===!0&&(n.alphaHash=!0),this.alphaToCoverage===!0&&(n.alphaToCoverage=!0),this.premultipliedAlpha===!0&&(n.premultipliedAlpha=!0),this.forceSinglePass===!0&&(n.forceSinglePass=!0),this.allowOverride===!1&&(n.allowOverride=!1),this.wireframe===!0&&(n.wireframe=!0),this.wireframeLinewidth>1&&(n.wireframeLinewidth=this.wireframeLinewidth),this.wireframeLinecap!=="round"&&(n.wireframeLinecap=this.wireframeLinecap),this.wireframeLinejoin!=="round"&&(n.wireframeLinejoin=this.wireframeLinejoin),this.flatShading===!0&&(n.flatShading=!0),this.visible===!1&&(n.visible=!1),this.toneMapped===!1&&(n.toneMapped=!1),this.fog===!1&&(n.fog=!1),Object.keys(this.userData).length>0&&(n.userData=this.userData);function i(r){const a=[];for(const o in r){const l=r[o];delete l.metadata,a.push(l)}return a}if(t){const r=i(e.textures),a=i(e.images);r.length>0&&(n.textures=r),a.length>0&&(n.images=a)}return n}clone(){return new this.constructor().copy(this)}copy(e){this.name=e.name,this.blending=e.blending,this.side=e.side,this.vertexColors=e.vertexColors,this.opacity=e.opacity,this.transparent=e.transparent,this.blendSrc=e.blendSrc,this.blendDst=e.blendDst,this.blendEquation=e.blendEquation,this.blendSrcAlpha=e.blendSrcAlpha,this.blendDstAlpha=e.blendDstAlpha,this.blendEquationAlpha=e.blendEquationAlpha,this.blendColor.copy(e.blendColor),this.blendAlpha=e.blendAlpha,this.depthFunc=e.depthFunc,this.depthTest=e.depthTest,this.depthWrite=e.depthWrite,this.stencilWriteMask=e.stencilWriteMask,this.stencilFunc=e.stencilFunc,this.stencilRef=e.stencilRef,this.stencilFuncMask=e.stencilFuncMask,this.stencilFail=e.stencilFail,this.stencilZFail=e.stencilZFail,this.stencilZPass=e.stencilZPass,this.stencilWrite=e.stencilWrite;const t=e.clippingPlanes;let n=null;if(t!==null){const i=t.length;n=new Array(i);for(let r=0;r!==i;++r)n[r]=t[r].clone()}return this.clippingPlanes=n,this.clipIntersection=e.clipIntersection,this.clipShadows=e.clipShadows,this.shadowSide=e.shadowSide,this.colorWrite=e.colorWrite,this.precision=e.precision,this.polygonOffset=e.polygonOffset,this.polygonOffsetFactor=e.polygonOffsetFactor,this.polygonOffsetUnits=e.polygonOffsetUnits,this.dithering=e.dithering,this.alphaTest=e.alphaTest,this.alphaHash=e.alphaHash,this.alphaToCoverage=e.alphaToCoverage,this.premultipliedAlpha=e.premultipliedAlpha,this.forceSinglePass=e.forceSinglePass,this.allowOverride=e.allowOverride,this.visible=e.visible,this.toneMapped=e.toneMapped,this.userData=JSON.parse(JSON.stringify(e.userData)),this}dispose(){this.dispatchEvent({type:"dispose"})}set needsUpdate(e){e===!0&&this.version++}}const Xn=new L,Qa=new L,vr=new L,oi=new L,eo=new L,xr=new L,to=new L;class Rs{constructor(e=new L,t=new L(0,0,-1)){this.origin=e,this.direction=t}set(e,t){return this.origin.copy(e),this.direction.copy(t),this}copy(e){return this.origin.copy(e.origin),this.direction.copy(e.direction),this}at(e,t){return t.copy(this.origin).addScaledVector(this.direction,e)}lookAt(e){return this.direction.copy(e).sub(this.origin).normalize(),this}recast(e){return this.origin.copy(this.at(e,Xn)),this}closestPointToPoint(e,t){t.subVectors(e,this.origin);const n=t.dot(this.direction);return n<0?t.copy(this.origin):t.copy(this.origin).addScaledVector(this.direction,n)}distanceToPoint(e){return Math.sqrt(this.distanceSqToPoint(e))}distanceSqToPoint(e){const t=Xn.subVectors(e,this.origin).dot(this.direction);return t<0?this.origin.distanceToSquared(e):(Xn.copy(this.origin).addScaledVector(this.direction,t),Xn.distanceToSquared(e))}distanceSqToSegment(e,t,n,i){Qa.copy(e).add(t).multiplyScalar(.5),vr.copy(t).sub(e).normalize(),oi.copy(this.origin).sub(Qa);const r=e.distanceTo(t)*.5,a=-this.direction.dot(vr),o=oi.dot(this.direction),l=-oi.dot(vr),c=oi.lengthSq(),h=Math.abs(1-a*a);let u,d,f,g;if(h>0)if(u=a*l-o,d=a*o-l,g=r*h,u>=0)if(d>=-g)if(d<=g){const x=1/h;u*=x,d*=x,f=u*(u+a*d+2*o)+d*(a*u+d+2*l)+c}else d=r,u=Math.max(0,-(a*d+o)),f=-u*u+d*(d+2*l)+c;else d=-r,u=Math.max(0,-(a*d+o)),f=-u*u+d*(d+2*l)+c;else d<=-g?(u=Math.max(0,-(-a*r+o)),d=u>0?-r:Math.min(Math.max(-r,-l),r),f=-u*u+d*(d+2*l)+c):d<=g?(u=0,d=Math.min(Math.max(-r,-l),r),f=d*(d+2*l)+c):(u=Math.max(0,-(a*r+o)),d=u>0?r:Math.min(Math.max(-r,-l),r),f=-u*u+d*(d+2*l)+c);else d=a>0?-r:r,u=Math.max(0,-(a*d+o)),f=-u*u+d*(d+2*l)+c;return n&&n.copy(this.origin).addScaledVector(this.direction,u),i&&i.copy(Qa).addScaledVector(vr,d),f}intersectSphere(e,t){Xn.subVectors(e.center,this.origin);const n=Xn.dot(this.direction),i=Xn.dot(Xn)-n*n,r=e.radius*e.radius;if(i>r)return null;const a=Math.sqrt(r-i),o=n-a,l=n+a;return l<0?null:o<0?this.at(l,t):this.at(o,t)}intersectsSphere(e){return e.radius<0?!1:this.distanceSqToPoint(e.center)<=e.radius*e.radius}distanceToPlane(e){const t=e.normal.dot(this.direction);if(t===0)return e.distanceToPoint(this.origin)===0?0:null;const n=-(this.origin.dot(e.normal)+e.constant)/t;return n>=0?n:null}intersectPlane(e,t){const n=this.distanceToPlane(e);return n===null?null:this.at(n,t)}intersectsPlane(e){const t=e.distanceToPoint(this.origin);return t===0||e.normal.dot(this.direction)*t<0}intersectBox(e,t){let n,i,r,a,o,l;const c=1/this.direction.x,h=1/this.direction.y,u=1/this.direction.z,d=this.origin;return c>=0?(n=(e.min.x-d.x)*c,i=(e.max.x-d.x)*c):(n=(e.max.x-d.x)*c,i=(e.min.x-d.x)*c),h>=0?(r=(e.min.y-d.y)*h,a=(e.max.y-d.y)*h):(r=(e.max.y-d.y)*h,a=(e.min.y-d.y)*h),n>a||r>i||((r>n||isNaN(n))&&(n=r),(a<i||isNaN(i))&&(i=a),u>=0?(o=(e.min.z-d.z)*u,l=(e.max.z-d.z)*u):(o=(e.max.z-d.z)*u,l=(e.min.z-d.z)*u),n>l||o>i)||((o>n||n!==n)&&(n=o),(l<i||i!==i)&&(i=l),i<0)?null:this.at(n>=0?n:i,t)}intersectsBox(e){return this.intersectBox(e,Xn)!==null}intersectTriangle(e,t,n,i,r){eo.subVectors(t,e),xr.subVectors(n,e),to.crossVectors(eo,xr);let a=this.direction.dot(to),o;if(a>0){if(i)return null;o=1}else if(a<0)o=-1,a=-a;else return null;oi.subVectors(this.origin,e);const l=o*this.direction.dot(xr.crossVectors(oi,xr));if(l<0)return null;const c=o*this.direction.dot(eo.cross(oi));if(c<0||l+c>a)return null;const h=-o*oi.dot(to);return h<0?null:this.at(h/a,r)}applyMatrix4(e){return this.origin.applyMatrix4(e),this.direction.transformDirection(e),this}equals(e){return e.origin.equals(this.origin)&&e.direction.equals(this.direction)}clone(){return new this.constructor().copy(this)}}class Nn extends dn{constructor(e){super(),this.isMeshBasicMaterial=!0,this.type="MeshBasicMaterial",this.color=new Ie(16777215),this.map=null,this.lightMap=null,this.lightMapIntensity=1,this.aoMap=null,this.aoMapIntensity=1,this.specularMap=null,this.alphaMap=null,this.envMap=null,this.envMapRotation=new Sn,this.combine=Il,this.reflectivity=1,this.refractionRatio=.98,this.wireframe=!1,this.wireframeLinewidth=1,this.wireframeLinecap="round",this.wireframeLinejoin="round",this.fog=!0,this.setValues(e)}copy(e){return super.copy(e),this.color.copy(e.color),this.map=e.map,this.lightMap=e.lightMap,this.lightMapIntensity=e.lightMapIntensity,this.aoMap=e.aoMap,this.aoMapIntensity=e.aoMapIntensity,this.specularMap=e.specularMap,this.alphaMap=e.alphaMap,this.envMap=e.envMap,this.envMapRotation.copy(e.envMapRotation),this.combine=e.combine,this.reflectivity=e.reflectivity,this.refractionRatio=e.refractionRatio,this.wireframe=e.wireframe,this.wireframeLinewidth=e.wireframeLinewidth,this.wireframeLinecap=e.wireframeLinecap,this.wireframeLinejoin=e.wireframeLinejoin,this.fog=e.fog,this}}const Kc=new Ve,bi=new Rs,Mr=new On,$c=new L,yr=new L,Sr=new L,br=new L,no=new L,Er=new L,Zc=new L,Tr=new L;class lt extends ft{constructor(e=new ln,t=new Nn){super(),this.isMesh=!0,this.type="Mesh",this.geometry=e,this.material=t,this.morphTargetDictionary=void 0,this.morphTargetInfluences=void 0,this.count=1,this.updateMorphTargets()}copy(e,t){return super.copy(e,t),e.morphTargetInfluences!==void 0&&(this.morphTargetInfluences=e.morphTargetInfluences.slice()),e.morphTargetDictionary!==void 0&&(this.morphTargetDictionary=Object.assign({},e.morphTargetDictionary)),this.material=Array.isArray(e.material)?e.material.slice():e.material,this.geometry=e.geometry,this}updateMorphTargets(){const t=this.geometry.morphAttributes,n=Object.keys(t);if(n.length>0){const i=t[n[0]];if(i!==void 0){this.morphTargetInfluences=[],this.morphTargetDictionary={};for(let r=0,a=i.length;r<a;r++){const o=i[r].name||String(r);this.morphTargetInfluences.push(0),this.morphTargetDictionary[o]=r}}}}getVertexPosition(e,t){const n=this.geometry,i=n.attributes.position,r=n.morphAttributes.position,a=n.morphTargetsRelative;t.fromBufferAttribute(i,e);const o=this.morphTargetInfluences;if(r&&o){Er.set(0,0,0);for(let l=0,c=r.length;l<c;l++){const h=o[l],u=r[l];h!==0&&(no.fromBufferAttribute(u,e),a?Er.addScaledVector(no,h):Er.addScaledVector(no.sub(t),h))}t.add(Er)}return t}raycast(e,t){const n=this.geometry,i=this.material,r=this.matrixWorld;i!==void 0&&(n.boundingSphere===null&&n.computeBoundingSphere(),Mr.copy(n.boundingSphere),Mr.applyMatrix4(r),bi.copy(e.ray).recast(e.near),!(Mr.containsPoint(bi.origin)===!1&&(bi.intersectSphere(Mr,$c)===null||bi.origin.distanceToSquared($c)>(e.far-e.near)**2))&&(Kc.copy(r).invert(),bi.copy(e.ray).applyMatrix4(Kc),!(n.boundingBox!==null&&bi.intersectsBox(n.boundingBox)===!1)&&this._computeIntersections(e,t,bi)))}_computeIntersections(e,t,n){let i;const r=this.geometry,a=this.material,o=r.index,l=r.attributes.position,c=r.attributes.uv,h=r.attributes.uv1,u=r.attributes.normal,d=r.groups,f=r.drawRange;if(o!==null)if(Array.isArray(a))for(let g=0,x=d.length;g<x;g++){const p=d[g],m=a[p.materialIndex],S=Math.max(p.start,f.start),T=Math.min(o.count,Math.min(p.start+p.count,f.start+f.count));for(let M=S,E=T;M<E;M+=3){const w=o.getX(M),C=o.getX(M+1),v=o.getX(M+2);i=Ar(this,m,e,n,c,h,u,w,C,v),i&&(i.faceIndex=Math.floor(M/3),i.face.materialIndex=p.materialIndex,t.push(i))}}else{const g=Math.max(0,f.start),x=Math.min(o.count,f.start+f.count);for(let p=g,m=x;p<m;p+=3){const S=o.getX(p),T=o.getX(p+1),M=o.getX(p+2);i=Ar(this,a,e,n,c,h,u,S,T,M),i&&(i.faceIndex=Math.floor(p/3),t.push(i))}}else if(l!==void 0)if(Array.isArray(a))for(let g=0,x=d.length;g<x;g++){const p=d[g],m=a[p.materialIndex],S=Math.max(p.start,f.start),T=Math.min(l.count,Math.min(p.start+p.count,f.start+f.count));for(let M=S,E=T;M<E;M+=3){const w=M,C=M+1,v=M+2;i=Ar(this,m,e,n,c,h,u,w,C,v),i&&(i.faceIndex=Math.floor(M/3),i.face.materialIndex=p.materialIndex,t.push(i))}}else{const g=Math.max(0,f.start),x=Math.min(l.count,f.start+f.count);for(let p=g,m=x;p<m;p+=3){const S=p,T=p+1,M=p+2;i=Ar(this,a,e,n,c,h,u,S,T,M),i&&(i.faceIndex=Math.floor(p/3),t.push(i))}}}}function up(s,e,t,n,i,r,a,o){let l;if(e.side===qt?l=n.intersectTriangle(a,r,i,!0,o):l=n.intersectTriangle(i,r,a,e.side===Zn,o),l===null)return null;Tr.copy(o),Tr.applyMatrix4(s.matrixWorld);const c=t.ray.origin.distanceTo(Tr);return c<t.near||c>t.far?null:{distance:c,point:Tr.clone(),object:s}}function Ar(s,e,t,n,i,r,a,o,l,c){s.getVertexPosition(o,yr),s.getVertexPosition(l,Sr),s.getVertexPosition(c,br);const h=up(s,e,t,n,yr,Sr,br,Zc);if(h){const u=new L;vn.getBarycoord(Zc,yr,Sr,br,u),i&&(h.uv=vn.getInterpolatedAttribute(i,o,l,c,u,new Le)),r&&(h.uv1=vn.getInterpolatedAttribute(r,o,l,c,u,new Le)),a&&(h.normal=vn.getInterpolatedAttribute(a,o,l,c,u,new L),h.normal.dot(n.direction)>0&&h.normal.multiplyScalar(-1));const d={a:o,b:l,c,normal:new L,materialIndex:0};vn.getNormal(yr,Sr,br,d.normal),h.face=d,h.barycoord=u}return h}const Jc=new L,Qc=new mt,eh=new mt,dp=new L,th=new Ve,wr=new L,io=new On,nh=new Ve,so=new Rs;class fp extends lt{constructor(e,t){super(e,t),this.isSkinnedMesh=!0,this.type="SkinnedMesh",this.bindMode=Cc,this.bindMatrix=new Ve,this.bindMatrixInverse=new Ve,this.boundingBox=null,this.boundingSphere=null}computeBoundingBox(){const e=this.geometry;this.boundingBox===null&&(this.boundingBox=new Qn),this.boundingBox.makeEmpty();const t=e.getAttribute("position");for(let n=0;n<t.count;n++)this.getVertexPosition(n,wr),this.boundingBox.expandByPoint(wr)}computeBoundingSphere(){const e=this.geometry;this.boundingSphere===null&&(this.boundingSphere=new On),this.boundingSphere.makeEmpty();const t=e.getAttribute("position");for(let n=0;n<t.count;n++)this.getVertexPosition(n,wr),this.boundingSphere.expandByPoint(wr)}copy(e,t){return super.copy(e,t),this.bindMode=e.bindMode,this.bindMatrix.copy(e.bindMatrix),this.bindMatrixInverse.copy(e.bindMatrixInverse),this.skeleton=e.skeleton,e.boundingBox!==null&&(this.boundingBox=e.boundingBox.clone()),e.boundingSphere!==null&&(this.boundingSphere=e.boundingSphere.clone()),this}raycast(e,t){const n=this.material,i=this.matrixWorld;n!==void 0&&(this.boundingSphere===null&&this.computeBoundingSphere(),io.copy(this.boundingSphere),io.applyMatrix4(i),e.ray.intersectsSphere(io)!==!1&&(nh.copy(i).invert(),so.copy(e.ray).applyMatrix4(nh),!(this.boundingBox!==null&&so.intersectsBox(this.boundingBox)===!1)&&this._computeIntersections(e,t,so)))}getVertexPosition(e,t){return super.getVertexPosition(e,t),this.applyBoneTransform(e,t),t}bind(e,t){this.skeleton=e,t===void 0&&(this.updateMatrixWorld(!0),this.skeleton.calculateInverses(),t=this.matrixWorld),this.bindMatrix.copy(t),this.bindMatrixInverse.copy(t).invert()}pose(){this.skeleton.pose()}normalizeSkinWeights(){const e=new mt,t=this.geometry.attributes.skinWeight;for(let n=0,i=t.count;n<i;n++){e.fromBufferAttribute(t,n);const r=1/e.manhattanLength();r!==1/0?e.multiplyScalar(r):e.set(1,0,0,0),t.setXYZW(n,e.x,e.y,e.z,e.w)}}updateMatrixWorld(e){super.updateMatrixWorld(e),this.bindMode===Cc?this.bindMatrixInverse.copy(this.matrixWorld).invert():this.bindMode===ff?this.bindMatrixInverse.copy(this.bindMatrix).invert():Pe("SkinnedMesh: Unrecognized bindMode: "+this.bindMode)}applyBoneTransform(e,t){const n=this.skeleton,i=this.geometry;Qc.fromBufferAttribute(i.attributes.skinIndex,e),eh.fromBufferAttribute(i.attributes.skinWeight,e),Jc.copy(t).applyMatrix4(this.bindMatrix),t.set(0,0,0);for(let r=0;r<4;r++){const a=eh.getComponent(r);if(a!==0){const o=Qc.getComponent(r);th.multiplyMatrices(n.bones[o].matrixWorld,n.boneInverses[o]),t.addScaledVector(dp.copy(Jc).applyMatrix4(th),a)}}return t.applyMatrix4(this.bindMatrixInverse)}}class wu extends ft{constructor(){super(),this.isBone=!0,this.type="Bone"}}class va extends Pt{constructor(e=null,t=1,n=1,i,r,a,o,l,c=xt,h=xt,u,d){super(null,a,o,l,c,h,i,r,u,d),this.isDataTexture=!0,this.image={data:e,width:t,height:n},this.generateMipmaps=!1,this.flipY=!1,this.unpackAlignment=1}}const ih=new Ve,pp=new Ve;class Ql{constructor(e=[],t=[]){this.uuid=Mn(),this.bones=e.slice(0),this.boneInverses=t,this.boneMatrices=null,this.previousBoneMatrices=null,this.boneTexture=null,this.init()}init(){const e=this.bones,t=this.boneInverses;if(this.boneMatrices=new Float32Array(e.length*16),t.length===0)this.calculateInverses();else if(e.length!==t.length){Pe("Skeleton: Number of inverse bone matrices does not match amount of bones."),this.boneInverses=[];for(let n=0,i=this.bones.length;n<i;n++)this.boneInverses.push(new Ve)}}calculateInverses(){this.boneInverses.length=0;for(let e=0,t=this.bones.length;e<t;e++){const n=new Ve;this.bones[e]&&n.copy(this.bones[e].matrixWorld).invert(),this.boneInverses.push(n)}}pose(){for(let e=0,t=this.bones.length;e<t;e++){const n=this.bones[e];n&&n.matrixWorld.copy(this.boneInverses[e]).invert()}for(let e=0,t=this.bones.length;e<t;e++){const n=this.bones[e];n&&(n.parent&&n.parent.isBone?(n.matrix.copy(n.parent.matrixWorld).invert(),n.matrix.multiply(n.matrixWorld)):n.matrix.copy(n.matrixWorld),n.matrix.decompose(n.position,n.quaternion,n.scale))}}update(){const e=this.bones,t=this.boneInverses,n=this.boneMatrices,i=this.boneTexture;for(let r=0,a=e.length;r<a;r++){const o=e[r]?e[r].matrixWorld:pp;ih.multiplyMatrices(o,t[r]),ih.toArray(n,r*16)}i!==null&&(i.needsUpdate=!0)}clone(){return new Ql(this.bones,this.boneInverses)}computeBoneTexture(){let e=Math.sqrt(this.bones.length*4);e=Math.ceil(e/4)*4,e=Math.max(e,4);const t=new Float32Array(e*e*4);t.set(this.boneMatrices);const n=new va(t,e,e,un,sn);return n.needsUpdate=!0,this.boneMatrices=t,this.boneTexture=n,this}getBoneByName(e){for(let t=0,n=this.bones.length;t<n;t++){const i=this.bones[t];if(i.name===e)return i}}dispose(){this.boneTexture!==null&&(this.boneTexture.dispose(),this.boneTexture=null)}fromJSON(e,t){this.uuid=e.uuid;for(let n=0,i=e.bones.length;n<i;n++){const r=e.bones[n];let a=t[r];a===void 0&&(Pe("Skeleton: No bone found with UUID:",r),a=new wu),this.bones.push(a),this.boneInverses.push(new Ve().fromArray(e.boneInverses[n]))}return this.init(),this}toJSON(){const e={metadata:{version:4.7,type:"Skeleton",generator:"Skeleton.toJSON"},bones:[],boneInverses:[]};e.uuid=this.uuid;const t=this.bones,n=this.boneInverses;for(let i=0,r=t.length;i<r;i++){const a=t[i];e.bones.push(a.uuid);const o=n[i];e.boneInverses.push(o.toArray())}return e}}class vl extends jt{constructor(e,t,n,i=1){super(e,t,n),this.isInstancedBufferAttribute=!0,this.meshPerAttribute=i}copy(e){return super.copy(e),this.meshPerAttribute=e.meshPerAttribute,this}toJSON(){const e=super.toJSON();return e.meshPerAttribute=this.meshPerAttribute,e.isInstancedBufferAttribute=!0,e}}const Zi=new Ve,sh=new Ve,Rr=[],rh=new Qn,mp=new Ve,Vs=new lt,zs=new On;class ec extends lt{constructor(e,t,n){super(e,t),this.isInstancedMesh=!0,this.instanceMatrix=new vl(new Float32Array(n*16),16),this.previousInstanceMatrix=null,this.instanceColor=null,this.morphTexture=null,this.count=n,this.boundingBox=null,this.boundingSphere=null;for(let i=0;i<n;i++)this.setMatrixAt(i,mp)}computeBoundingBox(){const e=this.geometry,t=this.count;this.boundingBox===null&&(this.boundingBox=new Qn),e.boundingBox===null&&e.computeBoundingBox(),this.boundingBox.makeEmpty();for(let n=0;n<t;n++)this.getMatrixAt(n,Zi),rh.copy(e.boundingBox).applyMatrix4(Zi),this.boundingBox.union(rh)}computeBoundingSphere(){const e=this.geometry,t=this.count;this.boundingSphere===null&&(this.boundingSphere=new On),e.boundingSphere===null&&e.computeBoundingSphere(),this.boundingSphere.makeEmpty();for(let n=0;n<t;n++)this.getMatrixAt(n,Zi),zs.copy(e.boundingSphere).applyMatrix4(Zi),this.boundingSphere.union(zs)}copy(e,t){return super.copy(e,t),this.instanceMatrix.copy(e.instanceMatrix),e.previousInstanceMatrix!==null&&(this.previousInstanceMatrix=e.previousInstanceMatrix.clone()),e.morphTexture!==null&&(this.morphTexture=e.morphTexture.clone()),e.instanceColor!==null&&(this.instanceColor=e.instanceColor.clone()),this.count=e.count,e.boundingBox!==null&&(this.boundingBox=e.boundingBox.clone()),e.boundingSphere!==null&&(this.boundingSphere=e.boundingSphere.clone()),this}getColorAt(e,t){t.fromArray(this.instanceColor.array,e*3)}getMatrixAt(e,t){t.fromArray(this.instanceMatrix.array,e*16)}getMorphAt(e,t){const n=t.morphTargetInfluences,i=this.morphTexture.source.data.data,r=n.length+1,a=e*r+1;for(let o=0;o<n.length;o++)n[o]=i[a+o]}raycast(e,t){const n=this.matrixWorld,i=this.count;if(Vs.geometry=this.geometry,Vs.material=this.material,Vs.material!==void 0&&(this.boundingSphere===null&&this.computeBoundingSphere(),zs.copy(this.boundingSphere),zs.applyMatrix4(n),e.ray.intersectsSphere(zs)!==!1))for(let r=0;r<i;r++){this.getMatrixAt(r,Zi),sh.multiplyMatrices(n,Zi),Vs.matrixWorld=sh,Vs.raycast(e,Rr);for(let a=0,o=Rr.length;a<o;a++){const l=Rr[a];l.instanceId=r,l.object=this,t.push(l)}Rr.length=0}}setColorAt(e,t){this.instanceColor===null&&(this.instanceColor=new vl(new Float32Array(this.instanceMatrix.count*3).fill(1),3)),t.toArray(this.instanceColor.array,e*3)}setMatrixAt(e,t){t.toArray(this.instanceMatrix.array,e*16)}setMorphAt(e,t){const n=t.morphTargetInfluences,i=n.length+1;this.morphTexture===null&&(this.morphTexture=new va(new Float32Array(i*this.count),i,this.count,ma,sn));const r=this.morphTexture.source.data.data;let a=0;for(let c=0;c<n.length;c++)a+=n[c];const o=this.geometry.morphTargetsRelative?1:1-a,l=i*e;r[l]=o,r.set(n,l+1)}updateMorphTargets(){}dispose(){this.dispatchEvent({type:"dispose"}),this.morphTexture!==null&&(this.morphTexture.dispose(),this.morphTexture=null)}}const ro=new L,gp=new L,_p=new He;class ui{constructor(e=new L(1,0,0),t=0){this.isPlane=!0,this.normal=e,this.constant=t}set(e,t){return this.normal.copy(e),this.constant=t,this}setComponents(e,t,n,i){return this.normal.set(e,t,n),this.constant=i,this}setFromNormalAndCoplanarPoint(e,t){return this.normal.copy(e),this.constant=-t.dot(this.normal),this}setFromCoplanarPoints(e,t,n){const i=ro.subVectors(n,t).cross(gp.subVectors(e,t)).normalize();return this.setFromNormalAndCoplanarPoint(i,e),this}copy(e){return this.normal.copy(e.normal),this.constant=e.constant,this}normalize(){const e=1/this.normal.length();return this.normal.multiplyScalar(e),this.constant*=e,this}negate(){return this.constant*=-1,this.normal.negate(),this}distanceToPoint(e){return this.normal.dot(e)+this.constant}distanceToSphere(e){return this.distanceToPoint(e.center)-e.radius}projectPoint(e,t){return t.copy(e).addScaledVector(this.normal,-this.distanceToPoint(e))}intersectLine(e,t){const n=e.delta(ro),i=this.normal.dot(n);if(i===0)return this.distanceToPoint(e.start)===0?t.copy(e.start):null;const r=-(e.start.dot(this.normal)+this.constant)/i;return r<0||r>1?null:t.copy(e.start).addScaledVector(n,r)}intersectsLine(e){const t=this.distanceToPoint(e.start),n=this.distanceToPoint(e.end);return t<0&&n>0||n<0&&t>0}intersectsBox(e){return e.intersectsPlane(this)}intersectsSphere(e){return e.intersectsPlane(this)}coplanarPoint(e){return e.copy(this.normal).multiplyScalar(-this.constant)}applyMatrix4(e,t){const n=t||_p.getNormalMatrix(e),i=this.coplanarPoint(ro).applyMatrix4(e),r=this.normal.applyMatrix3(n).normalize();return this.constant=-i.dot(r),this}translate(e){return this.constant-=e.dot(this.normal),this}equals(e){return e.normal.equals(this.normal)&&e.constant===this.constant}clone(){return new this.constructor().copy(this)}}const Ei=new On,vp=new Le(.5,.5),Cr=new L;class tc{constructor(e=new ui,t=new ui,n=new ui,i=new ui,r=new ui,a=new ui){this.planes=[e,t,n,i,r,a]}set(e,t,n,i,r,a){const o=this.planes;return o[0].copy(e),o[1].copy(t),o[2].copy(n),o[3].copy(i),o[4].copy(r),o[5].copy(a),this}copy(e){const t=this.planes;for(let n=0;n<6;n++)t[n].copy(e.planes[n]);return this}setFromProjectionMatrix(e,t=Ln,n=!1){const i=this.planes,r=e.elements,a=r[0],o=r[1],l=r[2],c=r[3],h=r[4],u=r[5],d=r[6],f=r[7],g=r[8],x=r[9],p=r[10],m=r[11],S=r[12],T=r[13],M=r[14],E=r[15];if(i[0].setComponents(c-a,f-h,m-g,E-S).normalize(),i[1].setComponents(c+a,f+h,m+g,E+S).normalize(),i[2].setComponents(c+o,f+u,m+x,E+T).normalize(),i[3].setComponents(c-o,f-u,m-x,E-T).normalize(),n)i[4].setComponents(l,d,p,M).normalize(),i[5].setComponents(c-l,f-d,m-p,E-M).normalize();else if(i[4].setComponents(c-l,f-d,m-p,E-M).normalize(),t===Ln)i[5].setComponents(c+l,f+d,m+p,E+M).normalize();else if(t===nr)i[5].setComponents(l,d,p,M).normalize();else throw new Error("THREE.Frustum.setFromProjectionMatrix(): Invalid coordinate system: "+t);return this}intersectsObject(e){if(e.boundingSphere!==void 0)e.boundingSphere===null&&e.computeBoundingSphere(),Ei.copy(e.boundingSphere).applyMatrix4(e.matrixWorld);else{const t=e.geometry;t.boundingSphere===null&&t.computeBoundingSphere(),Ei.copy(t.boundingSphere).applyMatrix4(e.matrixWorld)}return this.intersectsSphere(Ei)}intersectsSprite(e){Ei.center.set(0,0,0);const t=vp.distanceTo(e.center);return Ei.radius=.7071067811865476+t,Ei.applyMatrix4(e.matrixWorld),this.intersectsSphere(Ei)}intersectsSphere(e){const t=this.planes,n=e.center,i=-e.radius;for(let r=0;r<6;r++)if(t[r].distanceToPoint(n)<i)return!1;return!0}intersectsBox(e){const t=this.planes;for(let n=0;n<6;n++){const i=t[n];if(Cr.x=i.normal.x>0?e.max.x:e.min.x,Cr.y=i.normal.y>0?e.max.y:e.min.y,Cr.z=i.normal.z>0?e.max.z:e.min.z,i.distanceToPoint(Cr)<0)return!1}return!0}containsPoint(e){const t=this.planes;for(let n=0;n<6;n++)if(t[n].distanceToPoint(e)<0)return!1;return!0}clone(){return new this.constructor().copy(this)}}class Ru extends dn{constructor(e){super(),this.isLineBasicMaterial=!0,this.type="LineBasicMaterial",this.color=new Ie(16777215),this.map=null,this.linewidth=1,this.linecap="round",this.linejoin="round",this.fog=!0,this.setValues(e)}copy(e){return super.copy(e),this.color.copy(e.color),this.map=e.map,this.linewidth=e.linewidth,this.linecap=e.linecap,this.linejoin=e.linejoin,this.fog=e.fog,this}}const aa=new L,oa=new L,ah=new Ve,Hs=new Rs,Pr=new On,ao=new L,oh=new L;class nc extends ft{constructor(e=new ln,t=new Ru){super(),this.isLine=!0,this.type="Line",this.geometry=e,this.material=t,this.morphTargetDictionary=void 0,this.morphTargetInfluences=void 0,this.updateMorphTargets()}copy(e,t){return super.copy(e,t),this.material=Array.isArray(e.material)?e.material.slice():e.material,this.geometry=e.geometry,this}computeLineDistances(){const e=this.geometry;if(e.index===null){const t=e.attributes.position,n=[0];for(let i=1,r=t.count;i<r;i++)aa.fromBufferAttribute(t,i-1),oa.fromBufferAttribute(t,i),n[i]=n[i-1],n[i]+=aa.distanceTo(oa);e.setAttribute("lineDistance",new an(n,1))}else Pe("Line.computeLineDistances(): Computation only possible with non-indexed BufferGeometry.");return this}raycast(e,t){const n=this.geometry,i=this.matrixWorld,r=e.params.Line.threshold,a=n.drawRange;if(n.boundingSphere===null&&n.computeBoundingSphere(),Pr.copy(n.boundingSphere),Pr.applyMatrix4(i),Pr.radius+=r,e.ray.intersectsSphere(Pr)===!1)return;ah.copy(i).invert(),Hs.copy(e.ray).applyMatrix4(ah);const o=r/((this.scale.x+this.scale.y+this.scale.z)/3),l=o*o,c=this.isLineSegments?2:1,h=n.index,d=n.attributes.position;if(h!==null){const f=Math.max(0,a.start),g=Math.min(h.count,a.start+a.count);for(let x=f,p=g-1;x<p;x+=c){const m=h.getX(x),S=h.getX(x+1),T=Dr(this,e,Hs,l,m,S,x);T&&t.push(T)}if(this.isLineLoop){const x=h.getX(g-1),p=h.getX(f),m=Dr(this,e,Hs,l,x,p,g-1);m&&t.push(m)}}else{const f=Math.max(0,a.start),g=Math.min(d.count,a.start+a.count);for(let x=f,p=g-1;x<p;x+=c){const m=Dr(this,e,Hs,l,x,x+1,x);m&&t.push(m)}if(this.isLineLoop){const x=Dr(this,e,Hs,l,g-1,f,g-1);x&&t.push(x)}}}updateMorphTargets(){const t=this.geometry.morphAttributes,n=Object.keys(t);if(n.length>0){const i=t[n[0]];if(i!==void 0){this.morphTargetInfluences=[],this.morphTargetDictionary={};for(let r=0,a=i.length;r<a;r++){const o=i[r].name||String(r);this.morphTargetInfluences.push(0),this.morphTargetDictionary[o]=r}}}}}function Dr(s,e,t,n,i,r,a){const o=s.geometry.attributes.position;if(aa.fromBufferAttribute(o,i),oa.fromBufferAttribute(o,r),t.distanceSqToSegment(aa,oa,ao,oh)>n)return;ao.applyMatrix4(s.matrixWorld);const c=e.ray.origin.distanceTo(ao);if(!(c<e.near||c>e.far))return{distance:c,point:oh.clone().applyMatrix4(s.matrixWorld),index:a,face:null,faceIndex:null,barycoord:null,object:s}}const lh=new L,ch=new L;class xp extends nc{constructor(e,t){super(e,t),this.isLineSegments=!0,this.type="LineSegments"}computeLineDistances(){const e=this.geometry;if(e.index===null){const t=e.attributes.position,n=[];for(let i=0,r=t.count;i<r;i+=2)lh.fromBufferAttribute(t,i),ch.fromBufferAttribute(t,i+1),n[i]=i===0?0:n[i-1],n[i+1]=n[i]+lh.distanceTo(ch);e.setAttribute("lineDistance",new an(n,1))}else Pe("LineSegments.computeLineDistances(): Computation only possible with non-indexed BufferGeometry.");return this}}class Mp extends nc{constructor(e,t){super(e,t),this.isLineLoop=!0,this.type="LineLoop"}}class Cu extends dn{constructor(e){super(),this.isPointsMaterial=!0,this.type="PointsMaterial",this.color=new Ie(16777215),this.map=null,this.alphaMap=null,this.size=1,this.sizeAttenuation=!0,this.fog=!0,this.setValues(e)}copy(e){return super.copy(e),this.color.copy(e.color),this.map=e.map,this.alphaMap=e.alphaMap,this.size=e.size,this.sizeAttenuation=e.sizeAttenuation,this.fog=e.fog,this}}const hh=new Ve,xl=new Rs,Lr=new On,Ir=new L;class yp extends ft{constructor(e=new ln,t=new Cu){super(),this.isPoints=!0,this.type="Points",this.geometry=e,this.material=t,this.morphTargetDictionary=void 0,this.morphTargetInfluences=void 0,this.updateMorphTargets()}copy(e,t){return super.copy(e,t),this.material=Array.isArray(e.material)?e.material.slice():e.material,this.geometry=e.geometry,this}raycast(e,t){const n=this.geometry,i=this.matrixWorld,r=e.params.Points.threshold,a=n.drawRange;if(n.boundingSphere===null&&n.computeBoundingSphere(),Lr.copy(n.boundingSphere),Lr.applyMatrix4(i),Lr.radius+=r,e.ray.intersectsSphere(Lr)===!1)return;hh.copy(i).invert(),xl.copy(e.ray).applyMatrix4(hh);const o=r/((this.scale.x+this.scale.y+this.scale.z)/3),l=o*o,c=n.index,u=n.attributes.position;if(c!==null){const d=Math.max(0,a.start),f=Math.min(c.count,a.start+a.count);for(let g=d,x=f;g<x;g++){const p=c.getX(g);Ir.fromBufferAttribute(u,p),uh(Ir,p,l,i,e,t,this)}}else{const d=Math.max(0,a.start),f=Math.min(u.count,a.start+a.count);for(let g=d,x=f;g<x;g++)Ir.fromBufferAttribute(u,g),uh(Ir,g,l,i,e,t,this)}}updateMorphTargets(){const t=this.geometry.morphAttributes,n=Object.keys(t);if(n.length>0){const i=t[n[0]];if(i!==void 0){this.morphTargetInfluences=[],this.morphTargetDictionary={};for(let r=0,a=i.length;r<a;r++){const o=i[r].name||String(r);this.morphTargetInfluences.push(0),this.morphTargetDictionary[o]=r}}}}}function uh(s,e,t,n,i,r,a){const o=xl.distanceSqToPoint(s);if(o<t){const l=new L;xl.closestPointToPoint(s,l),l.applyMatrix4(n);const c=i.ray.origin.distanceTo(l);if(c<i.near||c>i.far)return;r.push({distance:c,distanceToRay:Math.sqrt(o),point:l,index:e,face:null,faceIndex:null,barycoord:null,object:a})}}class Pu extends Pt{constructor(e=[],t=Di,n,i,r,a,o,l,c,h){super(e,t,n,i,r,a,o,l,c,h),this.isCubeTexture=!0,this.flipY=!1}get images(){return this.image}set images(e){this.image=e}}class oo extends Pt{constructor(e,t,n,i,r,a,o,l,c){super(e,t,n,i,r,a,o,l,c),this.isCanvasTexture=!0,this.needsUpdate=!0}}class ys extends Pt{constructor(e,t,n=Fn,i,r,a,o=xt,l=xt,c,h=Jn,u=1){if(h!==Jn&&h!==pi)throw new Error("DepthTexture format must be either THREE.DepthFormat or THREE.DepthStencilFormat");const d={width:e,height:t,depth:u};super(d,i,r,a,o,l,h,n,c),this.isDepthTexture=!0,this.flipY=!1,this.generateMipmaps=!1,this.compareFunction=null}copy(e){return super.copy(e),this.source=new Kl(Object.assign({},e.image)),this.compareFunction=e.compareFunction,this}toJSON(e){const t=super.toJSON(e);return this.compareFunction!==null&&(t.compareFunction=this.compareFunction),t}}class Sp extends ys{constructor(e,t=Fn,n=Di,i,r,a=xt,o=xt,l,c=Jn){const h={width:e,height:e,depth:1},u=[h,h,h,h,h,h];super(e,e,t,n,i,r,a,o,l,c),this.image=u,this.isCubeDepthTexture=!0,this.isCubeTexture=!0}get images(){return this.image}set images(e){this.image=e}}class Du extends Pt{constructor(e=null){super(),this.sourceTexture=e,this.isExternalTexture=!0}copy(e){return super.copy(e),this.sourceTexture=e.sourceTexture,this}}class Cs extends ln{constructor(e=1,t=1,n=1,i=1,r=1,a=1){super(),this.type="BoxGeometry",this.parameters={width:e,height:t,depth:n,widthSegments:i,heightSegments:r,depthSegments:a};const o=this;i=Math.floor(i),r=Math.floor(r),a=Math.floor(a);const l=[],c=[],h=[],u=[];let d=0,f=0;g("z","y","x",-1,-1,n,t,e,a,r,0),g("z","y","x",1,-1,n,t,-e,a,r,1),g("x","z","y",1,1,e,n,t,i,a,2),g("x","z","y",1,-1,e,n,-t,i,a,3),g("x","y","z",1,-1,e,t,n,i,r,4),g("x","y","z",-1,-1,e,t,-n,i,r,5),this.setIndex(l),this.setAttribute("position",new an(c,3)),this.setAttribute("normal",new an(h,3)),this.setAttribute("uv",new an(u,2));function g(x,p,m,S,T,M,E,w,C,v,b){const D=M/C,R=E/v,F=M/2,O=E/2,X=w/2,V=C+1,k=v+1;let U=0,Q=0;const K=new L;for(let se=0;se<k;se++){const he=se*R-O;for(let le=0;le<V;le++){const $=le*D-F;K[x]=$*S,K[p]=he*T,K[m]=X,c.push(K.x,K.y,K.z),K[x]=0,K[p]=0,K[m]=w>0?1:-1,h.push(K.x,K.y,K.z),u.push(le/C),u.push(1-se/v),U+=1}}for(let se=0;se<v;se++)for(let he=0;he<C;he++){const le=d+he+V*se,$=d+he+V*(se+1),ce=d+(he+1)+V*(se+1),Re=d+(he+1)+V*se;l.push(le,$,Re),l.push($,ce,Re),Q+=6}o.addGroup(f,Q,b),f+=Q,d+=U}}copy(e){return super.copy(e),this.parameters=Object.assign({},e.parameters),this}static fromJSON(e){return new Cs(e.width,e.height,e.depth,e.widthSegments,e.heightSegments,e.depthSegments)}}class Pi extends ln{constructor(e=1,t=1,n=1,i=1){super(),this.type="PlaneGeometry",this.parameters={width:e,height:t,widthSegments:n,heightSegments:i};const r=e/2,a=t/2,o=Math.floor(n),l=Math.floor(i),c=o+1,h=l+1,u=e/o,d=t/l,f=[],g=[],x=[],p=[];for(let m=0;m<h;m++){const S=m*d-a;for(let T=0;T<c;T++){const M=T*u-r;g.push(M,-S,0),x.push(0,0,1),p.push(T/o),p.push(1-m/l)}}for(let m=0;m<l;m++)for(let S=0;S<o;S++){const T=S+c*m,M=S+c*(m+1),E=S+1+c*(m+1),w=S+1+c*m;f.push(T,M,w),f.push(M,E,w)}this.setIndex(f),this.setAttribute("position",new an(g,3)),this.setAttribute("normal",new an(x,3)),this.setAttribute("uv",new an(p,2))}copy(e){return super.copy(e),this.parameters=Object.assign({},e.parameters),this}static fromJSON(e){return new Pi(e.width,e.height,e.widthSegments,e.heightSegments)}}function Ss(s){const e={};for(const t in s){e[t]={};for(const n in s[t]){const i=s[t][n];i&&(i.isColor||i.isMatrix3||i.isMatrix4||i.isVector2||i.isVector3||i.isVector4||i.isTexture||i.isQuaternion)?i.isRenderTargetTexture?(Pe("UniformsUtils: Textures of render targets cannot be cloned via cloneUniforms() or mergeUniforms()."),e[t][n]=null):e[t][n]=i.clone():Array.isArray(i)?e[t][n]=i.slice():e[t][n]=i}}return e}function Yt(s){const e={};for(let t=0;t<s.length;t++){const n=Ss(s[t]);for(const i in n)e[i]=n[i]}return e}function bp(s){const e=[];for(let t=0;t<s.length;t++)e.push(s[t].clone());return e}function Lu(s){const e=s.getRenderTarget();return e===null?s.outputColorSpace:e.isXRRenderTarget===!0?e.texture.colorSpace:Ke.workingColorSpace}const mi={clone:Ss,merge:Yt};var Ep=`void main() {
	gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
}`,Tp=`void main() {
	gl_FragColor = vec4( 1.0, 0.0, 0.0, 1.0 );
}`;class kt extends dn{constructor(e){super(),this.isShaderMaterial=!0,this.type="ShaderMaterial",this.defines={},this.uniforms={},this.uniformsGroups=[],this.vertexShader=Ep,this.fragmentShader=Tp,this.linewidth=1,this.wireframe=!1,this.wireframeLinewidth=1,this.fog=!1,this.lights=!1,this.clipping=!1,this.forceSinglePass=!0,this.extensions={clipCullDistance:!1,multiDraw:!1},this.defaultAttributeValues={color:[1,1,1],uv:[0,0],uv1:[0,0]},this.index0AttributeName=void 0,this.uniformsNeedUpdate=!1,this.glslVersion=null,e!==void 0&&this.setValues(e)}copy(e){return super.copy(e),this.fragmentShader=e.fragmentShader,this.vertexShader=e.vertexShader,this.uniforms=Ss(e.uniforms),this.uniformsGroups=bp(e.uniformsGroups),this.defines=Object.assign({},e.defines),this.wireframe=e.wireframe,this.wireframeLinewidth=e.wireframeLinewidth,this.fog=e.fog,this.lights=e.lights,this.clipping=e.clipping,this.extensions=Object.assign({},e.extensions),this.glslVersion=e.glslVersion,this.defaultAttributeValues=Object.assign({},e.defaultAttributeValues),this.index0AttributeName=e.index0AttributeName,this.uniformsNeedUpdate=e.uniformsNeedUpdate,this}toJSON(e){const t=super.toJSON(e);t.glslVersion=this.glslVersion,t.uniforms={};for(const i in this.uniforms){const a=this.uniforms[i].value;a&&a.isTexture?t.uniforms[i]={type:"t",value:a.toJSON(e).uuid}:a&&a.isColor?t.uniforms[i]={type:"c",value:a.getHex()}:a&&a.isVector2?t.uniforms[i]={type:"v2",value:a.toArray()}:a&&a.isVector3?t.uniforms[i]={type:"v3",value:a.toArray()}:a&&a.isVector4?t.uniforms[i]={type:"v4",value:a.toArray()}:a&&a.isMatrix3?t.uniforms[i]={type:"m3",value:a.toArray()}:a&&a.isMatrix4?t.uniforms[i]={type:"m4",value:a.toArray()}:t.uniforms[i]={value:a}}Object.keys(this.defines).length>0&&(t.defines=this.defines),t.vertexShader=this.vertexShader,t.fragmentShader=this.fragmentShader,t.lights=this.lights,t.clipping=this.clipping;const n={};for(const i in this.extensions)this.extensions[i]===!0&&(n[i]=!0);return Object.keys(n).length>0&&(t.extensions=n),t}}class Iu extends kt{constructor(e){super(e),this.isRawShaderMaterial=!0,this.type="RawShaderMaterial"}}class bs extends dn{constructor(e){super(),this.isMeshStandardMaterial=!0,this.type="MeshStandardMaterial",this.defines={STANDARD:""},this.color=new Ie(16777215),this.roughness=1,this.metalness=0,this.map=null,this.lightMap=null,this.lightMapIntensity=1,this.aoMap=null,this.aoMapIntensity=1,this.emissive=new Ie(0),this.emissiveIntensity=1,this.emissiveMap=null,this.bumpMap=null,this.bumpScale=1,this.normalMap=null,this.normalMapType=ga,this.normalScale=new Le(1,1),this.displacementMap=null,this.displacementScale=1,this.displacementBias=0,this.roughnessMap=null,this.metalnessMap=null,this.alphaMap=null,this.envMap=null,this.envMapRotation=new Sn,this.envMapIntensity=1,this.wireframe=!1,this.wireframeLinewidth=1,this.wireframeLinecap="round",this.wireframeLinejoin="round",this.flatShading=!1,this.fog=!0,this.setValues(e)}copy(e){return super.copy(e),this.defines={STANDARD:""},this.color.copy(e.color),this.roughness=e.roughness,this.metalness=e.metalness,this.map=e.map,this.lightMap=e.lightMap,this.lightMapIntensity=e.lightMapIntensity,this.aoMap=e.aoMap,this.aoMapIntensity=e.aoMapIntensity,this.emissive.copy(e.emissive),this.emissiveMap=e.emissiveMap,this.emissiveIntensity=e.emissiveIntensity,this.bumpMap=e.bumpMap,this.bumpScale=e.bumpScale,this.normalMap=e.normalMap,this.normalMapType=e.normalMapType,this.normalScale.copy(e.normalScale),this.displacementMap=e.displacementMap,this.displacementScale=e.displacementScale,this.displacementBias=e.displacementBias,this.roughnessMap=e.roughnessMap,this.metalnessMap=e.metalnessMap,this.alphaMap=e.alphaMap,this.envMap=e.envMap,this.envMapRotation.copy(e.envMapRotation),this.envMapIntensity=e.envMapIntensity,this.wireframe=e.wireframe,this.wireframeLinewidth=e.wireframeLinewidth,this.wireframeLinecap=e.wireframeLinecap,this.wireframeLinejoin=e.wireframeLinejoin,this.flatShading=e.flatShading,this.fog=e.fog,this}}class Bn extends bs{constructor(e){super(),this.isMeshPhysicalMaterial=!0,this.defines={STANDARD:"",PHYSICAL:""},this.type="MeshPhysicalMaterial",this.anisotropyRotation=0,this.anisotropyMap=null,this.clearcoatMap=null,this.clearcoatRoughness=0,this.clearcoatRoughnessMap=null,this.clearcoatNormalScale=new Le(1,1),this.clearcoatNormalMap=null,this.ior=1.5,Object.defineProperty(this,"reflectivity",{get:function(){return Xe(2.5*(this.ior-1)/(this.ior+1),0,1)},set:function(t){this.ior=(1+.4*t)/(1-.4*t)}}),this.iridescenceMap=null,this.iridescenceIOR=1.3,this.iridescenceThicknessRange=[100,400],this.iridescenceThicknessMap=null,this.sheenColor=new Ie(0),this.sheenColorMap=null,this.sheenRoughness=1,this.sheenRoughnessMap=null,this.transmissionMap=null,this.thickness=0,this.thicknessMap=null,this.attenuationDistance=1/0,this.attenuationColor=new Ie(1,1,1),this.specularIntensity=1,this.specularIntensityMap=null,this.specularColor=new Ie(1,1,1),this.specularColorMap=null,this._anisotropy=0,this._clearcoat=0,this._dispersion=0,this._iridescence=0,this._sheen=0,this._transmission=0,this.setValues(e)}get anisotropy(){return this._anisotropy}set anisotropy(e){this._anisotropy>0!=e>0&&this.version++,this._anisotropy=e}get clearcoat(){return this._clearcoat}set clearcoat(e){this._clearcoat>0!=e>0&&this.version++,this._clearcoat=e}get iridescence(){return this._iridescence}set iridescence(e){this._iridescence>0!=e>0&&this.version++,this._iridescence=e}get dispersion(){return this._dispersion}set dispersion(e){this._dispersion>0!=e>0&&this.version++,this._dispersion=e}get sheen(){return this._sheen}set sheen(e){this._sheen>0!=e>0&&this.version++,this._sheen=e}get transmission(){return this._transmission}set transmission(e){this._transmission>0!=e>0&&this.version++,this._transmission=e}copy(e){return super.copy(e),this.defines={STANDARD:"",PHYSICAL:""},this.anisotropy=e.anisotropy,this.anisotropyRotation=e.anisotropyRotation,this.anisotropyMap=e.anisotropyMap,this.clearcoat=e.clearcoat,this.clearcoatMap=e.clearcoatMap,this.clearcoatRoughness=e.clearcoatRoughness,this.clearcoatRoughnessMap=e.clearcoatRoughnessMap,this.clearcoatNormalMap=e.clearcoatNormalMap,this.clearcoatNormalScale.copy(e.clearcoatNormalScale),this.dispersion=e.dispersion,this.ior=e.ior,this.iridescence=e.iridescence,this.iridescenceMap=e.iridescenceMap,this.iridescenceIOR=e.iridescenceIOR,this.iridescenceThicknessRange=[...e.iridescenceThicknessRange],this.iridescenceThicknessMap=e.iridescenceThicknessMap,this.sheen=e.sheen,this.sheenColor.copy(e.sheenColor),this.sheenColorMap=e.sheenColorMap,this.sheenRoughness=e.sheenRoughness,this.sheenRoughnessMap=e.sheenRoughnessMap,this.transmission=e.transmission,this.transmissionMap=e.transmissionMap,this.thickness=e.thickness,this.thicknessMap=e.thicknessMap,this.attenuationDistance=e.attenuationDistance,this.attenuationColor.copy(e.attenuationColor),this.specularIntensity=e.specularIntensity,this.specularIntensityMap=e.specularIntensityMap,this.specularColor.copy(e.specularColor),this.specularColorMap=e.specularColorMap,this}}class Ap extends dn{constructor(e){super(),this.isMeshNormalMaterial=!0,this.type="MeshNormalMaterial",this.bumpMap=null,this.bumpScale=1,this.normalMap=null,this.normalMapType=ga,this.normalScale=new Le(1,1),this.displacementMap=null,this.displacementScale=1,this.displacementBias=0,this.wireframe=!1,this.wireframeLinewidth=1,this.flatShading=!1,this.setValues(e)}copy(e){return super.copy(e),this.bumpMap=e.bumpMap,this.bumpScale=e.bumpScale,this.normalMap=e.normalMap,this.normalMapType=e.normalMapType,this.normalScale.copy(e.normalScale),this.displacementMap=e.displacementMap,this.displacementScale=e.displacementScale,this.displacementBias=e.displacementBias,this.wireframe=e.wireframe,this.wireframeLinewidth=e.wireframeLinewidth,this.flatShading=e.flatShading,this}}class wp extends dn{constructor(e){super(),this.isMeshLambertMaterial=!0,this.type="MeshLambertMaterial",this.color=new Ie(16777215),this.map=null,this.lightMap=null,this.lightMapIntensity=1,this.aoMap=null,this.aoMapIntensity=1,this.emissive=new Ie(0),this.emissiveIntensity=1,this.emissiveMap=null,this.bumpMap=null,this.bumpScale=1,this.normalMap=null,this.normalMapType=ga,this.normalScale=new Le(1,1),this.displacementMap=null,this.displacementScale=1,this.displacementBias=0,this.specularMap=null,this.alphaMap=null,this.envMap=null,this.envMapRotation=new Sn,this.combine=Il,this.reflectivity=1,this.envMapIntensity=1,this.refractionRatio=.98,this.wireframe=!1,this.wireframeLinewidth=1,this.wireframeLinecap="round",this.wireframeLinejoin="round",this.flatShading=!1,this.fog=!0,this.setValues(e)}copy(e){return super.copy(e),this.color.copy(e.color),this.map=e.map,this.lightMap=e.lightMap,this.lightMapIntensity=e.lightMapIntensity,this.aoMap=e.aoMap,this.aoMapIntensity=e.aoMapIntensity,this.emissive.copy(e.emissive),this.emissiveMap=e.emissiveMap,this.emissiveIntensity=e.emissiveIntensity,this.bumpMap=e.bumpMap,this.bumpScale=e.bumpScale,this.normalMap=e.normalMap,this.normalMapType=e.normalMapType,this.normalScale.copy(e.normalScale),this.displacementMap=e.displacementMap,this.displacementScale=e.displacementScale,this.displacementBias=e.displacementBias,this.specularMap=e.specularMap,this.alphaMap=e.alphaMap,this.envMap=e.envMap,this.envMapRotation.copy(e.envMapRotation),this.combine=e.combine,this.reflectivity=e.reflectivity,this.envMapIntensity=e.envMapIntensity,this.refractionRatio=e.refractionRatio,this.wireframe=e.wireframe,this.wireframeLinewidth=e.wireframeLinewidth,this.wireframeLinecap=e.wireframeLinecap,this.wireframeLinejoin=e.wireframeLinejoin,this.flatShading=e.flatShading,this.fog=e.fog,this}}class Nu extends dn{constructor(e){super(),this.isMeshDepthMaterial=!0,this.type="MeshDepthMaterial",this.depthPacking=gf,this.map=null,this.alphaMap=null,this.displacementMap=null,this.displacementScale=1,this.displacementBias=0,this.wireframe=!1,this.wireframeLinewidth=1,this.setValues(e)}copy(e){return super.copy(e),this.depthPacking=e.depthPacking,this.map=e.map,this.alphaMap=e.alphaMap,this.displacementMap=e.displacementMap,this.displacementScale=e.displacementScale,this.displacementBias=e.displacementBias,this.wireframe=e.wireframe,this.wireframeLinewidth=e.wireframeLinewidth,this}}class Rp extends dn{constructor(e){super(),this.isMeshDistanceMaterial=!0,this.type="MeshDistanceMaterial",this.map=null,this.alphaMap=null,this.displacementMap=null,this.displacementScale=1,this.displacementBias=0,this.setValues(e)}copy(e){return super.copy(e),this.map=e.map,this.alphaMap=e.alphaMap,this.displacementMap=e.displacementMap,this.displacementScale=e.displacementScale,this.displacementBias=e.displacementBias,this}}function Nr(s,e){return!s||s.constructor===e?s:typeof e.BYTES_PER_ELEMENT=="number"?new e(s):Array.prototype.slice.call(s)}function Cp(s){function e(i,r){return s[i]-s[r]}const t=s.length,n=new Array(t);for(let i=0;i!==t;++i)n[i]=i;return n.sort(e),n}function dh(s,e,t){const n=s.length,i=new s.constructor(n);for(let r=0,a=0;a!==n;++r){const o=t[r]*e;for(let l=0;l!==e;++l)i[a++]=s[o+l]}return i}function Uu(s,e,t,n){let i=1,r=s[0];for(;r!==void 0&&r[n]===void 0;)r=s[i++];if(r===void 0)return;let a=r[n];if(a!==void 0)if(Array.isArray(a))do a=r[n],a!==void 0&&(e.push(r.time),t.push(...a)),r=s[i++];while(r!==void 0);else if(a.toArray!==void 0)do a=r[n],a!==void 0&&(e.push(r.time),a.toArray(t,t.length)),r=s[i++];while(r!==void 0);else do a=r[n],a!==void 0&&(e.push(r.time),t.push(a)),r=s[i++];while(r!==void 0)}class Ps{constructor(e,t,n,i){this.parameterPositions=e,this._cachedIndex=0,this.resultBuffer=i!==void 0?i:new t.constructor(n),this.sampleValues=t,this.valueSize=n,this.settings=null,this.DefaultSettings_={}}evaluate(e){const t=this.parameterPositions;let n=this._cachedIndex,i=t[n],r=t[n-1];n:{e:{let a;t:{i:if(!(e<i)){for(let o=n+2;;){if(i===void 0){if(e<r)break i;return n=t.length,this._cachedIndex=n,this.copySampleValue_(n-1)}if(n===o)break;if(r=i,i=t[++n],e<i)break e}a=t.length;break t}if(!(e>=r)){const o=t[1];e<o&&(n=2,r=o);for(let l=n-2;;){if(r===void 0)return this._cachedIndex=0,this.copySampleValue_(0);if(n===l)break;if(i=r,r=t[--n-1],e>=r)break e}a=n,n=0;break t}break n}for(;n<a;){const o=n+a>>>1;e<t[o]?a=o:n=o+1}if(i=t[n],r=t[n-1],r===void 0)return this._cachedIndex=0,this.copySampleValue_(0);if(i===void 0)return n=t.length,this._cachedIndex=n,this.copySampleValue_(n-1)}this._cachedIndex=n,this.intervalChanged_(n,r,i)}return this.interpolate_(n,r,e,i)}getSettings_(){return this.settings||this.DefaultSettings_}copySampleValue_(e){const t=this.resultBuffer,n=this.sampleValues,i=this.valueSize,r=e*i;for(let a=0;a!==i;++a)t[a]=n[r+a];return t}interpolate_(){throw new Error("call to abstract method")}intervalChanged_(){}}class Pp extends Ps{constructor(e,t,n,i){super(e,t,n,i),this._weightPrev=-0,this._offsetPrev=-0,this._weightNext=-0,this._offsetNext=-0,this.DefaultSettings_={endingStart:Dc,endingEnd:Dc}}intervalChanged_(e,t,n){const i=this.parameterPositions;let r=e-2,a=e+1,o=i[r],l=i[a];if(o===void 0)switch(this.getSettings_().endingStart){case Lc:r=e,o=2*t-n;break;case Ic:r=i.length-2,o=t+i[r]-i[r+1];break;default:r=e,o=n}if(l===void 0)switch(this.getSettings_().endingEnd){case Lc:a=e,l=2*n-t;break;case Ic:a=1,l=n+i[1]-i[0];break;default:a=e-1,l=t}const c=(n-t)*.5,h=this.valueSize;this._weightPrev=c/(t-o),this._weightNext=c/(l-n),this._offsetPrev=r*h,this._offsetNext=a*h}interpolate_(e,t,n,i){const r=this.resultBuffer,a=this.sampleValues,o=this.valueSize,l=e*o,c=l-o,h=this._offsetPrev,u=this._offsetNext,d=this._weightPrev,f=this._weightNext,g=(n-t)/(i-t),x=g*g,p=x*g,m=-d*p+2*d*x-d*g,S=(1+d)*p+(-1.5-2*d)*x+(-.5+d)*g+1,T=(-1-f)*p+(1.5+f)*x+.5*g,M=f*p-f*x;for(let E=0;E!==o;++E)r[E]=m*a[h+E]+S*a[c+E]+T*a[l+E]+M*a[u+E];return r}}class Dp extends Ps{constructor(e,t,n,i){super(e,t,n,i)}interpolate_(e,t,n,i){const r=this.resultBuffer,a=this.sampleValues,o=this.valueSize,l=e*o,c=l-o,h=(n-t)/(i-t),u=1-h;for(let d=0;d!==o;++d)r[d]=a[c+d]*u+a[l+d]*h;return r}}class Lp extends Ps{constructor(e,t,n,i){super(e,t,n,i)}interpolate_(e){return this.copySampleValue_(e-1)}}class Ip extends Ps{interpolate_(e,t,n,i){const r=this.resultBuffer,a=this.sampleValues,o=this.valueSize,l=e*o,c=l-o,h=this.settings||this.DefaultSettings_,u=h.inTangents,d=h.outTangents;if(!u||!d){const x=(n-t)/(i-t),p=1-x;for(let m=0;m!==o;++m)r[m]=a[c+m]*p+a[l+m]*x;return r}const f=o*2,g=e-1;for(let x=0;x!==o;++x){const p=a[c+x],m=a[l+x],S=g*f+x*2,T=d[S],M=d[S+1],E=e*f+x*2,w=u[E],C=u[E+1];let v=(n-t)/(i-t),b,D,R,F,O;for(let X=0;X<8;X++){b=v*v,D=b*v,R=1-v,F=R*R,O=F*R;const k=O*t+3*F*v*T+3*R*b*w+D*i-n;if(Math.abs(k)<1e-10)break;const U=3*F*(T-t)+6*R*v*(w-T)+3*b*(i-w);if(Math.abs(U)<1e-10)break;v=v-k/U,v=Math.max(0,Math.min(1,v))}r[x]=O*p+3*F*v*M+3*R*b*C+D*m}return r}}class bn{constructor(e,t,n,i){if(e===void 0)throw new Error("THREE.KeyframeTrack: track name is undefined");if(t===void 0||t.length===0)throw new Error("THREE.KeyframeTrack: no keyframes in track named "+e);this.name=e,this.times=Nr(t,this.TimeBufferType),this.values=Nr(n,this.ValueBufferType),this.setInterpolation(i||this.DefaultInterpolation)}static toJSON(e){const t=e.constructor;let n;if(t.toJSON!==this.toJSON)n=t.toJSON(e);else{n={name:e.name,times:Nr(e.times,Array),values:Nr(e.values,Array)};const i=e.getInterpolation();i!==e.DefaultInterpolation&&(n.interpolation=i)}return n.type=e.ValueTypeName,n}InterpolantFactoryMethodDiscrete(e){return new Lp(this.times,this.values,this.getValueSize(),e)}InterpolantFactoryMethodLinear(e){return new Dp(this.times,this.values,this.getValueSize(),e)}InterpolantFactoryMethodSmooth(e){return new Pp(this.times,this.values,this.getValueSize(),e)}InterpolantFactoryMethodBezier(e){const t=new Ip(this.times,this.values,this.getValueSize(),e);return this.settings&&(t.settings=this.settings),t}setInterpolation(e){let t;switch(e){case er:t=this.InterpolantFactoryMethodDiscrete;break;case tr:t=this.InterpolantFactoryMethodLinear;break;case Ua:t=this.InterpolantFactoryMethodSmooth;break;case Pc:t=this.InterpolantFactoryMethodBezier;break}if(t===void 0){const n="unsupported interpolation for "+this.ValueTypeName+" keyframe track named "+this.name;if(this.createInterpolant===void 0)if(e!==this.DefaultInterpolation)this.setInterpolation(this.DefaultInterpolation);else throw new Error(n);return Pe("KeyframeTrack:",n),this}return this.createInterpolant=t,this}getInterpolation(){switch(this.createInterpolant){case this.InterpolantFactoryMethodDiscrete:return er;case this.InterpolantFactoryMethodLinear:return tr;case this.InterpolantFactoryMethodSmooth:return Ua;case this.InterpolantFactoryMethodBezier:return Pc}}getValueSize(){return this.values.length/this.times.length}shift(e){if(e!==0){const t=this.times;for(let n=0,i=t.length;n!==i;++n)t[n]+=e}return this}scale(e){if(e!==1){const t=this.times;for(let n=0,i=t.length;n!==i;++n)t[n]*=e}return this}trim(e,t){const n=this.times,i=n.length;let r=0,a=i-1;for(;r!==i&&n[r]<e;)++r;for(;a!==-1&&n[a]>t;)--a;if(++a,r!==0||a!==i){r>=a&&(a=Math.max(a,1),r=a-1);const o=this.getValueSize();this.times=n.slice(r,a),this.values=this.values.slice(r*o,a*o)}return this}validate(){let e=!0;const t=this.getValueSize();t-Math.floor(t)!==0&&(Ue("KeyframeTrack: Invalid value size in track.",this),e=!1);const n=this.times,i=this.values,r=n.length;r===0&&(Ue("KeyframeTrack: Track is empty.",this),e=!1);let a=null;for(let o=0;o!==r;o++){const l=n[o];if(typeof l=="number"&&isNaN(l)){Ue("KeyframeTrack: Time is not a valid number.",this,o,l),e=!1;break}if(a!==null&&a>l){Ue("KeyframeTrack: Out of order keys.",this,o,l,a),e=!1;break}a=l}if(i!==void 0&&wf(i))for(let o=0,l=i.length;o!==l;++o){const c=i[o];if(isNaN(c)){Ue("KeyframeTrack: Value is not a valid number.",this,o,c),e=!1;break}}return e}optimize(){const e=this.times.slice(),t=this.values.slice(),n=this.getValueSize(),i=this.getInterpolation()===Ua,r=e.length-1;let a=1;for(let o=1;o<r;++o){let l=!1;const c=e[o],h=e[o+1];if(c!==h&&(o!==1||c!==e[0]))if(i)l=!0;else{const u=o*n,d=u-n,f=u+n;for(let g=0;g!==n;++g){const x=t[u+g];if(x!==t[d+g]||x!==t[f+g]){l=!0;break}}}if(l){if(o!==a){e[a]=e[o];const u=o*n,d=a*n;for(let f=0;f!==n;++f)t[d+f]=t[u+f]}++a}}if(r>0){e[a]=e[r];for(let o=r*n,l=a*n,c=0;c!==n;++c)t[l+c]=t[o+c];++a}return a!==e.length?(this.times=e.slice(0,a),this.values=t.slice(0,a*n)):(this.times=e,this.values=t),this}clone(){const e=this.times.slice(),t=this.values.slice(),n=this.constructor,i=new n(this.name,e,t);return i.createInterpolant=this.createInterpolant,i}}bn.prototype.ValueTypeName="";bn.prototype.TimeBufferType=Float32Array;bn.prototype.ValueBufferType=Float32Array;bn.prototype.DefaultInterpolation=tr;class Ds extends bn{constructor(e,t,n){super(e,t,n)}}Ds.prototype.ValueTypeName="bool";Ds.prototype.ValueBufferType=Array;Ds.prototype.DefaultInterpolation=er;Ds.prototype.InterpolantFactoryMethodLinear=void 0;Ds.prototype.InterpolantFactoryMethodSmooth=void 0;class Fu extends bn{constructor(e,t,n,i){super(e,t,n,i)}}Fu.prototype.ValueTypeName="color";class Es extends bn{constructor(e,t,n,i){super(e,t,n,i)}}Es.prototype.ValueTypeName="number";class Np extends Ps{constructor(e,t,n,i){super(e,t,n,i)}interpolate_(e,t,n,i){const r=this.resultBuffer,a=this.sampleValues,o=this.valueSize,l=(n-t)/(i-t);let c=e*o;for(let h=c+o;c!==h;c+=4)yn.slerpFlat(r,0,a,c-o,a,c,l);return r}}class Ts extends bn{constructor(e,t,n,i){super(e,t,n,i)}InterpolantFactoryMethodLinear(e){return new Np(this.times,this.values,this.getValueSize(),e)}}Ts.prototype.ValueTypeName="quaternion";Ts.prototype.InterpolantFactoryMethodSmooth=void 0;class Ls extends bn{constructor(e,t,n){super(e,t,n)}}Ls.prototype.ValueTypeName="string";Ls.prototype.ValueBufferType=Array;Ls.prototype.DefaultInterpolation=er;Ls.prototype.InterpolantFactoryMethodLinear=void 0;Ls.prototype.InterpolantFactoryMethodSmooth=void 0;class As extends bn{constructor(e,t,n,i){super(e,t,n,i)}}As.prototype.ValueTypeName="vector";class Up{constructor(e="",t=-1,n=[],i=pf){this.name=e,this.tracks=n,this.duration=t,this.blendMode=i,this.uuid=Mn(),this.userData={},this.duration<0&&this.resetDuration()}static parse(e){const t=[],n=e.tracks,i=1/(e.fps||1);for(let a=0,o=n.length;a!==o;++a)t.push(Op(n[a]).scale(i));const r=new this(e.name,e.duration,t,e.blendMode);return r.uuid=e.uuid,r.userData=JSON.parse(e.userData||"{}"),r}static toJSON(e){const t=[],n=e.tracks,i={name:e.name,duration:e.duration,tracks:t,uuid:e.uuid,blendMode:e.blendMode,userData:JSON.stringify(e.userData)};for(let r=0,a=n.length;r!==a;++r)t.push(bn.toJSON(n[r]));return i}static CreateFromMorphTargetSequence(e,t,n,i){const r=t.length,a=[];for(let o=0;o<r;o++){let l=[],c=[];l.push((o+r-1)%r,o,(o+1)%r),c.push(0,1,0);const h=Cp(l);l=dh(l,1,h),c=dh(c,1,h),!i&&l[0]===0&&(l.push(r),c.push(c[0])),a.push(new Es(".morphTargetInfluences["+t[o].name+"]",l,c).scale(1/n))}return new this(e,-1,a)}static findByName(e,t){let n=e;if(!Array.isArray(e)){const i=e;n=i.geometry&&i.geometry.animations||i.animations}for(let i=0;i<n.length;i++)if(n[i].name===t)return n[i];return null}static CreateClipsFromMorphTargetSequences(e,t,n){const i={},r=/^([\w-]*?)([\d]+)$/;for(let o=0,l=e.length;o<l;o++){const c=e[o],h=c.name.match(r);if(h&&h.length>1){const u=h[1];let d=i[u];d||(i[u]=d=[]),d.push(c)}}const a=[];for(const o in i)a.push(this.CreateFromMorphTargetSequence(o,i[o],t,n));return a}static parseAnimation(e,t){if(Pe("AnimationClip: parseAnimation() is deprecated and will be removed with r185"),!e)return Ue("AnimationClip: No animation in JSONLoader data."),null;const n=function(u,d,f,g,x){if(f.length!==0){const p=[],m=[];Uu(f,p,m,g),p.length!==0&&x.push(new u(d,p,m))}},i=[],r=e.name||"default",a=e.fps||30,o=e.blendMode;let l=e.length||-1;const c=e.hierarchy||[];for(let u=0;u<c.length;u++){const d=c[u].keys;if(!(!d||d.length===0))if(d[0].morphTargets){const f={};let g;for(g=0;g<d.length;g++)if(d[g].morphTargets)for(let x=0;x<d[g].morphTargets.length;x++)f[d[g].morphTargets[x]]=-1;for(const x in f){const p=[],m=[];for(let S=0;S!==d[g].morphTargets.length;++S){const T=d[g];p.push(T.time),m.push(T.morphTarget===x?1:0)}i.push(new Es(".morphTargetInfluence["+x+"]",p,m))}l=f.length*a}else{const f=".bones["+t[u].name+"]";n(As,f+".position",d,"pos",i),n(Ts,f+".quaternion",d,"rot",i),n(As,f+".scale",d,"scl",i)}}return i.length===0?null:new this(r,l,i,o)}resetDuration(){const e=this.tracks;let t=0;for(let n=0,i=e.length;n!==i;++n){const r=this.tracks[n];t=Math.max(t,r.times[r.times.length-1])}return this.duration=t,this}trim(){for(let e=0;e<this.tracks.length;e++)this.tracks[e].trim(0,this.duration);return this}validate(){let e=!0;for(let t=0;t<this.tracks.length;t++)e=e&&this.tracks[t].validate();return e}optimize(){for(let e=0;e<this.tracks.length;e++)this.tracks[e].optimize();return this}clone(){const e=[];for(let n=0;n<this.tracks.length;n++)e.push(this.tracks[n].clone());const t=new this.constructor(this.name,this.duration,e,this.blendMode);return t.userData=JSON.parse(JSON.stringify(this.userData)),t}toJSON(){return this.constructor.toJSON(this)}}function Fp(s){switch(s.toLowerCase()){case"scalar":case"double":case"float":case"number":case"integer":return Es;case"vector":case"vector2":case"vector3":case"vector4":return As;case"color":return Fu;case"quaternion":return Ts;case"bool":case"boolean":return Ds;case"string":return Ls}throw new Error("THREE.KeyframeTrack: Unsupported typeName: "+s)}function Op(s){if(s.type===void 0)throw new Error("THREE.KeyframeTrack: track type undefined, can not parse");const e=Fp(s.type);if(s.times===void 0){const t=[],n=[];Uu(s.keys,t,n,"value"),s.times=t,s.values=n}return e.parse!==void 0?e.parse(s):new e(s.name,s.times,s.values,s.interpolation)}const Kn={enabled:!1,files:{},add:function(s,e){this.enabled!==!1&&(fh(s)||(this.files[s]=e))},get:function(s){if(this.enabled!==!1&&!fh(s))return this.files[s]},remove:function(s){delete this.files[s]},clear:function(){this.files={}}};function fh(s){try{const e=s.slice(s.indexOf(":")+1);return new URL(e).protocol==="blob:"}catch{return!1}}class Bp{constructor(e,t,n){const i=this;let r=!1,a=0,o=0,l;const c=[];this.onStart=void 0,this.onLoad=e,this.onProgress=t,this.onError=n,this._abortController=null,this.itemStart=function(h){o++,r===!1&&i.onStart!==void 0&&i.onStart(h,a,o),r=!0},this.itemEnd=function(h){a++,i.onProgress!==void 0&&i.onProgress(h,a,o),a===o&&(r=!1,i.onLoad!==void 0&&i.onLoad())},this.itemError=function(h){i.onError!==void 0&&i.onError(h)},this.resolveURL=function(h){return l?l(h):h},this.setURLModifier=function(h){return l=h,this},this.addHandler=function(h,u){return c.push(h,u),this},this.removeHandler=function(h){const u=c.indexOf(h);return u!==-1&&c.splice(u,2),this},this.getHandler=function(h){for(let u=0,d=c.length;u<d;u+=2){const f=c[u],g=c[u+1];if(f.global&&(f.lastIndex=0),f.test(h))return g}return null},this.abort=function(){return this.abortController.abort(),this._abortController=null,this}}get abortController(){return this._abortController||(this._abortController=new AbortController),this._abortController}}const kp=new Bp;class Is{constructor(e){this.manager=e!==void 0?e:kp,this.crossOrigin="anonymous",this.withCredentials=!1,this.path="",this.resourcePath="",this.requestHeader={},typeof __THREE_DEVTOOLS__<"u"&&__THREE_DEVTOOLS__.dispatchEvent(new CustomEvent("observe",{detail:this}))}load(){}loadAsync(e,t){const n=this;return new Promise(function(i,r){n.load(e,i,t,r)})}parse(){}setCrossOrigin(e){return this.crossOrigin=e,this}setWithCredentials(e){return this.withCredentials=e,this}setPath(e){return this.path=e,this}setResourcePath(e){return this.resourcePath=e,this}setRequestHeader(e){return this.requestHeader=e,this}abort(){return this}}Is.DEFAULT_MATERIAL_NAME="__DEFAULT";const Yn={};class Vp extends Error{constructor(e,t){super(e),this.response=t}}class Ou extends Is{constructor(e){super(e),this.mimeType="",this.responseType="",this._abortController=new AbortController}load(e,t,n,i){e===void 0&&(e=""),this.path!==void 0&&(e=this.path+e),e=this.manager.resolveURL(e);const r=Kn.get(`file:${e}`);if(r!==void 0)return this.manager.itemStart(e),setTimeout(()=>{t&&t(r),this.manager.itemEnd(e)},0),r;if(Yn[e]!==void 0){Yn[e].push({onLoad:t,onProgress:n,onError:i});return}Yn[e]=[],Yn[e].push({onLoad:t,onProgress:n,onError:i});const a=new Request(e,{headers:new Headers(this.requestHeader),credentials:this.withCredentials?"include":"same-origin",signal:typeof AbortSignal.any=="function"?AbortSignal.any([this._abortController.signal,this.manager.abortController.signal]):this._abortController.signal}),o=this.mimeType,l=this.responseType;fetch(a).then(c=>{if(c.status===200||c.status===0){if(c.status===0&&Pe("FileLoader: HTTP Status 0 received."),typeof ReadableStream>"u"||c.body===void 0||c.body.getReader===void 0)return c;const h=Yn[e],u=c.body.getReader(),d=c.headers.get("X-File-Size")||c.headers.get("Content-Length"),f=d?parseInt(d):0,g=f!==0;let x=0;const p=new ReadableStream({start(m){S();function S(){u.read().then(({done:T,value:M})=>{if(T)m.close();else{x+=M.byteLength;const E=new ProgressEvent("progress",{lengthComputable:g,loaded:x,total:f});for(let w=0,C=h.length;w<C;w++){const v=h[w];v.onProgress&&v.onProgress(E)}m.enqueue(M),S()}},T=>{m.error(T)})}}});return new Response(p)}else throw new Vp(`fetch for "${c.url}" responded with ${c.status}: ${c.statusText}`,c)}).then(c=>{switch(l){case"arraybuffer":return c.arrayBuffer();case"blob":return c.blob();case"document":return c.text().then(h=>new DOMParser().parseFromString(h,o));case"json":return c.json();default:if(o==="")return c.text();{const u=/charset="?([^;"\s]*)"?/i.exec(o),d=u&&u[1]?u[1].toLowerCase():void 0,f=new TextDecoder(d);return c.arrayBuffer().then(g=>f.decode(g))}}}).then(c=>{Kn.add(`file:${e}`,c);const h=Yn[e];delete Yn[e];for(let u=0,d=h.length;u<d;u++){const f=h[u];f.onLoad&&f.onLoad(c)}}).catch(c=>{const h=Yn[e];if(h===void 0)throw this.manager.itemError(e),c;delete Yn[e];for(let u=0,d=h.length;u<d;u++){const f=h[u];f.onError&&f.onError(c)}this.manager.itemError(e)}).finally(()=>{this.manager.itemEnd(e)}),this.manager.itemStart(e)}setResponseType(e){return this.responseType=e,this}setMimeType(e){return this.mimeType=e,this}abort(){return this._abortController.abort(),this._abortController=new AbortController,this}}const Ji=new WeakMap;class zp extends Is{constructor(e){super(e)}load(e,t,n,i){this.path!==void 0&&(e=this.path+e),e=this.manager.resolveURL(e);const r=this,a=Kn.get(`image:${e}`);if(a!==void 0){if(a.complete===!0)r.manager.itemStart(e),setTimeout(function(){t&&t(a),r.manager.itemEnd(e)},0);else{let u=Ji.get(a);u===void 0&&(u=[],Ji.set(a,u)),u.push({onLoad:t,onError:i})}return a}const o=ir("img");function l(){h(),t&&t(this);const u=Ji.get(this)||[];for(let d=0;d<u.length;d++){const f=u[d];f.onLoad&&f.onLoad(this)}Ji.delete(this),r.manager.itemEnd(e)}function c(u){h(),i&&i(u),Kn.remove(`image:${e}`);const d=Ji.get(this)||[];for(let f=0;f<d.length;f++){const g=d[f];g.onError&&g.onError(u)}Ji.delete(this),r.manager.itemError(e),r.manager.itemEnd(e)}function h(){o.removeEventListener("load",l,!1),o.removeEventListener("error",c,!1)}return o.addEventListener("load",l,!1),o.addEventListener("error",c,!1),e.slice(0,5)!=="data:"&&this.crossOrigin!==void 0&&(o.crossOrigin=this.crossOrigin),Kn.add(`image:${e}`,o),r.manager.itemStart(e),o.src=e,o}}class Hp extends Is{constructor(e){super(e)}load(e,t,n,i){const r=new Pt,a=new zp(this.manager);return a.setCrossOrigin(this.crossOrigin),a.setPath(this.path),a.load(e,function(o){r.image=o,r.needsUpdate=!0,t!==void 0&&t(r)},n,i),r}}class xa extends ft{constructor(e,t=1){super(),this.isLight=!0,this.type="Light",this.color=new Ie(e),this.intensity=t}dispose(){this.dispatchEvent({type:"dispose"})}copy(e,t){return super.copy(e,t),this.color.copy(e.color),this.intensity=e.intensity,this}toJSON(e){const t=super.toJSON(e);return t.object.color=this.color.getHex(),t.object.intensity=this.intensity,t}}class Gp extends xa{constructor(e,t,n){super(e,n),this.isHemisphereLight=!0,this.type="HemisphereLight",this.position.copy(ft.DEFAULT_UP),this.updateMatrix(),this.groundColor=new Ie(t)}copy(e,t){return super.copy(e,t),this.groundColor.copy(e.groundColor),this}toJSON(e){const t=super.toJSON(e);return t.object.groundColor=this.groundColor.getHex(),t}}const lo=new Ve,ph=new L,mh=new L;class ic{constructor(e){this.camera=e,this.intensity=1,this.bias=0,this.biasNode=null,this.normalBias=0,this.radius=1,this.blurSamples=8,this.mapSize=new Le(512,512),this.mapType=nn,this.map=null,this.mapPass=null,this.matrix=new Ve,this.autoUpdate=!0,this.needsUpdate=!1,this._frustum=new tc,this._frameExtents=new Le(1,1),this._viewportCount=1,this._viewports=[new mt(0,0,1,1)]}getViewportCount(){return this._viewportCount}getFrustum(){return this._frustum}updateMatrices(e){const t=this.camera,n=this.matrix;ph.setFromMatrixPosition(e.matrixWorld),t.position.copy(ph),mh.setFromMatrixPosition(e.target.matrixWorld),t.lookAt(mh),t.updateMatrixWorld(),lo.multiplyMatrices(t.projectionMatrix,t.matrixWorldInverse),this._frustum.setFromProjectionMatrix(lo,t.coordinateSystem,t.reversedDepth),t.coordinateSystem===nr||t.reversedDepth?n.set(.5,0,0,.5,0,.5,0,.5,0,0,1,0,0,0,0,1):n.set(.5,0,0,.5,0,.5,0,.5,0,0,.5,.5,0,0,0,1),n.multiply(lo)}getViewport(e){return this._viewports[e]}getFrameExtents(){return this._frameExtents}dispose(){this.map&&this.map.dispose(),this.mapPass&&this.mapPass.dispose()}copy(e){return this.camera=e.camera.clone(),this.intensity=e.intensity,this.bias=e.bias,this.radius=e.radius,this.autoUpdate=e.autoUpdate,this.needsUpdate=e.needsUpdate,this.normalBias=e.normalBias,this.blurSamples=e.blurSamples,this.mapSize.copy(e.mapSize),this.biasNode=e.biasNode,this}clone(){return new this.constructor().copy(this)}toJSON(){const e={};return this.intensity!==1&&(e.intensity=this.intensity),this.bias!==0&&(e.bias=this.bias),this.normalBias!==0&&(e.normalBias=this.normalBias),this.radius!==1&&(e.radius=this.radius),(this.mapSize.x!==512||this.mapSize.y!==512)&&(e.mapSize=this.mapSize.toArray()),e.camera=this.camera.toJSON(!1).object,delete e.camera.matrix,e}}const Ur=new L,Fr=new yn,Tn=new L;class Bu extends ft{constructor(){super(),this.isCamera=!0,this.type="Camera",this.matrixWorldInverse=new Ve,this.projectionMatrix=new Ve,this.projectionMatrixInverse=new Ve,this.coordinateSystem=Ln,this._reversedDepth=!1}get reversedDepth(){return this._reversedDepth}copy(e,t){return super.copy(e,t),this.matrixWorldInverse.copy(e.matrixWorldInverse),this.projectionMatrix.copy(e.projectionMatrix),this.projectionMatrixInverse.copy(e.projectionMatrixInverse),this.coordinateSystem=e.coordinateSystem,this}getWorldDirection(e){return super.getWorldDirection(e).negate()}updateMatrixWorld(e){super.updateMatrixWorld(e),this.matrixWorld.decompose(Ur,Fr,Tn),Tn.x===1&&Tn.y===1&&Tn.z===1?this.matrixWorldInverse.copy(this.matrixWorld).invert():this.matrixWorldInverse.compose(Ur,Fr,Tn.set(1,1,1)).invert()}updateWorldMatrix(e,t){super.updateWorldMatrix(e,t),this.matrixWorld.decompose(Ur,Fr,Tn),Tn.x===1&&Tn.y===1&&Tn.z===1?this.matrixWorldInverse.copy(this.matrixWorld).invert():this.matrixWorldInverse.compose(Ur,Fr,Tn.set(1,1,1)).invert()}clone(){return new this.constructor().copy(this)}}const li=new L,gh=new Le,_h=new Le;class Wt extends Bu{constructor(e=50,t=1,n=.1,i=2e3){super(),this.isPerspectiveCamera=!0,this.type="PerspectiveCamera",this.fov=e,this.zoom=1,this.near=n,this.far=i,this.focus=10,this.aspect=t,this.view=null,this.filmGauge=35,this.filmOffset=0,this.updateProjectionMatrix()}copy(e,t){return super.copy(e,t),this.fov=e.fov,this.zoom=e.zoom,this.near=e.near,this.far=e.far,this.focus=e.focus,this.aspect=e.aspect,this.view=e.view===null?null:Object.assign({},e.view),this.filmGauge=e.filmGauge,this.filmOffset=e.filmOffset,this}setFocalLength(e){const t=.5*this.getFilmHeight()/e;this.fov=Ms*2*Math.atan(t),this.updateProjectionMatrix()}getFocalLength(){const e=Math.tan($s*.5*this.fov);return .5*this.getFilmHeight()/e}getEffectiveFOV(){return Ms*2*Math.atan(Math.tan($s*.5*this.fov)/this.zoom)}getFilmWidth(){return this.filmGauge*Math.min(this.aspect,1)}getFilmHeight(){return this.filmGauge/Math.max(this.aspect,1)}getViewBounds(e,t,n){li.set(-1,-1,.5).applyMatrix4(this.projectionMatrixInverse),t.set(li.x,li.y).multiplyScalar(-e/li.z),li.set(1,1,.5).applyMatrix4(this.projectionMatrixInverse),n.set(li.x,li.y).multiplyScalar(-e/li.z)}getViewSize(e,t){return this.getViewBounds(e,gh,_h),t.subVectors(_h,gh)}setViewOffset(e,t,n,i,r,a){this.aspect=e/t,this.view===null&&(this.view={enabled:!0,fullWidth:1,fullHeight:1,offsetX:0,offsetY:0,width:1,height:1}),this.view.enabled=!0,this.view.fullWidth=e,this.view.fullHeight=t,this.view.offsetX=n,this.view.offsetY=i,this.view.width=r,this.view.height=a,this.updateProjectionMatrix()}clearViewOffset(){this.view!==null&&(this.view.enabled=!1),this.updateProjectionMatrix()}updateProjectionMatrix(){const e=this.near;let t=e*Math.tan($s*.5*this.fov)/this.zoom,n=2*t,i=this.aspect*n,r=-.5*i;const a=this.view;if(this.view!==null&&this.view.enabled){const l=a.fullWidth,c=a.fullHeight;r+=a.offsetX*i/l,t-=a.offsetY*n/c,i*=a.width/l,n*=a.height/c}const o=this.filmOffset;o!==0&&(r+=e*o/this.getFilmWidth()),this.projectionMatrix.makePerspective(r,r+i,t,t-n,e,this.far,this.coordinateSystem,this.reversedDepth),this.projectionMatrixInverse.copy(this.projectionMatrix).invert()}toJSON(e){const t=super.toJSON(e);return t.object.fov=this.fov,t.object.zoom=this.zoom,t.object.near=this.near,t.object.far=this.far,t.object.focus=this.focus,t.object.aspect=this.aspect,this.view!==null&&(t.object.view=Object.assign({},this.view)),t.object.filmGauge=this.filmGauge,t.object.filmOffset=this.filmOffset,t}}class Wp extends ic{constructor(){super(new Wt(50,1,.5,500)),this.isSpotLightShadow=!0,this.focus=1,this.aspect=1}updateMatrices(e){const t=this.camera,n=Ms*2*e.angle*this.focus,i=this.mapSize.width/this.mapSize.height*this.aspect,r=e.distance||t.far;(n!==t.fov||i!==t.aspect||r!==t.far)&&(t.fov=n,t.aspect=i,t.far=r,t.updateProjectionMatrix()),super.updateMatrices(e)}copy(e){return super.copy(e),this.focus=e.focus,this}}class Xp extends xa{constructor(e,t,n=0,i=Math.PI/3,r=0,a=2){super(e,t),this.isSpotLight=!0,this.type="SpotLight",this.position.copy(ft.DEFAULT_UP),this.updateMatrix(),this.target=new ft,this.distance=n,this.angle=i,this.penumbra=r,this.decay=a,this.map=null,this.shadow=new Wp}get power(){return this.intensity*Math.PI}set power(e){this.intensity=e/Math.PI}dispose(){super.dispose(),this.shadow.dispose()}copy(e,t){return super.copy(e,t),this.distance=e.distance,this.angle=e.angle,this.penumbra=e.penumbra,this.decay=e.decay,this.target=e.target.clone(),this.map=e.map,this.shadow=e.shadow.clone(),this}toJSON(e){const t=super.toJSON(e);return t.object.distance=this.distance,t.object.angle=this.angle,t.object.decay=this.decay,t.object.penumbra=this.penumbra,t.object.target=this.target.uuid,this.map&&this.map.isTexture&&(t.object.map=this.map.toJSON(e).uuid),t.object.shadow=this.shadow.toJSON(),t}}class Yp extends ic{constructor(){super(new Wt(90,1,.5,500)),this.isPointLightShadow=!0}}class ku extends xa{constructor(e,t,n=0,i=2){super(e,t),this.isPointLight=!0,this.type="PointLight",this.distance=n,this.decay=i,this.shadow=new Yp}get power(){return this.intensity*4*Math.PI}set power(e){this.intensity=e/(4*Math.PI)}dispose(){super.dispose(),this.shadow.dispose()}copy(e,t){return super.copy(e,t),this.distance=e.distance,this.decay=e.decay,this.shadow=e.shadow.clone(),this}toJSON(e){const t=super.toJSON(e);return t.object.distance=this.distance,t.object.decay=this.decay,t.object.shadow=this.shadow.toJSON(),t}}class or extends Bu{constructor(e=-1,t=1,n=1,i=-1,r=.1,a=2e3){super(),this.isOrthographicCamera=!0,this.type="OrthographicCamera",this.zoom=1,this.view=null,this.left=e,this.right=t,this.top=n,this.bottom=i,this.near=r,this.far=a,this.updateProjectionMatrix()}copy(e,t){return super.copy(e,t),this.left=e.left,this.right=e.right,this.top=e.top,this.bottom=e.bottom,this.near=e.near,this.far=e.far,this.zoom=e.zoom,this.view=e.view===null?null:Object.assign({},e.view),this}setViewOffset(e,t,n,i,r,a){this.view===null&&(this.view={enabled:!0,fullWidth:1,fullHeight:1,offsetX:0,offsetY:0,width:1,height:1}),this.view.enabled=!0,this.view.fullWidth=e,this.view.fullHeight=t,this.view.offsetX=n,this.view.offsetY=i,this.view.width=r,this.view.height=a,this.updateProjectionMatrix()}clearViewOffset(){this.view!==null&&(this.view.enabled=!1),this.updateProjectionMatrix()}updateProjectionMatrix(){const e=(this.right-this.left)/(2*this.zoom),t=(this.top-this.bottom)/(2*this.zoom),n=(this.right+this.left)/2,i=(this.top+this.bottom)/2;let r=n-e,a=n+e,o=i+t,l=i-t;if(this.view!==null&&this.view.enabled){const c=(this.right-this.left)/this.view.fullWidth/this.zoom,h=(this.top-this.bottom)/this.view.fullHeight/this.zoom;r+=c*this.view.offsetX,a=r+c*this.view.width,o-=h*this.view.offsetY,l=o-h*this.view.height}this.projectionMatrix.makeOrthographic(r,a,o,l,this.near,this.far,this.coordinateSystem,this.reversedDepth),this.projectionMatrixInverse.copy(this.projectionMatrix).invert()}toJSON(e){const t=super.toJSON(e);return t.object.zoom=this.zoom,t.object.left=this.left,t.object.right=this.right,t.object.top=this.top,t.object.bottom=this.bottom,t.object.near=this.near,t.object.far=this.far,this.view!==null&&(t.object.view=Object.assign({},this.view)),t}}class qp extends ic{constructor(){super(new or(-5,5,5,-5,.5,500)),this.isDirectionalLightShadow=!0}}class Ml extends xa{constructor(e,t){super(e,t),this.isDirectionalLight=!0,this.type="DirectionalLight",this.position.copy(ft.DEFAULT_UP),this.updateMatrix(),this.target=new ft,this.shadow=new qp}dispose(){super.dispose(),this.shadow.dispose()}copy(e){return super.copy(e),this.target=e.target.clone(),this.shadow=e.shadow.clone(),this}toJSON(e){const t=super.toJSON(e);return t.object.shadow=this.shadow.toJSON(),t.object.target=this.target.uuid,t}}class Js{static extractUrlBase(e){const t=e.lastIndexOf("/");return t===-1?"./":e.slice(0,t+1)}static resolveURL(e,t){return typeof e!="string"||e===""?"":(/^https?:\/\//i.test(t)&&/^\//.test(e)&&(t=t.replace(/(^https?:\/\/[^\/]+).*/i,"$1")),/^(https?:)?\/\//i.test(e)||/^data:.*,.*$/i.test(e)||/^blob:.*$/i.test(e)?e:t+e)}}const co=new WeakMap;class jp extends Is{constructor(e){super(e),this.isImageBitmapLoader=!0,typeof createImageBitmap>"u"&&Pe("ImageBitmapLoader: createImageBitmap() not supported."),typeof fetch>"u"&&Pe("ImageBitmapLoader: fetch() not supported."),this.options={premultiplyAlpha:"none"},this._abortController=new AbortController}setOptions(e){return this.options=e,this}load(e,t,n,i){e===void 0&&(e=""),this.path!==void 0&&(e=this.path+e),e=this.manager.resolveURL(e);const r=this,a=Kn.get(`image-bitmap:${e}`);if(a!==void 0){if(r.manager.itemStart(e),a.then){a.then(c=>{if(co.has(a)===!0)i&&i(co.get(a)),r.manager.itemError(e),r.manager.itemEnd(e);else return t&&t(c),r.manager.itemEnd(e),c});return}return setTimeout(function(){t&&t(a),r.manager.itemEnd(e)},0),a}const o={};o.credentials=this.crossOrigin==="anonymous"?"same-origin":"include",o.headers=this.requestHeader,o.signal=typeof AbortSignal.any=="function"?AbortSignal.any([this._abortController.signal,this.manager.abortController.signal]):this._abortController.signal;const l=fetch(e,o).then(function(c){return c.blob()}).then(function(c){return createImageBitmap(c,Object.assign(r.options,{colorSpaceConversion:"none"}))}).then(function(c){return Kn.add(`image-bitmap:${e}`,c),t&&t(c),r.manager.itemEnd(e),c}).catch(function(c){i&&i(c),co.set(l,c),Kn.remove(`image-bitmap:${e}`),r.manager.itemError(e),r.manager.itemEnd(e)});Kn.add(`image-bitmap:${e}`,l),r.manager.itemStart(e)}abort(){return this._abortController.abort(),this._abortController=new AbortController,this}}const Qi=-90,es=1;class Kp extends ft{constructor(e,t,n){super(),this.type="CubeCamera",this.renderTarget=n,this.coordinateSystem=null,this.activeMipmapLevel=0;const i=new Wt(Qi,es,e,t);i.layers=this.layers,this.add(i);const r=new Wt(Qi,es,e,t);r.layers=this.layers,this.add(r);const a=new Wt(Qi,es,e,t);a.layers=this.layers,this.add(a);const o=new Wt(Qi,es,e,t);o.layers=this.layers,this.add(o);const l=new Wt(Qi,es,e,t);l.layers=this.layers,this.add(l);const c=new Wt(Qi,es,e,t);c.layers=this.layers,this.add(c)}updateCoordinateSystem(){const e=this.coordinateSystem,t=this.children.concat(),[n,i,r,a,o,l]=t;for(const c of t)this.remove(c);if(e===Ln)n.up.set(0,1,0),n.lookAt(1,0,0),i.up.set(0,1,0),i.lookAt(-1,0,0),r.up.set(0,0,-1),r.lookAt(0,1,0),a.up.set(0,0,1),a.lookAt(0,-1,0),o.up.set(0,1,0),o.lookAt(0,0,1),l.up.set(0,1,0),l.lookAt(0,0,-1);else if(e===nr)n.up.set(0,-1,0),n.lookAt(-1,0,0),i.up.set(0,-1,0),i.lookAt(1,0,0),r.up.set(0,0,1),r.lookAt(0,1,0),a.up.set(0,0,-1),a.lookAt(0,-1,0),o.up.set(0,-1,0),o.lookAt(0,0,1),l.up.set(0,-1,0),l.lookAt(0,0,-1);else throw new Error("THREE.CubeCamera.updateCoordinateSystem(): Invalid coordinate system: "+e);for(const c of t)this.add(c),c.updateMatrixWorld()}update(e,t){this.parent===null&&this.updateMatrixWorld();const{renderTarget:n,activeMipmapLevel:i}=this;this.coordinateSystem!==e.coordinateSystem&&(this.coordinateSystem=e.coordinateSystem,this.updateCoordinateSystem());const[r,a,o,l,c,h]=this.children,u=e.getRenderTarget(),d=e.getActiveCubeFace(),f=e.getActiveMipmapLevel(),g=e.xr.enabled;e.xr.enabled=!1;const x=n.texture.generateMipmaps;n.texture.generateMipmaps=!1;let p=!1;e.isWebGLRenderer===!0?p=e.state.buffers.depth.getReversed():p=e.reversedDepthBuffer,e.setRenderTarget(n,0,i),p&&e.autoClear===!1&&e.clearDepth(),e.render(t,r),e.setRenderTarget(n,1,i),p&&e.autoClear===!1&&e.clearDepth(),e.render(t,a),e.setRenderTarget(n,2,i),p&&e.autoClear===!1&&e.clearDepth(),e.render(t,o),e.setRenderTarget(n,3,i),p&&e.autoClear===!1&&e.clearDepth(),e.render(t,l),e.setRenderTarget(n,4,i),p&&e.autoClear===!1&&e.clearDepth(),e.render(t,c),n.texture.generateMipmaps=x,e.setRenderTarget(n,5,i),p&&e.autoClear===!1&&e.clearDepth(),e.render(t,h),e.setRenderTarget(u,d,f),e.xr.enabled=g,n.texture.needsPMREMUpdate=!0}}class $p extends Wt{constructor(e=[]){super(),this.isArrayCamera=!0,this.isMultiViewCamera=!1,this.cameras=e}}class Zp{constructor(){this._previousTime=0,this._currentTime=0,this._startTime=performance.now(),this._delta=0,this._elapsed=0,this._timescale=1,this._document=null,this._pageVisibilityHandler=null}connect(e){this._document=e,e.hidden!==void 0&&(this._pageVisibilityHandler=Jp.bind(this),e.addEventListener("visibilitychange",this._pageVisibilityHandler,!1))}disconnect(){this._pageVisibilityHandler!==null&&(this._document.removeEventListener("visibilitychange",this._pageVisibilityHandler),this._pageVisibilityHandler=null),this._document=null}getDelta(){return this._delta/1e3}getElapsed(){return this._elapsed/1e3}getTimescale(){return this._timescale}setTimescale(e){return this._timescale=e,this}reset(){return this._currentTime=performance.now()-this._startTime,this}dispose(){this.disconnect()}update(e){return this._pageVisibilityHandler!==null&&this._document.hidden===!0?this._delta=0:(this._previousTime=this._currentTime,this._currentTime=(e!==void 0?e:performance.now())-this._startTime,this._delta=(this._currentTime-this._previousTime)*this._timescale,this._elapsed+=this._delta),this}}function Jp(){this._document.hidden===!1&&this.reset()}const sc="\\[\\]\\.:\\/",Qp=new RegExp("["+sc+"]","g"),rc="[^"+sc+"]",em="[^"+sc.replace("\\.","")+"]",tm=/((?:WC+[\/:])*)/.source.replace("WC",rc),nm=/(WCOD+)?/.source.replace("WCOD",em),im=/(?:\.(WC+)(?:\[(.+)\])?)?/.source.replace("WC",rc),sm=/\.(WC+)(?:\[(.+)\])?/.source.replace("WC",rc),rm=new RegExp("^"+tm+nm+im+sm+"$"),am=["material","materials","bones","map"];class om{constructor(e,t,n){const i=n||st.parseTrackName(t);this._targetGroup=e,this._bindings=e.subscribe_(t,i)}getValue(e,t){this.bind();const n=this._targetGroup.nCachedObjects_,i=this._bindings[n];i!==void 0&&i.getValue(e,t)}setValue(e,t){const n=this._bindings;for(let i=this._targetGroup.nCachedObjects_,r=n.length;i!==r;++i)n[i].setValue(e,t)}bind(){const e=this._bindings;for(let t=this._targetGroup.nCachedObjects_,n=e.length;t!==n;++t)e[t].bind()}unbind(){const e=this._bindings;for(let t=this._targetGroup.nCachedObjects_,n=e.length;t!==n;++t)e[t].unbind()}}class st{constructor(e,t,n){this.path=t,this.parsedPath=n||st.parseTrackName(t),this.node=st.findNode(e,this.parsedPath.nodeName),this.rootNode=e,this.getValue=this._getValue_unbound,this.setValue=this._setValue_unbound}static create(e,t,n){return e&&e.isAnimationObjectGroup?new st.Composite(e,t,n):new st(e,t,n)}static sanitizeNodeName(e){return e.replace(/\s/g,"_").replace(Qp,"")}static parseTrackName(e){const t=rm.exec(e);if(t===null)throw new Error("PropertyBinding: Cannot parse trackName: "+e);const n={nodeName:t[2],objectName:t[3],objectIndex:t[4],propertyName:t[5],propertyIndex:t[6]},i=n.nodeName&&n.nodeName.lastIndexOf(".");if(i!==void 0&&i!==-1){const r=n.nodeName.substring(i+1);am.indexOf(r)!==-1&&(n.nodeName=n.nodeName.substring(0,i),n.objectName=r)}if(n.propertyName===null||n.propertyName.length===0)throw new Error("PropertyBinding: can not parse propertyName from trackName: "+e);return n}static findNode(e,t){if(t===void 0||t===""||t==="."||t===-1||t===e.name||t===e.uuid)return e;if(e.skeleton){const n=e.skeleton.getBoneByName(t);if(n!==void 0)return n}if(e.children){const n=function(r){for(let a=0;a<r.length;a++){const o=r[a];if(o.name===t||o.uuid===t)return o;const l=n(o.children);if(l)return l}return null},i=n(e.children);if(i)return i}return null}_getValue_unavailable(){}_setValue_unavailable(){}_getValue_direct(e,t){e[t]=this.targetObject[this.propertyName]}_getValue_array(e,t){const n=this.resolvedProperty;for(let i=0,r=n.length;i!==r;++i)e[t++]=n[i]}_getValue_arrayElement(e,t){e[t]=this.resolvedProperty[this.propertyIndex]}_getValue_toArray(e,t){this.resolvedProperty.toArray(e,t)}_setValue_direct(e,t){this.targetObject[this.propertyName]=e[t]}_setValue_direct_setNeedsUpdate(e,t){this.targetObject[this.propertyName]=e[t],this.targetObject.needsUpdate=!0}_setValue_direct_setMatrixWorldNeedsUpdate(e,t){this.targetObject[this.propertyName]=e[t],this.targetObject.matrixWorldNeedsUpdate=!0}_setValue_array(e,t){const n=this.resolvedProperty;for(let i=0,r=n.length;i!==r;++i)n[i]=e[t++]}_setValue_array_setNeedsUpdate(e,t){const n=this.resolvedProperty;for(let i=0,r=n.length;i!==r;++i)n[i]=e[t++];this.targetObject.needsUpdate=!0}_setValue_array_setMatrixWorldNeedsUpdate(e,t){const n=this.resolvedProperty;for(let i=0,r=n.length;i!==r;++i)n[i]=e[t++];this.targetObject.matrixWorldNeedsUpdate=!0}_setValue_arrayElement(e,t){this.resolvedProperty[this.propertyIndex]=e[t]}_setValue_arrayElement_setNeedsUpdate(e,t){this.resolvedProperty[this.propertyIndex]=e[t],this.targetObject.needsUpdate=!0}_setValue_arrayElement_setMatrixWorldNeedsUpdate(e,t){this.resolvedProperty[this.propertyIndex]=e[t],this.targetObject.matrixWorldNeedsUpdate=!0}_setValue_fromArray(e,t){this.resolvedProperty.fromArray(e,t)}_setValue_fromArray_setNeedsUpdate(e,t){this.resolvedProperty.fromArray(e,t),this.targetObject.needsUpdate=!0}_setValue_fromArray_setMatrixWorldNeedsUpdate(e,t){this.resolvedProperty.fromArray(e,t),this.targetObject.matrixWorldNeedsUpdate=!0}_getValue_unbound(e,t){this.bind(),this.getValue(e,t)}_setValue_unbound(e,t){this.bind(),this.setValue(e,t)}bind(){let e=this.node;const t=this.parsedPath,n=t.objectName,i=t.propertyName;let r=t.propertyIndex;if(e||(e=st.findNode(this.rootNode,t.nodeName),this.node=e),this.getValue=this._getValue_unavailable,this.setValue=this._setValue_unavailable,!e){Pe("PropertyBinding: No target node found for track: "+this.path+".");return}if(n){let c=t.objectIndex;switch(n){case"materials":if(!e.material){Ue("PropertyBinding: Can not bind to material as node does not have a material.",this);return}if(!e.material.materials){Ue("PropertyBinding: Can not bind to material.materials as node.material does not have a materials array.",this);return}e=e.material.materials;break;case"bones":if(!e.skeleton){Ue("PropertyBinding: Can not bind to bones as node does not have a skeleton.",this);return}e=e.skeleton.bones;for(let h=0;h<e.length;h++)if(e[h].name===c){c=h;break}break;case"map":if("map"in e){e=e.map;break}if(!e.material){Ue("PropertyBinding: Can not bind to material as node does not have a material.",this);return}if(!e.material.map){Ue("PropertyBinding: Can not bind to material.map as node.material does not have a map.",this);return}e=e.material.map;break;default:if(e[n]===void 0){Ue("PropertyBinding: Can not bind to objectName of node undefined.",this);return}e=e[n]}if(c!==void 0){if(e[c]===void 0){Ue("PropertyBinding: Trying to bind to objectIndex of objectName, but is undefined.",this,e);return}e=e[c]}}const a=e[i];if(a===void 0){const c=t.nodeName;Ue("PropertyBinding: Trying to update property for track: "+c+"."+i+" but it wasn't found.",e);return}let o=this.Versioning.None;this.targetObject=e,e.isMaterial===!0?o=this.Versioning.NeedsUpdate:e.isObject3D===!0&&(o=this.Versioning.MatrixWorldNeedsUpdate);let l=this.BindingType.Direct;if(r!==void 0){if(i==="morphTargetInfluences"){if(!e.geometry){Ue("PropertyBinding: Can not bind to morphTargetInfluences because node does not have a geometry.",this);return}if(!e.geometry.morphAttributes){Ue("PropertyBinding: Can not bind to morphTargetInfluences because node does not have a geometry.morphAttributes.",this);return}e.morphTargetDictionary[r]!==void 0&&(r=e.morphTargetDictionary[r])}l=this.BindingType.ArrayElement,this.resolvedProperty=a,this.propertyIndex=r}else a.fromArray!==void 0&&a.toArray!==void 0?(l=this.BindingType.HasFromToArray,this.resolvedProperty=a):Array.isArray(a)?(l=this.BindingType.EntireArray,this.resolvedProperty=a):this.propertyName=i;this.getValue=this.GetterByBindingType[l],this.setValue=this.SetterByBindingTypeAndVersioning[l][o]}unbind(){this.node=null,this.getValue=this._getValue_unbound,this.setValue=this._setValue_unbound}}st.Composite=om;st.prototype.BindingType={Direct:0,EntireArray:1,ArrayElement:2,HasFromToArray:3};st.prototype.Versioning={None:0,NeedsUpdate:1,MatrixWorldNeedsUpdate:2};st.prototype.GetterByBindingType=[st.prototype._getValue_direct,st.prototype._getValue_array,st.prototype._getValue_arrayElement,st.prototype._getValue_toArray];st.prototype.SetterByBindingTypeAndVersioning=[[st.prototype._setValue_direct,st.prototype._setValue_direct_setNeedsUpdate,st.prototype._setValue_direct_setMatrixWorldNeedsUpdate],[st.prototype._setValue_array,st.prototype._setValue_array_setNeedsUpdate,st.prototype._setValue_array_setMatrixWorldNeedsUpdate],[st.prototype._setValue_arrayElement,st.prototype._setValue_arrayElement_setNeedsUpdate,st.prototype._setValue_arrayElement_setMatrixWorldNeedsUpdate],[st.prototype._setValue_fromArray,st.prototype._setValue_fromArray_setNeedsUpdate,st.prototype._setValue_fromArray_setMatrixWorldNeedsUpdate]];const vh=new Ve;class lm{constructor(e,t,n=0,i=1/0){this.ray=new Rs(e,t),this.near=n,this.far=i,this.camera=null,this.layers=new $l,this.params={Mesh:{},Line:{threshold:1},LOD:{},Points:{threshold:1},Sprite:{}}}set(e,t){this.ray.set(e,t)}setFromCamera(e,t){t.isPerspectiveCamera?(this.ray.origin.setFromMatrixPosition(t.matrixWorld),this.ray.direction.set(e.x,e.y,.5).unproject(t).sub(this.ray.origin).normalize(),this.camera=t):t.isOrthographicCamera?(this.ray.origin.set(e.x,e.y,(t.near+t.far)/(t.near-t.far)).unproject(t),this.ray.direction.set(0,0,-1).transformDirection(t.matrixWorld),this.camera=t):Ue("Raycaster: Unsupported camera type: "+t.type)}setFromXRController(e){return vh.identity().extractRotation(e.matrixWorld),this.ray.origin.setFromMatrixPosition(e.matrixWorld),this.ray.direction.set(0,0,-1).applyMatrix4(vh),this}intersectObject(e,t=!0,n=[]){return yl(e,this,n,t),n.sort(xh),n}intersectObjects(e,t=!0,n=[]){for(let i=0,r=e.length;i<r;i++)yl(e[i],this,n,t);return n.sort(xh),n}}function xh(s,e){return s.distance-e.distance}function yl(s,e,t,n){let i=!0;if(s.layers.test(e.layers)&&s.raycast(e,t)===!1&&(i=!1),i===!0&&n===!0){const r=s.children;for(let a=0,o=r.length;a<o;a++)yl(r[a],e,t,!0)}}class Mh{constructor(e=1,t=0,n=0){this.radius=e,this.phi=t,this.theta=n}set(e,t,n){return this.radius=e,this.phi=t,this.theta=n,this}copy(e){return this.radius=e.radius,this.phi=e.phi,this.theta=e.theta,this}makeSafe(){return this.phi=Xe(this.phi,1e-6,Math.PI-1e-6),this}setFromVector3(e){return this.setFromCartesianCoords(e.x,e.y,e.z)}setFromCartesianCoords(e,t,n){return this.radius=Math.sqrt(e*e+t*t+n*n),this.radius===0?(this.theta=0,this.phi=0):(this.theta=Math.atan2(e,n),this.phi=Math.acos(Xe(t/this.radius,-1,1))),this}clone(){return new this.constructor().copy(this)}}class cm extends Ni{constructor(e,t=null){super(),this.object=e,this.domElement=t,this.enabled=!0,this.state=-1,this.keys={},this.mouseButtons={LEFT:null,MIDDLE:null,RIGHT:null},this.touches={ONE:null,TWO:null}}connect(e){if(e===void 0){Pe("Controls: connect() now requires an element.");return}this.domElement!==null&&this.disconnect(),this.domElement=e}disconnect(){}dispose(){}update(){}}function yh(s,e,t,n){const i=hm(n);switch(t){case xu:return s*e;case ma:return s*e/i.components*i.byteLength;case Gl:return s*e/i.components*i.byteLength;case xs:return s*e*2/i.components*i.byteLength;case Wl:return s*e*2/i.components*i.byteLength;case Mu:return s*e*3/i.components*i.byteLength;case un:return s*e*4/i.components*i.byteLength;case Xl:return s*e*4/i.components*i.byteLength;case Kr:case $r:return Math.floor((s+3)/4)*Math.floor((e+3)/4)*8;case Zr:case Jr:return Math.floor((s+3)/4)*Math.floor((e+3)/4)*16;case ko:case zo:return Math.max(s,16)*Math.max(e,8)/4;case Bo:case Vo:return Math.max(s,8)*Math.max(e,8)/2;case Ho:case Go:case Xo:case Yo:return Math.floor((s+3)/4)*Math.floor((e+3)/4)*8;case Wo:case qo:case jo:return Math.floor((s+3)/4)*Math.floor((e+3)/4)*16;case Ko:return Math.floor((s+3)/4)*Math.floor((e+3)/4)*16;case $o:return Math.floor((s+4)/5)*Math.floor((e+3)/4)*16;case Zo:return Math.floor((s+4)/5)*Math.floor((e+4)/5)*16;case Jo:return Math.floor((s+5)/6)*Math.floor((e+4)/5)*16;case Qo:return Math.floor((s+5)/6)*Math.floor((e+5)/6)*16;case el:return Math.floor((s+7)/8)*Math.floor((e+4)/5)*16;case tl:return Math.floor((s+7)/8)*Math.floor((e+5)/6)*16;case nl:return Math.floor((s+7)/8)*Math.floor((e+7)/8)*16;case il:return Math.floor((s+9)/10)*Math.floor((e+4)/5)*16;case sl:return Math.floor((s+9)/10)*Math.floor((e+5)/6)*16;case rl:return Math.floor((s+9)/10)*Math.floor((e+7)/8)*16;case al:return Math.floor((s+9)/10)*Math.floor((e+9)/10)*16;case ol:return Math.floor((s+11)/12)*Math.floor((e+9)/10)*16;case ll:return Math.floor((s+11)/12)*Math.floor((e+11)/12)*16;case cl:case hl:case ul:return Math.ceil(s/4)*Math.ceil(e/4)*16;case dl:case fl:return Math.ceil(s/4)*Math.ceil(e/4)*8;case pl:case ml:return Math.ceil(s/4)*Math.ceil(e/4)*16}throw new Error(`Unable to determine texture byte length for ${t} format.`)}function hm(s){switch(s){case nn:case mu:return{byteLength:1,components:1};case Qs:case gu:case on:return{byteLength:2,components:1};case zl:case Hl:return{byteLength:2,components:4};case Fn:case Vl:case sn:return{byteLength:4,components:1};case _u:case vu:return{byteLength:4,components:3}}throw new Error(`Unknown texture type ${s}.`)}typeof __THREE_DEVTOOLS__<"u"&&__THREE_DEVTOOLS__.dispatchEvent(new CustomEvent("register",{detail:{revision:Ll}}));typeof window<"u"&&(window.__THREE__?Pe("WARNING: Multiple instances of Three.js being imported."):window.__THREE__=Ll);function Vu(){let s=null,e=!1,t=null,n=null;function i(r,a){t(r,a),n=s.requestAnimationFrame(i)}return{start:function(){e!==!0&&t!==null&&(n=s.requestAnimationFrame(i),e=!0)},stop:function(){s.cancelAnimationFrame(n),e=!1},setAnimationLoop:function(r){t=r},setContext:function(r){s=r}}}function um(s){const e=new WeakMap;function t(o,l){const c=o.array,h=o.usage,u=c.byteLength,d=s.createBuffer();s.bindBuffer(l,d),s.bufferData(l,c,h),o.onUploadCallback();let f;if(c instanceof Float32Array)f=s.FLOAT;else if(typeof Float16Array<"u"&&c instanceof Float16Array)f=s.HALF_FLOAT;else if(c instanceof Uint16Array)o.isFloat16BufferAttribute?f=s.HALF_FLOAT:f=s.UNSIGNED_SHORT;else if(c instanceof Int16Array)f=s.SHORT;else if(c instanceof Uint32Array)f=s.UNSIGNED_INT;else if(c instanceof Int32Array)f=s.INT;else if(c instanceof Int8Array)f=s.BYTE;else if(c instanceof Uint8Array)f=s.UNSIGNED_BYTE;else if(c instanceof Uint8ClampedArray)f=s.UNSIGNED_BYTE;else throw new Error("THREE.WebGLAttributes: Unsupported buffer data format: "+c);return{buffer:d,type:f,bytesPerElement:c.BYTES_PER_ELEMENT,version:o.version,size:u}}function n(o,l,c){const h=l.array,u=l.updateRanges;if(s.bindBuffer(c,o),u.length===0)s.bufferSubData(c,0,h);else{u.sort((f,g)=>f.start-g.start);let d=0;for(let f=1;f<u.length;f++){const g=u[d],x=u[f];x.start<=g.start+g.count+1?g.count=Math.max(g.count,x.start+x.count-g.start):(++d,u[d]=x)}u.length=d+1;for(let f=0,g=u.length;f<g;f++){const x=u[f];s.bufferSubData(c,x.start*h.BYTES_PER_ELEMENT,h,x.start,x.count)}l.clearUpdateRanges()}l.onUploadCallback()}function i(o){return o.isInterleavedBufferAttribute&&(o=o.data),e.get(o)}function r(o){o.isInterleavedBufferAttribute&&(o=o.data);const l=e.get(o);l&&(s.deleteBuffer(l.buffer),e.delete(o))}function a(o,l){if(o.isInterleavedBufferAttribute&&(o=o.data),o.isGLBufferAttribute){const h=e.get(o);(!h||h.version<o.version)&&e.set(o,{buffer:o.buffer,type:o.type,bytesPerElement:o.elementSize,version:o.version});return}const c=e.get(o);if(c===void 0)e.set(o,t(o,l));else if(c.version<o.version){if(c.size!==o.array.byteLength)throw new Error("THREE.WebGLAttributes: The size of the buffer attribute's array buffer does not match the original size. Resizing buffer attributes is not supported.");n(c.buffer,o,l),c.version=o.version}}return{get:i,remove:r,update:a}}var dm=`#ifdef USE_ALPHAHASH
	if ( diffuseColor.a < getAlphaHashThreshold( vPosition ) ) discard;
#endif`,fm=`#ifdef USE_ALPHAHASH
	const float ALPHA_HASH_SCALE = 0.05;
	float hash2D( vec2 value ) {
		return fract( 1.0e4 * sin( 17.0 * value.x + 0.1 * value.y ) * ( 0.1 + abs( sin( 13.0 * value.y + value.x ) ) ) );
	}
	float hash3D( vec3 value ) {
		return hash2D( vec2( hash2D( value.xy ), value.z ) );
	}
	float getAlphaHashThreshold( vec3 position ) {
		float maxDeriv = max(
			length( dFdx( position.xyz ) ),
			length( dFdy( position.xyz ) )
		);
		float pixScale = 1.0 / ( ALPHA_HASH_SCALE * maxDeriv );
		vec2 pixScales = vec2(
			exp2( floor( log2( pixScale ) ) ),
			exp2( ceil( log2( pixScale ) ) )
		);
		vec2 alpha = vec2(
			hash3D( floor( pixScales.x * position.xyz ) ),
			hash3D( floor( pixScales.y * position.xyz ) )
		);
		float lerpFactor = fract( log2( pixScale ) );
		float x = ( 1.0 - lerpFactor ) * alpha.x + lerpFactor * alpha.y;
		float a = min( lerpFactor, 1.0 - lerpFactor );
		vec3 cases = vec3(
			x * x / ( 2.0 * a * ( 1.0 - a ) ),
			( x - 0.5 * a ) / ( 1.0 - a ),
			1.0 - ( ( 1.0 - x ) * ( 1.0 - x ) / ( 2.0 * a * ( 1.0 - a ) ) )
		);
		float threshold = ( x < ( 1.0 - a ) )
			? ( ( x < a ) ? cases.x : cases.y )
			: cases.z;
		return clamp( threshold , 1.0e-6, 1.0 );
	}
#endif`,pm=`#ifdef USE_ALPHAMAP
	diffuseColor.a *= texture2D( alphaMap, vAlphaMapUv ).g;
#endif`,mm=`#ifdef USE_ALPHAMAP
	uniform sampler2D alphaMap;
#endif`,gm=`#ifdef USE_ALPHATEST
	#ifdef ALPHA_TO_COVERAGE
	diffuseColor.a = smoothstep( alphaTest, alphaTest + fwidth( diffuseColor.a ), diffuseColor.a );
	if ( diffuseColor.a == 0.0 ) discard;
	#else
	if ( diffuseColor.a < alphaTest ) discard;
	#endif
#endif`,_m=`#ifdef USE_ALPHATEST
	uniform float alphaTest;
#endif`,vm=`#ifdef USE_AOMAP
	float ambientOcclusion = ( texture2D( aoMap, vAoMapUv ).r - 1.0 ) * aoMapIntensity + 1.0;
	reflectedLight.indirectDiffuse *= ambientOcclusion;
	#if defined( USE_CLEARCOAT ) 
		clearcoatSpecularIndirect *= ambientOcclusion;
	#endif
	#if defined( USE_SHEEN ) 
		sheenSpecularIndirect *= ambientOcclusion;
	#endif
	#if defined( USE_ENVMAP ) && defined( STANDARD )
		float dotNV = saturate( dot( geometryNormal, geometryViewDir ) );
		reflectedLight.indirectSpecular *= computeSpecularOcclusion( dotNV, ambientOcclusion, material.roughness );
	#endif
#endif`,xm=`#ifdef USE_AOMAP
	uniform sampler2D aoMap;
	uniform float aoMapIntensity;
#endif`,Mm=`#ifdef USE_BATCHING
	#if ! defined( GL_ANGLE_multi_draw )
	#define gl_DrawID _gl_DrawID
	uniform int _gl_DrawID;
	#endif
	uniform highp sampler2D batchingTexture;
	uniform highp usampler2D batchingIdTexture;
	mat4 getBatchingMatrix( const in float i ) {
		int size = textureSize( batchingTexture, 0 ).x;
		int j = int( i ) * 4;
		int x = j % size;
		int y = j / size;
		vec4 v1 = texelFetch( batchingTexture, ivec2( x, y ), 0 );
		vec4 v2 = texelFetch( batchingTexture, ivec2( x + 1, y ), 0 );
		vec4 v3 = texelFetch( batchingTexture, ivec2( x + 2, y ), 0 );
		vec4 v4 = texelFetch( batchingTexture, ivec2( x + 3, y ), 0 );
		return mat4( v1, v2, v3, v4 );
	}
	float getIndirectIndex( const in int i ) {
		int size = textureSize( batchingIdTexture, 0 ).x;
		int x = i % size;
		int y = i / size;
		return float( texelFetch( batchingIdTexture, ivec2( x, y ), 0 ).r );
	}
#endif
#ifdef USE_BATCHING_COLOR
	uniform sampler2D batchingColorTexture;
	vec4 getBatchingColor( const in float i ) {
		int size = textureSize( batchingColorTexture, 0 ).x;
		int j = int( i );
		int x = j % size;
		int y = j / size;
		return texelFetch( batchingColorTexture, ivec2( x, y ), 0 );
	}
#endif`,ym=`#ifdef USE_BATCHING
	mat4 batchingMatrix = getBatchingMatrix( getIndirectIndex( gl_DrawID ) );
#endif`,Sm=`vec3 transformed = vec3( position );
#ifdef USE_ALPHAHASH
	vPosition = vec3( position );
#endif`,bm=`vec3 objectNormal = vec3( normal );
#ifdef USE_TANGENT
	vec3 objectTangent = vec3( tangent.xyz );
#endif`,Em=`float G_BlinnPhong_Implicit( ) {
	return 0.25;
}
float D_BlinnPhong( const in float shininess, const in float dotNH ) {
	return RECIPROCAL_PI * ( shininess * 0.5 + 1.0 ) * pow( dotNH, shininess );
}
vec3 BRDF_BlinnPhong( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, const in vec3 specularColor, const in float shininess ) {
	vec3 halfDir = normalize( lightDir + viewDir );
	float dotNH = saturate( dot( normal, halfDir ) );
	float dotVH = saturate( dot( viewDir, halfDir ) );
	vec3 F = F_Schlick( specularColor, 1.0, dotVH );
	float G = G_BlinnPhong_Implicit( );
	float D = D_BlinnPhong( shininess, dotNH );
	return F * ( G * D );
} // validated`,Tm=`#ifdef USE_IRIDESCENCE
	const mat3 XYZ_TO_REC709 = mat3(
		 3.2404542, -0.9692660,  0.0556434,
		-1.5371385,  1.8760108, -0.2040259,
		-0.4985314,  0.0415560,  1.0572252
	);
	vec3 Fresnel0ToIor( vec3 fresnel0 ) {
		vec3 sqrtF0 = sqrt( fresnel0 );
		return ( vec3( 1.0 ) + sqrtF0 ) / ( vec3( 1.0 ) - sqrtF0 );
	}
	vec3 IorToFresnel0( vec3 transmittedIor, float incidentIor ) {
		return pow2( ( transmittedIor - vec3( incidentIor ) ) / ( transmittedIor + vec3( incidentIor ) ) );
	}
	float IorToFresnel0( float transmittedIor, float incidentIor ) {
		return pow2( ( transmittedIor - incidentIor ) / ( transmittedIor + incidentIor ));
	}
	vec3 evalSensitivity( float OPD, vec3 shift ) {
		float phase = 2.0 * PI * OPD * 1.0e-9;
		vec3 val = vec3( 5.4856e-13, 4.4201e-13, 5.2481e-13 );
		vec3 pos = vec3( 1.6810e+06, 1.7953e+06, 2.2084e+06 );
		vec3 var = vec3( 4.3278e+09, 9.3046e+09, 6.6121e+09 );
		vec3 xyz = val * sqrt( 2.0 * PI * var ) * cos( pos * phase + shift ) * exp( - pow2( phase ) * var );
		xyz.x += 9.7470e-14 * sqrt( 2.0 * PI * 4.5282e+09 ) * cos( 2.2399e+06 * phase + shift[ 0 ] ) * exp( - 4.5282e+09 * pow2( phase ) );
		xyz /= 1.0685e-7;
		vec3 rgb = XYZ_TO_REC709 * xyz;
		return rgb;
	}
	vec3 evalIridescence( float outsideIOR, float eta2, float cosTheta1, float thinFilmThickness, vec3 baseF0 ) {
		vec3 I;
		float iridescenceIOR = mix( outsideIOR, eta2, smoothstep( 0.0, 0.03, thinFilmThickness ) );
		float sinTheta2Sq = pow2( outsideIOR / iridescenceIOR ) * ( 1.0 - pow2( cosTheta1 ) );
		float cosTheta2Sq = 1.0 - sinTheta2Sq;
		if ( cosTheta2Sq < 0.0 ) {
			return vec3( 1.0 );
		}
		float cosTheta2 = sqrt( cosTheta2Sq );
		float R0 = IorToFresnel0( iridescenceIOR, outsideIOR );
		float R12 = F_Schlick( R0, 1.0, cosTheta1 );
		float T121 = 1.0 - R12;
		float phi12 = 0.0;
		if ( iridescenceIOR < outsideIOR ) phi12 = PI;
		float phi21 = PI - phi12;
		vec3 baseIOR = Fresnel0ToIor( clamp( baseF0, 0.0, 0.9999 ) );		vec3 R1 = IorToFresnel0( baseIOR, iridescenceIOR );
		vec3 R23 = F_Schlick( R1, 1.0, cosTheta2 );
		vec3 phi23 = vec3( 0.0 );
		if ( baseIOR[ 0 ] < iridescenceIOR ) phi23[ 0 ] = PI;
		if ( baseIOR[ 1 ] < iridescenceIOR ) phi23[ 1 ] = PI;
		if ( baseIOR[ 2 ] < iridescenceIOR ) phi23[ 2 ] = PI;
		float OPD = 2.0 * iridescenceIOR * thinFilmThickness * cosTheta2;
		vec3 phi = vec3( phi21 ) + phi23;
		vec3 R123 = clamp( R12 * R23, 1e-5, 0.9999 );
		vec3 r123 = sqrt( R123 );
		vec3 Rs = pow2( T121 ) * R23 / ( vec3( 1.0 ) - R123 );
		vec3 C0 = R12 + Rs;
		I = C0;
		vec3 Cm = Rs - T121;
		for ( int m = 1; m <= 2; ++ m ) {
			Cm *= r123;
			vec3 Sm = 2.0 * evalSensitivity( float( m ) * OPD, float( m ) * phi );
			I += Cm * Sm;
		}
		return max( I, vec3( 0.0 ) );
	}
#endif`,Am=`#ifdef USE_BUMPMAP
	uniform sampler2D bumpMap;
	uniform float bumpScale;
	vec2 dHdxy_fwd() {
		vec2 dSTdx = dFdx( vBumpMapUv );
		vec2 dSTdy = dFdy( vBumpMapUv );
		float Hll = bumpScale * texture2D( bumpMap, vBumpMapUv ).x;
		float dBx = bumpScale * texture2D( bumpMap, vBumpMapUv + dSTdx ).x - Hll;
		float dBy = bumpScale * texture2D( bumpMap, vBumpMapUv + dSTdy ).x - Hll;
		return vec2( dBx, dBy );
	}
	vec3 perturbNormalArb( vec3 surf_pos, vec3 surf_norm, vec2 dHdxy, float faceDirection ) {
		vec3 vSigmaX = normalize( dFdx( surf_pos.xyz ) );
		vec3 vSigmaY = normalize( dFdy( surf_pos.xyz ) );
		vec3 vN = surf_norm;
		vec3 R1 = cross( vSigmaY, vN );
		vec3 R2 = cross( vN, vSigmaX );
		float fDet = dot( vSigmaX, R1 ) * faceDirection;
		vec3 vGrad = sign( fDet ) * ( dHdxy.x * R1 + dHdxy.y * R2 );
		return normalize( abs( fDet ) * surf_norm - vGrad );
	}
#endif`,wm=`#if NUM_CLIPPING_PLANES > 0
	vec4 plane;
	#ifdef ALPHA_TO_COVERAGE
		float distanceToPlane, distanceGradient;
		float clipOpacity = 1.0;
		#pragma unroll_loop_start
		for ( int i = 0; i < UNION_CLIPPING_PLANES; i ++ ) {
			plane = clippingPlanes[ i ];
			distanceToPlane = - dot( vClipPosition, plane.xyz ) + plane.w;
			distanceGradient = fwidth( distanceToPlane ) / 2.0;
			clipOpacity *= smoothstep( - distanceGradient, distanceGradient, distanceToPlane );
			if ( clipOpacity == 0.0 ) discard;
		}
		#pragma unroll_loop_end
		#if UNION_CLIPPING_PLANES < NUM_CLIPPING_PLANES
			float unionClipOpacity = 1.0;
			#pragma unroll_loop_start
			for ( int i = UNION_CLIPPING_PLANES; i < NUM_CLIPPING_PLANES; i ++ ) {
				plane = clippingPlanes[ i ];
				distanceToPlane = - dot( vClipPosition, plane.xyz ) + plane.w;
				distanceGradient = fwidth( distanceToPlane ) / 2.0;
				unionClipOpacity *= 1.0 - smoothstep( - distanceGradient, distanceGradient, distanceToPlane );
			}
			#pragma unroll_loop_end
			clipOpacity *= 1.0 - unionClipOpacity;
		#endif
		diffuseColor.a *= clipOpacity;
		if ( diffuseColor.a == 0.0 ) discard;
	#else
		#pragma unroll_loop_start
		for ( int i = 0; i < UNION_CLIPPING_PLANES; i ++ ) {
			plane = clippingPlanes[ i ];
			if ( dot( vClipPosition, plane.xyz ) > plane.w ) discard;
		}
		#pragma unroll_loop_end
		#if UNION_CLIPPING_PLANES < NUM_CLIPPING_PLANES
			bool clipped = true;
			#pragma unroll_loop_start
			for ( int i = UNION_CLIPPING_PLANES; i < NUM_CLIPPING_PLANES; i ++ ) {
				plane = clippingPlanes[ i ];
				clipped = ( dot( vClipPosition, plane.xyz ) > plane.w ) && clipped;
			}
			#pragma unroll_loop_end
			if ( clipped ) discard;
		#endif
	#endif
#endif`,Rm=`#if NUM_CLIPPING_PLANES > 0
	varying vec3 vClipPosition;
	uniform vec4 clippingPlanes[ NUM_CLIPPING_PLANES ];
#endif`,Cm=`#if NUM_CLIPPING_PLANES > 0
	varying vec3 vClipPosition;
#endif`,Pm=`#if NUM_CLIPPING_PLANES > 0
	vClipPosition = - mvPosition.xyz;
#endif`,Dm=`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA )
	diffuseColor *= vColor;
#endif`,Lm=`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA )
	varying vec4 vColor;
#endif`,Im=`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA ) || defined( USE_INSTANCING_COLOR ) || defined( USE_BATCHING_COLOR )
	varying vec4 vColor;
#endif`,Nm=`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA ) || defined( USE_INSTANCING_COLOR ) || defined( USE_BATCHING_COLOR )
	vColor = vec4( 1.0 );
#endif
#ifdef USE_COLOR_ALPHA
	vColor *= color;
#elif defined( USE_COLOR )
	vColor.rgb *= color;
#endif
#ifdef USE_INSTANCING_COLOR
	vColor.rgb *= instanceColor.rgb;
#endif
#ifdef USE_BATCHING_COLOR
	vColor *= getBatchingColor( getIndirectIndex( gl_DrawID ) );
#endif`,Um=`#define PI 3.141592653589793
#define PI2 6.283185307179586
#define PI_HALF 1.5707963267948966
#define RECIPROCAL_PI 0.3183098861837907
#define RECIPROCAL_PI2 0.15915494309189535
#define EPSILON 1e-6
#ifndef saturate
#define saturate( a ) clamp( a, 0.0, 1.0 )
#endif
#define whiteComplement( a ) ( 1.0 - saturate( a ) )
float pow2( const in float x ) { return x*x; }
vec3 pow2( const in vec3 x ) { return x*x; }
float pow3( const in float x ) { return x*x*x; }
float pow4( const in float x ) { float x2 = x*x; return x2*x2; }
float max3( const in vec3 v ) { return max( max( v.x, v.y ), v.z ); }
float average( const in vec3 v ) { return dot( v, vec3( 0.3333333 ) ); }
highp float rand( const in vec2 uv ) {
	const highp float a = 12.9898, b = 78.233, c = 43758.5453;
	highp float dt = dot( uv.xy, vec2( a,b ) ), sn = mod( dt, PI );
	return fract( sin( sn ) * c );
}
#ifdef HIGH_PRECISION
	float precisionSafeLength( vec3 v ) { return length( v ); }
#else
	float precisionSafeLength( vec3 v ) {
		float maxComponent = max3( abs( v ) );
		return length( v / maxComponent ) * maxComponent;
	}
#endif
struct IncidentLight {
	vec3 color;
	vec3 direction;
	bool visible;
};
struct ReflectedLight {
	vec3 directDiffuse;
	vec3 directSpecular;
	vec3 indirectDiffuse;
	vec3 indirectSpecular;
};
#ifdef USE_ALPHAHASH
	varying vec3 vPosition;
#endif
vec3 transformDirection( in vec3 dir, in mat4 matrix ) {
	return normalize( ( matrix * vec4( dir, 0.0 ) ).xyz );
}
vec3 inverseTransformDirection( in vec3 dir, in mat4 matrix ) {
	return normalize( ( vec4( dir, 0.0 ) * matrix ).xyz );
}
bool isPerspectiveMatrix( mat4 m ) {
	return m[ 2 ][ 3 ] == - 1.0;
}
vec2 equirectUv( in vec3 dir ) {
	float u = atan( dir.z, dir.x ) * RECIPROCAL_PI2 + 0.5;
	float v = asin( clamp( dir.y, - 1.0, 1.0 ) ) * RECIPROCAL_PI + 0.5;
	return vec2( u, v );
}
vec3 BRDF_Lambert( const in vec3 diffuseColor ) {
	return RECIPROCAL_PI * diffuseColor;
}
vec3 F_Schlick( const in vec3 f0, const in float f90, const in float dotVH ) {
	float fresnel = exp2( ( - 5.55473 * dotVH - 6.98316 ) * dotVH );
	return f0 * ( 1.0 - fresnel ) + ( f90 * fresnel );
}
float F_Schlick( const in float f0, const in float f90, const in float dotVH ) {
	float fresnel = exp2( ( - 5.55473 * dotVH - 6.98316 ) * dotVH );
	return f0 * ( 1.0 - fresnel ) + ( f90 * fresnel );
} // validated`,Fm=`#ifdef ENVMAP_TYPE_CUBE_UV
	#define cubeUV_minMipLevel 4.0
	#define cubeUV_minTileSize 16.0
	float getFace( vec3 direction ) {
		vec3 absDirection = abs( direction );
		float face = - 1.0;
		if ( absDirection.x > absDirection.z ) {
			if ( absDirection.x > absDirection.y )
				face = direction.x > 0.0 ? 0.0 : 3.0;
			else
				face = direction.y > 0.0 ? 1.0 : 4.0;
		} else {
			if ( absDirection.z > absDirection.y )
				face = direction.z > 0.0 ? 2.0 : 5.0;
			else
				face = direction.y > 0.0 ? 1.0 : 4.0;
		}
		return face;
	}
	vec2 getUV( vec3 direction, float face ) {
		vec2 uv;
		if ( face == 0.0 ) {
			uv = vec2( direction.z, direction.y ) / abs( direction.x );
		} else if ( face == 1.0 ) {
			uv = vec2( - direction.x, - direction.z ) / abs( direction.y );
		} else if ( face == 2.0 ) {
			uv = vec2( - direction.x, direction.y ) / abs( direction.z );
		} else if ( face == 3.0 ) {
			uv = vec2( - direction.z, direction.y ) / abs( direction.x );
		} else if ( face == 4.0 ) {
			uv = vec2( - direction.x, direction.z ) / abs( direction.y );
		} else {
			uv = vec2( direction.x, direction.y ) / abs( direction.z );
		}
		return 0.5 * ( uv + 1.0 );
	}
	vec3 bilinearCubeUV( sampler2D envMap, vec3 direction, float mipInt ) {
		float face = getFace( direction );
		float filterInt = max( cubeUV_minMipLevel - mipInt, 0.0 );
		mipInt = max( mipInt, cubeUV_minMipLevel );
		float faceSize = exp2( mipInt );
		highp vec2 uv = getUV( direction, face ) * ( faceSize - 2.0 ) + 1.0;
		if ( face > 2.0 ) {
			uv.y += faceSize;
			face -= 3.0;
		}
		uv.x += face * faceSize;
		uv.x += filterInt * 3.0 * cubeUV_minTileSize;
		uv.y += 4.0 * ( exp2( CUBEUV_MAX_MIP ) - faceSize );
		uv.x *= CUBEUV_TEXEL_WIDTH;
		uv.y *= CUBEUV_TEXEL_HEIGHT;
		#ifdef texture2DGradEXT
			return texture2DGradEXT( envMap, uv, vec2( 0.0 ), vec2( 0.0 ) ).rgb;
		#else
			return texture2D( envMap, uv ).rgb;
		#endif
	}
	#define cubeUV_r0 1.0
	#define cubeUV_m0 - 2.0
	#define cubeUV_r1 0.8
	#define cubeUV_m1 - 1.0
	#define cubeUV_r4 0.4
	#define cubeUV_m4 2.0
	#define cubeUV_r5 0.305
	#define cubeUV_m5 3.0
	#define cubeUV_r6 0.21
	#define cubeUV_m6 4.0
	float roughnessToMip( float roughness ) {
		float mip = 0.0;
		if ( roughness >= cubeUV_r1 ) {
			mip = ( cubeUV_r0 - roughness ) * ( cubeUV_m1 - cubeUV_m0 ) / ( cubeUV_r0 - cubeUV_r1 ) + cubeUV_m0;
		} else if ( roughness >= cubeUV_r4 ) {
			mip = ( cubeUV_r1 - roughness ) * ( cubeUV_m4 - cubeUV_m1 ) / ( cubeUV_r1 - cubeUV_r4 ) + cubeUV_m1;
		} else if ( roughness >= cubeUV_r5 ) {
			mip = ( cubeUV_r4 - roughness ) * ( cubeUV_m5 - cubeUV_m4 ) / ( cubeUV_r4 - cubeUV_r5 ) + cubeUV_m4;
		} else if ( roughness >= cubeUV_r6 ) {
			mip = ( cubeUV_r5 - roughness ) * ( cubeUV_m6 - cubeUV_m5 ) / ( cubeUV_r5 - cubeUV_r6 ) + cubeUV_m5;
		} else {
			mip = - 2.0 * log2( 1.16 * roughness );		}
		return mip;
	}
	vec4 textureCubeUV( sampler2D envMap, vec3 sampleDir, float roughness ) {
		float mip = clamp( roughnessToMip( roughness ), cubeUV_m0, CUBEUV_MAX_MIP );
		float mipF = fract( mip );
		float mipInt = floor( mip );
		vec3 color0 = bilinearCubeUV( envMap, sampleDir, mipInt );
		if ( mipF == 0.0 ) {
			return vec4( color0, 1.0 );
		} else {
			vec3 color1 = bilinearCubeUV( envMap, sampleDir, mipInt + 1.0 );
			return vec4( mix( color0, color1, mipF ), 1.0 );
		}
	}
#endif`,Om=`vec3 transformedNormal = objectNormal;
#ifdef USE_TANGENT
	vec3 transformedTangent = objectTangent;
#endif
#ifdef USE_BATCHING
	mat3 bm = mat3( batchingMatrix );
	transformedNormal /= vec3( dot( bm[ 0 ], bm[ 0 ] ), dot( bm[ 1 ], bm[ 1 ] ), dot( bm[ 2 ], bm[ 2 ] ) );
	transformedNormal = bm * transformedNormal;
	#ifdef USE_TANGENT
		transformedTangent = bm * transformedTangent;
	#endif
#endif
#ifdef USE_INSTANCING
	mat3 im = mat3( instanceMatrix );
	transformedNormal /= vec3( dot( im[ 0 ], im[ 0 ] ), dot( im[ 1 ], im[ 1 ] ), dot( im[ 2 ], im[ 2 ] ) );
	transformedNormal = im * transformedNormal;
	#ifdef USE_TANGENT
		transformedTangent = im * transformedTangent;
	#endif
#endif
transformedNormal = normalMatrix * transformedNormal;
#ifdef FLIP_SIDED
	transformedNormal = - transformedNormal;
#endif
#ifdef USE_TANGENT
	transformedTangent = ( modelViewMatrix * vec4( transformedTangent, 0.0 ) ).xyz;
	#ifdef FLIP_SIDED
		transformedTangent = - transformedTangent;
	#endif
#endif`,Bm=`#ifdef USE_DISPLACEMENTMAP
	uniform sampler2D displacementMap;
	uniform float displacementScale;
	uniform float displacementBias;
#endif`,km=`#ifdef USE_DISPLACEMENTMAP
	transformed += normalize( objectNormal ) * ( texture2D( displacementMap, vDisplacementMapUv ).x * displacementScale + displacementBias );
#endif`,Vm=`#ifdef USE_EMISSIVEMAP
	vec4 emissiveColor = texture2D( emissiveMap, vEmissiveMapUv );
	#ifdef DECODE_VIDEO_TEXTURE_EMISSIVE
		emissiveColor = sRGBTransferEOTF( emissiveColor );
	#endif
	totalEmissiveRadiance *= emissiveColor.rgb;
#endif`,zm=`#ifdef USE_EMISSIVEMAP
	uniform sampler2D emissiveMap;
#endif`,Hm="gl_FragColor = linearToOutputTexel( gl_FragColor );",Gm=`vec4 LinearTransferOETF( in vec4 value ) {
	return value;
}
vec4 sRGBTransferEOTF( in vec4 value ) {
	return vec4( mix( pow( value.rgb * 0.9478672986 + vec3( 0.0521327014 ), vec3( 2.4 ) ), value.rgb * 0.0773993808, vec3( lessThanEqual( value.rgb, vec3( 0.04045 ) ) ) ), value.a );
}
vec4 sRGBTransferOETF( in vec4 value ) {
	return vec4( mix( pow( value.rgb, vec3( 0.41666 ) ) * 1.055 - vec3( 0.055 ), value.rgb * 12.92, vec3( lessThanEqual( value.rgb, vec3( 0.0031308 ) ) ) ), value.a );
}`,Wm=`#ifdef USE_ENVMAP
	#ifdef ENV_WORLDPOS
		vec3 cameraToFrag;
		if ( isOrthographic ) {
			cameraToFrag = normalize( vec3( - viewMatrix[ 0 ][ 2 ], - viewMatrix[ 1 ][ 2 ], - viewMatrix[ 2 ][ 2 ] ) );
		} else {
			cameraToFrag = normalize( vWorldPosition - cameraPosition );
		}
		vec3 worldNormal = inverseTransformDirection( normal, viewMatrix );
		#ifdef ENVMAP_MODE_REFLECTION
			vec3 reflectVec = reflect( cameraToFrag, worldNormal );
		#else
			vec3 reflectVec = refract( cameraToFrag, worldNormal, refractionRatio );
		#endif
	#else
		vec3 reflectVec = vReflect;
	#endif
	#ifdef ENVMAP_TYPE_CUBE
		vec4 envColor = textureCube( envMap, envMapRotation * vec3( flipEnvMap * reflectVec.x, reflectVec.yz ) );
		#ifdef ENVMAP_BLENDING_MULTIPLY
			outgoingLight = mix( outgoingLight, outgoingLight * envColor.xyz, specularStrength * reflectivity );
		#elif defined( ENVMAP_BLENDING_MIX )
			outgoingLight = mix( outgoingLight, envColor.xyz, specularStrength * reflectivity );
		#elif defined( ENVMAP_BLENDING_ADD )
			outgoingLight += envColor.xyz * specularStrength * reflectivity;
		#endif
	#endif
#endif`,Xm=`#ifdef USE_ENVMAP
	uniform float envMapIntensity;
	uniform float flipEnvMap;
	uniform mat3 envMapRotation;
	#ifdef ENVMAP_TYPE_CUBE
		uniform samplerCube envMap;
	#else
		uniform sampler2D envMap;
	#endif
#endif`,Ym=`#ifdef USE_ENVMAP
	uniform float reflectivity;
	#if defined( USE_BUMPMAP ) || defined( USE_NORMALMAP ) || defined( PHONG ) || defined( LAMBERT )
		#define ENV_WORLDPOS
	#endif
	#ifdef ENV_WORLDPOS
		varying vec3 vWorldPosition;
		uniform float refractionRatio;
	#else
		varying vec3 vReflect;
	#endif
#endif`,qm=`#ifdef USE_ENVMAP
	#if defined( USE_BUMPMAP ) || defined( USE_NORMALMAP ) || defined( PHONG ) || defined( LAMBERT )
		#define ENV_WORLDPOS
	#endif
	#ifdef ENV_WORLDPOS
		
		varying vec3 vWorldPosition;
	#else
		varying vec3 vReflect;
		uniform float refractionRatio;
	#endif
#endif`,jm=`#ifdef USE_ENVMAP
	#ifdef ENV_WORLDPOS
		vWorldPosition = worldPosition.xyz;
	#else
		vec3 cameraToVertex;
		if ( isOrthographic ) {
			cameraToVertex = normalize( vec3( - viewMatrix[ 0 ][ 2 ], - viewMatrix[ 1 ][ 2 ], - viewMatrix[ 2 ][ 2 ] ) );
		} else {
			cameraToVertex = normalize( worldPosition.xyz - cameraPosition );
		}
		vec3 worldNormal = inverseTransformDirection( transformedNormal, viewMatrix );
		#ifdef ENVMAP_MODE_REFLECTION
			vReflect = reflect( cameraToVertex, worldNormal );
		#else
			vReflect = refract( cameraToVertex, worldNormal, refractionRatio );
		#endif
	#endif
#endif`,Km=`#ifdef USE_FOG
	vFogDepth = - mvPosition.z;
#endif`,$m=`#ifdef USE_FOG
	varying float vFogDepth;
#endif`,Zm=`#ifdef USE_FOG
	#ifdef FOG_EXP2
		float fogFactor = 1.0 - exp( - fogDensity * fogDensity * vFogDepth * vFogDepth );
	#else
		float fogFactor = smoothstep( fogNear, fogFar, vFogDepth );
	#endif
	gl_FragColor.rgb = mix( gl_FragColor.rgb, fogColor, fogFactor );
#endif`,Jm=`#ifdef USE_FOG
	uniform vec3 fogColor;
	varying float vFogDepth;
	#ifdef FOG_EXP2
		uniform float fogDensity;
	#else
		uniform float fogNear;
		uniform float fogFar;
	#endif
#endif`,Qm=`#ifdef USE_GRADIENTMAP
	uniform sampler2D gradientMap;
#endif
vec3 getGradientIrradiance( vec3 normal, vec3 lightDirection ) {
	float dotNL = dot( normal, lightDirection );
	vec2 coord = vec2( dotNL * 0.5 + 0.5, 0.0 );
	#ifdef USE_GRADIENTMAP
		return vec3( texture2D( gradientMap, coord ).r );
	#else
		vec2 fw = fwidth( coord ) * 0.5;
		return mix( vec3( 0.7 ), vec3( 1.0 ), smoothstep( 0.7 - fw.x, 0.7 + fw.x, coord.x ) );
	#endif
}`,eg=`#ifdef USE_LIGHTMAP
	uniform sampler2D lightMap;
	uniform float lightMapIntensity;
#endif`,tg=`LambertMaterial material;
material.diffuseColor = diffuseColor.rgb;
material.specularStrength = specularStrength;`,ng=`varying vec3 vViewPosition;
struct LambertMaterial {
	vec3 diffuseColor;
	float specularStrength;
};
void RE_Direct_Lambert( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in LambertMaterial material, inout ReflectedLight reflectedLight ) {
	float dotNL = saturate( dot( geometryNormal, directLight.direction ) );
	vec3 irradiance = dotNL * directLight.color;
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
void RE_IndirectDiffuse_Lambert( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in LambertMaterial material, inout ReflectedLight reflectedLight ) {
	reflectedLight.indirectDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
#define RE_Direct				RE_Direct_Lambert
#define RE_IndirectDiffuse		RE_IndirectDiffuse_Lambert`,ig=`uniform bool receiveShadow;
uniform vec3 ambientLightColor;
#if defined( USE_LIGHT_PROBES )
	uniform vec3 lightProbe[ 9 ];
#endif
vec3 shGetIrradianceAt( in vec3 normal, in vec3 shCoefficients[ 9 ] ) {
	float x = normal.x, y = normal.y, z = normal.z;
	vec3 result = shCoefficients[ 0 ] * 0.886227;
	result += shCoefficients[ 1 ] * 2.0 * 0.511664 * y;
	result += shCoefficients[ 2 ] * 2.0 * 0.511664 * z;
	result += shCoefficients[ 3 ] * 2.0 * 0.511664 * x;
	result += shCoefficients[ 4 ] * 2.0 * 0.429043 * x * y;
	result += shCoefficients[ 5 ] * 2.0 * 0.429043 * y * z;
	result += shCoefficients[ 6 ] * ( 0.743125 * z * z - 0.247708 );
	result += shCoefficients[ 7 ] * 2.0 * 0.429043 * x * z;
	result += shCoefficients[ 8 ] * 0.429043 * ( x * x - y * y );
	return result;
}
vec3 getLightProbeIrradiance( const in vec3 lightProbe[ 9 ], const in vec3 normal ) {
	vec3 worldNormal = inverseTransformDirection( normal, viewMatrix );
	vec3 irradiance = shGetIrradianceAt( worldNormal, lightProbe );
	return irradiance;
}
vec3 getAmbientLightIrradiance( const in vec3 ambientLightColor ) {
	vec3 irradiance = ambientLightColor;
	return irradiance;
}
float getDistanceAttenuation( const in float lightDistance, const in float cutoffDistance, const in float decayExponent ) {
	float distanceFalloff = 1.0 / max( pow( lightDistance, decayExponent ), 0.01 );
	if ( cutoffDistance > 0.0 ) {
		distanceFalloff *= pow2( saturate( 1.0 - pow4( lightDistance / cutoffDistance ) ) );
	}
	return distanceFalloff;
}
float getSpotAttenuation( const in float coneCosine, const in float penumbraCosine, const in float angleCosine ) {
	return smoothstep( coneCosine, penumbraCosine, angleCosine );
}
#if NUM_DIR_LIGHTS > 0
	struct DirectionalLight {
		vec3 direction;
		vec3 color;
	};
	uniform DirectionalLight directionalLights[ NUM_DIR_LIGHTS ];
	void getDirectionalLightInfo( const in DirectionalLight directionalLight, out IncidentLight light ) {
		light.color = directionalLight.color;
		light.direction = directionalLight.direction;
		light.visible = true;
	}
#endif
#if NUM_POINT_LIGHTS > 0
	struct PointLight {
		vec3 position;
		vec3 color;
		float distance;
		float decay;
	};
	uniform PointLight pointLights[ NUM_POINT_LIGHTS ];
	void getPointLightInfo( const in PointLight pointLight, const in vec3 geometryPosition, out IncidentLight light ) {
		vec3 lVector = pointLight.position - geometryPosition;
		light.direction = normalize( lVector );
		float lightDistance = length( lVector );
		light.color = pointLight.color;
		light.color *= getDistanceAttenuation( lightDistance, pointLight.distance, pointLight.decay );
		light.visible = ( light.color != vec3( 0.0 ) );
	}
#endif
#if NUM_SPOT_LIGHTS > 0
	struct SpotLight {
		vec3 position;
		vec3 direction;
		vec3 color;
		float distance;
		float decay;
		float coneCos;
		float penumbraCos;
	};
	uniform SpotLight spotLights[ NUM_SPOT_LIGHTS ];
	void getSpotLightInfo( const in SpotLight spotLight, const in vec3 geometryPosition, out IncidentLight light ) {
		vec3 lVector = spotLight.position - geometryPosition;
		light.direction = normalize( lVector );
		float angleCos = dot( light.direction, spotLight.direction );
		float spotAttenuation = getSpotAttenuation( spotLight.coneCos, spotLight.penumbraCos, angleCos );
		if ( spotAttenuation > 0.0 ) {
			float lightDistance = length( lVector );
			light.color = spotLight.color * spotAttenuation;
			light.color *= getDistanceAttenuation( lightDistance, spotLight.distance, spotLight.decay );
			light.visible = ( light.color != vec3( 0.0 ) );
		} else {
			light.color = vec3( 0.0 );
			light.visible = false;
		}
	}
#endif
#if NUM_RECT_AREA_LIGHTS > 0
	struct RectAreaLight {
		vec3 color;
		vec3 position;
		vec3 halfWidth;
		vec3 halfHeight;
	};
	uniform sampler2D ltc_1;	uniform sampler2D ltc_2;
	uniform RectAreaLight rectAreaLights[ NUM_RECT_AREA_LIGHTS ];
#endif
#if NUM_HEMI_LIGHTS > 0
	struct HemisphereLight {
		vec3 direction;
		vec3 skyColor;
		vec3 groundColor;
	};
	uniform HemisphereLight hemisphereLights[ NUM_HEMI_LIGHTS ];
	vec3 getHemisphereLightIrradiance( const in HemisphereLight hemiLight, const in vec3 normal ) {
		float dotNL = dot( normal, hemiLight.direction );
		float hemiDiffuseWeight = 0.5 * dotNL + 0.5;
		vec3 irradiance = mix( hemiLight.groundColor, hemiLight.skyColor, hemiDiffuseWeight );
		return irradiance;
	}
#endif`,sg=`#ifdef USE_ENVMAP
	vec3 getIBLIrradiance( const in vec3 normal ) {
		#ifdef ENVMAP_TYPE_CUBE_UV
			vec3 worldNormal = inverseTransformDirection( normal, viewMatrix );
			vec4 envMapColor = textureCubeUV( envMap, envMapRotation * worldNormal, 1.0 );
			return PI * envMapColor.rgb * envMapIntensity;
		#else
			return vec3( 0.0 );
		#endif
	}
	vec3 getIBLRadiance( const in vec3 viewDir, const in vec3 normal, const in float roughness ) {
		#ifdef ENVMAP_TYPE_CUBE_UV
			vec3 reflectVec = reflect( - viewDir, normal );
			reflectVec = normalize( mix( reflectVec, normal, pow4( roughness ) ) );
			reflectVec = inverseTransformDirection( reflectVec, viewMatrix );
			vec4 envMapColor = textureCubeUV( envMap, envMapRotation * reflectVec, roughness );
			return envMapColor.rgb * envMapIntensity;
		#else
			return vec3( 0.0 );
		#endif
	}
	#ifdef USE_ANISOTROPY
		vec3 getIBLAnisotropyRadiance( const in vec3 viewDir, const in vec3 normal, const in float roughness, const in vec3 bitangent, const in float anisotropy ) {
			#ifdef ENVMAP_TYPE_CUBE_UV
				vec3 bentNormal = cross( bitangent, viewDir );
				bentNormal = normalize( cross( bentNormal, bitangent ) );
				bentNormal = normalize( mix( bentNormal, normal, pow2( pow2( 1.0 - anisotropy * ( 1.0 - roughness ) ) ) ) );
				return getIBLRadiance( viewDir, bentNormal, roughness );
			#else
				return vec3( 0.0 );
			#endif
		}
	#endif
#endif`,rg=`ToonMaterial material;
material.diffuseColor = diffuseColor.rgb;`,ag=`varying vec3 vViewPosition;
struct ToonMaterial {
	vec3 diffuseColor;
};
void RE_Direct_Toon( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in ToonMaterial material, inout ReflectedLight reflectedLight ) {
	vec3 irradiance = getGradientIrradiance( geometryNormal, directLight.direction ) * directLight.color;
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
void RE_IndirectDiffuse_Toon( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in ToonMaterial material, inout ReflectedLight reflectedLight ) {
	reflectedLight.indirectDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
#define RE_Direct				RE_Direct_Toon
#define RE_IndirectDiffuse		RE_IndirectDiffuse_Toon`,og=`BlinnPhongMaterial material;
material.diffuseColor = diffuseColor.rgb;
material.specularColor = specular;
material.specularShininess = shininess;
material.specularStrength = specularStrength;`,lg=`varying vec3 vViewPosition;
struct BlinnPhongMaterial {
	vec3 diffuseColor;
	vec3 specularColor;
	float specularShininess;
	float specularStrength;
};
void RE_Direct_BlinnPhong( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in BlinnPhongMaterial material, inout ReflectedLight reflectedLight ) {
	float dotNL = saturate( dot( geometryNormal, directLight.direction ) );
	vec3 irradiance = dotNL * directLight.color;
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
	reflectedLight.directSpecular += irradiance * BRDF_BlinnPhong( directLight.direction, geometryViewDir, geometryNormal, material.specularColor, material.specularShininess ) * material.specularStrength;
}
void RE_IndirectDiffuse_BlinnPhong( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in BlinnPhongMaterial material, inout ReflectedLight reflectedLight ) {
	reflectedLight.indirectDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
#define RE_Direct				RE_Direct_BlinnPhong
#define RE_IndirectDiffuse		RE_IndirectDiffuse_BlinnPhong`,cg=`PhysicalMaterial material;
material.diffuseColor = diffuseColor.rgb;
material.diffuseContribution = diffuseColor.rgb * ( 1.0 - metalnessFactor );
material.metalness = metalnessFactor;
vec3 dxy = max( abs( dFdx( nonPerturbedNormal ) ), abs( dFdy( nonPerturbedNormal ) ) );
float geometryRoughness = max( max( dxy.x, dxy.y ), dxy.z );
material.roughness = max( roughnessFactor, 0.0525 );material.roughness += geometryRoughness;
material.roughness = min( material.roughness, 1.0 );
#ifdef IOR
	material.ior = ior;
	#ifdef USE_SPECULAR
		float specularIntensityFactor = specularIntensity;
		vec3 specularColorFactor = specularColor;
		#ifdef USE_SPECULAR_COLORMAP
			specularColorFactor *= texture2D( specularColorMap, vSpecularColorMapUv ).rgb;
		#endif
		#ifdef USE_SPECULAR_INTENSITYMAP
			specularIntensityFactor *= texture2D( specularIntensityMap, vSpecularIntensityMapUv ).a;
		#endif
		material.specularF90 = mix( specularIntensityFactor, 1.0, metalnessFactor );
	#else
		float specularIntensityFactor = 1.0;
		vec3 specularColorFactor = vec3( 1.0 );
		material.specularF90 = 1.0;
	#endif
	material.specularColor = min( pow2( ( material.ior - 1.0 ) / ( material.ior + 1.0 ) ) * specularColorFactor, vec3( 1.0 ) ) * specularIntensityFactor;
	material.specularColorBlended = mix( material.specularColor, diffuseColor.rgb, metalnessFactor );
#else
	material.specularColor = vec3( 0.04 );
	material.specularColorBlended = mix( material.specularColor, diffuseColor.rgb, metalnessFactor );
	material.specularF90 = 1.0;
#endif
#ifdef USE_CLEARCOAT
	material.clearcoat = clearcoat;
	material.clearcoatRoughness = clearcoatRoughness;
	material.clearcoatF0 = vec3( 0.04 );
	material.clearcoatF90 = 1.0;
	#ifdef USE_CLEARCOATMAP
		material.clearcoat *= texture2D( clearcoatMap, vClearcoatMapUv ).x;
	#endif
	#ifdef USE_CLEARCOAT_ROUGHNESSMAP
		material.clearcoatRoughness *= texture2D( clearcoatRoughnessMap, vClearcoatRoughnessMapUv ).y;
	#endif
	material.clearcoat = saturate( material.clearcoat );	material.clearcoatRoughness = max( material.clearcoatRoughness, 0.0525 );
	material.clearcoatRoughness += geometryRoughness;
	material.clearcoatRoughness = min( material.clearcoatRoughness, 1.0 );
#endif
#ifdef USE_DISPERSION
	material.dispersion = dispersion;
#endif
#ifdef USE_IRIDESCENCE
	material.iridescence = iridescence;
	material.iridescenceIOR = iridescenceIOR;
	#ifdef USE_IRIDESCENCEMAP
		material.iridescence *= texture2D( iridescenceMap, vIridescenceMapUv ).r;
	#endif
	#ifdef USE_IRIDESCENCE_THICKNESSMAP
		material.iridescenceThickness = (iridescenceThicknessMaximum - iridescenceThicknessMinimum) * texture2D( iridescenceThicknessMap, vIridescenceThicknessMapUv ).g + iridescenceThicknessMinimum;
	#else
		material.iridescenceThickness = iridescenceThicknessMaximum;
	#endif
#endif
#ifdef USE_SHEEN
	material.sheenColor = sheenColor;
	#ifdef USE_SHEEN_COLORMAP
		material.sheenColor *= texture2D( sheenColorMap, vSheenColorMapUv ).rgb;
	#endif
	material.sheenRoughness = clamp( sheenRoughness, 0.0001, 1.0 );
	#ifdef USE_SHEEN_ROUGHNESSMAP
		material.sheenRoughness *= texture2D( sheenRoughnessMap, vSheenRoughnessMapUv ).a;
	#endif
#endif
#ifdef USE_ANISOTROPY
	#ifdef USE_ANISOTROPYMAP
		mat2 anisotropyMat = mat2( anisotropyVector.x, anisotropyVector.y, - anisotropyVector.y, anisotropyVector.x );
		vec3 anisotropyPolar = texture2D( anisotropyMap, vAnisotropyMapUv ).rgb;
		vec2 anisotropyV = anisotropyMat * normalize( 2.0 * anisotropyPolar.rg - vec2( 1.0 ) ) * anisotropyPolar.b;
	#else
		vec2 anisotropyV = anisotropyVector;
	#endif
	material.anisotropy = length( anisotropyV );
	if( material.anisotropy == 0.0 ) {
		anisotropyV = vec2( 1.0, 0.0 );
	} else {
		anisotropyV /= material.anisotropy;
		material.anisotropy = saturate( material.anisotropy );
	}
	material.alphaT = mix( pow2( material.roughness ), 1.0, pow2( material.anisotropy ) );
	material.anisotropyT = tbn[ 0 ] * anisotropyV.x + tbn[ 1 ] * anisotropyV.y;
	material.anisotropyB = tbn[ 1 ] * anisotropyV.x - tbn[ 0 ] * anisotropyV.y;
#endif`,hg=`uniform sampler2D dfgLUT;
struct PhysicalMaterial {
	vec3 diffuseColor;
	vec3 diffuseContribution;
	vec3 specularColor;
	vec3 specularColorBlended;
	float roughness;
	float metalness;
	float specularF90;
	float dispersion;
	#ifdef USE_CLEARCOAT
		float clearcoat;
		float clearcoatRoughness;
		vec3 clearcoatF0;
		float clearcoatF90;
	#endif
	#ifdef USE_IRIDESCENCE
		float iridescence;
		float iridescenceIOR;
		float iridescenceThickness;
		vec3 iridescenceFresnel;
		vec3 iridescenceF0;
		vec3 iridescenceFresnelDielectric;
		vec3 iridescenceFresnelMetallic;
	#endif
	#ifdef USE_SHEEN
		vec3 sheenColor;
		float sheenRoughness;
	#endif
	#ifdef IOR
		float ior;
	#endif
	#ifdef USE_TRANSMISSION
		float transmission;
		float transmissionAlpha;
		float thickness;
		float attenuationDistance;
		vec3 attenuationColor;
	#endif
	#ifdef USE_ANISOTROPY
		float anisotropy;
		float alphaT;
		vec3 anisotropyT;
		vec3 anisotropyB;
	#endif
};
vec3 clearcoatSpecularDirect = vec3( 0.0 );
vec3 clearcoatSpecularIndirect = vec3( 0.0 );
vec3 sheenSpecularDirect = vec3( 0.0 );
vec3 sheenSpecularIndirect = vec3(0.0 );
vec3 Schlick_to_F0( const in vec3 f, const in float f90, const in float dotVH ) {
    float x = clamp( 1.0 - dotVH, 0.0, 1.0 );
    float x2 = x * x;
    float x5 = clamp( x * x2 * x2, 0.0, 0.9999 );
    return ( f - vec3( f90 ) * x5 ) / ( 1.0 - x5 );
}
float V_GGX_SmithCorrelated( const in float alpha, const in float dotNL, const in float dotNV ) {
	float a2 = pow2( alpha );
	float gv = dotNL * sqrt( a2 + ( 1.0 - a2 ) * pow2( dotNV ) );
	float gl = dotNV * sqrt( a2 + ( 1.0 - a2 ) * pow2( dotNL ) );
	return 0.5 / max( gv + gl, EPSILON );
}
float D_GGX( const in float alpha, const in float dotNH ) {
	float a2 = pow2( alpha );
	float denom = pow2( dotNH ) * ( a2 - 1.0 ) + 1.0;
	return RECIPROCAL_PI * a2 / pow2( denom );
}
#ifdef USE_ANISOTROPY
	float V_GGX_SmithCorrelated_Anisotropic( const in float alphaT, const in float alphaB, const in float dotTV, const in float dotBV, const in float dotTL, const in float dotBL, const in float dotNV, const in float dotNL ) {
		float gv = dotNL * length( vec3( alphaT * dotTV, alphaB * dotBV, dotNV ) );
		float gl = dotNV * length( vec3( alphaT * dotTL, alphaB * dotBL, dotNL ) );
		float v = 0.5 / ( gv + gl );
		return v;
	}
	float D_GGX_Anisotropic( const in float alphaT, const in float alphaB, const in float dotNH, const in float dotTH, const in float dotBH ) {
		float a2 = alphaT * alphaB;
		highp vec3 v = vec3( alphaB * dotTH, alphaT * dotBH, a2 * dotNH );
		highp float v2 = dot( v, v );
		float w2 = a2 / v2;
		return RECIPROCAL_PI * a2 * pow2 ( w2 );
	}
#endif
#ifdef USE_CLEARCOAT
	vec3 BRDF_GGX_Clearcoat( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, const in PhysicalMaterial material) {
		vec3 f0 = material.clearcoatF0;
		float f90 = material.clearcoatF90;
		float roughness = material.clearcoatRoughness;
		float alpha = pow2( roughness );
		vec3 halfDir = normalize( lightDir + viewDir );
		float dotNL = saturate( dot( normal, lightDir ) );
		float dotNV = saturate( dot( normal, viewDir ) );
		float dotNH = saturate( dot( normal, halfDir ) );
		float dotVH = saturate( dot( viewDir, halfDir ) );
		vec3 F = F_Schlick( f0, f90, dotVH );
		float V = V_GGX_SmithCorrelated( alpha, dotNL, dotNV );
		float D = D_GGX( alpha, dotNH );
		return F * ( V * D );
	}
#endif
vec3 BRDF_GGX( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, const in PhysicalMaterial material ) {
	vec3 f0 = material.specularColorBlended;
	float f90 = material.specularF90;
	float roughness = material.roughness;
	float alpha = pow2( roughness );
	vec3 halfDir = normalize( lightDir + viewDir );
	float dotNL = saturate( dot( normal, lightDir ) );
	float dotNV = saturate( dot( normal, viewDir ) );
	float dotNH = saturate( dot( normal, halfDir ) );
	float dotVH = saturate( dot( viewDir, halfDir ) );
	vec3 F = F_Schlick( f0, f90, dotVH );
	#ifdef USE_IRIDESCENCE
		F = mix( F, material.iridescenceFresnel, material.iridescence );
	#endif
	#ifdef USE_ANISOTROPY
		float dotTL = dot( material.anisotropyT, lightDir );
		float dotTV = dot( material.anisotropyT, viewDir );
		float dotTH = dot( material.anisotropyT, halfDir );
		float dotBL = dot( material.anisotropyB, lightDir );
		float dotBV = dot( material.anisotropyB, viewDir );
		float dotBH = dot( material.anisotropyB, halfDir );
		float V = V_GGX_SmithCorrelated_Anisotropic( material.alphaT, alpha, dotTV, dotBV, dotTL, dotBL, dotNV, dotNL );
		float D = D_GGX_Anisotropic( material.alphaT, alpha, dotNH, dotTH, dotBH );
	#else
		float V = V_GGX_SmithCorrelated( alpha, dotNL, dotNV );
		float D = D_GGX( alpha, dotNH );
	#endif
	return F * ( V * D );
}
vec2 LTC_Uv( const in vec3 N, const in vec3 V, const in float roughness ) {
	const float LUT_SIZE = 64.0;
	const float LUT_SCALE = ( LUT_SIZE - 1.0 ) / LUT_SIZE;
	const float LUT_BIAS = 0.5 / LUT_SIZE;
	float dotNV = saturate( dot( N, V ) );
	vec2 uv = vec2( roughness, sqrt( 1.0 - dotNV ) );
	uv = uv * LUT_SCALE + LUT_BIAS;
	return uv;
}
float LTC_ClippedSphereFormFactor( const in vec3 f ) {
	float l = length( f );
	return max( ( l * l + f.z ) / ( l + 1.0 ), 0.0 );
}
vec3 LTC_EdgeVectorFormFactor( const in vec3 v1, const in vec3 v2 ) {
	float x = dot( v1, v2 );
	float y = abs( x );
	float a = 0.8543985 + ( 0.4965155 + 0.0145206 * y ) * y;
	float b = 3.4175940 + ( 4.1616724 + y ) * y;
	float v = a / b;
	float theta_sintheta = ( x > 0.0 ) ? v : 0.5 * inversesqrt( max( 1.0 - x * x, 1e-7 ) ) - v;
	return cross( v1, v2 ) * theta_sintheta;
}
vec3 LTC_Evaluate( const in vec3 N, const in vec3 V, const in vec3 P, const in mat3 mInv, const in vec3 rectCoords[ 4 ] ) {
	vec3 v1 = rectCoords[ 1 ] - rectCoords[ 0 ];
	vec3 v2 = rectCoords[ 3 ] - rectCoords[ 0 ];
	vec3 lightNormal = cross( v1, v2 );
	if( dot( lightNormal, P - rectCoords[ 0 ] ) < 0.0 ) return vec3( 0.0 );
	vec3 T1, T2;
	T1 = normalize( V - N * dot( V, N ) );
	T2 = - cross( N, T1 );
	mat3 mat = mInv * transpose( mat3( T1, T2, N ) );
	vec3 coords[ 4 ];
	coords[ 0 ] = mat * ( rectCoords[ 0 ] - P );
	coords[ 1 ] = mat * ( rectCoords[ 1 ] - P );
	coords[ 2 ] = mat * ( rectCoords[ 2 ] - P );
	coords[ 3 ] = mat * ( rectCoords[ 3 ] - P );
	coords[ 0 ] = normalize( coords[ 0 ] );
	coords[ 1 ] = normalize( coords[ 1 ] );
	coords[ 2 ] = normalize( coords[ 2 ] );
	coords[ 3 ] = normalize( coords[ 3 ] );
	vec3 vectorFormFactor = vec3( 0.0 );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 0 ], coords[ 1 ] );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 1 ], coords[ 2 ] );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 2 ], coords[ 3 ] );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 3 ], coords[ 0 ] );
	float result = LTC_ClippedSphereFormFactor( vectorFormFactor );
	return vec3( result );
}
#if defined( USE_SHEEN )
float D_Charlie( float roughness, float dotNH ) {
	float alpha = pow2( roughness );
	float invAlpha = 1.0 / alpha;
	float cos2h = dotNH * dotNH;
	float sin2h = max( 1.0 - cos2h, 0.0078125 );
	return ( 2.0 + invAlpha ) * pow( sin2h, invAlpha * 0.5 ) / ( 2.0 * PI );
}
float V_Neubelt( float dotNV, float dotNL ) {
	return saturate( 1.0 / ( 4.0 * ( dotNL + dotNV - dotNL * dotNV ) ) );
}
vec3 BRDF_Sheen( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, vec3 sheenColor, const in float sheenRoughness ) {
	vec3 halfDir = normalize( lightDir + viewDir );
	float dotNL = saturate( dot( normal, lightDir ) );
	float dotNV = saturate( dot( normal, viewDir ) );
	float dotNH = saturate( dot( normal, halfDir ) );
	float D = D_Charlie( sheenRoughness, dotNH );
	float V = V_Neubelt( dotNV, dotNL );
	return sheenColor * ( D * V );
}
#endif
float IBLSheenBRDF( const in vec3 normal, const in vec3 viewDir, const in float roughness ) {
	float dotNV = saturate( dot( normal, viewDir ) );
	float r2 = roughness * roughness;
	float rInv = 1.0 / ( roughness + 0.1 );
	float a = -1.9362 + 1.0678 * roughness + 0.4573 * r2 - 0.8469 * rInv;
	float b = -0.6014 + 0.5538 * roughness - 0.4670 * r2 - 0.1255 * rInv;
	float DG = exp( a * dotNV + b );
	return saturate( DG );
}
vec3 EnvironmentBRDF( const in vec3 normal, const in vec3 viewDir, const in vec3 specularColor, const in float specularF90, const in float roughness ) {
	float dotNV = saturate( dot( normal, viewDir ) );
	vec2 fab = texture2D( dfgLUT, vec2( roughness, dotNV ) ).rg;
	return specularColor * fab.x + specularF90 * fab.y;
}
#ifdef USE_IRIDESCENCE
void computeMultiscatteringIridescence( const in vec3 normal, const in vec3 viewDir, const in vec3 specularColor, const in float specularF90, const in float iridescence, const in vec3 iridescenceF0, const in float roughness, inout vec3 singleScatter, inout vec3 multiScatter ) {
#else
void computeMultiscattering( const in vec3 normal, const in vec3 viewDir, const in vec3 specularColor, const in float specularF90, const in float roughness, inout vec3 singleScatter, inout vec3 multiScatter ) {
#endif
	float dotNV = saturate( dot( normal, viewDir ) );
	vec2 fab = texture2D( dfgLUT, vec2( roughness, dotNV ) ).rg;
	#ifdef USE_IRIDESCENCE
		vec3 Fr = mix( specularColor, iridescenceF0, iridescence );
	#else
		vec3 Fr = specularColor;
	#endif
	vec3 FssEss = Fr * fab.x + specularF90 * fab.y;
	float Ess = fab.x + fab.y;
	float Ems = 1.0 - Ess;
	vec3 Favg = Fr + ( 1.0 - Fr ) * 0.047619;	vec3 Fms = FssEss * Favg / ( 1.0 - Ems * Favg );
	singleScatter += FssEss;
	multiScatter += Fms * Ems;
}
vec3 BRDF_GGX_Multiscatter( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, const in PhysicalMaterial material ) {
	vec3 singleScatter = BRDF_GGX( lightDir, viewDir, normal, material );
	float dotNL = saturate( dot( normal, lightDir ) );
	float dotNV = saturate( dot( normal, viewDir ) );
	vec2 dfgV = texture2D( dfgLUT, vec2( material.roughness, dotNV ) ).rg;
	vec2 dfgL = texture2D( dfgLUT, vec2( material.roughness, dotNL ) ).rg;
	vec3 FssEss_V = material.specularColorBlended * dfgV.x + material.specularF90 * dfgV.y;
	vec3 FssEss_L = material.specularColorBlended * dfgL.x + material.specularF90 * dfgL.y;
	float Ess_V = dfgV.x + dfgV.y;
	float Ess_L = dfgL.x + dfgL.y;
	float Ems_V = 1.0 - Ess_V;
	float Ems_L = 1.0 - Ess_L;
	vec3 Favg = material.specularColorBlended + ( 1.0 - material.specularColorBlended ) * 0.047619;
	vec3 Fms = FssEss_V * FssEss_L * Favg / ( 1.0 - Ems_V * Ems_L * Favg + EPSILON );
	float compensationFactor = Ems_V * Ems_L;
	vec3 multiScatter = Fms * compensationFactor;
	return singleScatter + multiScatter;
}
#if NUM_RECT_AREA_LIGHTS > 0
	void RE_Direct_RectArea_Physical( const in RectAreaLight rectAreaLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight ) {
		vec3 normal = geometryNormal;
		vec3 viewDir = geometryViewDir;
		vec3 position = geometryPosition;
		vec3 lightPos = rectAreaLight.position;
		vec3 halfWidth = rectAreaLight.halfWidth;
		vec3 halfHeight = rectAreaLight.halfHeight;
		vec3 lightColor = rectAreaLight.color;
		float roughness = material.roughness;
		vec3 rectCoords[ 4 ];
		rectCoords[ 0 ] = lightPos + halfWidth - halfHeight;		rectCoords[ 1 ] = lightPos - halfWidth - halfHeight;
		rectCoords[ 2 ] = lightPos - halfWidth + halfHeight;
		rectCoords[ 3 ] = lightPos + halfWidth + halfHeight;
		vec2 uv = LTC_Uv( normal, viewDir, roughness );
		vec4 t1 = texture2D( ltc_1, uv );
		vec4 t2 = texture2D( ltc_2, uv );
		mat3 mInv = mat3(
			vec3( t1.x, 0, t1.y ),
			vec3(    0, 1,    0 ),
			vec3( t1.z, 0, t1.w )
		);
		vec3 fresnel = ( material.specularColorBlended * t2.x + ( material.specularF90 - material.specularColorBlended ) * t2.y );
		reflectedLight.directSpecular += lightColor * fresnel * LTC_Evaluate( normal, viewDir, position, mInv, rectCoords );
		reflectedLight.directDiffuse += lightColor * material.diffuseContribution * LTC_Evaluate( normal, viewDir, position, mat3( 1.0 ), rectCoords );
		#ifdef USE_CLEARCOAT
			vec3 Ncc = geometryClearcoatNormal;
			vec2 uvClearcoat = LTC_Uv( Ncc, viewDir, material.clearcoatRoughness );
			vec4 t1Clearcoat = texture2D( ltc_1, uvClearcoat );
			vec4 t2Clearcoat = texture2D( ltc_2, uvClearcoat );
			mat3 mInvClearcoat = mat3(
				vec3( t1Clearcoat.x, 0, t1Clearcoat.y ),
				vec3(             0, 1,             0 ),
				vec3( t1Clearcoat.z, 0, t1Clearcoat.w )
			);
			vec3 fresnelClearcoat = material.clearcoatF0 * t2Clearcoat.x + ( material.clearcoatF90 - material.clearcoatF0 ) * t2Clearcoat.y;
			clearcoatSpecularDirect += lightColor * fresnelClearcoat * LTC_Evaluate( Ncc, viewDir, position, mInvClearcoat, rectCoords );
		#endif
	}
#endif
void RE_Direct_Physical( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight ) {
	float dotNL = saturate( dot( geometryNormal, directLight.direction ) );
	vec3 irradiance = dotNL * directLight.color;
	#ifdef USE_CLEARCOAT
		float dotNLcc = saturate( dot( geometryClearcoatNormal, directLight.direction ) );
		vec3 ccIrradiance = dotNLcc * directLight.color;
		clearcoatSpecularDirect += ccIrradiance * BRDF_GGX_Clearcoat( directLight.direction, geometryViewDir, geometryClearcoatNormal, material );
	#endif
	#ifdef USE_SHEEN
 
 		sheenSpecularDirect += irradiance * BRDF_Sheen( directLight.direction, geometryViewDir, geometryNormal, material.sheenColor, material.sheenRoughness );
 
 		float sheenAlbedoV = IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness );
 		float sheenAlbedoL = IBLSheenBRDF( geometryNormal, directLight.direction, material.sheenRoughness );
 
 		float sheenEnergyComp = 1.0 - max3( material.sheenColor ) * max( sheenAlbedoV, sheenAlbedoL );
 
 		irradiance *= sheenEnergyComp;
 
 	#endif
	reflectedLight.directSpecular += irradiance * BRDF_GGX_Multiscatter( directLight.direction, geometryViewDir, geometryNormal, material );
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseContribution );
}
void RE_IndirectDiffuse_Physical( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight ) {
	vec3 diffuse = irradiance * BRDF_Lambert( material.diffuseContribution );
	#ifdef USE_SHEEN
		float sheenAlbedo = IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness );
		float sheenEnergyComp = 1.0 - max3( material.sheenColor ) * sheenAlbedo;
		diffuse *= sheenEnergyComp;
	#endif
	reflectedLight.indirectDiffuse += diffuse;
}
void RE_IndirectSpecular_Physical( const in vec3 radiance, const in vec3 irradiance, const in vec3 clearcoatRadiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight) {
	#ifdef USE_CLEARCOAT
		clearcoatSpecularIndirect += clearcoatRadiance * EnvironmentBRDF( geometryClearcoatNormal, geometryViewDir, material.clearcoatF0, material.clearcoatF90, material.clearcoatRoughness );
	#endif
	#ifdef USE_SHEEN
		sheenSpecularIndirect += irradiance * material.sheenColor * IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness ) * RECIPROCAL_PI;
 	#endif
	vec3 singleScatteringDielectric = vec3( 0.0 );
	vec3 multiScatteringDielectric = vec3( 0.0 );
	vec3 singleScatteringMetallic = vec3( 0.0 );
	vec3 multiScatteringMetallic = vec3( 0.0 );
	#ifdef USE_IRIDESCENCE
		computeMultiscatteringIridescence( geometryNormal, geometryViewDir, material.specularColor, material.specularF90, material.iridescence, material.iridescenceFresnelDielectric, material.roughness, singleScatteringDielectric, multiScatteringDielectric );
		computeMultiscatteringIridescence( geometryNormal, geometryViewDir, material.diffuseColor, material.specularF90, material.iridescence, material.iridescenceFresnelMetallic, material.roughness, singleScatteringMetallic, multiScatteringMetallic );
	#else
		computeMultiscattering( geometryNormal, geometryViewDir, material.specularColor, material.specularF90, material.roughness, singleScatteringDielectric, multiScatteringDielectric );
		computeMultiscattering( geometryNormal, geometryViewDir, material.diffuseColor, material.specularF90, material.roughness, singleScatteringMetallic, multiScatteringMetallic );
	#endif
	vec3 singleScattering = mix( singleScatteringDielectric, singleScatteringMetallic, material.metalness );
	vec3 multiScattering = mix( multiScatteringDielectric, multiScatteringMetallic, material.metalness );
	vec3 totalScatteringDielectric = singleScatteringDielectric + multiScatteringDielectric;
	vec3 diffuse = material.diffuseContribution * ( 1.0 - totalScatteringDielectric );
	vec3 cosineWeightedIrradiance = irradiance * RECIPROCAL_PI;
	vec3 indirectSpecular = radiance * singleScattering;
	indirectSpecular += multiScattering * cosineWeightedIrradiance;
	vec3 indirectDiffuse = diffuse * cosineWeightedIrradiance;
	#ifdef USE_SHEEN
		float sheenAlbedo = IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness );
		float sheenEnergyComp = 1.0 - max3( material.sheenColor ) * sheenAlbedo;
		indirectSpecular *= sheenEnergyComp;
		indirectDiffuse *= sheenEnergyComp;
	#endif
	reflectedLight.indirectSpecular += indirectSpecular;
	reflectedLight.indirectDiffuse += indirectDiffuse;
}
#define RE_Direct				RE_Direct_Physical
#define RE_Direct_RectArea		RE_Direct_RectArea_Physical
#define RE_IndirectDiffuse		RE_IndirectDiffuse_Physical
#define RE_IndirectSpecular		RE_IndirectSpecular_Physical
float computeSpecularOcclusion( const in float dotNV, const in float ambientOcclusion, const in float roughness ) {
	return saturate( pow( dotNV + ambientOcclusion, exp2( - 16.0 * roughness - 1.0 ) ) - 1.0 + ambientOcclusion );
}`,ug=`
vec3 geometryPosition = - vViewPosition;
vec3 geometryNormal = normal;
vec3 geometryViewDir = ( isOrthographic ) ? vec3( 0, 0, 1 ) : normalize( vViewPosition );
vec3 geometryClearcoatNormal = vec3( 0.0 );
#ifdef USE_CLEARCOAT
	geometryClearcoatNormal = clearcoatNormal;
#endif
#ifdef USE_IRIDESCENCE
	float dotNVi = saturate( dot( normal, geometryViewDir ) );
	if ( material.iridescenceThickness == 0.0 ) {
		material.iridescence = 0.0;
	} else {
		material.iridescence = saturate( material.iridescence );
	}
	if ( material.iridescence > 0.0 ) {
		material.iridescenceFresnelDielectric = evalIridescence( 1.0, material.iridescenceIOR, dotNVi, material.iridescenceThickness, material.specularColor );
		material.iridescenceFresnelMetallic = evalIridescence( 1.0, material.iridescenceIOR, dotNVi, material.iridescenceThickness, material.diffuseColor );
		material.iridescenceFresnel = mix( material.iridescenceFresnelDielectric, material.iridescenceFresnelMetallic, material.metalness );
		material.iridescenceF0 = Schlick_to_F0( material.iridescenceFresnel, 1.0, dotNVi );
	}
#endif
IncidentLight directLight;
#if ( NUM_POINT_LIGHTS > 0 ) && defined( RE_Direct )
	PointLight pointLight;
	#if defined( USE_SHADOWMAP ) && NUM_POINT_LIGHT_SHADOWS > 0
	PointLightShadow pointLightShadow;
	#endif
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_POINT_LIGHTS; i ++ ) {
		pointLight = pointLights[ i ];
		getPointLightInfo( pointLight, geometryPosition, directLight );
		#if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_POINT_LIGHT_SHADOWS ) && ( defined( SHADOWMAP_TYPE_PCF ) || defined( SHADOWMAP_TYPE_BASIC ) )
		pointLightShadow = pointLightShadows[ i ];
		directLight.color *= ( directLight.visible && receiveShadow ) ? getPointShadow( pointShadowMap[ i ], pointLightShadow.shadowMapSize, pointLightShadow.shadowIntensity, pointLightShadow.shadowBias, pointLightShadow.shadowRadius, vPointShadowCoord[ i ], pointLightShadow.shadowCameraNear, pointLightShadow.shadowCameraFar ) : 1.0;
		#endif
		RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if ( NUM_SPOT_LIGHTS > 0 ) && defined( RE_Direct )
	SpotLight spotLight;
	vec4 spotColor;
	vec3 spotLightCoord;
	bool inSpotLightMap;
	#if defined( USE_SHADOWMAP ) && NUM_SPOT_LIGHT_SHADOWS > 0
	SpotLightShadow spotLightShadow;
	#endif
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_SPOT_LIGHTS; i ++ ) {
		spotLight = spotLights[ i ];
		getSpotLightInfo( spotLight, geometryPosition, directLight );
		#if ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS_WITH_MAPS )
		#define SPOT_LIGHT_MAP_INDEX UNROLLED_LOOP_INDEX
		#elif ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS )
		#define SPOT_LIGHT_MAP_INDEX NUM_SPOT_LIGHT_MAPS
		#else
		#define SPOT_LIGHT_MAP_INDEX ( UNROLLED_LOOP_INDEX - NUM_SPOT_LIGHT_SHADOWS + NUM_SPOT_LIGHT_SHADOWS_WITH_MAPS )
		#endif
		#if ( SPOT_LIGHT_MAP_INDEX < NUM_SPOT_LIGHT_MAPS )
			spotLightCoord = vSpotLightCoord[ i ].xyz / vSpotLightCoord[ i ].w;
			inSpotLightMap = all( lessThan( abs( spotLightCoord * 2. - 1. ), vec3( 1.0 ) ) );
			spotColor = texture2D( spotLightMap[ SPOT_LIGHT_MAP_INDEX ], spotLightCoord.xy );
			directLight.color = inSpotLightMap ? directLight.color * spotColor.rgb : directLight.color;
		#endif
		#undef SPOT_LIGHT_MAP_INDEX
		#if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS )
		spotLightShadow = spotLightShadows[ i ];
		directLight.color *= ( directLight.visible && receiveShadow ) ? getShadow( spotShadowMap[ i ], spotLightShadow.shadowMapSize, spotLightShadow.shadowIntensity, spotLightShadow.shadowBias, spotLightShadow.shadowRadius, vSpotLightCoord[ i ] ) : 1.0;
		#endif
		RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if ( NUM_DIR_LIGHTS > 0 ) && defined( RE_Direct )
	DirectionalLight directionalLight;
	#if defined( USE_SHADOWMAP ) && NUM_DIR_LIGHT_SHADOWS > 0
	DirectionalLightShadow directionalLightShadow;
	#endif
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_DIR_LIGHTS; i ++ ) {
		directionalLight = directionalLights[ i ];
		getDirectionalLightInfo( directionalLight, directLight );
		#if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_DIR_LIGHT_SHADOWS )
		directionalLightShadow = directionalLightShadows[ i ];
		directLight.color *= ( directLight.visible && receiveShadow ) ? getShadow( directionalShadowMap[ i ], directionalLightShadow.shadowMapSize, directionalLightShadow.shadowIntensity, directionalLightShadow.shadowBias, directionalLightShadow.shadowRadius, vDirectionalShadowCoord[ i ] ) : 1.0;
		#endif
		RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if ( NUM_RECT_AREA_LIGHTS > 0 ) && defined( RE_Direct_RectArea )
	RectAreaLight rectAreaLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_RECT_AREA_LIGHTS; i ++ ) {
		rectAreaLight = rectAreaLights[ i ];
		RE_Direct_RectArea( rectAreaLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if defined( RE_IndirectDiffuse )
	vec3 iblIrradiance = vec3( 0.0 );
	vec3 irradiance = getAmbientLightIrradiance( ambientLightColor );
	#if defined( USE_LIGHT_PROBES )
		irradiance += getLightProbeIrradiance( lightProbe, geometryNormal );
	#endif
	#if ( NUM_HEMI_LIGHTS > 0 )
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_HEMI_LIGHTS; i ++ ) {
			irradiance += getHemisphereLightIrradiance( hemisphereLights[ i ], geometryNormal );
		}
		#pragma unroll_loop_end
	#endif
#endif
#if defined( RE_IndirectSpecular )
	vec3 radiance = vec3( 0.0 );
	vec3 clearcoatRadiance = vec3( 0.0 );
#endif`,dg=`#if defined( RE_IndirectDiffuse )
	#ifdef USE_LIGHTMAP
		vec4 lightMapTexel = texture2D( lightMap, vLightMapUv );
		vec3 lightMapIrradiance = lightMapTexel.rgb * lightMapIntensity;
		irradiance += lightMapIrradiance;
	#endif
	#if defined( USE_ENVMAP ) && defined( ENVMAP_TYPE_CUBE_UV )
		#if defined( STANDARD ) || defined( LAMBERT ) || defined( PHONG )
			iblIrradiance += getIBLIrradiance( geometryNormal );
		#endif
	#endif
#endif
#if defined( USE_ENVMAP ) && defined( RE_IndirectSpecular )
	#ifdef USE_ANISOTROPY
		radiance += getIBLAnisotropyRadiance( geometryViewDir, geometryNormal, material.roughness, material.anisotropyB, material.anisotropy );
	#else
		radiance += getIBLRadiance( geometryViewDir, geometryNormal, material.roughness );
	#endif
	#ifdef USE_CLEARCOAT
		clearcoatRadiance += getIBLRadiance( geometryViewDir, geometryClearcoatNormal, material.clearcoatRoughness );
	#endif
#endif`,fg=`#if defined( RE_IndirectDiffuse )
	#if defined( LAMBERT ) || defined( PHONG )
		irradiance += iblIrradiance;
	#endif
	RE_IndirectDiffuse( irradiance, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
#endif
#if defined( RE_IndirectSpecular )
	RE_IndirectSpecular( radiance, iblIrradiance, clearcoatRadiance, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
#endif`,pg=`#if defined( USE_LOGARITHMIC_DEPTH_BUFFER )
	gl_FragDepth = vIsPerspective == 0.0 ? gl_FragCoord.z : log2( vFragDepth ) * logDepthBufFC * 0.5;
#endif`,mg=`#if defined( USE_LOGARITHMIC_DEPTH_BUFFER )
	uniform float logDepthBufFC;
	varying float vFragDepth;
	varying float vIsPerspective;
#endif`,gg=`#ifdef USE_LOGARITHMIC_DEPTH_BUFFER
	varying float vFragDepth;
	varying float vIsPerspective;
#endif`,_g=`#ifdef USE_LOGARITHMIC_DEPTH_BUFFER
	vFragDepth = 1.0 + gl_Position.w;
	vIsPerspective = float( isPerspectiveMatrix( projectionMatrix ) );
#endif`,vg=`#ifdef USE_MAP
	vec4 sampledDiffuseColor = texture2D( map, vMapUv );
	#ifdef DECODE_VIDEO_TEXTURE
		sampledDiffuseColor = sRGBTransferEOTF( sampledDiffuseColor );
	#endif
	diffuseColor *= sampledDiffuseColor;
#endif`,xg=`#ifdef USE_MAP
	uniform sampler2D map;
#endif`,Mg=`#if defined( USE_MAP ) || defined( USE_ALPHAMAP )
	#if defined( USE_POINTS_UV )
		vec2 uv = vUv;
	#else
		vec2 uv = ( uvTransform * vec3( gl_PointCoord.x, 1.0 - gl_PointCoord.y, 1 ) ).xy;
	#endif
#endif
#ifdef USE_MAP
	diffuseColor *= texture2D( map, uv );
#endif
#ifdef USE_ALPHAMAP
	diffuseColor.a *= texture2D( alphaMap, uv ).g;
#endif`,yg=`#if defined( USE_POINTS_UV )
	varying vec2 vUv;
#else
	#if defined( USE_MAP ) || defined( USE_ALPHAMAP )
		uniform mat3 uvTransform;
	#endif
#endif
#ifdef USE_MAP
	uniform sampler2D map;
#endif
#ifdef USE_ALPHAMAP
	uniform sampler2D alphaMap;
#endif`,Sg=`float metalnessFactor = metalness;
#ifdef USE_METALNESSMAP
	vec4 texelMetalness = texture2D( metalnessMap, vMetalnessMapUv );
	metalnessFactor *= texelMetalness.b;
#endif`,bg=`#ifdef USE_METALNESSMAP
	uniform sampler2D metalnessMap;
#endif`,Eg=`#ifdef USE_INSTANCING_MORPH
	float morphTargetInfluences[ MORPHTARGETS_COUNT ];
	float morphTargetBaseInfluence = texelFetch( morphTexture, ivec2( 0, gl_InstanceID ), 0 ).r;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		morphTargetInfluences[i] =  texelFetch( morphTexture, ivec2( i + 1, gl_InstanceID ), 0 ).r;
	}
#endif`,Tg=`#if defined( USE_MORPHCOLORS )
	vColor *= morphTargetBaseInfluence;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		#if defined( USE_COLOR_ALPHA )
			if ( morphTargetInfluences[ i ] != 0.0 ) vColor += getMorph( gl_VertexID, i, 2 ) * morphTargetInfluences[ i ];
		#elif defined( USE_COLOR )
			if ( morphTargetInfluences[ i ] != 0.0 ) vColor += getMorph( gl_VertexID, i, 2 ).rgb * morphTargetInfluences[ i ];
		#endif
	}
#endif`,Ag=`#ifdef USE_MORPHNORMALS
	objectNormal *= morphTargetBaseInfluence;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		if ( morphTargetInfluences[ i ] != 0.0 ) objectNormal += getMorph( gl_VertexID, i, 1 ).xyz * morphTargetInfluences[ i ];
	}
#endif`,wg=`#ifdef USE_MORPHTARGETS
	#ifndef USE_INSTANCING_MORPH
		uniform float morphTargetBaseInfluence;
		uniform float morphTargetInfluences[ MORPHTARGETS_COUNT ];
	#endif
	uniform sampler2DArray morphTargetsTexture;
	uniform ivec2 morphTargetsTextureSize;
	vec4 getMorph( const in int vertexIndex, const in int morphTargetIndex, const in int offset ) {
		int texelIndex = vertexIndex * MORPHTARGETS_TEXTURE_STRIDE + offset;
		int y = texelIndex / morphTargetsTextureSize.x;
		int x = texelIndex - y * morphTargetsTextureSize.x;
		ivec3 morphUV = ivec3( x, y, morphTargetIndex );
		return texelFetch( morphTargetsTexture, morphUV, 0 );
	}
#endif`,Rg=`#ifdef USE_MORPHTARGETS
	transformed *= morphTargetBaseInfluence;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		if ( morphTargetInfluences[ i ] != 0.0 ) transformed += getMorph( gl_VertexID, i, 0 ).xyz * morphTargetInfluences[ i ];
	}
#endif`,Cg=`float faceDirection = gl_FrontFacing ? 1.0 : - 1.0;
#ifdef FLAT_SHADED
	vec3 fdx = dFdx( vViewPosition );
	vec3 fdy = dFdy( vViewPosition );
	vec3 normal = normalize( cross( fdx, fdy ) );
#else
	vec3 normal = normalize( vNormal );
	#ifdef DOUBLE_SIDED
		normal *= faceDirection;
	#endif
#endif
#if defined( USE_NORMALMAP_TANGENTSPACE ) || defined( USE_CLEARCOAT_NORMALMAP ) || defined( USE_ANISOTROPY )
	#ifdef USE_TANGENT
		mat3 tbn = mat3( normalize( vTangent ), normalize( vBitangent ), normal );
	#else
		mat3 tbn = getTangentFrame( - vViewPosition, normal,
		#if defined( USE_NORMALMAP )
			vNormalMapUv
		#elif defined( USE_CLEARCOAT_NORMALMAP )
			vClearcoatNormalMapUv
		#else
			vUv
		#endif
		);
	#endif
	#if defined( DOUBLE_SIDED ) && ! defined( FLAT_SHADED )
		tbn[0] *= faceDirection;
		tbn[1] *= faceDirection;
	#endif
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	#ifdef USE_TANGENT
		mat3 tbn2 = mat3( normalize( vTangent ), normalize( vBitangent ), normal );
	#else
		mat3 tbn2 = getTangentFrame( - vViewPosition, normal, vClearcoatNormalMapUv );
	#endif
	#if defined( DOUBLE_SIDED ) && ! defined( FLAT_SHADED )
		tbn2[0] *= faceDirection;
		tbn2[1] *= faceDirection;
	#endif
#endif
vec3 nonPerturbedNormal = normal;`,Pg=`#ifdef USE_NORMALMAP_OBJECTSPACE
	normal = texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0;
	#ifdef FLIP_SIDED
		normal = - normal;
	#endif
	#ifdef DOUBLE_SIDED
		normal = normal * faceDirection;
	#endif
	normal = normalize( normalMatrix * normal );
#elif defined( USE_NORMALMAP_TANGENTSPACE )
	vec3 mapN = texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0;
	mapN.xy *= normalScale;
	normal = normalize( tbn * mapN );
#elif defined( USE_BUMPMAP )
	normal = perturbNormalArb( - vViewPosition, normal, dHdxy_fwd(), faceDirection );
#endif`,Dg=`#ifndef FLAT_SHADED
	varying vec3 vNormal;
	#ifdef USE_TANGENT
		varying vec3 vTangent;
		varying vec3 vBitangent;
	#endif
#endif`,Lg=`#ifndef FLAT_SHADED
	varying vec3 vNormal;
	#ifdef USE_TANGENT
		varying vec3 vTangent;
		varying vec3 vBitangent;
	#endif
#endif`,Ig=`#ifndef FLAT_SHADED
	vNormal = normalize( transformedNormal );
	#ifdef USE_TANGENT
		vTangent = normalize( transformedTangent );
		vBitangent = normalize( cross( vNormal, vTangent ) * tangent.w );
	#endif
#endif`,Ng=`#ifdef USE_NORMALMAP
	uniform sampler2D normalMap;
	uniform vec2 normalScale;
#endif
#ifdef USE_NORMALMAP_OBJECTSPACE
	uniform mat3 normalMatrix;
#endif
#if ! defined ( USE_TANGENT ) && ( defined ( USE_NORMALMAP_TANGENTSPACE ) || defined ( USE_CLEARCOAT_NORMALMAP ) || defined( USE_ANISOTROPY ) )
	mat3 getTangentFrame( vec3 eye_pos, vec3 surf_norm, vec2 uv ) {
		vec3 q0 = dFdx( eye_pos.xyz );
		vec3 q1 = dFdy( eye_pos.xyz );
		vec2 st0 = dFdx( uv.st );
		vec2 st1 = dFdy( uv.st );
		vec3 N = surf_norm;
		vec3 q1perp = cross( q1, N );
		vec3 q0perp = cross( N, q0 );
		vec3 T = q1perp * st0.x + q0perp * st1.x;
		vec3 B = q1perp * st0.y + q0perp * st1.y;
		float det = max( dot( T, T ), dot( B, B ) );
		float scale = ( det == 0.0 ) ? 0.0 : inversesqrt( det );
		return mat3( T * scale, B * scale, N );
	}
#endif`,Ug=`#ifdef USE_CLEARCOAT
	vec3 clearcoatNormal = nonPerturbedNormal;
#endif`,Fg=`#ifdef USE_CLEARCOAT_NORMALMAP
	vec3 clearcoatMapN = texture2D( clearcoatNormalMap, vClearcoatNormalMapUv ).xyz * 2.0 - 1.0;
	clearcoatMapN.xy *= clearcoatNormalScale;
	clearcoatNormal = normalize( tbn2 * clearcoatMapN );
#endif`,Og=`#ifdef USE_CLEARCOATMAP
	uniform sampler2D clearcoatMap;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	uniform sampler2D clearcoatNormalMap;
	uniform vec2 clearcoatNormalScale;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	uniform sampler2D clearcoatRoughnessMap;
#endif`,Bg=`#ifdef USE_IRIDESCENCEMAP
	uniform sampler2D iridescenceMap;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	uniform sampler2D iridescenceThicknessMap;
#endif`,kg=`#ifdef OPAQUE
diffuseColor.a = 1.0;
#endif
#ifdef USE_TRANSMISSION
diffuseColor.a *= material.transmissionAlpha;
#endif
gl_FragColor = vec4( outgoingLight, diffuseColor.a );`,Vg=`vec3 packNormalToRGB( const in vec3 normal ) {
	return normalize( normal ) * 0.5 + 0.5;
}
vec3 unpackRGBToNormal( const in vec3 rgb ) {
	return 2.0 * rgb.xyz - 1.0;
}
const float PackUpscale = 256. / 255.;const float UnpackDownscale = 255. / 256.;const float ShiftRight8 = 1. / 256.;
const float Inv255 = 1. / 255.;
const vec4 PackFactors = vec4( 1.0, 256.0, 256.0 * 256.0, 256.0 * 256.0 * 256.0 );
const vec2 UnpackFactors2 = vec2( UnpackDownscale, 1.0 / PackFactors.g );
const vec3 UnpackFactors3 = vec3( UnpackDownscale / PackFactors.rg, 1.0 / PackFactors.b );
const vec4 UnpackFactors4 = vec4( UnpackDownscale / PackFactors.rgb, 1.0 / PackFactors.a );
vec4 packDepthToRGBA( const in float v ) {
	if( v <= 0.0 )
		return vec4( 0., 0., 0., 0. );
	if( v >= 1.0 )
		return vec4( 1., 1., 1., 1. );
	float vuf;
	float af = modf( v * PackFactors.a, vuf );
	float bf = modf( vuf * ShiftRight8, vuf );
	float gf = modf( vuf * ShiftRight8, vuf );
	return vec4( vuf * Inv255, gf * PackUpscale, bf * PackUpscale, af );
}
vec3 packDepthToRGB( const in float v ) {
	if( v <= 0.0 )
		return vec3( 0., 0., 0. );
	if( v >= 1.0 )
		return vec3( 1., 1., 1. );
	float vuf;
	float bf = modf( v * PackFactors.b, vuf );
	float gf = modf( vuf * ShiftRight8, vuf );
	return vec3( vuf * Inv255, gf * PackUpscale, bf );
}
vec2 packDepthToRG( const in float v ) {
	if( v <= 0.0 )
		return vec2( 0., 0. );
	if( v >= 1.0 )
		return vec2( 1., 1. );
	float vuf;
	float gf = modf( v * 256., vuf );
	return vec2( vuf * Inv255, gf );
}
float unpackRGBAToDepth( const in vec4 v ) {
	return dot( v, UnpackFactors4 );
}
float unpackRGBToDepth( const in vec3 v ) {
	return dot( v, UnpackFactors3 );
}
float unpackRGToDepth( const in vec2 v ) {
	return v.r * UnpackFactors2.r + v.g * UnpackFactors2.g;
}
vec4 pack2HalfToRGBA( const in vec2 v ) {
	vec4 r = vec4( v.x, fract( v.x * 255.0 ), v.y, fract( v.y * 255.0 ) );
	return vec4( r.x - r.y / 255.0, r.y, r.z - r.w / 255.0, r.w );
}
vec2 unpackRGBATo2Half( const in vec4 v ) {
	return vec2( v.x + ( v.y / 255.0 ), v.z + ( v.w / 255.0 ) );
}
float viewZToOrthographicDepth( const in float viewZ, const in float near, const in float far ) {
	return ( viewZ + near ) / ( near - far );
}
float orthographicDepthToViewZ( const in float depth, const in float near, const in float far ) {
	#ifdef USE_REVERSED_DEPTH_BUFFER
	
		return depth * ( far - near ) - far;
	#else
		return depth * ( near - far ) - near;
	#endif
}
float viewZToPerspectiveDepth( const in float viewZ, const in float near, const in float far ) {
	return ( ( near + viewZ ) * far ) / ( ( far - near ) * viewZ );
}
float perspectiveDepthToViewZ( const in float depth, const in float near, const in float far ) {
	
	#ifdef USE_REVERSED_DEPTH_BUFFER
		return ( near * far ) / ( ( near - far ) * depth - near );
	#else
		return ( near * far ) / ( ( far - near ) * depth - far );
	#endif
}`,zg=`#ifdef PREMULTIPLIED_ALPHA
	gl_FragColor.rgb *= gl_FragColor.a;
#endif`,Hg=`vec4 mvPosition = vec4( transformed, 1.0 );
#ifdef USE_BATCHING
	mvPosition = batchingMatrix * mvPosition;
#endif
#ifdef USE_INSTANCING
	mvPosition = instanceMatrix * mvPosition;
#endif
mvPosition = modelViewMatrix * mvPosition;
gl_Position = projectionMatrix * mvPosition;`,Gg=`#ifdef DITHERING
	gl_FragColor.rgb = dithering( gl_FragColor.rgb );
#endif`,Wg=`#ifdef DITHERING
	vec3 dithering( vec3 color ) {
		float grid_position = rand( gl_FragCoord.xy );
		vec3 dither_shift_RGB = vec3( 0.25 / 255.0, -0.25 / 255.0, 0.25 / 255.0 );
		dither_shift_RGB = mix( 2.0 * dither_shift_RGB, -2.0 * dither_shift_RGB, grid_position );
		return color + dither_shift_RGB;
	}
#endif`,Xg=`float roughnessFactor = roughness;
#ifdef USE_ROUGHNESSMAP
	vec4 texelRoughness = texture2D( roughnessMap, vRoughnessMapUv );
	roughnessFactor *= texelRoughness.g;
#endif`,Yg=`#ifdef USE_ROUGHNESSMAP
	uniform sampler2D roughnessMap;
#endif`,qg=`#if NUM_SPOT_LIGHT_COORDS > 0
	varying vec4 vSpotLightCoord[ NUM_SPOT_LIGHT_COORDS ];
#endif
#if NUM_SPOT_LIGHT_MAPS > 0
	uniform sampler2D spotLightMap[ NUM_SPOT_LIGHT_MAPS ];
#endif
#ifdef USE_SHADOWMAP
	#if NUM_DIR_LIGHT_SHADOWS > 0
		#if defined( SHADOWMAP_TYPE_PCF )
			uniform sampler2DShadow directionalShadowMap[ NUM_DIR_LIGHT_SHADOWS ];
		#else
			uniform sampler2D directionalShadowMap[ NUM_DIR_LIGHT_SHADOWS ];
		#endif
		varying vec4 vDirectionalShadowCoord[ NUM_DIR_LIGHT_SHADOWS ];
		struct DirectionalLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform DirectionalLightShadow directionalLightShadows[ NUM_DIR_LIGHT_SHADOWS ];
	#endif
	#if NUM_SPOT_LIGHT_SHADOWS > 0
		#if defined( SHADOWMAP_TYPE_PCF )
			uniform sampler2DShadow spotShadowMap[ NUM_SPOT_LIGHT_SHADOWS ];
		#else
			uniform sampler2D spotShadowMap[ NUM_SPOT_LIGHT_SHADOWS ];
		#endif
		struct SpotLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform SpotLightShadow spotLightShadows[ NUM_SPOT_LIGHT_SHADOWS ];
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
		#if defined( SHADOWMAP_TYPE_PCF )
			uniform samplerCubeShadow pointShadowMap[ NUM_POINT_LIGHT_SHADOWS ];
		#elif defined( SHADOWMAP_TYPE_BASIC )
			uniform samplerCube pointShadowMap[ NUM_POINT_LIGHT_SHADOWS ];
		#endif
		varying vec4 vPointShadowCoord[ NUM_POINT_LIGHT_SHADOWS ];
		struct PointLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
			float shadowCameraNear;
			float shadowCameraFar;
		};
		uniform PointLightShadow pointLightShadows[ NUM_POINT_LIGHT_SHADOWS ];
	#endif
	#if defined( SHADOWMAP_TYPE_PCF )
		float interleavedGradientNoise( vec2 position ) {
			return fract( 52.9829189 * fract( dot( position, vec2( 0.06711056, 0.00583715 ) ) ) );
		}
		vec2 vogelDiskSample( int sampleIndex, int samplesCount, float phi ) {
			const float goldenAngle = 2.399963229728653;
			float r = sqrt( ( float( sampleIndex ) + 0.5 ) / float( samplesCount ) );
			float theta = float( sampleIndex ) * goldenAngle + phi;
			return vec2( cos( theta ), sin( theta ) ) * r;
		}
	#endif
	#if defined( SHADOWMAP_TYPE_PCF )
		float getShadow( sampler2DShadow shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord ) {
			float shadow = 1.0;
			shadowCoord.xyz /= shadowCoord.w;
			shadowCoord.z += shadowBias;
			bool inFrustum = shadowCoord.x >= 0.0 && shadowCoord.x <= 1.0 && shadowCoord.y >= 0.0 && shadowCoord.y <= 1.0;
			bool frustumTest = inFrustum && shadowCoord.z <= 1.0;
			if ( frustumTest ) {
				vec2 texelSize = vec2( 1.0 ) / shadowMapSize;
				float radius = shadowRadius * texelSize.x;
				float phi = interleavedGradientNoise( gl_FragCoord.xy ) * PI2;
				shadow = (
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 0, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 1, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 2, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 3, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 4, 5, phi ) * radius, shadowCoord.z ) )
				) * 0.2;
			}
			return mix( 1.0, shadow, shadowIntensity );
		}
	#elif defined( SHADOWMAP_TYPE_VSM )
		float getShadow( sampler2D shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord ) {
			float shadow = 1.0;
			shadowCoord.xyz /= shadowCoord.w;
			#ifdef USE_REVERSED_DEPTH_BUFFER
				shadowCoord.z -= shadowBias;
			#else
				shadowCoord.z += shadowBias;
			#endif
			bool inFrustum = shadowCoord.x >= 0.0 && shadowCoord.x <= 1.0 && shadowCoord.y >= 0.0 && shadowCoord.y <= 1.0;
			bool frustumTest = inFrustum && shadowCoord.z <= 1.0;
			if ( frustumTest ) {
				vec2 distribution = texture2D( shadowMap, shadowCoord.xy ).rg;
				float mean = distribution.x;
				float variance = distribution.y * distribution.y;
				#ifdef USE_REVERSED_DEPTH_BUFFER
					float hard_shadow = step( mean, shadowCoord.z );
				#else
					float hard_shadow = step( shadowCoord.z, mean );
				#endif
				
				if ( hard_shadow == 1.0 ) {
					shadow = 1.0;
				} else {
					variance = max( variance, 0.0000001 );
					float d = shadowCoord.z - mean;
					float p_max = variance / ( variance + d * d );
					p_max = clamp( ( p_max - 0.3 ) / 0.65, 0.0, 1.0 );
					shadow = max( hard_shadow, p_max );
				}
			}
			return mix( 1.0, shadow, shadowIntensity );
		}
	#else
		float getShadow( sampler2D shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord ) {
			float shadow = 1.0;
			shadowCoord.xyz /= shadowCoord.w;
			#ifdef USE_REVERSED_DEPTH_BUFFER
				shadowCoord.z -= shadowBias;
			#else
				shadowCoord.z += shadowBias;
			#endif
			bool inFrustum = shadowCoord.x >= 0.0 && shadowCoord.x <= 1.0 && shadowCoord.y >= 0.0 && shadowCoord.y <= 1.0;
			bool frustumTest = inFrustum && shadowCoord.z <= 1.0;
			if ( frustumTest ) {
				float depth = texture2D( shadowMap, shadowCoord.xy ).r;
				#ifdef USE_REVERSED_DEPTH_BUFFER
					shadow = step( depth, shadowCoord.z );
				#else
					shadow = step( shadowCoord.z, depth );
				#endif
			}
			return mix( 1.0, shadow, shadowIntensity );
		}
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
	#if defined( SHADOWMAP_TYPE_PCF )
	float getPointShadow( samplerCubeShadow shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord, float shadowCameraNear, float shadowCameraFar ) {
		float shadow = 1.0;
		vec3 lightToPosition = shadowCoord.xyz;
		vec3 bd3D = normalize( lightToPosition );
		vec3 absVec = abs( lightToPosition );
		float viewSpaceZ = max( max( absVec.x, absVec.y ), absVec.z );
		if ( viewSpaceZ - shadowCameraFar <= 0.0 && viewSpaceZ - shadowCameraNear >= 0.0 ) {
			#ifdef USE_REVERSED_DEPTH_BUFFER
				float dp = ( shadowCameraNear * ( shadowCameraFar - viewSpaceZ ) ) / ( viewSpaceZ * ( shadowCameraFar - shadowCameraNear ) );
				dp -= shadowBias;
			#else
				float dp = ( shadowCameraFar * ( viewSpaceZ - shadowCameraNear ) ) / ( viewSpaceZ * ( shadowCameraFar - shadowCameraNear ) );
				dp += shadowBias;
			#endif
			float texelSize = shadowRadius / shadowMapSize.x;
			vec3 absDir = abs( bd3D );
			vec3 tangent = absDir.x > absDir.z ? vec3( 0.0, 1.0, 0.0 ) : vec3( 1.0, 0.0, 0.0 );
			tangent = normalize( cross( bd3D, tangent ) );
			vec3 bitangent = cross( bd3D, tangent );
			float phi = interleavedGradientNoise( gl_FragCoord.xy ) * PI2;
			vec2 sample0 = vogelDiskSample( 0, 5, phi );
			vec2 sample1 = vogelDiskSample( 1, 5, phi );
			vec2 sample2 = vogelDiskSample( 2, 5, phi );
			vec2 sample3 = vogelDiskSample( 3, 5, phi );
			vec2 sample4 = vogelDiskSample( 4, 5, phi );
			shadow = (
				texture( shadowMap, vec4( bd3D + ( tangent * sample0.x + bitangent * sample0.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample1.x + bitangent * sample1.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample2.x + bitangent * sample2.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample3.x + bitangent * sample3.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample4.x + bitangent * sample4.y ) * texelSize, dp ) )
			) * 0.2;
		}
		return mix( 1.0, shadow, shadowIntensity );
	}
	#elif defined( SHADOWMAP_TYPE_BASIC )
	float getPointShadow( samplerCube shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord, float shadowCameraNear, float shadowCameraFar ) {
		float shadow = 1.0;
		vec3 lightToPosition = shadowCoord.xyz;
		vec3 absVec = abs( lightToPosition );
		float viewSpaceZ = max( max( absVec.x, absVec.y ), absVec.z );
		if ( viewSpaceZ - shadowCameraFar <= 0.0 && viewSpaceZ - shadowCameraNear >= 0.0 ) {
			float dp = ( shadowCameraFar * ( viewSpaceZ - shadowCameraNear ) ) / ( viewSpaceZ * ( shadowCameraFar - shadowCameraNear ) );
			dp += shadowBias;
			vec3 bd3D = normalize( lightToPosition );
			float depth = textureCube( shadowMap, bd3D ).r;
			#ifdef USE_REVERSED_DEPTH_BUFFER
				depth = 1.0 - depth;
			#endif
			shadow = step( dp, depth );
		}
		return mix( 1.0, shadow, shadowIntensity );
	}
	#endif
	#endif
#endif`,jg=`#if NUM_SPOT_LIGHT_COORDS > 0
	uniform mat4 spotLightMatrix[ NUM_SPOT_LIGHT_COORDS ];
	varying vec4 vSpotLightCoord[ NUM_SPOT_LIGHT_COORDS ];
#endif
#ifdef USE_SHADOWMAP
	#if NUM_DIR_LIGHT_SHADOWS > 0
		uniform mat4 directionalShadowMatrix[ NUM_DIR_LIGHT_SHADOWS ];
		varying vec4 vDirectionalShadowCoord[ NUM_DIR_LIGHT_SHADOWS ];
		struct DirectionalLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform DirectionalLightShadow directionalLightShadows[ NUM_DIR_LIGHT_SHADOWS ];
	#endif
	#if NUM_SPOT_LIGHT_SHADOWS > 0
		struct SpotLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform SpotLightShadow spotLightShadows[ NUM_SPOT_LIGHT_SHADOWS ];
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
		uniform mat4 pointShadowMatrix[ NUM_POINT_LIGHT_SHADOWS ];
		varying vec4 vPointShadowCoord[ NUM_POINT_LIGHT_SHADOWS ];
		struct PointLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
			float shadowCameraNear;
			float shadowCameraFar;
		};
		uniform PointLightShadow pointLightShadows[ NUM_POINT_LIGHT_SHADOWS ];
	#endif
#endif`,Kg=`#if ( defined( USE_SHADOWMAP ) && ( NUM_DIR_LIGHT_SHADOWS > 0 || NUM_POINT_LIGHT_SHADOWS > 0 ) ) || ( NUM_SPOT_LIGHT_COORDS > 0 )
	vec3 shadowWorldNormal = inverseTransformDirection( transformedNormal, viewMatrix );
	vec4 shadowWorldPosition;
#endif
#if defined( USE_SHADOWMAP )
	#if NUM_DIR_LIGHT_SHADOWS > 0
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_DIR_LIGHT_SHADOWS; i ++ ) {
			shadowWorldPosition = worldPosition + vec4( shadowWorldNormal * directionalLightShadows[ i ].shadowNormalBias, 0 );
			vDirectionalShadowCoord[ i ] = directionalShadowMatrix[ i ] * shadowWorldPosition;
		}
		#pragma unroll_loop_end
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_POINT_LIGHT_SHADOWS; i ++ ) {
			shadowWorldPosition = worldPosition + vec4( shadowWorldNormal * pointLightShadows[ i ].shadowNormalBias, 0 );
			vPointShadowCoord[ i ] = pointShadowMatrix[ i ] * shadowWorldPosition;
		}
		#pragma unroll_loop_end
	#endif
#endif
#if NUM_SPOT_LIGHT_COORDS > 0
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_SPOT_LIGHT_COORDS; i ++ ) {
		shadowWorldPosition = worldPosition;
		#if ( defined( USE_SHADOWMAP ) && UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS )
			shadowWorldPosition.xyz += shadowWorldNormal * spotLightShadows[ i ].shadowNormalBias;
		#endif
		vSpotLightCoord[ i ] = spotLightMatrix[ i ] * shadowWorldPosition;
	}
	#pragma unroll_loop_end
#endif`,$g=`float getShadowMask() {
	float shadow = 1.0;
	#ifdef USE_SHADOWMAP
	#if NUM_DIR_LIGHT_SHADOWS > 0
	DirectionalLightShadow directionalLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_DIR_LIGHT_SHADOWS; i ++ ) {
		directionalLight = directionalLightShadows[ i ];
		shadow *= receiveShadow ? getShadow( directionalShadowMap[ i ], directionalLight.shadowMapSize, directionalLight.shadowIntensity, directionalLight.shadowBias, directionalLight.shadowRadius, vDirectionalShadowCoord[ i ] ) : 1.0;
	}
	#pragma unroll_loop_end
	#endif
	#if NUM_SPOT_LIGHT_SHADOWS > 0
	SpotLightShadow spotLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_SPOT_LIGHT_SHADOWS; i ++ ) {
		spotLight = spotLightShadows[ i ];
		shadow *= receiveShadow ? getShadow( spotShadowMap[ i ], spotLight.shadowMapSize, spotLight.shadowIntensity, spotLight.shadowBias, spotLight.shadowRadius, vSpotLightCoord[ i ] ) : 1.0;
	}
	#pragma unroll_loop_end
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0 && ( defined( SHADOWMAP_TYPE_PCF ) || defined( SHADOWMAP_TYPE_BASIC ) )
	PointLightShadow pointLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_POINT_LIGHT_SHADOWS; i ++ ) {
		pointLight = pointLightShadows[ i ];
		shadow *= receiveShadow ? getPointShadow( pointShadowMap[ i ], pointLight.shadowMapSize, pointLight.shadowIntensity, pointLight.shadowBias, pointLight.shadowRadius, vPointShadowCoord[ i ], pointLight.shadowCameraNear, pointLight.shadowCameraFar ) : 1.0;
	}
	#pragma unroll_loop_end
	#endif
	#endif
	return shadow;
}`,Zg=`#ifdef USE_SKINNING
	mat4 boneMatX = getBoneMatrix( skinIndex.x );
	mat4 boneMatY = getBoneMatrix( skinIndex.y );
	mat4 boneMatZ = getBoneMatrix( skinIndex.z );
	mat4 boneMatW = getBoneMatrix( skinIndex.w );
#endif`,Jg=`#ifdef USE_SKINNING
	uniform mat4 bindMatrix;
	uniform mat4 bindMatrixInverse;
	uniform highp sampler2D boneTexture;
	mat4 getBoneMatrix( const in float i ) {
		int size = textureSize( boneTexture, 0 ).x;
		int j = int( i ) * 4;
		int x = j % size;
		int y = j / size;
		vec4 v1 = texelFetch( boneTexture, ivec2( x, y ), 0 );
		vec4 v2 = texelFetch( boneTexture, ivec2( x + 1, y ), 0 );
		vec4 v3 = texelFetch( boneTexture, ivec2( x + 2, y ), 0 );
		vec4 v4 = texelFetch( boneTexture, ivec2( x + 3, y ), 0 );
		return mat4( v1, v2, v3, v4 );
	}
#endif`,Qg=`#ifdef USE_SKINNING
	vec4 skinVertex = bindMatrix * vec4( transformed, 1.0 );
	vec4 skinned = vec4( 0.0 );
	skinned += boneMatX * skinVertex * skinWeight.x;
	skinned += boneMatY * skinVertex * skinWeight.y;
	skinned += boneMatZ * skinVertex * skinWeight.z;
	skinned += boneMatW * skinVertex * skinWeight.w;
	transformed = ( bindMatrixInverse * skinned ).xyz;
#endif`,e0=`#ifdef USE_SKINNING
	mat4 skinMatrix = mat4( 0.0 );
	skinMatrix += skinWeight.x * boneMatX;
	skinMatrix += skinWeight.y * boneMatY;
	skinMatrix += skinWeight.z * boneMatZ;
	skinMatrix += skinWeight.w * boneMatW;
	skinMatrix = bindMatrixInverse * skinMatrix * bindMatrix;
	objectNormal = vec4( skinMatrix * vec4( objectNormal, 0.0 ) ).xyz;
	#ifdef USE_TANGENT
		objectTangent = vec4( skinMatrix * vec4( objectTangent, 0.0 ) ).xyz;
	#endif
#endif`,t0=`float specularStrength;
#ifdef USE_SPECULARMAP
	vec4 texelSpecular = texture2D( specularMap, vSpecularMapUv );
	specularStrength = texelSpecular.r;
#else
	specularStrength = 1.0;
#endif`,n0=`#ifdef USE_SPECULARMAP
	uniform sampler2D specularMap;
#endif`,i0=`#if defined( TONE_MAPPING )
	gl_FragColor.rgb = toneMapping( gl_FragColor.rgb );
#endif`,s0=`#ifndef saturate
#define saturate( a ) clamp( a, 0.0, 1.0 )
#endif
uniform float toneMappingExposure;
vec3 LinearToneMapping( vec3 color ) {
	return saturate( toneMappingExposure * color );
}
vec3 ReinhardToneMapping( vec3 color ) {
	color *= toneMappingExposure;
	return saturate( color / ( vec3( 1.0 ) + color ) );
}
vec3 CineonToneMapping( vec3 color ) {
	color *= toneMappingExposure;
	color = max( vec3( 0.0 ), color - 0.004 );
	return pow( ( color * ( 6.2 * color + 0.5 ) ) / ( color * ( 6.2 * color + 1.7 ) + 0.06 ), vec3( 2.2 ) );
}
vec3 RRTAndODTFit( vec3 v ) {
	vec3 a = v * ( v + 0.0245786 ) - 0.000090537;
	vec3 b = v * ( 0.983729 * v + 0.4329510 ) + 0.238081;
	return a / b;
}
vec3 ACESFilmicToneMapping( vec3 color ) {
	const mat3 ACESInputMat = mat3(
		vec3( 0.59719, 0.07600, 0.02840 ),		vec3( 0.35458, 0.90834, 0.13383 ),
		vec3( 0.04823, 0.01566, 0.83777 )
	);
	const mat3 ACESOutputMat = mat3(
		vec3(  1.60475, -0.10208, -0.00327 ),		vec3( -0.53108,  1.10813, -0.07276 ),
		vec3( -0.07367, -0.00605,  1.07602 )
	);
	color *= toneMappingExposure / 0.6;
	color = ACESInputMat * color;
	color = RRTAndODTFit( color );
	color = ACESOutputMat * color;
	return saturate( color );
}
const mat3 LINEAR_REC2020_TO_LINEAR_SRGB = mat3(
	vec3( 1.6605, - 0.1246, - 0.0182 ),
	vec3( - 0.5876, 1.1329, - 0.1006 ),
	vec3( - 0.0728, - 0.0083, 1.1187 )
);
const mat3 LINEAR_SRGB_TO_LINEAR_REC2020 = mat3(
	vec3( 0.6274, 0.0691, 0.0164 ),
	vec3( 0.3293, 0.9195, 0.0880 ),
	vec3( 0.0433, 0.0113, 0.8956 )
);
vec3 agxDefaultContrastApprox( vec3 x ) {
	vec3 x2 = x * x;
	vec3 x4 = x2 * x2;
	return + 15.5 * x4 * x2
		- 40.14 * x4 * x
		+ 31.96 * x4
		- 6.868 * x2 * x
		+ 0.4298 * x2
		+ 0.1191 * x
		- 0.00232;
}
vec3 AgXToneMapping( vec3 color ) {
	const mat3 AgXInsetMatrix = mat3(
		vec3( 0.856627153315983, 0.137318972929847, 0.11189821299995 ),
		vec3( 0.0951212405381588, 0.761241990602591, 0.0767994186031903 ),
		vec3( 0.0482516061458583, 0.101439036467562, 0.811302368396859 )
	);
	const mat3 AgXOutsetMatrix = mat3(
		vec3( 1.1271005818144368, - 0.1413297634984383, - 0.14132976349843826 ),
		vec3( - 0.11060664309660323, 1.157823702216272, - 0.11060664309660294 ),
		vec3( - 0.016493938717834573, - 0.016493938717834257, 1.2519364065950405 )
	);
	const float AgxMinEv = - 12.47393;	const float AgxMaxEv = 4.026069;
	color *= toneMappingExposure;
	color = LINEAR_SRGB_TO_LINEAR_REC2020 * color;
	color = AgXInsetMatrix * color;
	color = max( color, 1e-10 );	color = log2( color );
	color = ( color - AgxMinEv ) / ( AgxMaxEv - AgxMinEv );
	color = clamp( color, 0.0, 1.0 );
	color = agxDefaultContrastApprox( color );
	color = AgXOutsetMatrix * color;
	color = pow( max( vec3( 0.0 ), color ), vec3( 2.2 ) );
	color = LINEAR_REC2020_TO_LINEAR_SRGB * color;
	color = clamp( color, 0.0, 1.0 );
	return color;
}
vec3 NeutralToneMapping( vec3 color ) {
	const float StartCompression = 0.8 - 0.04;
	const float Desaturation = 0.15;
	color *= toneMappingExposure;
	float x = min( color.r, min( color.g, color.b ) );
	float offset = x < 0.08 ? x - 6.25 * x * x : 0.04;
	color -= offset;
	float peak = max( color.r, max( color.g, color.b ) );
	if ( peak < StartCompression ) return color;
	float d = 1. - StartCompression;
	float newPeak = 1. - d * d / ( peak + d - StartCompression );
	color *= newPeak / peak;
	float g = 1. - 1. / ( Desaturation * ( peak - newPeak ) + 1. );
	return mix( color, vec3( newPeak ), g );
}
vec3 CustomToneMapping( vec3 color ) { return color; }`,r0=`#ifdef USE_TRANSMISSION
	material.transmission = transmission;
	material.transmissionAlpha = 1.0;
	material.thickness = thickness;
	material.attenuationDistance = attenuationDistance;
	material.attenuationColor = attenuationColor;
	#ifdef USE_TRANSMISSIONMAP
		material.transmission *= texture2D( transmissionMap, vTransmissionMapUv ).r;
	#endif
	#ifdef USE_THICKNESSMAP
		material.thickness *= texture2D( thicknessMap, vThicknessMapUv ).g;
	#endif
	vec3 pos = vWorldPosition;
	vec3 v = normalize( cameraPosition - pos );
	vec3 n = inverseTransformDirection( normal, viewMatrix );
	vec4 transmitted = getIBLVolumeRefraction(
		n, v, material.roughness, material.diffuseContribution, material.specularColorBlended, material.specularF90,
		pos, modelMatrix, viewMatrix, projectionMatrix, material.dispersion, material.ior, material.thickness,
		material.attenuationColor, material.attenuationDistance );
	material.transmissionAlpha = mix( material.transmissionAlpha, transmitted.a, material.transmission );
	totalDiffuse = mix( totalDiffuse, transmitted.rgb, material.transmission );
#endif`,a0=`#ifdef USE_TRANSMISSION
	uniform float transmission;
	uniform float thickness;
	uniform float attenuationDistance;
	uniform vec3 attenuationColor;
	#ifdef USE_TRANSMISSIONMAP
		uniform sampler2D transmissionMap;
	#endif
	#ifdef USE_THICKNESSMAP
		uniform sampler2D thicknessMap;
	#endif
	uniform vec2 transmissionSamplerSize;
	uniform sampler2D transmissionSamplerMap;
	uniform mat4 modelMatrix;
	uniform mat4 projectionMatrix;
	varying vec3 vWorldPosition;
	float w0( float a ) {
		return ( 1.0 / 6.0 ) * ( a * ( a * ( - a + 3.0 ) - 3.0 ) + 1.0 );
	}
	float w1( float a ) {
		return ( 1.0 / 6.0 ) * ( a *  a * ( 3.0 * a - 6.0 ) + 4.0 );
	}
	float w2( float a ){
		return ( 1.0 / 6.0 ) * ( a * ( a * ( - 3.0 * a + 3.0 ) + 3.0 ) + 1.0 );
	}
	float w3( float a ) {
		return ( 1.0 / 6.0 ) * ( a * a * a );
	}
	float g0( float a ) {
		return w0( a ) + w1( a );
	}
	float g1( float a ) {
		return w2( a ) + w3( a );
	}
	float h0( float a ) {
		return - 1.0 + w1( a ) / ( w0( a ) + w1( a ) );
	}
	float h1( float a ) {
		return 1.0 + w3( a ) / ( w2( a ) + w3( a ) );
	}
	vec4 bicubic( sampler2D tex, vec2 uv, vec4 texelSize, float lod ) {
		uv = uv * texelSize.zw + 0.5;
		vec2 iuv = floor( uv );
		vec2 fuv = fract( uv );
		float g0x = g0( fuv.x );
		float g1x = g1( fuv.x );
		float h0x = h0( fuv.x );
		float h1x = h1( fuv.x );
		float h0y = h0( fuv.y );
		float h1y = h1( fuv.y );
		vec2 p0 = ( vec2( iuv.x + h0x, iuv.y + h0y ) - 0.5 ) * texelSize.xy;
		vec2 p1 = ( vec2( iuv.x + h1x, iuv.y + h0y ) - 0.5 ) * texelSize.xy;
		vec2 p2 = ( vec2( iuv.x + h0x, iuv.y + h1y ) - 0.5 ) * texelSize.xy;
		vec2 p3 = ( vec2( iuv.x + h1x, iuv.y + h1y ) - 0.5 ) * texelSize.xy;
		return g0( fuv.y ) * ( g0x * textureLod( tex, p0, lod ) + g1x * textureLod( tex, p1, lod ) ) +
			g1( fuv.y ) * ( g0x * textureLod( tex, p2, lod ) + g1x * textureLod( tex, p3, lod ) );
	}
	vec4 textureBicubic( sampler2D sampler, vec2 uv, float lod ) {
		vec2 fLodSize = vec2( textureSize( sampler, int( lod ) ) );
		vec2 cLodSize = vec2( textureSize( sampler, int( lod + 1.0 ) ) );
		vec2 fLodSizeInv = 1.0 / fLodSize;
		vec2 cLodSizeInv = 1.0 / cLodSize;
		vec4 fSample = bicubic( sampler, uv, vec4( fLodSizeInv, fLodSize ), floor( lod ) );
		vec4 cSample = bicubic( sampler, uv, vec4( cLodSizeInv, cLodSize ), ceil( lod ) );
		return mix( fSample, cSample, fract( lod ) );
	}
	vec3 getVolumeTransmissionRay( const in vec3 n, const in vec3 v, const in float thickness, const in float ior, const in mat4 modelMatrix ) {
		vec3 refractionVector = refract( - v, normalize( n ), 1.0 / ior );
		vec3 modelScale;
		modelScale.x = length( vec3( modelMatrix[ 0 ].xyz ) );
		modelScale.y = length( vec3( modelMatrix[ 1 ].xyz ) );
		modelScale.z = length( vec3( modelMatrix[ 2 ].xyz ) );
		return normalize( refractionVector ) * thickness * modelScale;
	}
	float applyIorToRoughness( const in float roughness, const in float ior ) {
		return roughness * clamp( ior * 2.0 - 2.0, 0.0, 1.0 );
	}
	vec4 getTransmissionSample( const in vec2 fragCoord, const in float roughness, const in float ior ) {
		float lod = log2( transmissionSamplerSize.x ) * applyIorToRoughness( roughness, ior );
		return textureBicubic( transmissionSamplerMap, fragCoord.xy, lod );
	}
	vec3 volumeAttenuation( const in float transmissionDistance, const in vec3 attenuationColor, const in float attenuationDistance ) {
		if ( isinf( attenuationDistance ) ) {
			return vec3( 1.0 );
		} else {
			vec3 attenuationCoefficient = -log( attenuationColor ) / attenuationDistance;
			vec3 transmittance = exp( - attenuationCoefficient * transmissionDistance );			return transmittance;
		}
	}
	vec4 getIBLVolumeRefraction( const in vec3 n, const in vec3 v, const in float roughness, const in vec3 diffuseColor,
		const in vec3 specularColor, const in float specularF90, const in vec3 position, const in mat4 modelMatrix,
		const in mat4 viewMatrix, const in mat4 projMatrix, const in float dispersion, const in float ior, const in float thickness,
		const in vec3 attenuationColor, const in float attenuationDistance ) {
		vec4 transmittedLight;
		vec3 transmittance;
		#ifdef USE_DISPERSION
			float halfSpread = ( ior - 1.0 ) * 0.025 * dispersion;
			vec3 iors = vec3( ior - halfSpread, ior, ior + halfSpread );
			for ( int i = 0; i < 3; i ++ ) {
				vec3 transmissionRay = getVolumeTransmissionRay( n, v, thickness, iors[ i ], modelMatrix );
				vec3 refractedRayExit = position + transmissionRay;
				vec4 ndcPos = projMatrix * viewMatrix * vec4( refractedRayExit, 1.0 );
				vec2 refractionCoords = ndcPos.xy / ndcPos.w;
				refractionCoords += 1.0;
				refractionCoords /= 2.0;
				vec4 transmissionSample = getTransmissionSample( refractionCoords, roughness, iors[ i ] );
				transmittedLight[ i ] = transmissionSample[ i ];
				transmittedLight.a += transmissionSample.a;
				transmittance[ i ] = diffuseColor[ i ] * volumeAttenuation( length( transmissionRay ), attenuationColor, attenuationDistance )[ i ];
			}
			transmittedLight.a /= 3.0;
		#else
			vec3 transmissionRay = getVolumeTransmissionRay( n, v, thickness, ior, modelMatrix );
			vec3 refractedRayExit = position + transmissionRay;
			vec4 ndcPos = projMatrix * viewMatrix * vec4( refractedRayExit, 1.0 );
			vec2 refractionCoords = ndcPos.xy / ndcPos.w;
			refractionCoords += 1.0;
			refractionCoords /= 2.0;
			transmittedLight = getTransmissionSample( refractionCoords, roughness, ior );
			transmittance = diffuseColor * volumeAttenuation( length( transmissionRay ), attenuationColor, attenuationDistance );
		#endif
		vec3 attenuatedColor = transmittance * transmittedLight.rgb;
		vec3 F = EnvironmentBRDF( n, v, specularColor, specularF90, roughness );
		float transmittanceFactor = ( transmittance.r + transmittance.g + transmittance.b ) / 3.0;
		return vec4( ( 1.0 - F ) * attenuatedColor, 1.0 - ( 1.0 - transmittedLight.a ) * transmittanceFactor );
	}
#endif`,o0=`#if defined( USE_UV ) || defined( USE_ANISOTROPY )
	varying vec2 vUv;
#endif
#ifdef USE_MAP
	varying vec2 vMapUv;
#endif
#ifdef USE_ALPHAMAP
	varying vec2 vAlphaMapUv;
#endif
#ifdef USE_LIGHTMAP
	varying vec2 vLightMapUv;
#endif
#ifdef USE_AOMAP
	varying vec2 vAoMapUv;
#endif
#ifdef USE_BUMPMAP
	varying vec2 vBumpMapUv;
#endif
#ifdef USE_NORMALMAP
	varying vec2 vNormalMapUv;
#endif
#ifdef USE_EMISSIVEMAP
	varying vec2 vEmissiveMapUv;
#endif
#ifdef USE_METALNESSMAP
	varying vec2 vMetalnessMapUv;
#endif
#ifdef USE_ROUGHNESSMAP
	varying vec2 vRoughnessMapUv;
#endif
#ifdef USE_ANISOTROPYMAP
	varying vec2 vAnisotropyMapUv;
#endif
#ifdef USE_CLEARCOATMAP
	varying vec2 vClearcoatMapUv;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	varying vec2 vClearcoatNormalMapUv;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	varying vec2 vClearcoatRoughnessMapUv;
#endif
#ifdef USE_IRIDESCENCEMAP
	varying vec2 vIridescenceMapUv;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	varying vec2 vIridescenceThicknessMapUv;
#endif
#ifdef USE_SHEEN_COLORMAP
	varying vec2 vSheenColorMapUv;
#endif
#ifdef USE_SHEEN_ROUGHNESSMAP
	varying vec2 vSheenRoughnessMapUv;
#endif
#ifdef USE_SPECULARMAP
	varying vec2 vSpecularMapUv;
#endif
#ifdef USE_SPECULAR_COLORMAP
	varying vec2 vSpecularColorMapUv;
#endif
#ifdef USE_SPECULAR_INTENSITYMAP
	varying vec2 vSpecularIntensityMapUv;
#endif
#ifdef USE_TRANSMISSIONMAP
	uniform mat3 transmissionMapTransform;
	varying vec2 vTransmissionMapUv;
#endif
#ifdef USE_THICKNESSMAP
	uniform mat3 thicknessMapTransform;
	varying vec2 vThicknessMapUv;
#endif`,l0=`#if defined( USE_UV ) || defined( USE_ANISOTROPY )
	varying vec2 vUv;
#endif
#ifdef USE_MAP
	uniform mat3 mapTransform;
	varying vec2 vMapUv;
#endif
#ifdef USE_ALPHAMAP
	uniform mat3 alphaMapTransform;
	varying vec2 vAlphaMapUv;
#endif
#ifdef USE_LIGHTMAP
	uniform mat3 lightMapTransform;
	varying vec2 vLightMapUv;
#endif
#ifdef USE_AOMAP
	uniform mat3 aoMapTransform;
	varying vec2 vAoMapUv;
#endif
#ifdef USE_BUMPMAP
	uniform mat3 bumpMapTransform;
	varying vec2 vBumpMapUv;
#endif
#ifdef USE_NORMALMAP
	uniform mat3 normalMapTransform;
	varying vec2 vNormalMapUv;
#endif
#ifdef USE_DISPLACEMENTMAP
	uniform mat3 displacementMapTransform;
	varying vec2 vDisplacementMapUv;
#endif
#ifdef USE_EMISSIVEMAP
	uniform mat3 emissiveMapTransform;
	varying vec2 vEmissiveMapUv;
#endif
#ifdef USE_METALNESSMAP
	uniform mat3 metalnessMapTransform;
	varying vec2 vMetalnessMapUv;
#endif
#ifdef USE_ROUGHNESSMAP
	uniform mat3 roughnessMapTransform;
	varying vec2 vRoughnessMapUv;
#endif
#ifdef USE_ANISOTROPYMAP
	uniform mat3 anisotropyMapTransform;
	varying vec2 vAnisotropyMapUv;
#endif
#ifdef USE_CLEARCOATMAP
	uniform mat3 clearcoatMapTransform;
	varying vec2 vClearcoatMapUv;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	uniform mat3 clearcoatNormalMapTransform;
	varying vec2 vClearcoatNormalMapUv;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	uniform mat3 clearcoatRoughnessMapTransform;
	varying vec2 vClearcoatRoughnessMapUv;
#endif
#ifdef USE_SHEEN_COLORMAP
	uniform mat3 sheenColorMapTransform;
	varying vec2 vSheenColorMapUv;
#endif
#ifdef USE_SHEEN_ROUGHNESSMAP
	uniform mat3 sheenRoughnessMapTransform;
	varying vec2 vSheenRoughnessMapUv;
#endif
#ifdef USE_IRIDESCENCEMAP
	uniform mat3 iridescenceMapTransform;
	varying vec2 vIridescenceMapUv;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	uniform mat3 iridescenceThicknessMapTransform;
	varying vec2 vIridescenceThicknessMapUv;
#endif
#ifdef USE_SPECULARMAP
	uniform mat3 specularMapTransform;
	varying vec2 vSpecularMapUv;
#endif
#ifdef USE_SPECULAR_COLORMAP
	uniform mat3 specularColorMapTransform;
	varying vec2 vSpecularColorMapUv;
#endif
#ifdef USE_SPECULAR_INTENSITYMAP
	uniform mat3 specularIntensityMapTransform;
	varying vec2 vSpecularIntensityMapUv;
#endif
#ifdef USE_TRANSMISSIONMAP
	uniform mat3 transmissionMapTransform;
	varying vec2 vTransmissionMapUv;
#endif
#ifdef USE_THICKNESSMAP
	uniform mat3 thicknessMapTransform;
	varying vec2 vThicknessMapUv;
#endif`,c0=`#if defined( USE_UV ) || defined( USE_ANISOTROPY )
	vUv = vec3( uv, 1 ).xy;
#endif
#ifdef USE_MAP
	vMapUv = ( mapTransform * vec3( MAP_UV, 1 ) ).xy;
#endif
#ifdef USE_ALPHAMAP
	vAlphaMapUv = ( alphaMapTransform * vec3( ALPHAMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_LIGHTMAP
	vLightMapUv = ( lightMapTransform * vec3( LIGHTMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_AOMAP
	vAoMapUv = ( aoMapTransform * vec3( AOMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_BUMPMAP
	vBumpMapUv = ( bumpMapTransform * vec3( BUMPMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_NORMALMAP
	vNormalMapUv = ( normalMapTransform * vec3( NORMALMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_DISPLACEMENTMAP
	vDisplacementMapUv = ( displacementMapTransform * vec3( DISPLACEMENTMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_EMISSIVEMAP
	vEmissiveMapUv = ( emissiveMapTransform * vec3( EMISSIVEMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_METALNESSMAP
	vMetalnessMapUv = ( metalnessMapTransform * vec3( METALNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_ROUGHNESSMAP
	vRoughnessMapUv = ( roughnessMapTransform * vec3( ROUGHNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_ANISOTROPYMAP
	vAnisotropyMapUv = ( anisotropyMapTransform * vec3( ANISOTROPYMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_CLEARCOATMAP
	vClearcoatMapUv = ( clearcoatMapTransform * vec3( CLEARCOATMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	vClearcoatNormalMapUv = ( clearcoatNormalMapTransform * vec3( CLEARCOAT_NORMALMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	vClearcoatRoughnessMapUv = ( clearcoatRoughnessMapTransform * vec3( CLEARCOAT_ROUGHNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_IRIDESCENCEMAP
	vIridescenceMapUv = ( iridescenceMapTransform * vec3( IRIDESCENCEMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	vIridescenceThicknessMapUv = ( iridescenceThicknessMapTransform * vec3( IRIDESCENCE_THICKNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SHEEN_COLORMAP
	vSheenColorMapUv = ( sheenColorMapTransform * vec3( SHEEN_COLORMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SHEEN_ROUGHNESSMAP
	vSheenRoughnessMapUv = ( sheenRoughnessMapTransform * vec3( SHEEN_ROUGHNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SPECULARMAP
	vSpecularMapUv = ( specularMapTransform * vec3( SPECULARMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SPECULAR_COLORMAP
	vSpecularColorMapUv = ( specularColorMapTransform * vec3( SPECULAR_COLORMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SPECULAR_INTENSITYMAP
	vSpecularIntensityMapUv = ( specularIntensityMapTransform * vec3( SPECULAR_INTENSITYMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_TRANSMISSIONMAP
	vTransmissionMapUv = ( transmissionMapTransform * vec3( TRANSMISSIONMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_THICKNESSMAP
	vThicknessMapUv = ( thicknessMapTransform * vec3( THICKNESSMAP_UV, 1 ) ).xy;
#endif`,h0=`#if defined( USE_ENVMAP ) || defined( DISTANCE ) || defined ( USE_SHADOWMAP ) || defined ( USE_TRANSMISSION ) || NUM_SPOT_LIGHT_COORDS > 0
	vec4 worldPosition = vec4( transformed, 1.0 );
	#ifdef USE_BATCHING
		worldPosition = batchingMatrix * worldPosition;
	#endif
	#ifdef USE_INSTANCING
		worldPosition = instanceMatrix * worldPosition;
	#endif
	worldPosition = modelMatrix * worldPosition;
#endif`;const u0=`varying vec2 vUv;
uniform mat3 uvTransform;
void main() {
	vUv = ( uvTransform * vec3( uv, 1 ) ).xy;
	gl_Position = vec4( position.xy, 1.0, 1.0 );
}`,d0=`uniform sampler2D t2D;
uniform float backgroundIntensity;
varying vec2 vUv;
void main() {
	vec4 texColor = texture2D( t2D, vUv );
	#ifdef DECODE_VIDEO_TEXTURE
		texColor = vec4( mix( pow( texColor.rgb * 0.9478672986 + vec3( 0.0521327014 ), vec3( 2.4 ) ), texColor.rgb * 0.0773993808, vec3( lessThanEqual( texColor.rgb, vec3( 0.04045 ) ) ) ), texColor.w );
	#endif
	texColor.rgb *= backgroundIntensity;
	gl_FragColor = texColor;
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,f0=`varying vec3 vWorldDirection;
#include <common>
void main() {
	vWorldDirection = transformDirection( position, modelMatrix );
	#include <begin_vertex>
	#include <project_vertex>
	gl_Position.z = gl_Position.w;
}`,p0=`#ifdef ENVMAP_TYPE_CUBE
	uniform samplerCube envMap;
#elif defined( ENVMAP_TYPE_CUBE_UV )
	uniform sampler2D envMap;
#endif
uniform float flipEnvMap;
uniform float backgroundBlurriness;
uniform float backgroundIntensity;
uniform mat3 backgroundRotation;
varying vec3 vWorldDirection;
#include <cube_uv_reflection_fragment>
void main() {
	#ifdef ENVMAP_TYPE_CUBE
		vec4 texColor = textureCube( envMap, backgroundRotation * vec3( flipEnvMap * vWorldDirection.x, vWorldDirection.yz ) );
	#elif defined( ENVMAP_TYPE_CUBE_UV )
		vec4 texColor = textureCubeUV( envMap, backgroundRotation * vWorldDirection, backgroundBlurriness );
	#else
		vec4 texColor = vec4( 0.0, 0.0, 0.0, 1.0 );
	#endif
	texColor.rgb *= backgroundIntensity;
	gl_FragColor = texColor;
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,m0=`varying vec3 vWorldDirection;
#include <common>
void main() {
	vWorldDirection = transformDirection( position, modelMatrix );
	#include <begin_vertex>
	#include <project_vertex>
	gl_Position.z = gl_Position.w;
}`,g0=`uniform samplerCube tCube;
uniform float tFlip;
uniform float opacity;
varying vec3 vWorldDirection;
void main() {
	vec4 texColor = textureCube( tCube, vec3( tFlip * vWorldDirection.x, vWorldDirection.yz ) );
	gl_FragColor = texColor;
	gl_FragColor.a *= opacity;
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,_0=`#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
varying vec2 vHighPrecisionZW;
void main() {
	#include <uv_vertex>
	#include <batching_vertex>
	#include <skinbase_vertex>
	#include <morphinstance_vertex>
	#ifdef USE_DISPLACEMENTMAP
		#include <beginnormal_vertex>
		#include <morphnormal_vertex>
		#include <skinnormal_vertex>
	#endif
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vHighPrecisionZW = gl_Position.zw;
}`,v0=`#if DEPTH_PACKING == 3200
	uniform float opacity;
#endif
#include <common>
#include <packing>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
varying vec2 vHighPrecisionZW;
void main() {
	vec4 diffuseColor = vec4( 1.0 );
	#include <clipping_planes_fragment>
	#if DEPTH_PACKING == 3200
		diffuseColor.a = opacity;
	#endif
	#include <map_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <logdepthbuf_fragment>
	#ifdef USE_REVERSED_DEPTH_BUFFER
		float fragCoordZ = vHighPrecisionZW[ 0 ] / vHighPrecisionZW[ 1 ];
	#else
		float fragCoordZ = 0.5 * vHighPrecisionZW[ 0 ] / vHighPrecisionZW[ 1 ] + 0.5;
	#endif
	#if DEPTH_PACKING == 3200
		gl_FragColor = vec4( vec3( 1.0 - fragCoordZ ), opacity );
	#elif DEPTH_PACKING == 3201
		gl_FragColor = packDepthToRGBA( fragCoordZ );
	#elif DEPTH_PACKING == 3202
		gl_FragColor = vec4( packDepthToRGB( fragCoordZ ), 1.0 );
	#elif DEPTH_PACKING == 3203
		gl_FragColor = vec4( packDepthToRG( fragCoordZ ), 0.0, 1.0 );
	#endif
}`,x0=`#define DISTANCE
varying vec3 vWorldPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <batching_vertex>
	#include <skinbase_vertex>
	#include <morphinstance_vertex>
	#ifdef USE_DISPLACEMENTMAP
		#include <beginnormal_vertex>
		#include <morphnormal_vertex>
		#include <skinnormal_vertex>
	#endif
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <worldpos_vertex>
	#include <clipping_planes_vertex>
	vWorldPosition = worldPosition.xyz;
}`,M0=`#define DISTANCE
uniform vec3 referencePosition;
uniform float nearDistance;
uniform float farDistance;
varying vec3 vWorldPosition;
#include <common>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <clipping_planes_pars_fragment>
void main () {
	vec4 diffuseColor = vec4( 1.0 );
	#include <clipping_planes_fragment>
	#include <map_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	float dist = length( vWorldPosition - referencePosition );
	dist = ( dist - nearDistance ) / ( farDistance - nearDistance );
	dist = saturate( dist );
	gl_FragColor = vec4( dist, 0.0, 0.0, 1.0 );
}`,y0=`varying vec3 vWorldDirection;
#include <common>
void main() {
	vWorldDirection = transformDirection( position, modelMatrix );
	#include <begin_vertex>
	#include <project_vertex>
}`,S0=`uniform sampler2D tEquirect;
varying vec3 vWorldDirection;
#include <common>
void main() {
	vec3 direction = normalize( vWorldDirection );
	vec2 sampleUV = equirectUv( direction );
	gl_FragColor = texture2D( tEquirect, sampleUV );
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,b0=`uniform float scale;
attribute float lineDistance;
varying float vLineDistance;
#include <common>
#include <uv_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	vLineDistance = scale * lineDistance;
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <fog_vertex>
}`,E0=`uniform vec3 diffuse;
uniform float opacity;
uniform float dashSize;
uniform float totalSize;
varying float vLineDistance;
#include <common>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <fog_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	if ( mod( vLineDistance, totalSize ) > dashSize ) {
		discard;
	}
	vec3 outgoingLight = vec3( 0.0 );
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	outgoingLight = diffuseColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
}`,T0=`#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <envmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#if defined ( USE_ENVMAP ) || defined ( USE_SKINNING )
		#include <beginnormal_vertex>
		#include <morphnormal_vertex>
		#include <skinbase_vertex>
		#include <skinnormal_vertex>
		#include <defaultnormal_vertex>
	#endif
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <worldpos_vertex>
	#include <envmap_vertex>
	#include <fog_vertex>
}`,A0=`uniform vec3 diffuse;
uniform float opacity;
#ifndef FLAT_SHADED
	varying vec3 vNormal;
#endif
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_pars_fragment>
#include <fog_pars_fragment>
#include <specularmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <specularmap_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	#ifdef USE_LIGHTMAP
		vec4 lightMapTexel = texture2D( lightMap, vLightMapUv );
		reflectedLight.indirectDiffuse += lightMapTexel.rgb * lightMapIntensity * RECIPROCAL_PI;
	#else
		reflectedLight.indirectDiffuse += vec3( 1.0 );
	#endif
	#include <aomap_fragment>
	reflectedLight.indirectDiffuse *= diffuseColor.rgb;
	vec3 outgoingLight = reflectedLight.indirectDiffuse;
	#include <envmap_fragment>
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,w0=`#define LAMBERT
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <envmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <envmap_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,R0=`#define LAMBERT
uniform vec3 diffuse;
uniform vec3 emissive;
uniform float opacity;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <cube_uv_reflection_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_pars_fragment>
#include <envmap_physical_pars_fragment>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_lambert_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <specularmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <specularmap_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_lambert_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + totalEmissiveRadiance;
	#include <envmap_fragment>
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,C0=`#define MATCAP
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <color_pars_vertex>
#include <displacementmap_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <fog_vertex>
	vViewPosition = - mvPosition.xyz;
}`,P0=`#define MATCAP
uniform vec3 diffuse;
uniform float opacity;
uniform sampler2D matcap;
varying vec3 vViewPosition;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <fog_pars_fragment>
#include <normal_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	vec3 viewDir = normalize( vViewPosition );
	vec3 x = normalize( vec3( viewDir.z, 0.0, - viewDir.x ) );
	vec3 y = cross( viewDir, x );
	vec2 uv = vec2( dot( x, normal ), dot( y, normal ) ) * 0.495 + 0.5;
	#ifdef USE_MATCAP
		vec4 matcapColor = texture2D( matcap, uv );
	#else
		vec4 matcapColor = vec4( vec3( mix( 0.2, 0.8, uv.y ) ), 1.0 );
	#endif
	vec3 outgoingLight = diffuseColor.rgb * matcapColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,D0=`#define NORMAL
#if defined( FLAT_SHADED ) || defined( USE_BUMPMAP ) || defined( USE_NORMALMAP_TANGENTSPACE )
	varying vec3 vViewPosition;
#endif
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphinstance_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
#if defined( FLAT_SHADED ) || defined( USE_BUMPMAP ) || defined( USE_NORMALMAP_TANGENTSPACE )
	vViewPosition = - mvPosition.xyz;
#endif
}`,L0=`#define NORMAL
uniform float opacity;
#if defined( FLAT_SHADED ) || defined( USE_BUMPMAP ) || defined( USE_NORMALMAP_TANGENTSPACE )
	varying vec3 vViewPosition;
#endif
#include <uv_pars_fragment>
#include <normal_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( 0.0, 0.0, 0.0, opacity );
	#include <clipping_planes_fragment>
	#include <logdepthbuf_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	gl_FragColor = vec4( normalize( normal ) * 0.5 + 0.5, diffuseColor.a );
	#ifdef OPAQUE
		gl_FragColor.a = 1.0;
	#endif
}`,I0=`#define PHONG
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <envmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphinstance_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <envmap_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,N0=`#define PHONG
uniform vec3 diffuse;
uniform vec3 emissive;
uniform vec3 specular;
uniform float shininess;
uniform float opacity;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <cube_uv_reflection_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_pars_fragment>
#include <envmap_physical_pars_fragment>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_phong_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <specularmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <specularmap_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_phong_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + reflectedLight.directSpecular + reflectedLight.indirectSpecular + totalEmissiveRadiance;
	#include <envmap_fragment>
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,U0=`#define STANDARD
varying vec3 vViewPosition;
#ifdef USE_TRANSMISSION
	varying vec3 vWorldPosition;
#endif
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
#ifdef USE_TRANSMISSION
	vWorldPosition = worldPosition.xyz;
#endif
}`,F0=`#define STANDARD
#ifdef PHYSICAL
	#define IOR
	#define USE_SPECULAR
#endif
uniform vec3 diffuse;
uniform vec3 emissive;
uniform float roughness;
uniform float metalness;
uniform float opacity;
#ifdef IOR
	uniform float ior;
#endif
#ifdef USE_SPECULAR
	uniform float specularIntensity;
	uniform vec3 specularColor;
	#ifdef USE_SPECULAR_COLORMAP
		uniform sampler2D specularColorMap;
	#endif
	#ifdef USE_SPECULAR_INTENSITYMAP
		uniform sampler2D specularIntensityMap;
	#endif
#endif
#ifdef USE_CLEARCOAT
	uniform float clearcoat;
	uniform float clearcoatRoughness;
#endif
#ifdef USE_DISPERSION
	uniform float dispersion;
#endif
#ifdef USE_IRIDESCENCE
	uniform float iridescence;
	uniform float iridescenceIOR;
	uniform float iridescenceThicknessMinimum;
	uniform float iridescenceThicknessMaximum;
#endif
#ifdef USE_SHEEN
	uniform vec3 sheenColor;
	uniform float sheenRoughness;
	#ifdef USE_SHEEN_COLORMAP
		uniform sampler2D sheenColorMap;
	#endif
	#ifdef USE_SHEEN_ROUGHNESSMAP
		uniform sampler2D sheenRoughnessMap;
	#endif
#endif
#ifdef USE_ANISOTROPY
	uniform vec2 anisotropyVector;
	#ifdef USE_ANISOTROPYMAP
		uniform sampler2D anisotropyMap;
	#endif
#endif
varying vec3 vViewPosition;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <iridescence_fragment>
#include <cube_uv_reflection_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_physical_pars_fragment>
#include <fog_pars_fragment>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_physical_pars_fragment>
#include <transmission_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <clearcoat_pars_fragment>
#include <iridescence_pars_fragment>
#include <roughnessmap_pars_fragment>
#include <metalnessmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <roughnessmap_fragment>
	#include <metalnessmap_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <clearcoat_normal_fragment_begin>
	#include <clearcoat_normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_physical_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 totalDiffuse = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse;
	vec3 totalSpecular = reflectedLight.directSpecular + reflectedLight.indirectSpecular;
	#include <transmission_fragment>
	vec3 outgoingLight = totalDiffuse + totalSpecular + totalEmissiveRadiance;
	#ifdef USE_SHEEN
 
		outgoingLight = outgoingLight + sheenSpecularDirect + sheenSpecularIndirect;
 
 	#endif
	#ifdef USE_CLEARCOAT
		float dotNVcc = saturate( dot( geometryClearcoatNormal, geometryViewDir ) );
		vec3 Fcc = F_Schlick( material.clearcoatF0, material.clearcoatF90, dotNVcc );
		outgoingLight = outgoingLight * ( 1.0 - material.clearcoat * Fcc ) + ( clearcoatSpecularDirect + clearcoatSpecularIndirect ) * material.clearcoat;
	#endif
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,O0=`#define TOON
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,B0=`#define TOON
uniform vec3 diffuse;
uniform vec3 emissive;
uniform float opacity;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <gradientmap_pars_fragment>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_toon_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_toon_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + totalEmissiveRadiance;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,k0=`uniform float size;
uniform float scale;
#include <common>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
#ifdef USE_POINTS_UV
	varying vec2 vUv;
	uniform mat3 uvTransform;
#endif
void main() {
	#ifdef USE_POINTS_UV
		vUv = ( uvTransform * vec3( uv, 1 ) ).xy;
	#endif
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <project_vertex>
	gl_PointSize = size;
	#ifdef USE_SIZEATTENUATION
		bool isPerspective = isPerspectiveMatrix( projectionMatrix );
		if ( isPerspective ) gl_PointSize *= ( scale / - mvPosition.z );
	#endif
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <worldpos_vertex>
	#include <fog_vertex>
}`,V0=`uniform vec3 diffuse;
uniform float opacity;
#include <common>
#include <color_pars_fragment>
#include <map_particle_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <fog_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	vec3 outgoingLight = vec3( 0.0 );
	#include <logdepthbuf_fragment>
	#include <map_particle_fragment>
	#include <color_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	outgoingLight = diffuseColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
}`,z0=`#include <common>
#include <batching_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <shadowmap_pars_vertex>
void main() {
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphinstance_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <worldpos_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,H0=`uniform vec3 color;
uniform float opacity;
#include <common>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <logdepthbuf_pars_fragment>
#include <shadowmap_pars_fragment>
#include <shadowmask_pars_fragment>
void main() {
	#include <logdepthbuf_fragment>
	gl_FragColor = vec4( color, opacity * ( 1.0 - getShadowMask() ) );
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
}`,G0=`uniform float rotation;
uniform vec2 center;
#include <common>
#include <uv_pars_vertex>
#include <fog_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	vec4 mvPosition = modelViewMatrix[ 3 ];
	vec2 scale = vec2( length( modelMatrix[ 0 ].xyz ), length( modelMatrix[ 1 ].xyz ) );
	#ifndef USE_SIZEATTENUATION
		bool isPerspective = isPerspectiveMatrix( projectionMatrix );
		if ( isPerspective ) scale *= - mvPosition.z;
	#endif
	vec2 alignedPosition = ( position.xy - ( center - vec2( 0.5 ) ) ) * scale;
	vec2 rotatedPosition;
	rotatedPosition.x = cos( rotation ) * alignedPosition.x - sin( rotation ) * alignedPosition.y;
	rotatedPosition.y = sin( rotation ) * alignedPosition.x + cos( rotation ) * alignedPosition.y;
	mvPosition.xy += rotatedPosition;
	gl_Position = projectionMatrix * mvPosition;
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <fog_vertex>
}`,W0=`uniform vec3 diffuse;
uniform float opacity;
#include <common>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <fog_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	vec3 outgoingLight = vec3( 0.0 );
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	outgoingLight = diffuseColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
}`,Ge={alphahash_fragment:dm,alphahash_pars_fragment:fm,alphamap_fragment:pm,alphamap_pars_fragment:mm,alphatest_fragment:gm,alphatest_pars_fragment:_m,aomap_fragment:vm,aomap_pars_fragment:xm,batching_pars_vertex:Mm,batching_vertex:ym,begin_vertex:Sm,beginnormal_vertex:bm,bsdfs:Em,iridescence_fragment:Tm,bumpmap_pars_fragment:Am,clipping_planes_fragment:wm,clipping_planes_pars_fragment:Rm,clipping_planes_pars_vertex:Cm,clipping_planes_vertex:Pm,color_fragment:Dm,color_pars_fragment:Lm,color_pars_vertex:Im,color_vertex:Nm,common:Um,cube_uv_reflection_fragment:Fm,defaultnormal_vertex:Om,displacementmap_pars_vertex:Bm,displacementmap_vertex:km,emissivemap_fragment:Vm,emissivemap_pars_fragment:zm,colorspace_fragment:Hm,colorspace_pars_fragment:Gm,envmap_fragment:Wm,envmap_common_pars_fragment:Xm,envmap_pars_fragment:Ym,envmap_pars_vertex:qm,envmap_physical_pars_fragment:sg,envmap_vertex:jm,fog_vertex:Km,fog_pars_vertex:$m,fog_fragment:Zm,fog_pars_fragment:Jm,gradientmap_pars_fragment:Qm,lightmap_pars_fragment:eg,lights_lambert_fragment:tg,lights_lambert_pars_fragment:ng,lights_pars_begin:ig,lights_toon_fragment:rg,lights_toon_pars_fragment:ag,lights_phong_fragment:og,lights_phong_pars_fragment:lg,lights_physical_fragment:cg,lights_physical_pars_fragment:hg,lights_fragment_begin:ug,lights_fragment_maps:dg,lights_fragment_end:fg,logdepthbuf_fragment:pg,logdepthbuf_pars_fragment:mg,logdepthbuf_pars_vertex:gg,logdepthbuf_vertex:_g,map_fragment:vg,map_pars_fragment:xg,map_particle_fragment:Mg,map_particle_pars_fragment:yg,metalnessmap_fragment:Sg,metalnessmap_pars_fragment:bg,morphinstance_vertex:Eg,morphcolor_vertex:Tg,morphnormal_vertex:Ag,morphtarget_pars_vertex:wg,morphtarget_vertex:Rg,normal_fragment_begin:Cg,normal_fragment_maps:Pg,normal_pars_fragment:Dg,normal_pars_vertex:Lg,normal_vertex:Ig,normalmap_pars_fragment:Ng,clearcoat_normal_fragment_begin:Ug,clearcoat_normal_fragment_maps:Fg,clearcoat_pars_fragment:Og,iridescence_pars_fragment:Bg,opaque_fragment:kg,packing:Vg,premultiplied_alpha_fragment:zg,project_vertex:Hg,dithering_fragment:Gg,dithering_pars_fragment:Wg,roughnessmap_fragment:Xg,roughnessmap_pars_fragment:Yg,shadowmap_pars_fragment:qg,shadowmap_pars_vertex:jg,shadowmap_vertex:Kg,shadowmask_pars_fragment:$g,skinbase_vertex:Zg,skinning_pars_vertex:Jg,skinning_vertex:Qg,skinnormal_vertex:e0,specularmap_fragment:t0,specularmap_pars_fragment:n0,tonemapping_fragment:i0,tonemapping_pars_fragment:s0,transmission_fragment:r0,transmission_pars_fragment:a0,uv_pars_fragment:o0,uv_pars_vertex:l0,uv_vertex:c0,worldpos_vertex:h0,background_vert:u0,background_frag:d0,backgroundCube_vert:f0,backgroundCube_frag:p0,cube_vert:m0,cube_frag:g0,depth_vert:_0,depth_frag:v0,distance_vert:x0,distance_frag:M0,equirect_vert:y0,equirect_frag:S0,linedashed_vert:b0,linedashed_frag:E0,meshbasic_vert:T0,meshbasic_frag:A0,meshlambert_vert:w0,meshlambert_frag:R0,meshmatcap_vert:C0,meshmatcap_frag:P0,meshnormal_vert:D0,meshnormal_frag:L0,meshphong_vert:I0,meshphong_frag:N0,meshphysical_vert:U0,meshphysical_frag:F0,meshtoon_vert:O0,meshtoon_frag:B0,points_vert:k0,points_frag:V0,shadow_vert:z0,shadow_frag:H0,sprite_vert:G0,sprite_frag:W0},ue={common:{diffuse:{value:new Ie(16777215)},opacity:{value:1},map:{value:null},mapTransform:{value:new He},alphaMap:{value:null},alphaMapTransform:{value:new He},alphaTest:{value:0}},specularmap:{specularMap:{value:null},specularMapTransform:{value:new He}},envmap:{envMap:{value:null},envMapRotation:{value:new He},flipEnvMap:{value:-1},reflectivity:{value:1},ior:{value:1.5},refractionRatio:{value:.98},dfgLUT:{value:null}},aomap:{aoMap:{value:null},aoMapIntensity:{value:1},aoMapTransform:{value:new He}},lightmap:{lightMap:{value:null},lightMapIntensity:{value:1},lightMapTransform:{value:new He}},bumpmap:{bumpMap:{value:null},bumpMapTransform:{value:new He},bumpScale:{value:1}},normalmap:{normalMap:{value:null},normalMapTransform:{value:new He},normalScale:{value:new Le(1,1)}},displacementmap:{displacementMap:{value:null},displacementMapTransform:{value:new He},displacementScale:{value:1},displacementBias:{value:0}},emissivemap:{emissiveMap:{value:null},emissiveMapTransform:{value:new He}},metalnessmap:{metalnessMap:{value:null},metalnessMapTransform:{value:new He}},roughnessmap:{roughnessMap:{value:null},roughnessMapTransform:{value:new He}},gradientmap:{gradientMap:{value:null}},fog:{fogDensity:{value:25e-5},fogNear:{value:1},fogFar:{value:2e3},fogColor:{value:new Ie(16777215)}},lights:{ambientLightColor:{value:[]},lightProbe:{value:[]},directionalLights:{value:[],properties:{direction:{},color:{}}},directionalLightShadows:{value:[],properties:{shadowIntensity:1,shadowBias:{},shadowNormalBias:{},shadowRadius:{},shadowMapSize:{}}},directionalShadowMatrix:{value:[]},spotLights:{value:[],properties:{color:{},position:{},direction:{},distance:{},coneCos:{},penumbraCos:{},decay:{}}},spotLightShadows:{value:[],properties:{shadowIntensity:1,shadowBias:{},shadowNormalBias:{},shadowRadius:{},shadowMapSize:{}}},spotLightMap:{value:[]},spotLightMatrix:{value:[]},pointLights:{value:[],properties:{color:{},position:{},decay:{},distance:{}}},pointLightShadows:{value:[],properties:{shadowIntensity:1,shadowBias:{},shadowNormalBias:{},shadowRadius:{},shadowMapSize:{},shadowCameraNear:{},shadowCameraFar:{}}},pointShadowMatrix:{value:[]},hemisphereLights:{value:[],properties:{direction:{},skyColor:{},groundColor:{}}},rectAreaLights:{value:[],properties:{color:{},position:{},width:{},height:{}}},ltc_1:{value:null},ltc_2:{value:null}},points:{diffuse:{value:new Ie(16777215)},opacity:{value:1},size:{value:1},scale:{value:1},map:{value:null},alphaMap:{value:null},alphaMapTransform:{value:new He},alphaTest:{value:0},uvTransform:{value:new He}},sprite:{diffuse:{value:new Ie(16777215)},opacity:{value:1},center:{value:new Le(.5,.5)},rotation:{value:0},map:{value:null},mapTransform:{value:new He},alphaMap:{value:null},alphaMapTransform:{value:new He},alphaTest:{value:0}}},Rn={basic:{uniforms:Yt([ue.common,ue.specularmap,ue.envmap,ue.aomap,ue.lightmap,ue.fog]),vertexShader:Ge.meshbasic_vert,fragmentShader:Ge.meshbasic_frag},lambert:{uniforms:Yt([ue.common,ue.specularmap,ue.envmap,ue.aomap,ue.lightmap,ue.emissivemap,ue.bumpmap,ue.normalmap,ue.displacementmap,ue.fog,ue.lights,{emissive:{value:new Ie(0)},envMapIntensity:{value:1}}]),vertexShader:Ge.meshlambert_vert,fragmentShader:Ge.meshlambert_frag},phong:{uniforms:Yt([ue.common,ue.specularmap,ue.envmap,ue.aomap,ue.lightmap,ue.emissivemap,ue.bumpmap,ue.normalmap,ue.displacementmap,ue.fog,ue.lights,{emissive:{value:new Ie(0)},specular:{value:new Ie(1118481)},shininess:{value:30},envMapIntensity:{value:1}}]),vertexShader:Ge.meshphong_vert,fragmentShader:Ge.meshphong_frag},standard:{uniforms:Yt([ue.common,ue.envmap,ue.aomap,ue.lightmap,ue.emissivemap,ue.bumpmap,ue.normalmap,ue.displacementmap,ue.roughnessmap,ue.metalnessmap,ue.fog,ue.lights,{emissive:{value:new Ie(0)},roughness:{value:1},metalness:{value:0},envMapIntensity:{value:1}}]),vertexShader:Ge.meshphysical_vert,fragmentShader:Ge.meshphysical_frag},toon:{uniforms:Yt([ue.common,ue.aomap,ue.lightmap,ue.emissivemap,ue.bumpmap,ue.normalmap,ue.displacementmap,ue.gradientmap,ue.fog,ue.lights,{emissive:{value:new Ie(0)}}]),vertexShader:Ge.meshtoon_vert,fragmentShader:Ge.meshtoon_frag},matcap:{uniforms:Yt([ue.common,ue.bumpmap,ue.normalmap,ue.displacementmap,ue.fog,{matcap:{value:null}}]),vertexShader:Ge.meshmatcap_vert,fragmentShader:Ge.meshmatcap_frag},points:{uniforms:Yt([ue.points,ue.fog]),vertexShader:Ge.points_vert,fragmentShader:Ge.points_frag},dashed:{uniforms:Yt([ue.common,ue.fog,{scale:{value:1},dashSize:{value:1},totalSize:{value:2}}]),vertexShader:Ge.linedashed_vert,fragmentShader:Ge.linedashed_frag},depth:{uniforms:Yt([ue.common,ue.displacementmap]),vertexShader:Ge.depth_vert,fragmentShader:Ge.depth_frag},normal:{uniforms:Yt([ue.common,ue.bumpmap,ue.normalmap,ue.displacementmap,{opacity:{value:1}}]),vertexShader:Ge.meshnormal_vert,fragmentShader:Ge.meshnormal_frag},sprite:{uniforms:Yt([ue.sprite,ue.fog]),vertexShader:Ge.sprite_vert,fragmentShader:Ge.sprite_frag},background:{uniforms:{uvTransform:{value:new He},t2D:{value:null},backgroundIntensity:{value:1}},vertexShader:Ge.background_vert,fragmentShader:Ge.background_frag},backgroundCube:{uniforms:{envMap:{value:null},flipEnvMap:{value:-1},backgroundBlurriness:{value:0},backgroundIntensity:{value:1},backgroundRotation:{value:new He}},vertexShader:Ge.backgroundCube_vert,fragmentShader:Ge.backgroundCube_frag},cube:{uniforms:{tCube:{value:null},tFlip:{value:-1},opacity:{value:1}},vertexShader:Ge.cube_vert,fragmentShader:Ge.cube_frag},equirect:{uniforms:{tEquirect:{value:null}},vertexShader:Ge.equirect_vert,fragmentShader:Ge.equirect_frag},distance:{uniforms:Yt([ue.common,ue.displacementmap,{referencePosition:{value:new L},nearDistance:{value:1},farDistance:{value:1e3}}]),vertexShader:Ge.distance_vert,fragmentShader:Ge.distance_frag},shadow:{uniforms:Yt([ue.lights,ue.fog,{color:{value:new Ie(0)},opacity:{value:1}}]),vertexShader:Ge.shadow_vert,fragmentShader:Ge.shadow_frag}};Rn.physical={uniforms:Yt([Rn.standard.uniforms,{clearcoat:{value:0},clearcoatMap:{value:null},clearcoatMapTransform:{value:new He},clearcoatNormalMap:{value:null},clearcoatNormalMapTransform:{value:new He},clearcoatNormalScale:{value:new Le(1,1)},clearcoatRoughness:{value:0},clearcoatRoughnessMap:{value:null},clearcoatRoughnessMapTransform:{value:new He},dispersion:{value:0},iridescence:{value:0},iridescenceMap:{value:null},iridescenceMapTransform:{value:new He},iridescenceIOR:{value:1.3},iridescenceThicknessMinimum:{value:100},iridescenceThicknessMaximum:{value:400},iridescenceThicknessMap:{value:null},iridescenceThicknessMapTransform:{value:new He},sheen:{value:0},sheenColor:{value:new Ie(0)},sheenColorMap:{value:null},sheenColorMapTransform:{value:new He},sheenRoughness:{value:1},sheenRoughnessMap:{value:null},sheenRoughnessMapTransform:{value:new He},transmission:{value:0},transmissionMap:{value:null},transmissionMapTransform:{value:new He},transmissionSamplerSize:{value:new Le},transmissionSamplerMap:{value:null},thickness:{value:0},thicknessMap:{value:null},thicknessMapTransform:{value:new He},attenuationDistance:{value:0},attenuationColor:{value:new Ie(0)},specularColor:{value:new Ie(1,1,1)},specularColorMap:{value:null},specularColorMapTransform:{value:new He},specularIntensity:{value:1},specularIntensityMap:{value:null},specularIntensityMapTransform:{value:new He},anisotropyVector:{value:new Le},anisotropyMap:{value:null},anisotropyMapTransform:{value:new He}}]),vertexShader:Ge.meshphysical_vert,fragmentShader:Ge.meshphysical_frag};const Or={r:0,b:0,g:0},Ti=new Sn,X0=new Ve;function Y0(s,e,t,n,i,r){const a=new Ie(0);let o=i===!0?0:1,l,c,h=null,u=0,d=null;function f(S){let T=S.isScene===!0?S.background:null;if(T&&T.isTexture){const M=S.backgroundBlurriness>0;T=e.get(T,M)}return T}function g(S){let T=!1;const M=f(S);M===null?p(a,o):M&&M.isColor&&(p(M,1),T=!0);const E=s.xr.getEnvironmentBlendMode();E==="additive"?t.buffers.color.setClear(0,0,0,1,r):E==="alpha-blend"&&t.buffers.color.setClear(0,0,0,0,r),(s.autoClear||T)&&(t.buffers.depth.setTest(!0),t.buffers.depth.setMask(!0),t.buffers.color.setMask(!0),s.clear(s.autoClearColor,s.autoClearDepth,s.autoClearStencil))}function x(S,T){const M=f(T);M&&(M.isCubeTexture||M.mapping===pa)?(c===void 0&&(c=new lt(new Cs(1,1,1),new kt({name:"BackgroundCubeMaterial",uniforms:Ss(Rn.backgroundCube.uniforms),vertexShader:Rn.backgroundCube.vertexShader,fragmentShader:Rn.backgroundCube.fragmentShader,side:qt,depthTest:!1,depthWrite:!1,fog:!1,allowOverride:!1})),c.geometry.deleteAttribute("normal"),c.geometry.deleteAttribute("uv"),c.onBeforeRender=function(E,w,C){this.matrixWorld.copyPosition(C.matrixWorld)},Object.defineProperty(c.material,"envMap",{get:function(){return this.uniforms.envMap.value}}),n.update(c)),Ti.copy(T.backgroundRotation),Ti.x*=-1,Ti.y*=-1,Ti.z*=-1,M.isCubeTexture&&M.isRenderTargetTexture===!1&&(Ti.y*=-1,Ti.z*=-1),c.material.uniforms.envMap.value=M,c.material.uniforms.flipEnvMap.value=M.isCubeTexture&&M.isRenderTargetTexture===!1?-1:1,c.material.uniforms.backgroundBlurriness.value=T.backgroundBlurriness,c.material.uniforms.backgroundIntensity.value=T.backgroundIntensity,c.material.uniforms.backgroundRotation.value.setFromMatrix4(X0.makeRotationFromEuler(Ti)),c.material.toneMapped=Ke.getTransfer(M.colorSpace)!==tt,(h!==M||u!==M.version||d!==s.toneMapping)&&(c.material.needsUpdate=!0,h=M,u=M.version,d=s.toneMapping),c.layers.enableAll(),S.unshift(c,c.geometry,c.material,0,0,null)):M&&M.isTexture&&(l===void 0&&(l=new lt(new Pi(2,2),new kt({name:"BackgroundMaterial",uniforms:Ss(Rn.background.uniforms),vertexShader:Rn.background.vertexShader,fragmentShader:Rn.background.fragmentShader,side:Zn,depthTest:!1,depthWrite:!1,fog:!1,allowOverride:!1})),l.geometry.deleteAttribute("normal"),Object.defineProperty(l.material,"map",{get:function(){return this.uniforms.t2D.value}}),n.update(l)),l.material.uniforms.t2D.value=M,l.material.uniforms.backgroundIntensity.value=T.backgroundIntensity,l.material.toneMapped=Ke.getTransfer(M.colorSpace)!==tt,M.matrixAutoUpdate===!0&&M.updateMatrix(),l.material.uniforms.uvTransform.value.copy(M.matrix),(h!==M||u!==M.version||d!==s.toneMapping)&&(l.material.needsUpdate=!0,h=M,u=M.version,d=s.toneMapping),l.layers.enableAll(),S.unshift(l,l.geometry,l.material,0,0,null))}function p(S,T){S.getRGB(Or,Lu(s)),t.buffers.color.setClear(Or.r,Or.g,Or.b,T,r)}function m(){c!==void 0&&(c.geometry.dispose(),c.material.dispose(),c=void 0),l!==void 0&&(l.geometry.dispose(),l.material.dispose(),l=void 0)}return{getClearColor:function(){return a},setClearColor:function(S,T=1){a.set(S),o=T,p(a,o)},getClearAlpha:function(){return o},setClearAlpha:function(S){o=S,p(a,o)},render:g,addToRenderList:x,dispose:m}}function q0(s,e){const t=s.getParameter(s.MAX_VERTEX_ATTRIBS),n={},i=d(null);let r=i,a=!1;function o(R,F,O,X,V){let k=!1;const U=u(R,X,O,F);r!==U&&(r=U,c(r.object)),k=f(R,X,O,V),k&&g(R,X,O,V),V!==null&&e.update(V,s.ELEMENT_ARRAY_BUFFER),(k||a)&&(a=!1,M(R,F,O,X),V!==null&&s.bindBuffer(s.ELEMENT_ARRAY_BUFFER,e.get(V).buffer))}function l(){return s.createVertexArray()}function c(R){return s.bindVertexArray(R)}function h(R){return s.deleteVertexArray(R)}function u(R,F,O,X){const V=X.wireframe===!0;let k=n[F.id];k===void 0&&(k={},n[F.id]=k);const U=R.isInstancedMesh===!0?R.id:0;let Q=k[U];Q===void 0&&(Q={},k[U]=Q);let K=Q[O.id];K===void 0&&(K={},Q[O.id]=K);let se=K[V];return se===void 0&&(se=d(l()),K[V]=se),se}function d(R){const F=[],O=[],X=[];for(let V=0;V<t;V++)F[V]=0,O[V]=0,X[V]=0;return{geometry:null,program:null,wireframe:!1,newAttributes:F,enabledAttributes:O,attributeDivisors:X,object:R,attributes:{},index:null}}function f(R,F,O,X){const V=r.attributes,k=F.attributes;let U=0;const Q=O.getAttributes();for(const K in Q)if(Q[K].location>=0){const he=V[K];let le=k[K];if(le===void 0&&(K==="instanceMatrix"&&R.instanceMatrix&&(le=R.instanceMatrix),K==="instanceColor"&&R.instanceColor&&(le=R.instanceColor)),he===void 0||he.attribute!==le||le&&he.data!==le.data)return!0;U++}return r.attributesNum!==U||r.index!==X}function g(R,F,O,X){const V={},k=F.attributes;let U=0;const Q=O.getAttributes();for(const K in Q)if(Q[K].location>=0){let he=k[K];he===void 0&&(K==="instanceMatrix"&&R.instanceMatrix&&(he=R.instanceMatrix),K==="instanceColor"&&R.instanceColor&&(he=R.instanceColor));const le={};le.attribute=he,he&&he.data&&(le.data=he.data),V[K]=le,U++}r.attributes=V,r.attributesNum=U,r.index=X}function x(){const R=r.newAttributes;for(let F=0,O=R.length;F<O;F++)R[F]=0}function p(R){m(R,0)}function m(R,F){const O=r.newAttributes,X=r.enabledAttributes,V=r.attributeDivisors;O[R]=1,X[R]===0&&(s.enableVertexAttribArray(R),X[R]=1),V[R]!==F&&(s.vertexAttribDivisor(R,F),V[R]=F)}function S(){const R=r.newAttributes,F=r.enabledAttributes;for(let O=0,X=F.length;O<X;O++)F[O]!==R[O]&&(s.disableVertexAttribArray(O),F[O]=0)}function T(R,F,O,X,V,k,U){U===!0?s.vertexAttribIPointer(R,F,O,V,k):s.vertexAttribPointer(R,F,O,X,V,k)}function M(R,F,O,X){x();const V=X.attributes,k=O.getAttributes(),U=F.defaultAttributeValues;for(const Q in k){const K=k[Q];if(K.location>=0){let se=V[Q];if(se===void 0&&(Q==="instanceMatrix"&&R.instanceMatrix&&(se=R.instanceMatrix),Q==="instanceColor"&&R.instanceColor&&(se=R.instanceColor)),se!==void 0){const he=se.normalized,le=se.itemSize,$=e.get(se);if($===void 0)continue;const ce=$.buffer,Re=$.type,G=$.bytesPerElement,Z=Re===s.INT||Re===s.UNSIGNED_INT||se.gpuType===Vl;if(se.isInterleavedBufferAttribute){const ee=se.data,we=ee.stride,ve=se.offset;if(ee.isInstancedInterleavedBuffer){for(let Fe=0;Fe<K.locationSize;Fe++)m(K.location+Fe,ee.meshPerAttribute);R.isInstancedMesh!==!0&&X._maxInstanceCount===void 0&&(X._maxInstanceCount=ee.meshPerAttribute*ee.count)}else for(let Fe=0;Fe<K.locationSize;Fe++)p(K.location+Fe);s.bindBuffer(s.ARRAY_BUFFER,ce);for(let Fe=0;Fe<K.locationSize;Fe++)T(K.location+Fe,le/K.locationSize,Re,he,we*G,(ve+le/K.locationSize*Fe)*G,Z)}else{if(se.isInstancedBufferAttribute){for(let ee=0;ee<K.locationSize;ee++)m(K.location+ee,se.meshPerAttribute);R.isInstancedMesh!==!0&&X._maxInstanceCount===void 0&&(X._maxInstanceCount=se.meshPerAttribute*se.count)}else for(let ee=0;ee<K.locationSize;ee++)p(K.location+ee);s.bindBuffer(s.ARRAY_BUFFER,ce);for(let ee=0;ee<K.locationSize;ee++)T(K.location+ee,le/K.locationSize,Re,he,le*G,le/K.locationSize*ee*G,Z)}}else if(U!==void 0){const he=U[Q];if(he!==void 0)switch(he.length){case 2:s.vertexAttrib2fv(K.location,he);break;case 3:s.vertexAttrib3fv(K.location,he);break;case 4:s.vertexAttrib4fv(K.location,he);break;default:s.vertexAttrib1fv(K.location,he)}}}}S()}function E(){b();for(const R in n){const F=n[R];for(const O in F){const X=F[O];for(const V in X){const k=X[V];for(const U in k)h(k[U].object),delete k[U];delete X[V]}}delete n[R]}}function w(R){if(n[R.id]===void 0)return;const F=n[R.id];for(const O in F){const X=F[O];for(const V in X){const k=X[V];for(const U in k)h(k[U].object),delete k[U];delete X[V]}}delete n[R.id]}function C(R){for(const F in n){const O=n[F];for(const X in O){const V=O[X];if(V[R.id]===void 0)continue;const k=V[R.id];for(const U in k)h(k[U].object),delete k[U];delete V[R.id]}}}function v(R){for(const F in n){const O=n[F],X=R.isInstancedMesh===!0?R.id:0,V=O[X];if(V!==void 0){for(const k in V){const U=V[k];for(const Q in U)h(U[Q].object),delete U[Q];delete V[k]}delete O[X],Object.keys(O).length===0&&delete n[F]}}}function b(){D(),a=!0,r!==i&&(r=i,c(r.object))}function D(){i.geometry=null,i.program=null,i.wireframe=!1}return{setup:o,reset:b,resetDefaultState:D,dispose:E,releaseStatesOfGeometry:w,releaseStatesOfObject:v,releaseStatesOfProgram:C,initAttributes:x,enableAttribute:p,disableUnusedAttributes:S}}function j0(s,e,t){let n;function i(c){n=c}function r(c,h){s.drawArrays(n,c,h),t.update(h,n,1)}function a(c,h,u){u!==0&&(s.drawArraysInstanced(n,c,h,u),t.update(h,n,u))}function o(c,h,u){if(u===0)return;e.get("WEBGL_multi_draw").multiDrawArraysWEBGL(n,c,0,h,0,u);let f=0;for(let g=0;g<u;g++)f+=h[g];t.update(f,n,1)}function l(c,h,u,d){if(u===0)return;const f=e.get("WEBGL_multi_draw");if(f===null)for(let g=0;g<c.length;g++)a(c[g],h[g],d[g]);else{f.multiDrawArraysInstancedWEBGL(n,c,0,h,0,d,0,u);let g=0;for(let x=0;x<u;x++)g+=h[x]*d[x];t.update(g,n,1)}}this.setMode=i,this.render=r,this.renderInstances=a,this.renderMultiDraw=o,this.renderMultiDrawInstances=l}function K0(s,e,t,n){let i;function r(){if(i!==void 0)return i;if(e.has("EXT_texture_filter_anisotropic")===!0){const C=e.get("EXT_texture_filter_anisotropic");i=s.getParameter(C.MAX_TEXTURE_MAX_ANISOTROPY_EXT)}else i=0;return i}function a(C){return!(C!==un&&n.convert(C)!==s.getParameter(s.IMPLEMENTATION_COLOR_READ_FORMAT))}function o(C){const v=C===on&&(e.has("EXT_color_buffer_half_float")||e.has("EXT_color_buffer_float"));return!(C!==nn&&n.convert(C)!==s.getParameter(s.IMPLEMENTATION_COLOR_READ_TYPE)&&C!==sn&&!v)}function l(C){if(C==="highp"){if(s.getShaderPrecisionFormat(s.VERTEX_SHADER,s.HIGH_FLOAT).precision>0&&s.getShaderPrecisionFormat(s.FRAGMENT_SHADER,s.HIGH_FLOAT).precision>0)return"highp";C="mediump"}return C==="mediump"&&s.getShaderPrecisionFormat(s.VERTEX_SHADER,s.MEDIUM_FLOAT).precision>0&&s.getShaderPrecisionFormat(s.FRAGMENT_SHADER,s.MEDIUM_FLOAT).precision>0?"mediump":"lowp"}let c=t.precision!==void 0?t.precision:"highp";const h=l(c);h!==c&&(Pe("WebGLRenderer:",c,"not supported, using",h,"instead."),c=h);const u=t.logarithmicDepthBuffer===!0,d=t.reversedDepthBuffer===!0&&e.has("EXT_clip_control"),f=s.getParameter(s.MAX_TEXTURE_IMAGE_UNITS),g=s.getParameter(s.MAX_VERTEX_TEXTURE_IMAGE_UNITS),x=s.getParameter(s.MAX_TEXTURE_SIZE),p=s.getParameter(s.MAX_CUBE_MAP_TEXTURE_SIZE),m=s.getParameter(s.MAX_VERTEX_ATTRIBS),S=s.getParameter(s.MAX_VERTEX_UNIFORM_VECTORS),T=s.getParameter(s.MAX_VARYING_VECTORS),M=s.getParameter(s.MAX_FRAGMENT_UNIFORM_VECTORS),E=s.getParameter(s.MAX_SAMPLES),w=s.getParameter(s.SAMPLES);return{isWebGL2:!0,getMaxAnisotropy:r,getMaxPrecision:l,textureFormatReadable:a,textureTypeReadable:o,precision:c,logarithmicDepthBuffer:u,reversedDepthBuffer:d,maxTextures:f,maxVertexTextures:g,maxTextureSize:x,maxCubemapSize:p,maxAttributes:m,maxVertexUniforms:S,maxVaryings:T,maxFragmentUniforms:M,maxSamples:E,samples:w}}function $0(s){const e=this;let t=null,n=0,i=!1,r=!1;const a=new ui,o=new He,l={value:null,needsUpdate:!1};this.uniform=l,this.numPlanes=0,this.numIntersection=0,this.init=function(u,d){const f=u.length!==0||d||n!==0||i;return i=d,n=u.length,f},this.beginShadows=function(){r=!0,h(null)},this.endShadows=function(){r=!1},this.setGlobalState=function(u,d){t=h(u,d,0)},this.setState=function(u,d,f){const g=u.clippingPlanes,x=u.clipIntersection,p=u.clipShadows,m=s.get(u);if(!i||g===null||g.length===0||r&&!p)r?h(null):c();else{const S=r?0:n,T=S*4;let M=m.clippingState||null;l.value=M,M=h(g,d,T,f);for(let E=0;E!==T;++E)M[E]=t[E];m.clippingState=M,this.numIntersection=x?this.numPlanes:0,this.numPlanes+=S}};function c(){l.value!==t&&(l.value=t,l.needsUpdate=n>0),e.numPlanes=n,e.numIntersection=0}function h(u,d,f,g){const x=u!==null?u.length:0;let p=null;if(x!==0){if(p=l.value,g!==!0||p===null){const m=f+x*4,S=d.matrixWorldInverse;o.getNormalMatrix(S),(p===null||p.length<m)&&(p=new Float32Array(m));for(let T=0,M=f;T!==x;++T,M+=4)a.copy(u[T]).applyMatrix4(S,o),a.normal.toArray(p,M),p[M+3]=a.constant}l.value=p,l.needsUpdate=!0}return e.numPlanes=x,e.numIntersection=0,p}}const gi=4,Sh=[.125,.215,.35,.446,.526,.582],Ci=20,Z0=256,Gs=new or,bh=new Ie;let ho=null,uo=0,fo=0,po=!1;const J0=new L;class Sl{constructor(e){this._renderer=e,this._pingPongRenderTarget=null,this._lodMax=0,this._cubeSize=0,this._sizeLods=[],this._sigmas=[],this._lodMeshes=[],this._backgroundBox=null,this._cubemapMaterial=null,this._equirectMaterial=null,this._blurMaterial=null,this._ggxMaterial=null}fromScene(e,t=0,n=.1,i=100,r={}){const{size:a=256,position:o=J0}=r;ho=this._renderer.getRenderTarget(),uo=this._renderer.getActiveCubeFace(),fo=this._renderer.getActiveMipmapLevel(),po=this._renderer.xr.enabled,this._renderer.xr.enabled=!1,this._setSize(a);const l=this._allocateTargets();return l.depthBuffer=!0,this._sceneToCubeUV(e,n,i,l,o),t>0&&this._blur(l,0,0,t),this._applyPMREM(l),this._cleanup(l),l}fromEquirectangular(e,t=null){return this._fromTexture(e,t)}fromCubemap(e,t=null){return this._fromTexture(e,t)}compileCubemapShader(){this._cubemapMaterial===null&&(this._cubemapMaterial=Ah(),this._compileMaterial(this._cubemapMaterial))}compileEquirectangularShader(){this._equirectMaterial===null&&(this._equirectMaterial=Th(),this._compileMaterial(this._equirectMaterial))}dispose(){this._dispose(),this._cubemapMaterial!==null&&this._cubemapMaterial.dispose(),this._equirectMaterial!==null&&this._equirectMaterial.dispose(),this._backgroundBox!==null&&(this._backgroundBox.geometry.dispose(),this._backgroundBox.material.dispose())}_setSize(e){this._lodMax=Math.floor(Math.log2(e)),this._cubeSize=Math.pow(2,this._lodMax)}_dispose(){this._blurMaterial!==null&&this._blurMaterial.dispose(),this._ggxMaterial!==null&&this._ggxMaterial.dispose(),this._pingPongRenderTarget!==null&&this._pingPongRenderTarget.dispose();for(let e=0;e<this._lodMeshes.length;e++)this._lodMeshes[e].geometry.dispose()}_cleanup(e){this._renderer.setRenderTarget(ho,uo,fo),this._renderer.xr.enabled=po,e.scissorTest=!1,ts(e,0,0,e.width,e.height)}_fromTexture(e,t){e.mapping===Di||e.mapping===_s?this._setSize(e.image.length===0?16:e.image[0].width||e.image[0].image.width):this._setSize(e.image.width/4),ho=this._renderer.getRenderTarget(),uo=this._renderer.getActiveCubeFace(),fo=this._renderer.getActiveMipmapLevel(),po=this._renderer.xr.enabled,this._renderer.xr.enabled=!1;const n=t||this._allocateTargets();return this._textureToCubeUV(e,n),this._applyPMREM(n),this._cleanup(n),n}_allocateTargets(){const e=3*Math.max(this._cubeSize,112),t=4*this._cubeSize,n={magFilter:Ct,minFilter:Ct,generateMipmaps:!1,type:on,format:un,colorSpace:Kt,depthBuffer:!1},i=Eh(e,t,n);if(this._pingPongRenderTarget===null||this._pingPongRenderTarget.width!==e||this._pingPongRenderTarget.height!==t){this._pingPongRenderTarget!==null&&this._dispose(),this._pingPongRenderTarget=Eh(e,t,n);const{_lodMax:r}=this;({lodMeshes:this._lodMeshes,sizeLods:this._sizeLods,sigmas:this._sigmas}=Q0(r)),this._blurMaterial=t_(r,e,t),this._ggxMaterial=e_(r,e,t)}return i}_compileMaterial(e){const t=new lt(new ln,e);this._renderer.compile(t,Gs)}_sceneToCubeUV(e,t,n,i,r){const l=new Wt(90,1,t,n),c=[1,-1,1,1,1,1],h=[1,1,1,-1,-1,-1],u=this._renderer,d=u.autoClear,f=u.toneMapping;u.getClearColor(bh),u.toneMapping=Un,u.autoClear=!1,u.state.buffers.depth.getReversed()&&(u.setRenderTarget(i),u.clearDepth(),u.setRenderTarget(null)),this._backgroundBox===null&&(this._backgroundBox=new lt(new Cs,new Nn({name:"PMREM.Background",side:qt,depthWrite:!1,depthTest:!1})));const x=this._backgroundBox,p=x.material;let m=!1;const S=e.background;S?S.isColor&&(p.color.copy(S),e.background=null,m=!0):(p.color.copy(bh),m=!0);for(let T=0;T<6;T++){const M=T%3;M===0?(l.up.set(0,c[T],0),l.position.set(r.x,r.y,r.z),l.lookAt(r.x+h[T],r.y,r.z)):M===1?(l.up.set(0,0,c[T]),l.position.set(r.x,r.y,r.z),l.lookAt(r.x,r.y+h[T],r.z)):(l.up.set(0,c[T],0),l.position.set(r.x,r.y,r.z),l.lookAt(r.x,r.y,r.z+h[T]));const E=this._cubeSize;ts(i,M*E,T>2?E:0,E,E),u.setRenderTarget(i),m&&u.render(x,l),u.render(e,l)}u.toneMapping=f,u.autoClear=d,e.background=S}_textureToCubeUV(e,t){const n=this._renderer,i=e.mapping===Di||e.mapping===_s;i?(this._cubemapMaterial===null&&(this._cubemapMaterial=Ah()),this._cubemapMaterial.uniforms.flipEnvMap.value=e.isRenderTargetTexture===!1?-1:1):this._equirectMaterial===null&&(this._equirectMaterial=Th());const r=i?this._cubemapMaterial:this._equirectMaterial,a=this._lodMeshes[0];a.material=r;const o=r.uniforms;o.envMap.value=e;const l=this._cubeSize;ts(t,0,0,3*l,2*l),n.setRenderTarget(t),n.render(a,Gs)}_applyPMREM(e){const t=this._renderer,n=t.autoClear;t.autoClear=!1;const i=this._lodMeshes.length;for(let r=1;r<i;r++)this._applyGGXFilter(e,r-1,r);t.autoClear=n}_applyGGXFilter(e,t,n){const i=this._renderer,r=this._pingPongRenderTarget,a=this._ggxMaterial,o=this._lodMeshes[n];o.material=a;const l=a.uniforms,c=n/(this._lodMeshes.length-1),h=t/(this._lodMeshes.length-1),u=Math.sqrt(c*c-h*h),d=0+c*1.25,f=u*d,{_lodMax:g}=this,x=this._sizeLods[n],p=3*x*(n>g-gi?n-g+gi:0),m=4*(this._cubeSize-x);l.envMap.value=e.texture,l.roughness.value=f,l.mipInt.value=g-t,ts(r,p,m,3*x,2*x),i.setRenderTarget(r),i.render(o,Gs),l.envMap.value=r.texture,l.roughness.value=0,l.mipInt.value=g-n,ts(e,p,m,3*x,2*x),i.setRenderTarget(e),i.render(o,Gs)}_blur(e,t,n,i,r){const a=this._pingPongRenderTarget;this._halfBlur(e,a,t,n,i,"latitudinal",r),this._halfBlur(a,e,n,n,i,"longitudinal",r)}_halfBlur(e,t,n,i,r,a,o){const l=this._renderer,c=this._blurMaterial;a!=="latitudinal"&&a!=="longitudinal"&&Ue("blur direction must be either latitudinal or longitudinal!");const h=3,u=this._lodMeshes[i];u.material=c;const d=c.uniforms,f=this._sizeLods[n]-1,g=isFinite(r)?Math.PI/(2*f):2*Math.PI/(2*Ci-1),x=r/g,p=isFinite(r)?1+Math.floor(h*x):Ci;p>Ci&&Pe(`sigmaRadians, ${r}, is too large and will clip, as it requested ${p} samples when the maximum is set to ${Ci}`);const m=[];let S=0;for(let C=0;C<Ci;++C){const v=C/x,b=Math.exp(-v*v/2);m.push(b),C===0?S+=b:C<p&&(S+=2*b)}for(let C=0;C<m.length;C++)m[C]=m[C]/S;d.envMap.value=e.texture,d.samples.value=p,d.weights.value=m,d.latitudinal.value=a==="latitudinal",o&&(d.poleAxis.value=o);const{_lodMax:T}=this;d.dTheta.value=g,d.mipInt.value=T-n;const M=this._sizeLods[i],E=3*M*(i>T-gi?i-T+gi:0),w=4*(this._cubeSize-M);ts(t,E,w,3*M,2*M),l.setRenderTarget(t),l.render(u,Gs)}}function Q0(s){const e=[],t=[],n=[];let i=s;const r=s-gi+1+Sh.length;for(let a=0;a<r;a++){const o=Math.pow(2,i);e.push(o);let l=1/o;a>s-gi?l=Sh[a-s+gi-1]:a===0&&(l=0),t.push(l);const c=1/(o-2),h=-c,u=1+c,d=[h,h,u,h,u,u,h,h,u,u,h,u],f=6,g=6,x=3,p=2,m=1,S=new Float32Array(x*g*f),T=new Float32Array(p*g*f),M=new Float32Array(m*g*f);for(let w=0;w<f;w++){const C=w%3*2/3-1,v=w>2?0:-1,b=[C,v,0,C+2/3,v,0,C+2/3,v+1,0,C,v,0,C+2/3,v+1,0,C,v+1,0];S.set(b,x*g*w),T.set(d,p*g*w);const D=[w,w,w,w,w,w];M.set(D,m*g*w)}const E=new ln;E.setAttribute("position",new jt(S,x)),E.setAttribute("uv",new jt(T,p)),E.setAttribute("faceIndex",new jt(M,m)),n.push(new lt(E,null)),i>gi&&i--}return{lodMeshes:n,sizeLods:e,sigmas:t}}function Eh(s,e,t){const n=new Jt(s,e,t);return n.texture.mapping=pa,n.texture.name="PMREM.cubeUv",n.scissorTest=!0,n}function ts(s,e,t,n,i){s.viewport.set(e,t,n,i),s.scissor.set(e,t,n,i)}function e_(s,e,t){return new kt({name:"PMREMGGXConvolution",defines:{GGX_SAMPLES:Z0,CUBEUV_TEXEL_WIDTH:1/e,CUBEUV_TEXEL_HEIGHT:1/t,CUBEUV_MAX_MIP:`${s}.0`},uniforms:{envMap:{value:null},roughness:{value:0},mipInt:{value:0}},vertexShader:Ma(),fragmentShader:`

			precision highp float;
			precision highp int;

			varying vec3 vOutputDirection;

			uniform sampler2D envMap;
			uniform float roughness;
			uniform float mipInt;

			#define ENVMAP_TYPE_CUBE_UV
			#include <cube_uv_reflection_fragment>

			#define PI 3.14159265359

			// Van der Corput radical inverse
			float radicalInverse_VdC(uint bits) {
				bits = (bits << 16u) | (bits >> 16u);
				bits = ((bits & 0x55555555u) << 1u) | ((bits & 0xAAAAAAAAu) >> 1u);
				bits = ((bits & 0x33333333u) << 2u) | ((bits & 0xCCCCCCCCu) >> 2u);
				bits = ((bits & 0x0F0F0F0Fu) << 4u) | ((bits & 0xF0F0F0F0u) >> 4u);
				bits = ((bits & 0x00FF00FFu) << 8u) | ((bits & 0xFF00FF00u) >> 8u);
				return float(bits) * 2.3283064365386963e-10; // / 0x100000000
			}

			// Hammersley sequence
			vec2 hammersley(uint i, uint N) {
				return vec2(float(i) / float(N), radicalInverse_VdC(i));
			}

			// GGX VNDF importance sampling (Eric Heitz 2018)
			// "Sampling the GGX Distribution of Visible Normals"
			// https://jcgt.org/published/0007/04/01/
			vec3 importanceSampleGGX_VNDF(vec2 Xi, vec3 V, float roughness) {
				float alpha = roughness * roughness;

				// Section 4.1: Orthonormal basis
				vec3 T1 = vec3(1.0, 0.0, 0.0);
				vec3 T2 = cross(V, T1);

				// Section 4.2: Parameterization of projected area
				float r = sqrt(Xi.x);
				float phi = 2.0 * PI * Xi.y;
				float t1 = r * cos(phi);
				float t2 = r * sin(phi);
				float s = 0.5 * (1.0 + V.z);
				t2 = (1.0 - s) * sqrt(1.0 - t1 * t1) + s * t2;

				// Section 4.3: Reprojection onto hemisphere
				vec3 Nh = t1 * T1 + t2 * T2 + sqrt(max(0.0, 1.0 - t1 * t1 - t2 * t2)) * V;

				// Section 3.4: Transform back to ellipsoid configuration
				return normalize(vec3(alpha * Nh.x, alpha * Nh.y, max(0.0, Nh.z)));
			}

			void main() {
				vec3 N = normalize(vOutputDirection);
				vec3 V = N; // Assume view direction equals normal for pre-filtering

				vec3 prefilteredColor = vec3(0.0);
				float totalWeight = 0.0;

				// For very low roughness, just sample the environment directly
				if (roughness < 0.001) {
					gl_FragColor = vec4(bilinearCubeUV(envMap, N, mipInt), 1.0);
					return;
				}

				// Tangent space basis for VNDF sampling
				vec3 up = abs(N.z) < 0.999 ? vec3(0.0, 0.0, 1.0) : vec3(1.0, 0.0, 0.0);
				vec3 tangent = normalize(cross(up, N));
				vec3 bitangent = cross(N, tangent);

				for(uint i = 0u; i < uint(GGX_SAMPLES); i++) {
					vec2 Xi = hammersley(i, uint(GGX_SAMPLES));

					// For PMREM, V = N, so in tangent space V is always (0, 0, 1)
					vec3 H_tangent = importanceSampleGGX_VNDF(Xi, vec3(0.0, 0.0, 1.0), roughness);

					// Transform H back to world space
					vec3 H = normalize(tangent * H_tangent.x + bitangent * H_tangent.y + N * H_tangent.z);
					vec3 L = normalize(2.0 * dot(V, H) * H - V);

					float NdotL = max(dot(N, L), 0.0);

					if(NdotL > 0.0) {
						// Sample environment at fixed mip level
						// VNDF importance sampling handles the distribution filtering
						vec3 sampleColor = bilinearCubeUV(envMap, L, mipInt);

						// Weight by NdotL for the split-sum approximation
						// VNDF PDF naturally accounts for the visible microfacet distribution
						prefilteredColor += sampleColor * NdotL;
						totalWeight += NdotL;
					}
				}

				if (totalWeight > 0.0) {
					prefilteredColor = prefilteredColor / totalWeight;
				}

				gl_FragColor = vec4(prefilteredColor, 1.0);
			}
		`,blending:Bt,depthTest:!1,depthWrite:!1})}function t_(s,e,t){const n=new Float32Array(Ci),i=new L(0,1,0);return new kt({name:"SphericalGaussianBlur",defines:{n:Ci,CUBEUV_TEXEL_WIDTH:1/e,CUBEUV_TEXEL_HEIGHT:1/t,CUBEUV_MAX_MIP:`${s}.0`},uniforms:{envMap:{value:null},samples:{value:1},weights:{value:n},latitudinal:{value:!1},dTheta:{value:0},mipInt:{value:0},poleAxis:{value:i}},vertexShader:Ma(),fragmentShader:`

			precision mediump float;
			precision mediump int;

			varying vec3 vOutputDirection;

			uniform sampler2D envMap;
			uniform int samples;
			uniform float weights[ n ];
			uniform bool latitudinal;
			uniform float dTheta;
			uniform float mipInt;
			uniform vec3 poleAxis;

			#define ENVMAP_TYPE_CUBE_UV
			#include <cube_uv_reflection_fragment>

			vec3 getSample( float theta, vec3 axis ) {

				float cosTheta = cos( theta );
				// Rodrigues' axis-angle rotation
				vec3 sampleDirection = vOutputDirection * cosTheta
					+ cross( axis, vOutputDirection ) * sin( theta )
					+ axis * dot( axis, vOutputDirection ) * ( 1.0 - cosTheta );

				return bilinearCubeUV( envMap, sampleDirection, mipInt );

			}

			void main() {

				vec3 axis = latitudinal ? poleAxis : cross( poleAxis, vOutputDirection );

				if ( all( equal( axis, vec3( 0.0 ) ) ) ) {

					axis = vec3( vOutputDirection.z, 0.0, - vOutputDirection.x );

				}

				axis = normalize( axis );

				gl_FragColor = vec4( 0.0, 0.0, 0.0, 1.0 );
				gl_FragColor.rgb += weights[ 0 ] * getSample( 0.0, axis );

				for ( int i = 1; i < n; i++ ) {

					if ( i >= samples ) {

						break;

					}

					float theta = dTheta * float( i );
					gl_FragColor.rgb += weights[ i ] * getSample( -1.0 * theta, axis );
					gl_FragColor.rgb += weights[ i ] * getSample( theta, axis );

				}

			}
		`,blending:Bt,depthTest:!1,depthWrite:!1})}function Th(){return new kt({name:"EquirectangularToCubeUV",uniforms:{envMap:{value:null}},vertexShader:Ma(),fragmentShader:`

			precision mediump float;
			precision mediump int;

			varying vec3 vOutputDirection;

			uniform sampler2D envMap;

			#include <common>

			void main() {

				vec3 outputDirection = normalize( vOutputDirection );
				vec2 uv = equirectUv( outputDirection );

				gl_FragColor = vec4( texture2D ( envMap, uv ).rgb, 1.0 );

			}
		`,blending:Bt,depthTest:!1,depthWrite:!1})}function Ah(){return new kt({name:"CubemapToCubeUV",uniforms:{envMap:{value:null},flipEnvMap:{value:-1}},vertexShader:Ma(),fragmentShader:`

			precision mediump float;
			precision mediump int;

			uniform float flipEnvMap;

			varying vec3 vOutputDirection;

			uniform samplerCube envMap;

			void main() {

				gl_FragColor = textureCube( envMap, vec3( flipEnvMap * vOutputDirection.x, vOutputDirection.yz ) );

			}
		`,blending:Bt,depthTest:!1,depthWrite:!1})}function Ma(){return`

		precision mediump float;
		precision mediump int;

		attribute float faceIndex;

		varying vec3 vOutputDirection;

		// RH coordinate system; PMREM face-indexing convention
		vec3 getDirection( vec2 uv, float face ) {

			uv = 2.0 * uv - 1.0;

			vec3 direction = vec3( uv, 1.0 );

			if ( face == 0.0 ) {

				direction = direction.zyx; // ( 1, v, u ) pos x

			} else if ( face == 1.0 ) {

				direction = direction.xzy;
				direction.xz *= -1.0; // ( -u, 1, -v ) pos y

			} else if ( face == 2.0 ) {

				direction.x *= -1.0; // ( -u, v, 1 ) pos z

			} else if ( face == 3.0 ) {

				direction = direction.zyx;
				direction.xz *= -1.0; // ( -1, v, -u ) neg x

			} else if ( face == 4.0 ) {

				direction = direction.xzy;
				direction.xy *= -1.0; // ( -u, -1, v ) neg y

			} else if ( face == 5.0 ) {

				direction.z *= -1.0; // ( u, v, -1 ) neg z

			}

			return direction;

		}

		void main() {

			vOutputDirection = getDirection( uv, faceIndex );
			gl_Position = vec4( position, 1.0 );

		}
	`}class zu extends Jt{constructor(e=1,t={}){super(e,e,t),this.isWebGLCubeRenderTarget=!0;const n={width:e,height:e,depth:1},i=[n,n,n,n,n,n];this.texture=new Pu(i),this._setTextureOptions(t),this.texture.isRenderTargetTexture=!0}fromEquirectangularTexture(e,t){this.texture.type=t.type,this.texture.colorSpace=t.colorSpace,this.texture.generateMipmaps=t.generateMipmaps,this.texture.minFilter=t.minFilter,this.texture.magFilter=t.magFilter;const n={uniforms:{tEquirect:{value:null}},vertexShader:`

				varying vec3 vWorldDirection;

				vec3 transformDirection( in vec3 dir, in mat4 matrix ) {

					return normalize( ( matrix * vec4( dir, 0.0 ) ).xyz );

				}

				void main() {

					vWorldDirection = transformDirection( position, modelMatrix );

					#include <begin_vertex>
					#include <project_vertex>

				}
			`,fragmentShader:`

				uniform sampler2D tEquirect;

				varying vec3 vWorldDirection;

				#include <common>

				void main() {

					vec3 direction = normalize( vWorldDirection );

					vec2 sampleUV = equirectUv( direction );

					gl_FragColor = texture2D( tEquirect, sampleUV );

				}
			`},i=new Cs(5,5,5),r=new kt({name:"CubemapFromEquirect",uniforms:Ss(n.uniforms),vertexShader:n.vertexShader,fragmentShader:n.fragmentShader,side:qt,blending:Bt});r.uniforms.tEquirect.value=t;const a=new lt(i,r),o=t.minFilter;return t.minFilter===jn&&(t.minFilter=Ct),new Kp(1,10,this).update(e,a),t.minFilter=o,a.geometry.dispose(),a.material.dispose(),this}clear(e,t=!0,n=!0,i=!0){const r=e.getRenderTarget();for(let a=0;a<6;a++)e.setRenderTarget(this,a),e.clear(t,n,i);e.setRenderTarget(r)}}function n_(s){let e=new WeakMap,t=new WeakMap,n=null;function i(d,f=!1){return d==null?null:f?a(d):r(d)}function r(d){if(d&&d.isTexture){const f=d.mapping;if(f===Ia||f===Na)if(e.has(d)){const g=e.get(d).texture;return o(g,d.mapping)}else{const g=d.image;if(g&&g.height>0){const x=new zu(g.height);return x.fromEquirectangularTexture(s,d),e.set(d,x),d.addEventListener("dispose",c),o(x.texture,d.mapping)}else return null}}return d}function a(d){if(d&&d.isTexture){const f=d.mapping,g=f===Ia||f===Na,x=f===Di||f===_s;if(g||x){let p=t.get(d);const m=p!==void 0?p.texture.pmremVersion:0;if(d.isRenderTargetTexture&&d.pmremVersion!==m)return n===null&&(n=new Sl(s)),p=g?n.fromEquirectangular(d,p):n.fromCubemap(d,p),p.texture.pmremVersion=d.pmremVersion,t.set(d,p),p.texture;if(p!==void 0)return p.texture;{const S=d.image;return g&&S&&S.height>0||x&&S&&l(S)?(n===null&&(n=new Sl(s)),p=g?n.fromEquirectangular(d):n.fromCubemap(d),p.texture.pmremVersion=d.pmremVersion,t.set(d,p),d.addEventListener("dispose",h),p.texture):null}}}return d}function o(d,f){return f===Ia?d.mapping=Di:f===Na&&(d.mapping=_s),d}function l(d){let f=0;const g=6;for(let x=0;x<g;x++)d[x]!==void 0&&f++;return f===g}function c(d){const f=d.target;f.removeEventListener("dispose",c);const g=e.get(f);g!==void 0&&(e.delete(f),g.dispose())}function h(d){const f=d.target;f.removeEventListener("dispose",h);const g=t.get(f);g!==void 0&&(t.delete(f),g.dispose())}function u(){e=new WeakMap,t=new WeakMap,n!==null&&(n.dispose(),n=null)}return{get:i,dispose:u}}function i_(s){const e={};function t(n){if(e[n]!==void 0)return e[n];const i=s.getExtension(n);return e[n]=i,i}return{has:function(n){return t(n)!==null},init:function(){t("EXT_color_buffer_float"),t("WEBGL_clip_cull_distance"),t("OES_texture_float_linear"),t("EXT_color_buffer_half_float"),t("WEBGL_multisampled_render_to_texture"),t("WEBGL_render_shared_exponent")},get:function(n){const i=t(n);return i===null&&ra("WebGLRenderer: "+n+" extension not supported."),i}}}function s_(s,e,t,n){const i={},r=new WeakMap;function a(u){const d=u.target;d.index!==null&&e.remove(d.index);for(const g in d.attributes)e.remove(d.attributes[g]);d.removeEventListener("dispose",a),delete i[d.id];const f=r.get(d);f&&(e.remove(f),r.delete(d)),n.releaseStatesOfGeometry(d),d.isInstancedBufferGeometry===!0&&delete d._maxInstanceCount,t.memory.geometries--}function o(u,d){return i[d.id]===!0||(d.addEventListener("dispose",a),i[d.id]=!0,t.memory.geometries++),d}function l(u){const d=u.attributes;for(const f in d)e.update(d[f],s.ARRAY_BUFFER)}function c(u){const d=[],f=u.index,g=u.attributes.position;let x=0;if(g===void 0)return;if(f!==null){const S=f.array;x=f.version;for(let T=0,M=S.length;T<M;T+=3){const E=S[T+0],w=S[T+1],C=S[T+2];d.push(E,w,w,C,C,E)}}else{const S=g.array;x=g.version;for(let T=0,M=S.length/3-1;T<M;T+=3){const E=T+0,w=T+1,C=T+2;d.push(E,w,w,C,C,E)}}const p=new(g.count>=65535?Au:Tu)(d,1);p.version=x;const m=r.get(u);m&&e.remove(m),r.set(u,p)}function h(u){const d=r.get(u);if(d){const f=u.index;f!==null&&d.version<f.version&&c(u)}else c(u);return r.get(u)}return{get:o,update:l,getWireframeAttribute:h}}function r_(s,e,t){let n;function i(d){n=d}let r,a;function o(d){r=d.type,a=d.bytesPerElement}function l(d,f){s.drawElements(n,f,r,d*a),t.update(f,n,1)}function c(d,f,g){g!==0&&(s.drawElementsInstanced(n,f,r,d*a,g),t.update(f,n,g))}function h(d,f,g){if(g===0)return;e.get("WEBGL_multi_draw").multiDrawElementsWEBGL(n,f,0,r,d,0,g);let p=0;for(let m=0;m<g;m++)p+=f[m];t.update(p,n,1)}function u(d,f,g,x){if(g===0)return;const p=e.get("WEBGL_multi_draw");if(p===null)for(let m=0;m<d.length;m++)c(d[m]/a,f[m],x[m]);else{p.multiDrawElementsInstancedWEBGL(n,f,0,r,d,0,x,0,g);let m=0;for(let S=0;S<g;S++)m+=f[S]*x[S];t.update(m,n,1)}}this.setMode=i,this.setIndex=o,this.render=l,this.renderInstances=c,this.renderMultiDraw=h,this.renderMultiDrawInstances=u}function a_(s){const e={geometries:0,textures:0},t={frame:0,calls:0,triangles:0,points:0,lines:0};function n(r,a,o){switch(t.calls++,a){case s.TRIANGLES:t.triangles+=o*(r/3);break;case s.LINES:t.lines+=o*(r/2);break;case s.LINE_STRIP:t.lines+=o*(r-1);break;case s.LINE_LOOP:t.lines+=o*r;break;case s.POINTS:t.points+=o*r;break;default:Ue("WebGLInfo: Unknown draw mode:",a);break}}function i(){t.calls=0,t.triangles=0,t.points=0,t.lines=0}return{memory:e,render:t,programs:null,autoReset:!0,reset:i,update:n}}function o_(s,e,t){const n=new WeakMap,i=new mt;function r(a,o,l){const c=a.morphTargetInfluences,h=o.morphAttributes.position||o.morphAttributes.normal||o.morphAttributes.color,u=h!==void 0?h.length:0;let d=n.get(o);if(d===void 0||d.count!==u){let D=function(){v.dispose(),n.delete(o),o.removeEventListener("dispose",D)};var f=D;d!==void 0&&d.texture.dispose();const g=o.morphAttributes.position!==void 0,x=o.morphAttributes.normal!==void 0,p=o.morphAttributes.color!==void 0,m=o.morphAttributes.position||[],S=o.morphAttributes.normal||[],T=o.morphAttributes.color||[];let M=0;g===!0&&(M=1),x===!0&&(M=2),p===!0&&(M=3);let E=o.attributes.position.count*M,w=1;E>e.maxTextureSize&&(w=Math.ceil(E/e.maxTextureSize),E=e.maxTextureSize);const C=new Float32Array(E*w*4*u),v=new bu(C,E,w,u);v.type=sn,v.needsUpdate=!0;const b=M*4;for(let R=0;R<u;R++){const F=m[R],O=S[R],X=T[R],V=E*w*4*R;for(let k=0;k<F.count;k++){const U=k*b;g===!0&&(i.fromBufferAttribute(F,k),C[V+U+0]=i.x,C[V+U+1]=i.y,C[V+U+2]=i.z,C[V+U+3]=0),x===!0&&(i.fromBufferAttribute(O,k),C[V+U+4]=i.x,C[V+U+5]=i.y,C[V+U+6]=i.z,C[V+U+7]=0),p===!0&&(i.fromBufferAttribute(X,k),C[V+U+8]=i.x,C[V+U+9]=i.y,C[V+U+10]=i.z,C[V+U+11]=X.itemSize===4?i.w:1)}}d={count:u,texture:v,size:new Le(E,w)},n.set(o,d),o.addEventListener("dispose",D)}if(a.isInstancedMesh===!0&&a.morphTexture!==null)l.getUniforms().setValue(s,"morphTexture",a.morphTexture,t);else{let g=0;for(let p=0;p<c.length;p++)g+=c[p];const x=o.morphTargetsRelative?1:1-g;l.getUniforms().setValue(s,"morphTargetBaseInfluence",x),l.getUniforms().setValue(s,"morphTargetInfluences",c)}l.getUniforms().setValue(s,"morphTargetsTexture",d.texture,t),l.getUniforms().setValue(s,"morphTargetsTextureSize",d.size)}return{update:r}}function l_(s,e,t,n,i){let r=new WeakMap;function a(c){const h=i.render.frame,u=c.geometry,d=e.get(c,u);if(r.get(d)!==h&&(e.update(d),r.set(d,h)),c.isInstancedMesh&&(c.hasEventListener("dispose",l)===!1&&c.addEventListener("dispose",l),r.get(c)!==h&&(t.update(c.instanceMatrix,s.ARRAY_BUFFER),c.instanceColor!==null&&t.update(c.instanceColor,s.ARRAY_BUFFER),r.set(c,h))),c.isSkinnedMesh){const f=c.skeleton;r.get(f)!==h&&(f.update(),r.set(f,h))}return d}function o(){r=new WeakMap}function l(c){const h=c.target;h.removeEventListener("dispose",l),n.releaseStatesOfObject(h),t.remove(h.instanceMatrix),h.instanceColor!==null&&t.remove(h.instanceColor)}return{update:a,dispose:o}}const c_={[Nl]:"LINEAR_TONE_MAPPING",[Ul]:"REINHARD_TONE_MAPPING",[Fl]:"CINEON_TONE_MAPPING",[ar]:"ACES_FILMIC_TONE_MAPPING",[Bl]:"AGX_TONE_MAPPING",[kl]:"NEUTRAL_TONE_MAPPING",[Ol]:"CUSTOM_TONE_MAPPING"};function h_(s,e,t,n,i){const r=new Jt(e,t,{type:s,depthBuffer:n,stencilBuffer:i}),a=new Jt(e,t,{type:on,depthBuffer:!1,stencilBuffer:!1}),o=new ln;o.setAttribute("position",new an([-1,3,0,-1,-1,0,3,-1,0],3)),o.setAttribute("uv",new an([0,2,0,0,2,0],2));const l=new Iu({uniforms:{tDiffuse:{value:null}},vertexShader:`
			precision highp float;

			uniform mat4 modelViewMatrix;
			uniform mat4 projectionMatrix;

			attribute vec3 position;
			attribute vec2 uv;

			varying vec2 vUv;

			void main() {
				vUv = uv;
				gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
			}`,fragmentShader:`
			precision highp float;

			uniform sampler2D tDiffuse;

			varying vec2 vUv;

			#include <tonemapping_pars_fragment>
			#include <colorspace_pars_fragment>

			void main() {
				gl_FragColor = texture2D( tDiffuse, vUv );

				#ifdef LINEAR_TONE_MAPPING
					gl_FragColor.rgb = LinearToneMapping( gl_FragColor.rgb );
				#elif defined( REINHARD_TONE_MAPPING )
					gl_FragColor.rgb = ReinhardToneMapping( gl_FragColor.rgb );
				#elif defined( CINEON_TONE_MAPPING )
					gl_FragColor.rgb = CineonToneMapping( gl_FragColor.rgb );
				#elif defined( ACES_FILMIC_TONE_MAPPING )
					gl_FragColor.rgb = ACESFilmicToneMapping( gl_FragColor.rgb );
				#elif defined( AGX_TONE_MAPPING )
					gl_FragColor.rgb = AgXToneMapping( gl_FragColor.rgb );
				#elif defined( NEUTRAL_TONE_MAPPING )
					gl_FragColor.rgb = NeutralToneMapping( gl_FragColor.rgb );
				#elif defined( CUSTOM_TONE_MAPPING )
					gl_FragColor.rgb = CustomToneMapping( gl_FragColor.rgb );
				#endif

				#ifdef SRGB_TRANSFER
					gl_FragColor = sRGBTransferOETF( gl_FragColor );
				#endif
			}`,depthTest:!1,depthWrite:!1}),c=new lt(o,l),h=new or(-1,1,1,-1,0,1);let u=null,d=null,f=!1,g,x=null,p=[],m=!1;this.setSize=function(S,T){r.setSize(S,T),a.setSize(S,T);for(let M=0;M<p.length;M++){const E=p[M];E.setSize&&E.setSize(S,T)}},this.setEffects=function(S){p=S,m=p.length>0&&p[0].isRenderPass===!0;const T=r.width,M=r.height;for(let E=0;E<p.length;E++){const w=p[E];w.setSize&&w.setSize(T,M)}},this.begin=function(S,T){if(f||S.toneMapping===Un&&p.length===0)return!1;if(x=T,T!==null){const M=T.width,E=T.height;(r.width!==M||r.height!==E)&&this.setSize(M,E)}return m===!1&&S.setRenderTarget(r),g=S.toneMapping,S.toneMapping=Un,!0},this.hasRenderPass=function(){return m},this.end=function(S,T){S.toneMapping=g,f=!0;let M=r,E=a;for(let w=0;w<p.length;w++){const C=p[w];if(C.enabled!==!1&&(C.render(S,E,M,T),C.needsSwap!==!1)){const v=M;M=E,E=v}}if(u!==S.outputColorSpace||d!==S.toneMapping){u=S.outputColorSpace,d=S.toneMapping,l.defines={},Ke.getTransfer(u)===tt&&(l.defines.SRGB_TRANSFER="");const w=c_[d];w&&(l.defines[w]=""),l.needsUpdate=!0}l.uniforms.tDiffuse.value=M.texture,S.setRenderTarget(x),S.render(c,h),x=null,f=!1},this.isCompositing=function(){return f},this.dispose=function(){r.dispose(),a.dispose(),o.dispose(),l.dispose()}}const Hu=new Pt,bl=new ys(1,1),Gu=new bu,Wu=new Jf,Xu=new Pu,wh=[],Rh=[],Ch=new Float32Array(16),Ph=new Float32Array(9),Dh=new Float32Array(4);function Ns(s,e,t){const n=s[0];if(n<=0||n>0)return s;const i=e*t;let r=wh[i];if(r===void 0&&(r=new Float32Array(i),wh[i]=r),e!==0){n.toArray(r,0);for(let a=1,o=0;a!==e;++a)o+=t,s[a].toArray(r,o)}return r}function Dt(s,e){if(s.length!==e.length)return!1;for(let t=0,n=s.length;t<n;t++)if(s[t]!==e[t])return!1;return!0}function Lt(s,e){for(let t=0,n=e.length;t<n;t++)s[t]=e[t]}function ya(s,e){let t=Rh[e];t===void 0&&(t=new Int32Array(e),Rh[e]=t);for(let n=0;n!==e;++n)t[n]=s.allocateTextureUnit();return t}function u_(s,e){const t=this.cache;t[0]!==e&&(s.uniform1f(this.addr,e),t[0]=e)}function d_(s,e){const t=this.cache;if(e.x!==void 0)(t[0]!==e.x||t[1]!==e.y)&&(s.uniform2f(this.addr,e.x,e.y),t[0]=e.x,t[1]=e.y);else{if(Dt(t,e))return;s.uniform2fv(this.addr,e),Lt(t,e)}}function f_(s,e){const t=this.cache;if(e.x!==void 0)(t[0]!==e.x||t[1]!==e.y||t[2]!==e.z)&&(s.uniform3f(this.addr,e.x,e.y,e.z),t[0]=e.x,t[1]=e.y,t[2]=e.z);else if(e.r!==void 0)(t[0]!==e.r||t[1]!==e.g||t[2]!==e.b)&&(s.uniform3f(this.addr,e.r,e.g,e.b),t[0]=e.r,t[1]=e.g,t[2]=e.b);else{if(Dt(t,e))return;s.uniform3fv(this.addr,e),Lt(t,e)}}function p_(s,e){const t=this.cache;if(e.x!==void 0)(t[0]!==e.x||t[1]!==e.y||t[2]!==e.z||t[3]!==e.w)&&(s.uniform4f(this.addr,e.x,e.y,e.z,e.w),t[0]=e.x,t[1]=e.y,t[2]=e.z,t[3]=e.w);else{if(Dt(t,e))return;s.uniform4fv(this.addr,e),Lt(t,e)}}function m_(s,e){const t=this.cache,n=e.elements;if(n===void 0){if(Dt(t,e))return;s.uniformMatrix2fv(this.addr,!1,e),Lt(t,e)}else{if(Dt(t,n))return;Dh.set(n),s.uniformMatrix2fv(this.addr,!1,Dh),Lt(t,n)}}function g_(s,e){const t=this.cache,n=e.elements;if(n===void 0){if(Dt(t,e))return;s.uniformMatrix3fv(this.addr,!1,e),Lt(t,e)}else{if(Dt(t,n))return;Ph.set(n),s.uniformMatrix3fv(this.addr,!1,Ph),Lt(t,n)}}function __(s,e){const t=this.cache,n=e.elements;if(n===void 0){if(Dt(t,e))return;s.uniformMatrix4fv(this.addr,!1,e),Lt(t,e)}else{if(Dt(t,n))return;Ch.set(n),s.uniformMatrix4fv(this.addr,!1,Ch),Lt(t,n)}}function v_(s,e){const t=this.cache;t[0]!==e&&(s.uniform1i(this.addr,e),t[0]=e)}function x_(s,e){const t=this.cache;if(e.x!==void 0)(t[0]!==e.x||t[1]!==e.y)&&(s.uniform2i(this.addr,e.x,e.y),t[0]=e.x,t[1]=e.y);else{if(Dt(t,e))return;s.uniform2iv(this.addr,e),Lt(t,e)}}function M_(s,e){const t=this.cache;if(e.x!==void 0)(t[0]!==e.x||t[1]!==e.y||t[2]!==e.z)&&(s.uniform3i(this.addr,e.x,e.y,e.z),t[0]=e.x,t[1]=e.y,t[2]=e.z);else{if(Dt(t,e))return;s.uniform3iv(this.addr,e),Lt(t,e)}}function y_(s,e){const t=this.cache;if(e.x!==void 0)(t[0]!==e.x||t[1]!==e.y||t[2]!==e.z||t[3]!==e.w)&&(s.uniform4i(this.addr,e.x,e.y,e.z,e.w),t[0]=e.x,t[1]=e.y,t[2]=e.z,t[3]=e.w);else{if(Dt(t,e))return;s.uniform4iv(this.addr,e),Lt(t,e)}}function S_(s,e){const t=this.cache;t[0]!==e&&(s.uniform1ui(this.addr,e),t[0]=e)}function b_(s,e){const t=this.cache;if(e.x!==void 0)(t[0]!==e.x||t[1]!==e.y)&&(s.uniform2ui(this.addr,e.x,e.y),t[0]=e.x,t[1]=e.y);else{if(Dt(t,e))return;s.uniform2uiv(this.addr,e),Lt(t,e)}}function E_(s,e){const t=this.cache;if(e.x!==void 0)(t[0]!==e.x||t[1]!==e.y||t[2]!==e.z)&&(s.uniform3ui(this.addr,e.x,e.y,e.z),t[0]=e.x,t[1]=e.y,t[2]=e.z);else{if(Dt(t,e))return;s.uniform3uiv(this.addr,e),Lt(t,e)}}function T_(s,e){const t=this.cache;if(e.x!==void 0)(t[0]!==e.x||t[1]!==e.y||t[2]!==e.z||t[3]!==e.w)&&(s.uniform4ui(this.addr,e.x,e.y,e.z,e.w),t[0]=e.x,t[1]=e.y,t[2]=e.z,t[3]=e.w);else{if(Dt(t,e))return;s.uniform4uiv(this.addr,e),Lt(t,e)}}function A_(s,e,t){const n=this.cache,i=t.allocateTextureUnit();n[0]!==i&&(s.uniform1i(this.addr,i),n[0]=i);let r;this.type===s.SAMPLER_2D_SHADOW?(bl.compareFunction=t.isReversedDepthBuffer()?ql:Yl,r=bl):r=Hu,t.setTexture2D(e||r,i)}function w_(s,e,t){const n=this.cache,i=t.allocateTextureUnit();n[0]!==i&&(s.uniform1i(this.addr,i),n[0]=i),t.setTexture3D(e||Wu,i)}function R_(s,e,t){const n=this.cache,i=t.allocateTextureUnit();n[0]!==i&&(s.uniform1i(this.addr,i),n[0]=i),t.setTextureCube(e||Xu,i)}function C_(s,e,t){const n=this.cache,i=t.allocateTextureUnit();n[0]!==i&&(s.uniform1i(this.addr,i),n[0]=i),t.setTexture2DArray(e||Gu,i)}function P_(s){switch(s){case 5126:return u_;case 35664:return d_;case 35665:return f_;case 35666:return p_;case 35674:return m_;case 35675:return g_;case 35676:return __;case 5124:case 35670:return v_;case 35667:case 35671:return x_;case 35668:case 35672:return M_;case 35669:case 35673:return y_;case 5125:return S_;case 36294:return b_;case 36295:return E_;case 36296:return T_;case 35678:case 36198:case 36298:case 36306:case 35682:return A_;case 35679:case 36299:case 36307:return w_;case 35680:case 36300:case 36308:case 36293:return R_;case 36289:case 36303:case 36311:case 36292:return C_}}function D_(s,e){s.uniform1fv(this.addr,e)}function L_(s,e){const t=Ns(e,this.size,2);s.uniform2fv(this.addr,t)}function I_(s,e){const t=Ns(e,this.size,3);s.uniform3fv(this.addr,t)}function N_(s,e){const t=Ns(e,this.size,4);s.uniform4fv(this.addr,t)}function U_(s,e){const t=Ns(e,this.size,4);s.uniformMatrix2fv(this.addr,!1,t)}function F_(s,e){const t=Ns(e,this.size,9);s.uniformMatrix3fv(this.addr,!1,t)}function O_(s,e){const t=Ns(e,this.size,16);s.uniformMatrix4fv(this.addr,!1,t)}function B_(s,e){s.uniform1iv(this.addr,e)}function k_(s,e){s.uniform2iv(this.addr,e)}function V_(s,e){s.uniform3iv(this.addr,e)}function z_(s,e){s.uniform4iv(this.addr,e)}function H_(s,e){s.uniform1uiv(this.addr,e)}function G_(s,e){s.uniform2uiv(this.addr,e)}function W_(s,e){s.uniform3uiv(this.addr,e)}function X_(s,e){s.uniform4uiv(this.addr,e)}function Y_(s,e,t){const n=this.cache,i=e.length,r=ya(t,i);Dt(n,r)||(s.uniform1iv(this.addr,r),Lt(n,r));let a;this.type===s.SAMPLER_2D_SHADOW?a=bl:a=Hu;for(let o=0;o!==i;++o)t.setTexture2D(e[o]||a,r[o])}function q_(s,e,t){const n=this.cache,i=e.length,r=ya(t,i);Dt(n,r)||(s.uniform1iv(this.addr,r),Lt(n,r));for(let a=0;a!==i;++a)t.setTexture3D(e[a]||Wu,r[a])}function j_(s,e,t){const n=this.cache,i=e.length,r=ya(t,i);Dt(n,r)||(s.uniform1iv(this.addr,r),Lt(n,r));for(let a=0;a!==i;++a)t.setTextureCube(e[a]||Xu,r[a])}function K_(s,e,t){const n=this.cache,i=e.length,r=ya(t,i);Dt(n,r)||(s.uniform1iv(this.addr,r),Lt(n,r));for(let a=0;a!==i;++a)t.setTexture2DArray(e[a]||Gu,r[a])}function $_(s){switch(s){case 5126:return D_;case 35664:return L_;case 35665:return I_;case 35666:return N_;case 35674:return U_;case 35675:return F_;case 35676:return O_;case 5124:case 35670:return B_;case 35667:case 35671:return k_;case 35668:case 35672:return V_;case 35669:case 35673:return z_;case 5125:return H_;case 36294:return G_;case 36295:return W_;case 36296:return X_;case 35678:case 36198:case 36298:case 36306:case 35682:return Y_;case 35679:case 36299:case 36307:return q_;case 35680:case 36300:case 36308:case 36293:return j_;case 36289:case 36303:case 36311:case 36292:return K_}}class Z_{constructor(e,t,n){this.id=e,this.addr=n,this.cache=[],this.type=t.type,this.setValue=P_(t.type)}}class J_{constructor(e,t,n){this.id=e,this.addr=n,this.cache=[],this.type=t.type,this.size=t.size,this.setValue=$_(t.type)}}class Q_{constructor(e){this.id=e,this.seq=[],this.map={}}setValue(e,t,n){const i=this.seq;for(let r=0,a=i.length;r!==a;++r){const o=i[r];o.setValue(e,t[o.id],n)}}}const mo=/(\w+)(\])?(\[|\.)?/g;function Lh(s,e){s.seq.push(e),s.map[e.id]=e}function ev(s,e,t){const n=s.name,i=n.length;for(mo.lastIndex=0;;){const r=mo.exec(n),a=mo.lastIndex;let o=r[1];const l=r[2]==="]",c=r[3];if(l&&(o=o|0),c===void 0||c==="["&&a+2===i){Lh(t,c===void 0?new Z_(o,s,e):new J_(o,s,e));break}else{let u=t.map[o];u===void 0&&(u=new Q_(o),Lh(t,u)),t=u}}}class Qr{constructor(e,t){this.seq=[],this.map={};const n=e.getProgramParameter(t,e.ACTIVE_UNIFORMS);for(let a=0;a<n;++a){const o=e.getActiveUniform(t,a),l=e.getUniformLocation(t,o.name);ev(o,l,this)}const i=[],r=[];for(const a of this.seq)a.type===e.SAMPLER_2D_SHADOW||a.type===e.SAMPLER_CUBE_SHADOW||a.type===e.SAMPLER_2D_ARRAY_SHADOW?i.push(a):r.push(a);i.length>0&&(this.seq=i.concat(r))}setValue(e,t,n,i){const r=this.map[t];r!==void 0&&r.setValue(e,n,i)}setOptional(e,t,n){const i=t[n];i!==void 0&&this.setValue(e,n,i)}static upload(e,t,n,i){for(let r=0,a=t.length;r!==a;++r){const o=t[r],l=n[o.id];l.needsUpdate!==!1&&o.setValue(e,l.value,i)}}static seqWithValue(e,t){const n=[];for(let i=0,r=e.length;i!==r;++i){const a=e[i];a.id in t&&n.push(a)}return n}}function Ih(s,e,t){const n=s.createShader(e);return s.shaderSource(n,t),s.compileShader(n),n}const tv=37297;let nv=0;function iv(s,e){const t=s.split(`
`),n=[],i=Math.max(e-6,0),r=Math.min(e+6,t.length);for(let a=i;a<r;a++){const o=a+1;n.push(`${o===e?">":" "} ${o}: ${t[a]}`)}return n.join(`
`)}const Nh=new He;function sv(s){Ke._getMatrix(Nh,Ke.workingColorSpace,s);const e=`mat3( ${Nh.elements.map(t=>t.toFixed(4))} )`;switch(Ke.getTransfer(s)){case ia:return[e,"LinearTransferOETF"];case tt:return[e,"sRGBTransferOETF"];default:return Pe("WebGLProgram: Unsupported color space: ",s),[e,"LinearTransferOETF"]}}function Uh(s,e,t){const n=s.getShaderParameter(e,s.COMPILE_STATUS),r=(s.getShaderInfoLog(e)||"").trim();if(n&&r==="")return"";const a=/ERROR: 0:(\d+)/.exec(r);if(a){const o=parseInt(a[1]);return t.toUpperCase()+`

`+r+`

`+iv(s.getShaderSource(e),o)}else return r}function rv(s,e){const t=sv(e);return[`vec4 ${s}( vec4 value ) {`,`	return ${t[1]}( vec4( value.rgb * ${t[0]}, value.a ) );`,"}"].join(`
`)}const av={[Nl]:"Linear",[Ul]:"Reinhard",[Fl]:"Cineon",[ar]:"ACESFilmic",[Bl]:"AgX",[kl]:"Neutral",[Ol]:"Custom"};function ov(s,e){const t=av[e];return t===void 0?(Pe("WebGLProgram: Unsupported toneMapping:",e),"vec3 "+s+"( vec3 color ) { return LinearToneMapping( color ); }"):"vec3 "+s+"( vec3 color ) { return "+t+"ToneMapping( color ); }"}const Br=new L;function lv(){Ke.getLuminanceCoefficients(Br);const s=Br.x.toFixed(4),e=Br.y.toFixed(4),t=Br.z.toFixed(4);return["float luminance( const in vec3 rgb ) {",`	const vec3 weights = vec3( ${s}, ${e}, ${t} );`,"	return dot( weights, rgb );","}"].join(`
`)}function cv(s){return[s.extensionClipCullDistance?"#extension GL_ANGLE_clip_cull_distance : require":"",s.extensionMultiDraw?"#extension GL_ANGLE_multi_draw : require":""].filter(js).join(`
`)}function hv(s){const e=[];for(const t in s){const n=s[t];n!==!1&&e.push("#define "+t+" "+n)}return e.join(`
`)}function uv(s,e){const t={},n=s.getProgramParameter(e,s.ACTIVE_ATTRIBUTES);for(let i=0;i<n;i++){const r=s.getActiveAttrib(e,i),a=r.name;let o=1;r.type===s.FLOAT_MAT2&&(o=2),r.type===s.FLOAT_MAT3&&(o=3),r.type===s.FLOAT_MAT4&&(o=4),t[a]={type:r.type,location:s.getAttribLocation(e,a),locationSize:o}}return t}function js(s){return s!==""}function Fh(s,e){const t=e.numSpotLightShadows+e.numSpotLightMaps-e.numSpotLightShadowsWithMaps;return s.replace(/NUM_DIR_LIGHTS/g,e.numDirLights).replace(/NUM_SPOT_LIGHTS/g,e.numSpotLights).replace(/NUM_SPOT_LIGHT_MAPS/g,e.numSpotLightMaps).replace(/NUM_SPOT_LIGHT_COORDS/g,t).replace(/NUM_RECT_AREA_LIGHTS/g,e.numRectAreaLights).replace(/NUM_POINT_LIGHTS/g,e.numPointLights).replace(/NUM_HEMI_LIGHTS/g,e.numHemiLights).replace(/NUM_DIR_LIGHT_SHADOWS/g,e.numDirLightShadows).replace(/NUM_SPOT_LIGHT_SHADOWS_WITH_MAPS/g,e.numSpotLightShadowsWithMaps).replace(/NUM_SPOT_LIGHT_SHADOWS/g,e.numSpotLightShadows).replace(/NUM_POINT_LIGHT_SHADOWS/g,e.numPointLightShadows)}function Oh(s,e){return s.replace(/NUM_CLIPPING_PLANES/g,e.numClippingPlanes).replace(/UNION_CLIPPING_PLANES/g,e.numClippingPlanes-e.numClipIntersection)}const dv=/^[ \t]*#include +<([\w\d./]+)>/gm;function El(s){return s.replace(dv,pv)}const fv=new Map;function pv(s,e){let t=Ge[e];if(t===void 0){const n=fv.get(e);if(n!==void 0)t=Ge[n],Pe('WebGLRenderer: Shader chunk "%s" has been deprecated. Use "%s" instead.',e,n);else throw new Error("Can not resolve #include <"+e+">")}return El(t)}const mv=/#pragma unroll_loop_start\s+for\s*\(\s*int\s+i\s*=\s*(\d+)\s*;\s*i\s*<\s*(\d+)\s*;\s*i\s*\+\+\s*\)\s*{([\s\S]+?)}\s+#pragma unroll_loop_end/g;function Bh(s){return s.replace(mv,gv)}function gv(s,e,t,n){let i="";for(let r=parseInt(e);r<parseInt(t);r++)i+=n.replace(/\[\s*i\s*\]/g,"[ "+r+" ]").replace(/UNROLLED_LOOP_INDEX/g,r);return i}function kh(s){let e=`precision ${s.precision} float;
	precision ${s.precision} int;
	precision ${s.precision} sampler2D;
	precision ${s.precision} samplerCube;
	precision ${s.precision} sampler3D;
	precision ${s.precision} sampler2DArray;
	precision ${s.precision} sampler2DShadow;
	precision ${s.precision} samplerCubeShadow;
	precision ${s.precision} sampler2DArrayShadow;
	precision ${s.precision} isampler2D;
	precision ${s.precision} isampler3D;
	precision ${s.precision} isamplerCube;
	precision ${s.precision} isampler2DArray;
	precision ${s.precision} usampler2D;
	precision ${s.precision} usampler3D;
	precision ${s.precision} usamplerCube;
	precision ${s.precision} usampler2DArray;
	`;return s.precision==="highp"?e+=`
#define HIGH_PRECISION`:s.precision==="mediump"?e+=`
#define MEDIUM_PRECISION`:s.precision==="lowp"&&(e+=`
#define LOW_PRECISION`),e}const _v={[qr]:"SHADOWMAP_TYPE_PCF",[Ys]:"SHADOWMAP_TYPE_VSM"};function vv(s){return _v[s.shadowMapType]||"SHADOWMAP_TYPE_BASIC"}const xv={[Di]:"ENVMAP_TYPE_CUBE",[_s]:"ENVMAP_TYPE_CUBE",[pa]:"ENVMAP_TYPE_CUBE_UV"};function Mv(s){return s.envMap===!1?"ENVMAP_TYPE_CUBE":xv[s.envMapMode]||"ENVMAP_TYPE_CUBE"}const yv={[_s]:"ENVMAP_MODE_REFRACTION"};function Sv(s){return s.envMap===!1?"ENVMAP_MODE_REFLECTION":yv[s.envMapMode]||"ENVMAP_MODE_REFLECTION"}const bv={[Il]:"ENVMAP_BLENDING_MULTIPLY",[uf]:"ENVMAP_BLENDING_MIX",[df]:"ENVMAP_BLENDING_ADD"};function Ev(s){return s.envMap===!1?"ENVMAP_BLENDING_NONE":bv[s.combine]||"ENVMAP_BLENDING_NONE"}function Tv(s){const e=s.envMapCubeUVHeight;if(e===null)return null;const t=Math.log2(e)-2,n=1/e;return{texelWidth:1/(3*Math.max(Math.pow(2,t),112)),texelHeight:n,maxMip:t}}function Av(s,e,t,n){const i=s.getContext(),r=t.defines;let a=t.vertexShader,o=t.fragmentShader;const l=vv(t),c=Mv(t),h=Sv(t),u=Ev(t),d=Tv(t),f=cv(t),g=hv(r),x=i.createProgram();let p,m,S=t.glslVersion?"#version "+t.glslVersion+`
`:"";t.isRawShaderMaterial?(p=["#define SHADER_TYPE "+t.shaderType,"#define SHADER_NAME "+t.shaderName,g].filter(js).join(`
`),p.length>0&&(p+=`
`),m=["#define SHADER_TYPE "+t.shaderType,"#define SHADER_NAME "+t.shaderName,g].filter(js).join(`
`),m.length>0&&(m+=`
`)):(p=[kh(t),"#define SHADER_TYPE "+t.shaderType,"#define SHADER_NAME "+t.shaderName,g,t.extensionClipCullDistance?"#define USE_CLIP_DISTANCE":"",t.batching?"#define USE_BATCHING":"",t.batchingColor?"#define USE_BATCHING_COLOR":"",t.instancing?"#define USE_INSTANCING":"",t.instancingColor?"#define USE_INSTANCING_COLOR":"",t.instancingMorph?"#define USE_INSTANCING_MORPH":"",t.useFog&&t.fog?"#define USE_FOG":"",t.useFog&&t.fogExp2?"#define FOG_EXP2":"",t.map?"#define USE_MAP":"",t.envMap?"#define USE_ENVMAP":"",t.envMap?"#define "+h:"",t.lightMap?"#define USE_LIGHTMAP":"",t.aoMap?"#define USE_AOMAP":"",t.bumpMap?"#define USE_BUMPMAP":"",t.normalMap?"#define USE_NORMALMAP":"",t.normalMapObjectSpace?"#define USE_NORMALMAP_OBJECTSPACE":"",t.normalMapTangentSpace?"#define USE_NORMALMAP_TANGENTSPACE":"",t.displacementMap?"#define USE_DISPLACEMENTMAP":"",t.emissiveMap?"#define USE_EMISSIVEMAP":"",t.anisotropy?"#define USE_ANISOTROPY":"",t.anisotropyMap?"#define USE_ANISOTROPYMAP":"",t.clearcoatMap?"#define USE_CLEARCOATMAP":"",t.clearcoatRoughnessMap?"#define USE_CLEARCOAT_ROUGHNESSMAP":"",t.clearcoatNormalMap?"#define USE_CLEARCOAT_NORMALMAP":"",t.iridescenceMap?"#define USE_IRIDESCENCEMAP":"",t.iridescenceThicknessMap?"#define USE_IRIDESCENCE_THICKNESSMAP":"",t.specularMap?"#define USE_SPECULARMAP":"",t.specularColorMap?"#define USE_SPECULAR_COLORMAP":"",t.specularIntensityMap?"#define USE_SPECULAR_INTENSITYMAP":"",t.roughnessMap?"#define USE_ROUGHNESSMAP":"",t.metalnessMap?"#define USE_METALNESSMAP":"",t.alphaMap?"#define USE_ALPHAMAP":"",t.alphaHash?"#define USE_ALPHAHASH":"",t.transmission?"#define USE_TRANSMISSION":"",t.transmissionMap?"#define USE_TRANSMISSIONMAP":"",t.thicknessMap?"#define USE_THICKNESSMAP":"",t.sheenColorMap?"#define USE_SHEEN_COLORMAP":"",t.sheenRoughnessMap?"#define USE_SHEEN_ROUGHNESSMAP":"",t.mapUv?"#define MAP_UV "+t.mapUv:"",t.alphaMapUv?"#define ALPHAMAP_UV "+t.alphaMapUv:"",t.lightMapUv?"#define LIGHTMAP_UV "+t.lightMapUv:"",t.aoMapUv?"#define AOMAP_UV "+t.aoMapUv:"",t.emissiveMapUv?"#define EMISSIVEMAP_UV "+t.emissiveMapUv:"",t.bumpMapUv?"#define BUMPMAP_UV "+t.bumpMapUv:"",t.normalMapUv?"#define NORMALMAP_UV "+t.normalMapUv:"",t.displacementMapUv?"#define DISPLACEMENTMAP_UV "+t.displacementMapUv:"",t.metalnessMapUv?"#define METALNESSMAP_UV "+t.metalnessMapUv:"",t.roughnessMapUv?"#define ROUGHNESSMAP_UV "+t.roughnessMapUv:"",t.anisotropyMapUv?"#define ANISOTROPYMAP_UV "+t.anisotropyMapUv:"",t.clearcoatMapUv?"#define CLEARCOATMAP_UV "+t.clearcoatMapUv:"",t.clearcoatNormalMapUv?"#define CLEARCOAT_NORMALMAP_UV "+t.clearcoatNormalMapUv:"",t.clearcoatRoughnessMapUv?"#define CLEARCOAT_ROUGHNESSMAP_UV "+t.clearcoatRoughnessMapUv:"",t.iridescenceMapUv?"#define IRIDESCENCEMAP_UV "+t.iridescenceMapUv:"",t.iridescenceThicknessMapUv?"#define IRIDESCENCE_THICKNESSMAP_UV "+t.iridescenceThicknessMapUv:"",t.sheenColorMapUv?"#define SHEEN_COLORMAP_UV "+t.sheenColorMapUv:"",t.sheenRoughnessMapUv?"#define SHEEN_ROUGHNESSMAP_UV "+t.sheenRoughnessMapUv:"",t.specularMapUv?"#define SPECULARMAP_UV "+t.specularMapUv:"",t.specularColorMapUv?"#define SPECULAR_COLORMAP_UV "+t.specularColorMapUv:"",t.specularIntensityMapUv?"#define SPECULAR_INTENSITYMAP_UV "+t.specularIntensityMapUv:"",t.transmissionMapUv?"#define TRANSMISSIONMAP_UV "+t.transmissionMapUv:"",t.thicknessMapUv?"#define THICKNESSMAP_UV "+t.thicknessMapUv:"",t.vertexTangents&&t.flatShading===!1?"#define USE_TANGENT":"",t.vertexColors?"#define USE_COLOR":"",t.vertexAlphas?"#define USE_COLOR_ALPHA":"",t.vertexUv1s?"#define USE_UV1":"",t.vertexUv2s?"#define USE_UV2":"",t.vertexUv3s?"#define USE_UV3":"",t.pointsUvs?"#define USE_POINTS_UV":"",t.flatShading?"#define FLAT_SHADED":"",t.skinning?"#define USE_SKINNING":"",t.morphTargets?"#define USE_MORPHTARGETS":"",t.morphNormals&&t.flatShading===!1?"#define USE_MORPHNORMALS":"",t.morphColors?"#define USE_MORPHCOLORS":"",t.morphTargetsCount>0?"#define MORPHTARGETS_TEXTURE_STRIDE "+t.morphTextureStride:"",t.morphTargetsCount>0?"#define MORPHTARGETS_COUNT "+t.morphTargetsCount:"",t.doubleSided?"#define DOUBLE_SIDED":"",t.flipSided?"#define FLIP_SIDED":"",t.shadowMapEnabled?"#define USE_SHADOWMAP":"",t.shadowMapEnabled?"#define "+l:"",t.sizeAttenuation?"#define USE_SIZEATTENUATION":"",t.numLightProbes>0?"#define USE_LIGHT_PROBES":"",t.logarithmicDepthBuffer?"#define USE_LOGARITHMIC_DEPTH_BUFFER":"",t.reversedDepthBuffer?"#define USE_REVERSED_DEPTH_BUFFER":"","uniform mat4 modelMatrix;","uniform mat4 modelViewMatrix;","uniform mat4 projectionMatrix;","uniform mat4 viewMatrix;","uniform mat3 normalMatrix;","uniform vec3 cameraPosition;","uniform bool isOrthographic;","#ifdef USE_INSTANCING","	attribute mat4 instanceMatrix;","#endif","#ifdef USE_INSTANCING_COLOR","	attribute vec3 instanceColor;","#endif","#ifdef USE_INSTANCING_MORPH","	uniform sampler2D morphTexture;","#endif","attribute vec3 position;","attribute vec3 normal;","attribute vec2 uv;","#ifdef USE_UV1","	attribute vec2 uv1;","#endif","#ifdef USE_UV2","	attribute vec2 uv2;","#endif","#ifdef USE_UV3","	attribute vec2 uv3;","#endif","#ifdef USE_TANGENT","	attribute vec4 tangent;","#endif","#if defined( USE_COLOR_ALPHA )","	attribute vec4 color;","#elif defined( USE_COLOR )","	attribute vec3 color;","#endif","#ifdef USE_SKINNING","	attribute vec4 skinIndex;","	attribute vec4 skinWeight;","#endif",`
`].filter(js).join(`
`),m=[kh(t),"#define SHADER_TYPE "+t.shaderType,"#define SHADER_NAME "+t.shaderName,g,t.useFog&&t.fog?"#define USE_FOG":"",t.useFog&&t.fogExp2?"#define FOG_EXP2":"",t.alphaToCoverage?"#define ALPHA_TO_COVERAGE":"",t.map?"#define USE_MAP":"",t.matcap?"#define USE_MATCAP":"",t.envMap?"#define USE_ENVMAP":"",t.envMap?"#define "+c:"",t.envMap?"#define "+h:"",t.envMap?"#define "+u:"",d?"#define CUBEUV_TEXEL_WIDTH "+d.texelWidth:"",d?"#define CUBEUV_TEXEL_HEIGHT "+d.texelHeight:"",d?"#define CUBEUV_MAX_MIP "+d.maxMip+".0":"",t.lightMap?"#define USE_LIGHTMAP":"",t.aoMap?"#define USE_AOMAP":"",t.bumpMap?"#define USE_BUMPMAP":"",t.normalMap?"#define USE_NORMALMAP":"",t.normalMapObjectSpace?"#define USE_NORMALMAP_OBJECTSPACE":"",t.normalMapTangentSpace?"#define USE_NORMALMAP_TANGENTSPACE":"",t.emissiveMap?"#define USE_EMISSIVEMAP":"",t.anisotropy?"#define USE_ANISOTROPY":"",t.anisotropyMap?"#define USE_ANISOTROPYMAP":"",t.clearcoat?"#define USE_CLEARCOAT":"",t.clearcoatMap?"#define USE_CLEARCOATMAP":"",t.clearcoatRoughnessMap?"#define USE_CLEARCOAT_ROUGHNESSMAP":"",t.clearcoatNormalMap?"#define USE_CLEARCOAT_NORMALMAP":"",t.dispersion?"#define USE_DISPERSION":"",t.iridescence?"#define USE_IRIDESCENCE":"",t.iridescenceMap?"#define USE_IRIDESCENCEMAP":"",t.iridescenceThicknessMap?"#define USE_IRIDESCENCE_THICKNESSMAP":"",t.specularMap?"#define USE_SPECULARMAP":"",t.specularColorMap?"#define USE_SPECULAR_COLORMAP":"",t.specularIntensityMap?"#define USE_SPECULAR_INTENSITYMAP":"",t.roughnessMap?"#define USE_ROUGHNESSMAP":"",t.metalnessMap?"#define USE_METALNESSMAP":"",t.alphaMap?"#define USE_ALPHAMAP":"",t.alphaTest?"#define USE_ALPHATEST":"",t.alphaHash?"#define USE_ALPHAHASH":"",t.sheen?"#define USE_SHEEN":"",t.sheenColorMap?"#define USE_SHEEN_COLORMAP":"",t.sheenRoughnessMap?"#define USE_SHEEN_ROUGHNESSMAP":"",t.transmission?"#define USE_TRANSMISSION":"",t.transmissionMap?"#define USE_TRANSMISSIONMAP":"",t.thicknessMap?"#define USE_THICKNESSMAP":"",t.vertexTangents&&t.flatShading===!1?"#define USE_TANGENT":"",t.vertexColors||t.instancingColor?"#define USE_COLOR":"",t.vertexAlphas||t.batchingColor?"#define USE_COLOR_ALPHA":"",t.vertexUv1s?"#define USE_UV1":"",t.vertexUv2s?"#define USE_UV2":"",t.vertexUv3s?"#define USE_UV3":"",t.pointsUvs?"#define USE_POINTS_UV":"",t.gradientMap?"#define USE_GRADIENTMAP":"",t.flatShading?"#define FLAT_SHADED":"",t.doubleSided?"#define DOUBLE_SIDED":"",t.flipSided?"#define FLIP_SIDED":"",t.shadowMapEnabled?"#define USE_SHADOWMAP":"",t.shadowMapEnabled?"#define "+l:"",t.premultipliedAlpha?"#define PREMULTIPLIED_ALPHA":"",t.numLightProbes>0?"#define USE_LIGHT_PROBES":"",t.decodeVideoTexture?"#define DECODE_VIDEO_TEXTURE":"",t.decodeVideoTextureEmissive?"#define DECODE_VIDEO_TEXTURE_EMISSIVE":"",t.logarithmicDepthBuffer?"#define USE_LOGARITHMIC_DEPTH_BUFFER":"",t.reversedDepthBuffer?"#define USE_REVERSED_DEPTH_BUFFER":"","uniform mat4 viewMatrix;","uniform vec3 cameraPosition;","uniform bool isOrthographic;",t.toneMapping!==Un?"#define TONE_MAPPING":"",t.toneMapping!==Un?Ge.tonemapping_pars_fragment:"",t.toneMapping!==Un?ov("toneMapping",t.toneMapping):"",t.dithering?"#define DITHERING":"",t.opaque?"#define OPAQUE":"",Ge.colorspace_pars_fragment,rv("linearToOutputTexel",t.outputColorSpace),lv(),t.useDepthPacking?"#define DEPTH_PACKING "+t.depthPacking:"",`
`].filter(js).join(`
`)),a=El(a),a=Fh(a,t),a=Oh(a,t),o=El(o),o=Fh(o,t),o=Oh(o,t),a=Bh(a),o=Bh(o),t.isRawShaderMaterial!==!0&&(S=`#version 300 es
`,p=[f,"#define attribute in","#define varying out","#define texture2D texture"].join(`
`)+`
`+p,m=["#define varying in",t.glslVersion===Uc?"":"layout(location = 0) out highp vec4 pc_fragColor;",t.glslVersion===Uc?"":"#define gl_FragColor pc_fragColor","#define gl_FragDepthEXT gl_FragDepth","#define texture2D texture","#define textureCube texture","#define texture2DProj textureProj","#define texture2DLodEXT textureLod","#define texture2DProjLodEXT textureProjLod","#define textureCubeLodEXT textureLod","#define texture2DGradEXT textureGrad","#define texture2DProjGradEXT textureProjGrad","#define textureCubeGradEXT textureGrad"].join(`
`)+`
`+m);const T=S+p+a,M=S+m+o,E=Ih(i,i.VERTEX_SHADER,T),w=Ih(i,i.FRAGMENT_SHADER,M);i.attachShader(x,E),i.attachShader(x,w),t.index0AttributeName!==void 0?i.bindAttribLocation(x,0,t.index0AttributeName):t.morphTargets===!0&&i.bindAttribLocation(x,0,"position"),i.linkProgram(x);function C(R){if(s.debug.checkShaderErrors){const F=i.getProgramInfoLog(x)||"",O=i.getShaderInfoLog(E)||"",X=i.getShaderInfoLog(w)||"",V=F.trim(),k=O.trim(),U=X.trim();let Q=!0,K=!0;if(i.getProgramParameter(x,i.LINK_STATUS)===!1)if(Q=!1,typeof s.debug.onShaderError=="function")s.debug.onShaderError(i,x,E,w);else{const se=Uh(i,E,"vertex"),he=Uh(i,w,"fragment");Ue("THREE.WebGLProgram: Shader Error "+i.getError()+" - VALIDATE_STATUS "+i.getProgramParameter(x,i.VALIDATE_STATUS)+`

Material Name: `+R.name+`
Material Type: `+R.type+`

Program Info Log: `+V+`
`+se+`
`+he)}else V!==""?Pe("WebGLProgram: Program Info Log:",V):(k===""||U==="")&&(K=!1);K&&(R.diagnostics={runnable:Q,programLog:V,vertexShader:{log:k,prefix:p},fragmentShader:{log:U,prefix:m}})}i.deleteShader(E),i.deleteShader(w),v=new Qr(i,x),b=uv(i,x)}let v;this.getUniforms=function(){return v===void 0&&C(this),v};let b;this.getAttributes=function(){return b===void 0&&C(this),b};let D=t.rendererExtensionParallelShaderCompile===!1;return this.isReady=function(){return D===!1&&(D=i.getProgramParameter(x,tv)),D},this.destroy=function(){n.releaseStatesOfProgram(this),i.deleteProgram(x),this.program=void 0},this.type=t.shaderType,this.name=t.shaderName,this.id=nv++,this.cacheKey=e,this.usedTimes=1,this.program=x,this.vertexShader=E,this.fragmentShader=w,this}let wv=0;class Rv{constructor(){this.shaderCache=new Map,this.materialCache=new Map}update(e){const t=e.vertexShader,n=e.fragmentShader,i=this._getShaderStage(t),r=this._getShaderStage(n),a=this._getShaderCacheForMaterial(e);return a.has(i)===!1&&(a.add(i),i.usedTimes++),a.has(r)===!1&&(a.add(r),r.usedTimes++),this}remove(e){const t=this.materialCache.get(e);for(const n of t)n.usedTimes--,n.usedTimes===0&&this.shaderCache.delete(n.code);return this.materialCache.delete(e),this}getVertexShaderID(e){return this._getShaderStage(e.vertexShader).id}getFragmentShaderID(e){return this._getShaderStage(e.fragmentShader).id}dispose(){this.shaderCache.clear(),this.materialCache.clear()}_getShaderCacheForMaterial(e){const t=this.materialCache;let n=t.get(e);return n===void 0&&(n=new Set,t.set(e,n)),n}_getShaderStage(e){const t=this.shaderCache;let n=t.get(e);return n===void 0&&(n=new Cv(e),t.set(e,n)),n}}class Cv{constructor(e){this.id=wv++,this.code=e,this.usedTimes=0}}function Pv(s,e,t,n,i,r){const a=new $l,o=new Rv,l=new Set,c=[],h=new Map,u=n.logarithmicDepthBuffer;let d=n.precision;const f={MeshDepthMaterial:"depth",MeshDistanceMaterial:"distance",MeshNormalMaterial:"normal",MeshBasicMaterial:"basic",MeshLambertMaterial:"lambert",MeshPhongMaterial:"phong",MeshToonMaterial:"toon",MeshStandardMaterial:"physical",MeshPhysicalMaterial:"physical",MeshMatcapMaterial:"matcap",LineBasicMaterial:"basic",LineDashedMaterial:"dashed",PointsMaterial:"points",ShadowMaterial:"shadow",SpriteMaterial:"sprite"};function g(v){return l.add(v),v===0?"uv":`uv${v}`}function x(v,b,D,R,F){const O=R.fog,X=F.geometry,V=v.isMeshStandardMaterial||v.isMeshLambertMaterial||v.isMeshPhongMaterial?R.environment:null,k=v.isMeshStandardMaterial||v.isMeshLambertMaterial&&!v.envMap||v.isMeshPhongMaterial&&!v.envMap,U=e.get(v.envMap||V,k),Q=U&&U.mapping===pa?U.image.height:null,K=f[v.type];v.precision!==null&&(d=n.getMaxPrecision(v.precision),d!==v.precision&&Pe("WebGLProgram.getParameters:",v.precision,"not supported, using",d,"instead."));const se=X.morphAttributes.position||X.morphAttributes.normal||X.morphAttributes.color,he=se!==void 0?se.length:0;let le=0;X.morphAttributes.position!==void 0&&(le=1),X.morphAttributes.normal!==void 0&&(le=2),X.morphAttributes.color!==void 0&&(le=3);let $,ce,Re,G;if(K){const nt=Rn[K];$=nt.vertexShader,ce=nt.fragmentShader}else $=v.vertexShader,ce=v.fragmentShader,o.update(v),Re=o.getVertexShaderID(v),G=o.getFragmentShaderID(v);const Z=s.getRenderTarget(),ee=s.state.buffers.depth.getReversed(),we=F.isInstancedMesh===!0,ve=F.isBatchedMesh===!0,Fe=!!v.map,Mt=!!v.matcap,qe=!!U,Ze=!!v.aoMap,Qe=!!v.lightMap,ke=!!v.bumpMap,pt=!!v.normalMap,P=!!v.displacementMap,gt=!!v.emissiveMap,$e=!!v.metalnessMap,et=!!v.roughnessMap,Me=v.anisotropy>0,A=v.clearcoat>0,_=v.dispersion>0,N=v.iridescence>0,j=v.sheen>0,J=v.transmission>0,Y=Me&&!!v.anisotropyMap,ge=A&&!!v.clearcoatMap,re=A&&!!v.clearcoatNormalMap,Ee=A&&!!v.clearcoatRoughnessMap,Ne=N&&!!v.iridescenceMap,te=N&&!!v.iridescenceThicknessMap,ae=j&&!!v.sheenColorMap,ye=j&&!!v.sheenRoughnessMap,Se=!!v.specularMap,fe=!!v.specularColorMap,Oe=!!v.specularIntensityMap,I=J&&!!v.transmissionMap,oe=J&&!!v.thicknessMap,ne=!!v.gradientMap,xe=!!v.alphaMap,ie=v.alphaTest>0,q=!!v.alphaHash,be=!!v.extensions;let Be=Un;v.toneMapped&&(Z===null||Z.isXRRenderTarget===!0)&&(Be=s.toneMapping);const dt={shaderID:K,shaderType:v.type,shaderName:v.name,vertexShader:$,fragmentShader:ce,defines:v.defines,customVertexShaderID:Re,customFragmentShaderID:G,isRawShaderMaterial:v.isRawShaderMaterial===!0,glslVersion:v.glslVersion,precision:d,batching:ve,batchingColor:ve&&F._colorsTexture!==null,instancing:we,instancingColor:we&&F.instanceColor!==null,instancingMorph:we&&F.morphTexture!==null,outputColorSpace:Z===null?s.outputColorSpace:Z.isXRRenderTarget===!0?Z.texture.colorSpace:Kt,alphaToCoverage:!!v.alphaToCoverage,map:Fe,matcap:Mt,envMap:qe,envMapMode:qe&&U.mapping,envMapCubeUVHeight:Q,aoMap:Ze,lightMap:Qe,bumpMap:ke,normalMap:pt,displacementMap:P,emissiveMap:gt,normalMapObjectSpace:pt&&v.normalMapType===vf,normalMapTangentSpace:pt&&v.normalMapType===ga,metalnessMap:$e,roughnessMap:et,anisotropy:Me,anisotropyMap:Y,clearcoat:A,clearcoatMap:ge,clearcoatNormalMap:re,clearcoatRoughnessMap:Ee,dispersion:_,iridescence:N,iridescenceMap:Ne,iridescenceThicknessMap:te,sheen:j,sheenColorMap:ae,sheenRoughnessMap:ye,specularMap:Se,specularColorMap:fe,specularIntensityMap:Oe,transmission:J,transmissionMap:I,thicknessMap:oe,gradientMap:ne,opaque:v.transparent===!1&&v.blending===cs&&v.alphaToCoverage===!1,alphaMap:xe,alphaTest:ie,alphaHash:q,combine:v.combine,mapUv:Fe&&g(v.map.channel),aoMapUv:Ze&&g(v.aoMap.channel),lightMapUv:Qe&&g(v.lightMap.channel),bumpMapUv:ke&&g(v.bumpMap.channel),normalMapUv:pt&&g(v.normalMap.channel),displacementMapUv:P&&g(v.displacementMap.channel),emissiveMapUv:gt&&g(v.emissiveMap.channel),metalnessMapUv:$e&&g(v.metalnessMap.channel),roughnessMapUv:et&&g(v.roughnessMap.channel),anisotropyMapUv:Y&&g(v.anisotropyMap.channel),clearcoatMapUv:ge&&g(v.clearcoatMap.channel),clearcoatNormalMapUv:re&&g(v.clearcoatNormalMap.channel),clearcoatRoughnessMapUv:Ee&&g(v.clearcoatRoughnessMap.channel),iridescenceMapUv:Ne&&g(v.iridescenceMap.channel),iridescenceThicknessMapUv:te&&g(v.iridescenceThicknessMap.channel),sheenColorMapUv:ae&&g(v.sheenColorMap.channel),sheenRoughnessMapUv:ye&&g(v.sheenRoughnessMap.channel),specularMapUv:Se&&g(v.specularMap.channel),specularColorMapUv:fe&&g(v.specularColorMap.channel),specularIntensityMapUv:Oe&&g(v.specularIntensityMap.channel),transmissionMapUv:I&&g(v.transmissionMap.channel),thicknessMapUv:oe&&g(v.thicknessMap.channel),alphaMapUv:xe&&g(v.alphaMap.channel),vertexTangents:!!X.attributes.tangent&&(pt||Me),vertexColors:v.vertexColors,vertexAlphas:v.vertexColors===!0&&!!X.attributes.color&&X.attributes.color.itemSize===4,pointsUvs:F.isPoints===!0&&!!X.attributes.uv&&(Fe||xe),fog:!!O,useFog:v.fog===!0,fogExp2:!!O&&O.isFogExp2,flatShading:v.wireframe===!1&&(v.flatShading===!0||X.attributes.normal===void 0&&pt===!1&&(v.isMeshLambertMaterial||v.isMeshPhongMaterial||v.isMeshStandardMaterial||v.isMeshPhysicalMaterial)),sizeAttenuation:v.sizeAttenuation===!0,logarithmicDepthBuffer:u,reversedDepthBuffer:ee,skinning:F.isSkinnedMesh===!0,morphTargets:X.morphAttributes.position!==void 0,morphNormals:X.morphAttributes.normal!==void 0,morphColors:X.morphAttributes.color!==void 0,morphTargetsCount:he,morphTextureStride:le,numDirLights:b.directional.length,numPointLights:b.point.length,numSpotLights:b.spot.length,numSpotLightMaps:b.spotLightMap.length,numRectAreaLights:b.rectArea.length,numHemiLights:b.hemi.length,numDirLightShadows:b.directionalShadowMap.length,numPointLightShadows:b.pointShadowMap.length,numSpotLightShadows:b.spotShadowMap.length,numSpotLightShadowsWithMaps:b.numSpotLightShadowsWithMaps,numLightProbes:b.numLightProbes,numClippingPlanes:r.numPlanes,numClipIntersection:r.numIntersection,dithering:v.dithering,shadowMapEnabled:s.shadowMap.enabled&&D.length>0,shadowMapType:s.shadowMap.type,toneMapping:Be,decodeVideoTexture:Fe&&v.map.isVideoTexture===!0&&Ke.getTransfer(v.map.colorSpace)===tt,decodeVideoTextureEmissive:gt&&v.emissiveMap.isVideoTexture===!0&&Ke.getTransfer(v.emissiveMap.colorSpace)===tt,premultipliedAlpha:v.premultipliedAlpha,doubleSided:v.side===Pn,flipSided:v.side===qt,useDepthPacking:v.depthPacking>=0,depthPacking:v.depthPacking||0,index0AttributeName:v.index0AttributeName,extensionClipCullDistance:be&&v.extensions.clipCullDistance===!0&&t.has("WEBGL_clip_cull_distance"),extensionMultiDraw:(be&&v.extensions.multiDraw===!0||ve)&&t.has("WEBGL_multi_draw"),rendererExtensionParallelShaderCompile:t.has("KHR_parallel_shader_compile"),customProgramCacheKey:v.customProgramCacheKey()};return dt.vertexUv1s=l.has(1),dt.vertexUv2s=l.has(2),dt.vertexUv3s=l.has(3),l.clear(),dt}function p(v){const b=[];if(v.shaderID?b.push(v.shaderID):(b.push(v.customVertexShaderID),b.push(v.customFragmentShaderID)),v.defines!==void 0)for(const D in v.defines)b.push(D),b.push(v.defines[D]);return v.isRawShaderMaterial===!1&&(m(b,v),S(b,v),b.push(s.outputColorSpace)),b.push(v.customProgramCacheKey),b.join()}function m(v,b){v.push(b.precision),v.push(b.outputColorSpace),v.push(b.envMapMode),v.push(b.envMapCubeUVHeight),v.push(b.mapUv),v.push(b.alphaMapUv),v.push(b.lightMapUv),v.push(b.aoMapUv),v.push(b.bumpMapUv),v.push(b.normalMapUv),v.push(b.displacementMapUv),v.push(b.emissiveMapUv),v.push(b.metalnessMapUv),v.push(b.roughnessMapUv),v.push(b.anisotropyMapUv),v.push(b.clearcoatMapUv),v.push(b.clearcoatNormalMapUv),v.push(b.clearcoatRoughnessMapUv),v.push(b.iridescenceMapUv),v.push(b.iridescenceThicknessMapUv),v.push(b.sheenColorMapUv),v.push(b.sheenRoughnessMapUv),v.push(b.specularMapUv),v.push(b.specularColorMapUv),v.push(b.specularIntensityMapUv),v.push(b.transmissionMapUv),v.push(b.thicknessMapUv),v.push(b.combine),v.push(b.fogExp2),v.push(b.sizeAttenuation),v.push(b.morphTargetsCount),v.push(b.morphAttributeCount),v.push(b.numDirLights),v.push(b.numPointLights),v.push(b.numSpotLights),v.push(b.numSpotLightMaps),v.push(b.numHemiLights),v.push(b.numRectAreaLights),v.push(b.numDirLightShadows),v.push(b.numPointLightShadows),v.push(b.numSpotLightShadows),v.push(b.numSpotLightShadowsWithMaps),v.push(b.numLightProbes),v.push(b.shadowMapType),v.push(b.toneMapping),v.push(b.numClippingPlanes),v.push(b.numClipIntersection),v.push(b.depthPacking)}function S(v,b){a.disableAll(),b.instancing&&a.enable(0),b.instancingColor&&a.enable(1),b.instancingMorph&&a.enable(2),b.matcap&&a.enable(3),b.envMap&&a.enable(4),b.normalMapObjectSpace&&a.enable(5),b.normalMapTangentSpace&&a.enable(6),b.clearcoat&&a.enable(7),b.iridescence&&a.enable(8),b.alphaTest&&a.enable(9),b.vertexColors&&a.enable(10),b.vertexAlphas&&a.enable(11),b.vertexUv1s&&a.enable(12),b.vertexUv2s&&a.enable(13),b.vertexUv3s&&a.enable(14),b.vertexTangents&&a.enable(15),b.anisotropy&&a.enable(16),b.alphaHash&&a.enable(17),b.batching&&a.enable(18),b.dispersion&&a.enable(19),b.batchingColor&&a.enable(20),b.gradientMap&&a.enable(21),v.push(a.mask),a.disableAll(),b.fog&&a.enable(0),b.useFog&&a.enable(1),b.flatShading&&a.enable(2),b.logarithmicDepthBuffer&&a.enable(3),b.reversedDepthBuffer&&a.enable(4),b.skinning&&a.enable(5),b.morphTargets&&a.enable(6),b.morphNormals&&a.enable(7),b.morphColors&&a.enable(8),b.premultipliedAlpha&&a.enable(9),b.shadowMapEnabled&&a.enable(10),b.doubleSided&&a.enable(11),b.flipSided&&a.enable(12),b.useDepthPacking&&a.enable(13),b.dithering&&a.enable(14),b.transmission&&a.enable(15),b.sheen&&a.enable(16),b.opaque&&a.enable(17),b.pointsUvs&&a.enable(18),b.decodeVideoTexture&&a.enable(19),b.decodeVideoTextureEmissive&&a.enable(20),b.alphaToCoverage&&a.enable(21),v.push(a.mask)}function T(v){const b=f[v.type];let D;if(b){const R=Rn[b];D=mi.clone(R.uniforms)}else D=v.uniforms;return D}function M(v,b){let D=h.get(b);return D!==void 0?++D.usedTimes:(D=new Av(s,b,v,i),c.push(D),h.set(b,D)),D}function E(v){if(--v.usedTimes===0){const b=c.indexOf(v);c[b]=c[c.length-1],c.pop(),h.delete(v.cacheKey),v.destroy()}}function w(v){o.remove(v)}function C(){o.dispose()}return{getParameters:x,getProgramCacheKey:p,getUniforms:T,acquireProgram:M,releaseProgram:E,releaseShaderCache:w,programs:c,dispose:C}}function Dv(){let s=new WeakMap;function e(a){return s.has(a)}function t(a){let o=s.get(a);return o===void 0&&(o={},s.set(a,o)),o}function n(a){s.delete(a)}function i(a,o,l){s.get(a)[o]=l}function r(){s=new WeakMap}return{has:e,get:t,remove:n,update:i,dispose:r}}function Lv(s,e){return s.groupOrder!==e.groupOrder?s.groupOrder-e.groupOrder:s.renderOrder!==e.renderOrder?s.renderOrder-e.renderOrder:s.material.id!==e.material.id?s.material.id-e.material.id:s.materialVariant!==e.materialVariant?s.materialVariant-e.materialVariant:s.z!==e.z?s.z-e.z:s.id-e.id}function Vh(s,e){return s.groupOrder!==e.groupOrder?s.groupOrder-e.groupOrder:s.renderOrder!==e.renderOrder?s.renderOrder-e.renderOrder:s.z!==e.z?e.z-s.z:s.id-e.id}function zh(){const s=[];let e=0;const t=[],n=[],i=[];function r(){e=0,t.length=0,n.length=0,i.length=0}function a(d){let f=0;return d.isInstancedMesh&&(f+=2),d.isSkinnedMesh&&(f+=1),f}function o(d,f,g,x,p,m){let S=s[e];return S===void 0?(S={id:d.id,object:d,geometry:f,material:g,materialVariant:a(d),groupOrder:x,renderOrder:d.renderOrder,z:p,group:m},s[e]=S):(S.id=d.id,S.object=d,S.geometry=f,S.material=g,S.materialVariant=a(d),S.groupOrder=x,S.renderOrder=d.renderOrder,S.z=p,S.group=m),e++,S}function l(d,f,g,x,p,m){const S=o(d,f,g,x,p,m);g.transmission>0?n.push(S):g.transparent===!0?i.push(S):t.push(S)}function c(d,f,g,x,p,m){const S=o(d,f,g,x,p,m);g.transmission>0?n.unshift(S):g.transparent===!0?i.unshift(S):t.unshift(S)}function h(d,f){t.length>1&&t.sort(d||Lv),n.length>1&&n.sort(f||Vh),i.length>1&&i.sort(f||Vh)}function u(){for(let d=e,f=s.length;d<f;d++){const g=s[d];if(g.id===null)break;g.id=null,g.object=null,g.geometry=null,g.material=null,g.group=null}}return{opaque:t,transmissive:n,transparent:i,init:r,push:l,unshift:c,finish:u,sort:h}}function Iv(){let s=new WeakMap;function e(n,i){const r=s.get(n);let a;return r===void 0?(a=new zh,s.set(n,[a])):i>=r.length?(a=new zh,r.push(a)):a=r[i],a}function t(){s=new WeakMap}return{get:e,dispose:t}}function Nv(){const s={};return{get:function(e){if(s[e.id]!==void 0)return s[e.id];let t;switch(e.type){case"DirectionalLight":t={direction:new L,color:new Ie};break;case"SpotLight":t={position:new L,direction:new L,color:new Ie,distance:0,coneCos:0,penumbraCos:0,decay:0};break;case"PointLight":t={position:new L,color:new Ie,distance:0,decay:0};break;case"HemisphereLight":t={direction:new L,skyColor:new Ie,groundColor:new Ie};break;case"RectAreaLight":t={color:new Ie,position:new L,halfWidth:new L,halfHeight:new L};break}return s[e.id]=t,t}}}function Uv(){const s={};return{get:function(e){if(s[e.id]!==void 0)return s[e.id];let t;switch(e.type){case"DirectionalLight":t={shadowIntensity:1,shadowBias:0,shadowNormalBias:0,shadowRadius:1,shadowMapSize:new Le};break;case"SpotLight":t={shadowIntensity:1,shadowBias:0,shadowNormalBias:0,shadowRadius:1,shadowMapSize:new Le};break;case"PointLight":t={shadowIntensity:1,shadowBias:0,shadowNormalBias:0,shadowRadius:1,shadowMapSize:new Le,shadowCameraNear:1,shadowCameraFar:1e3};break}return s[e.id]=t,t}}}let Fv=0;function Ov(s,e){return(e.castShadow?2:0)-(s.castShadow?2:0)+(e.map?1:0)-(s.map?1:0)}function Bv(s){const e=new Nv,t=Uv(),n={version:0,hash:{directionalLength:-1,pointLength:-1,spotLength:-1,rectAreaLength:-1,hemiLength:-1,numDirectionalShadows:-1,numPointShadows:-1,numSpotShadows:-1,numSpotMaps:-1,numLightProbes:-1},ambient:[0,0,0],probe:[],directional:[],directionalShadow:[],directionalShadowMap:[],directionalShadowMatrix:[],spot:[],spotLightMap:[],spotShadow:[],spotShadowMap:[],spotLightMatrix:[],rectArea:[],rectAreaLTC1:null,rectAreaLTC2:null,point:[],pointShadow:[],pointShadowMap:[],pointShadowMatrix:[],hemi:[],numSpotLightShadowsWithMaps:0,numLightProbes:0};for(let c=0;c<9;c++)n.probe.push(new L);const i=new L,r=new Ve,a=new Ve;function o(c){let h=0,u=0,d=0;for(let b=0;b<9;b++)n.probe[b].set(0,0,0);let f=0,g=0,x=0,p=0,m=0,S=0,T=0,M=0,E=0,w=0,C=0;c.sort(Ov);for(let b=0,D=c.length;b<D;b++){const R=c[b],F=R.color,O=R.intensity,X=R.distance;let V=null;if(R.shadow&&R.shadow.map&&(R.shadow.map.texture.format===xs?V=R.shadow.map.texture:V=R.shadow.map.depthTexture||R.shadow.map.texture),R.isAmbientLight)h+=F.r*O,u+=F.g*O,d+=F.b*O;else if(R.isLightProbe){for(let k=0;k<9;k++)n.probe[k].addScaledVector(R.sh.coefficients[k],O);C++}else if(R.isDirectionalLight){const k=e.get(R);if(k.color.copy(R.color).multiplyScalar(R.intensity),R.castShadow){const U=R.shadow,Q=t.get(R);Q.shadowIntensity=U.intensity,Q.shadowBias=U.bias,Q.shadowNormalBias=U.normalBias,Q.shadowRadius=U.radius,Q.shadowMapSize=U.mapSize,n.directionalShadow[f]=Q,n.directionalShadowMap[f]=V,n.directionalShadowMatrix[f]=R.shadow.matrix,S++}n.directional[f]=k,f++}else if(R.isSpotLight){const k=e.get(R);k.position.setFromMatrixPosition(R.matrixWorld),k.color.copy(F).multiplyScalar(O),k.distance=X,k.coneCos=Math.cos(R.angle),k.penumbraCos=Math.cos(R.angle*(1-R.penumbra)),k.decay=R.decay,n.spot[x]=k;const U=R.shadow;if(R.map&&(n.spotLightMap[E]=R.map,E++,U.updateMatrices(R),R.castShadow&&w++),n.spotLightMatrix[x]=U.matrix,R.castShadow){const Q=t.get(R);Q.shadowIntensity=U.intensity,Q.shadowBias=U.bias,Q.shadowNormalBias=U.normalBias,Q.shadowRadius=U.radius,Q.shadowMapSize=U.mapSize,n.spotShadow[x]=Q,n.spotShadowMap[x]=V,M++}x++}else if(R.isRectAreaLight){const k=e.get(R);k.color.copy(F).multiplyScalar(O),k.halfWidth.set(R.width*.5,0,0),k.halfHeight.set(0,R.height*.5,0),n.rectArea[p]=k,p++}else if(R.isPointLight){const k=e.get(R);if(k.color.copy(R.color).multiplyScalar(R.intensity),k.distance=R.distance,k.decay=R.decay,R.castShadow){const U=R.shadow,Q=t.get(R);Q.shadowIntensity=U.intensity,Q.shadowBias=U.bias,Q.shadowNormalBias=U.normalBias,Q.shadowRadius=U.radius,Q.shadowMapSize=U.mapSize,Q.shadowCameraNear=U.camera.near,Q.shadowCameraFar=U.camera.far,n.pointShadow[g]=Q,n.pointShadowMap[g]=V,n.pointShadowMatrix[g]=R.shadow.matrix,T++}n.point[g]=k,g++}else if(R.isHemisphereLight){const k=e.get(R);k.skyColor.copy(R.color).multiplyScalar(O),k.groundColor.copy(R.groundColor).multiplyScalar(O),n.hemi[m]=k,m++}}p>0&&(s.has("OES_texture_float_linear")===!0?(n.rectAreaLTC1=ue.LTC_FLOAT_1,n.rectAreaLTC2=ue.LTC_FLOAT_2):(n.rectAreaLTC1=ue.LTC_HALF_1,n.rectAreaLTC2=ue.LTC_HALF_2)),n.ambient[0]=h,n.ambient[1]=u,n.ambient[2]=d;const v=n.hash;(v.directionalLength!==f||v.pointLength!==g||v.spotLength!==x||v.rectAreaLength!==p||v.hemiLength!==m||v.numDirectionalShadows!==S||v.numPointShadows!==T||v.numSpotShadows!==M||v.numSpotMaps!==E||v.numLightProbes!==C)&&(n.directional.length=f,n.spot.length=x,n.rectArea.length=p,n.point.length=g,n.hemi.length=m,n.directionalShadow.length=S,n.directionalShadowMap.length=S,n.pointShadow.length=T,n.pointShadowMap.length=T,n.spotShadow.length=M,n.spotShadowMap.length=M,n.directionalShadowMatrix.length=S,n.pointShadowMatrix.length=T,n.spotLightMatrix.length=M+E-w,n.spotLightMap.length=E,n.numSpotLightShadowsWithMaps=w,n.numLightProbes=C,v.directionalLength=f,v.pointLength=g,v.spotLength=x,v.rectAreaLength=p,v.hemiLength=m,v.numDirectionalShadows=S,v.numPointShadows=T,v.numSpotShadows=M,v.numSpotMaps=E,v.numLightProbes=C,n.version=Fv++)}function l(c,h){let u=0,d=0,f=0,g=0,x=0;const p=h.matrixWorldInverse;for(let m=0,S=c.length;m<S;m++){const T=c[m];if(T.isDirectionalLight){const M=n.directional[u];M.direction.setFromMatrixPosition(T.matrixWorld),i.setFromMatrixPosition(T.target.matrixWorld),M.direction.sub(i),M.direction.transformDirection(p),u++}else if(T.isSpotLight){const M=n.spot[f];M.position.setFromMatrixPosition(T.matrixWorld),M.position.applyMatrix4(p),M.direction.setFromMatrixPosition(T.matrixWorld),i.setFromMatrixPosition(T.target.matrixWorld),M.direction.sub(i),M.direction.transformDirection(p),f++}else if(T.isRectAreaLight){const M=n.rectArea[g];M.position.setFromMatrixPosition(T.matrixWorld),M.position.applyMatrix4(p),a.identity(),r.copy(T.matrixWorld),r.premultiply(p),a.extractRotation(r),M.halfWidth.set(T.width*.5,0,0),M.halfHeight.set(0,T.height*.5,0),M.halfWidth.applyMatrix4(a),M.halfHeight.applyMatrix4(a),g++}else if(T.isPointLight){const M=n.point[d];M.position.setFromMatrixPosition(T.matrixWorld),M.position.applyMatrix4(p),d++}else if(T.isHemisphereLight){const M=n.hemi[x];M.direction.setFromMatrixPosition(T.matrixWorld),M.direction.transformDirection(p),x++}}}return{setup:o,setupView:l,state:n}}function Hh(s){const e=new Bv(s),t=[],n=[];function i(h){c.camera=h,t.length=0,n.length=0}function r(h){t.push(h)}function a(h){n.push(h)}function o(){e.setup(t)}function l(h){e.setupView(t,h)}const c={lightsArray:t,shadowsArray:n,camera:null,lights:e,transmissionRenderTarget:{}};return{init:i,state:c,setupLights:o,setupLightsView:l,pushLight:r,pushShadow:a}}function kv(s){let e=new WeakMap;function t(i,r=0){const a=e.get(i);let o;return a===void 0?(o=new Hh(s),e.set(i,[o])):r>=a.length?(o=new Hh(s),a.push(o)):o=a[r],o}function n(){e=new WeakMap}return{get:t,dispose:n}}const Vv=`void main() {
	gl_Position = vec4( position, 1.0 );
}`,zv=`uniform sampler2D shadow_pass;
uniform vec2 resolution;
uniform float radius;
void main() {
	const float samples = float( VSM_SAMPLES );
	float mean = 0.0;
	float squared_mean = 0.0;
	float uvStride = samples <= 1.0 ? 0.0 : 2.0 / ( samples - 1.0 );
	float uvStart = samples <= 1.0 ? 0.0 : - 1.0;
	for ( float i = 0.0; i < samples; i ++ ) {
		float uvOffset = uvStart + i * uvStride;
		#ifdef HORIZONTAL_PASS
			vec2 distribution = texture2D( shadow_pass, ( gl_FragCoord.xy + vec2( uvOffset, 0.0 ) * radius ) / resolution ).rg;
			mean += distribution.x;
			squared_mean += distribution.y * distribution.y + distribution.x * distribution.x;
		#else
			float depth = texture2D( shadow_pass, ( gl_FragCoord.xy + vec2( 0.0, uvOffset ) * radius ) / resolution ).r;
			mean += depth;
			squared_mean += depth * depth;
		#endif
	}
	mean = mean / samples;
	squared_mean = squared_mean / samples;
	float std_dev = sqrt( max( 0.0, squared_mean - mean * mean ) );
	gl_FragColor = vec4( mean, std_dev, 0.0, 1.0 );
}`,Hv=[new L(1,0,0),new L(-1,0,0),new L(0,1,0),new L(0,-1,0),new L(0,0,1),new L(0,0,-1)],Gv=[new L(0,-1,0),new L(0,-1,0),new L(0,0,1),new L(0,0,-1),new L(0,-1,0),new L(0,-1,0)],Gh=new Ve,Ws=new L,go=new L;function Wv(s,e,t){let n=new tc;const i=new Le,r=new Le,a=new mt,o=new Nu,l=new Rp,c={},h=t.maxTextureSize,u={[Zn]:qt,[qt]:Zn,[Pn]:Pn},d=new kt({defines:{VSM_SAMPLES:8},uniforms:{shadow_pass:{value:null},resolution:{value:new Le},radius:{value:4}},vertexShader:Vv,fragmentShader:zv}),f=d.clone();f.defines.HORIZONTAL_PASS=1;const g=new ln;g.setAttribute("position",new jt(new Float32Array([-1,-1,.5,3,-1,.5,-1,3,.5]),3));const x=new lt(g,d),p=this;this.enabled=!1,this.autoUpdate=!0,this.needsUpdate=!1,this.type=qr;let m=this.type;this.render=function(w,C,v){if(p.enabled===!1||p.autoUpdate===!1&&p.needsUpdate===!1||w.length===0)return;this.type===cu&&(Pe("WebGLShadowMap: PCFSoftShadowMap has been deprecated. Using PCFShadowMap instead."),this.type=qr);const b=s.getRenderTarget(),D=s.getActiveCubeFace(),R=s.getActiveMipmapLevel(),F=s.state;F.setBlending(Bt),F.buffers.depth.getReversed()===!0?F.buffers.color.setClear(0,0,0,0):F.buffers.color.setClear(1,1,1,1),F.buffers.depth.setTest(!0),F.setScissorTest(!1);const O=m!==this.type;O&&C.traverse(function(X){X.material&&(Array.isArray(X.material)?X.material.forEach(V=>V.needsUpdate=!0):X.material.needsUpdate=!0)});for(let X=0,V=w.length;X<V;X++){const k=w[X],U=k.shadow;if(U===void 0){Pe("WebGLShadowMap:",k,"has no shadow.");continue}if(U.autoUpdate===!1&&U.needsUpdate===!1)continue;i.copy(U.mapSize);const Q=U.getFrameExtents();i.multiply(Q),r.copy(U.mapSize),(i.x>h||i.y>h)&&(i.x>h&&(r.x=Math.floor(h/Q.x),i.x=r.x*Q.x,U.mapSize.x=r.x),i.y>h&&(r.y=Math.floor(h/Q.y),i.y=r.y*Q.y,U.mapSize.y=r.y));const K=s.state.buffers.depth.getReversed();if(U.camera._reversedDepth=K,U.map===null||O===!0){if(U.map!==null&&(U.map.depthTexture!==null&&(U.map.depthTexture.dispose(),U.map.depthTexture=null),U.map.dispose()),this.type===Ys){if(k.isPointLight){Pe("WebGLShadowMap: VSM shadow maps are not supported for PointLights. Use PCF or BasicShadowMap instead.");continue}U.map=new Jt(i.x,i.y,{format:xs,type:on,minFilter:Ct,magFilter:Ct,generateMipmaps:!1}),U.map.texture.name=k.name+".shadowMap",U.map.depthTexture=new ys(i.x,i.y,sn),U.map.depthTexture.name=k.name+".shadowMapDepth",U.map.depthTexture.format=Jn,U.map.depthTexture.compareFunction=null,U.map.depthTexture.minFilter=xt,U.map.depthTexture.magFilter=xt}else k.isPointLight?(U.map=new zu(i.x),U.map.depthTexture=new Sp(i.x,Fn)):(U.map=new Jt(i.x,i.y),U.map.depthTexture=new ys(i.x,i.y,Fn)),U.map.depthTexture.name=k.name+".shadowMap",U.map.depthTexture.format=Jn,this.type===qr?(U.map.depthTexture.compareFunction=K?ql:Yl,U.map.depthTexture.minFilter=Ct,U.map.depthTexture.magFilter=Ct):(U.map.depthTexture.compareFunction=null,U.map.depthTexture.minFilter=xt,U.map.depthTexture.magFilter=xt);U.camera.updateProjectionMatrix()}const se=U.map.isWebGLCubeRenderTarget?6:1;for(let he=0;he<se;he++){if(U.map.isWebGLCubeRenderTarget)s.setRenderTarget(U.map,he),s.clear();else{he===0&&(s.setRenderTarget(U.map),s.clear());const le=U.getViewport(he);a.set(r.x*le.x,r.y*le.y,r.x*le.z,r.y*le.w),F.viewport(a)}if(k.isPointLight){const le=U.camera,$=U.matrix,ce=k.distance||le.far;ce!==le.far&&(le.far=ce,le.updateProjectionMatrix()),Ws.setFromMatrixPosition(k.matrixWorld),le.position.copy(Ws),go.copy(le.position),go.add(Hv[he]),le.up.copy(Gv[he]),le.lookAt(go),le.updateMatrixWorld(),$.makeTranslation(-Ws.x,-Ws.y,-Ws.z),Gh.multiplyMatrices(le.projectionMatrix,le.matrixWorldInverse),U._frustum.setFromProjectionMatrix(Gh,le.coordinateSystem,le.reversedDepth)}else U.updateMatrices(k);n=U.getFrustum(),M(C,v,U.camera,k,this.type)}U.isPointLightShadow!==!0&&this.type===Ys&&S(U,v),U.needsUpdate=!1}m=this.type,p.needsUpdate=!1,s.setRenderTarget(b,D,R)};function S(w,C){const v=e.update(x);d.defines.VSM_SAMPLES!==w.blurSamples&&(d.defines.VSM_SAMPLES=w.blurSamples,f.defines.VSM_SAMPLES=w.blurSamples,d.needsUpdate=!0,f.needsUpdate=!0),w.mapPass===null&&(w.mapPass=new Jt(i.x,i.y,{format:xs,type:on})),d.uniforms.shadow_pass.value=w.map.depthTexture,d.uniforms.resolution.value=w.mapSize,d.uniforms.radius.value=w.radius,s.setRenderTarget(w.mapPass),s.clear(),s.renderBufferDirect(C,null,v,d,x,null),f.uniforms.shadow_pass.value=w.mapPass.texture,f.uniforms.resolution.value=w.mapSize,f.uniforms.radius.value=w.radius,s.setRenderTarget(w.map),s.clear(),s.renderBufferDirect(C,null,v,f,x,null)}function T(w,C,v,b){let D=null;const R=v.isPointLight===!0?w.customDistanceMaterial:w.customDepthMaterial;if(R!==void 0)D=R;else if(D=v.isPointLight===!0?l:o,s.localClippingEnabled&&C.clipShadows===!0&&Array.isArray(C.clippingPlanes)&&C.clippingPlanes.length!==0||C.displacementMap&&C.displacementScale!==0||C.alphaMap&&C.alphaTest>0||C.map&&C.alphaTest>0||C.alphaToCoverage===!0){const F=D.uuid,O=C.uuid;let X=c[F];X===void 0&&(X={},c[F]=X);let V=X[O];V===void 0&&(V=D.clone(),X[O]=V,C.addEventListener("dispose",E)),D=V}if(D.visible=C.visible,D.wireframe=C.wireframe,b===Ys?D.side=C.shadowSide!==null?C.shadowSide:C.side:D.side=C.shadowSide!==null?C.shadowSide:u[C.side],D.alphaMap=C.alphaMap,D.alphaTest=C.alphaToCoverage===!0?.5:C.alphaTest,D.map=C.map,D.clipShadows=C.clipShadows,D.clippingPlanes=C.clippingPlanes,D.clipIntersection=C.clipIntersection,D.displacementMap=C.displacementMap,D.displacementScale=C.displacementScale,D.displacementBias=C.displacementBias,D.wireframeLinewidth=C.wireframeLinewidth,D.linewidth=C.linewidth,v.isPointLight===!0&&D.isMeshDistanceMaterial===!0){const F=s.properties.get(D);F.light=v}return D}function M(w,C,v,b,D){if(w.visible===!1)return;if(w.layers.test(C.layers)&&(w.isMesh||w.isLine||w.isPoints)&&(w.castShadow||w.receiveShadow&&D===Ys)&&(!w.frustumCulled||n.intersectsObject(w))){w.modelViewMatrix.multiplyMatrices(v.matrixWorldInverse,w.matrixWorld);const O=e.update(w),X=w.material;if(Array.isArray(X)){const V=O.groups;for(let k=0,U=V.length;k<U;k++){const Q=V[k],K=X[Q.materialIndex];if(K&&K.visible){const se=T(w,K,b,D);w.onBeforeShadow(s,w,C,v,O,se,Q),s.renderBufferDirect(v,null,O,se,w,Q),w.onAfterShadow(s,w,C,v,O,se,Q)}}}else if(X.visible){const V=T(w,X,b,D);w.onBeforeShadow(s,w,C,v,O,V,null),s.renderBufferDirect(v,null,O,V,w,null),w.onAfterShadow(s,w,C,v,O,V,null)}}const F=w.children;for(let O=0,X=F.length;O<X;O++)M(F[O],C,v,b,D)}function E(w){w.target.removeEventListener("dispose",E);for(const v in c){const b=c[v],D=w.target.uuid;D in b&&(b[D].dispose(),delete b[D])}}}function Xv(s,e){function t(){let I=!1;const oe=new mt;let ne=null;const xe=new mt(0,0,0,0);return{setMask:function(ie){ne!==ie&&!I&&(s.colorMask(ie,ie,ie,ie),ne=ie)},setLocked:function(ie){I=ie},setClear:function(ie,q,be,Be,dt){dt===!0&&(ie*=Be,q*=Be,be*=Be),oe.set(ie,q,be,Be),xe.equals(oe)===!1&&(s.clearColor(ie,q,be,Be),xe.copy(oe))},reset:function(){I=!1,ne=null,xe.set(-1,0,0,0)}}}function n(){let I=!1,oe=!1,ne=null,xe=null,ie=null;return{setReversed:function(q){if(oe!==q){const be=e.get("EXT_clip_control");q?be.clipControlEXT(be.LOWER_LEFT_EXT,be.ZERO_TO_ONE_EXT):be.clipControlEXT(be.LOWER_LEFT_EXT,be.NEGATIVE_ONE_TO_ONE_EXT),oe=q;const Be=ie;ie=null,this.setClear(Be)}},getReversed:function(){return oe},setTest:function(q){q?Z(s.DEPTH_TEST):ee(s.DEPTH_TEST)},setMask:function(q){ne!==q&&!I&&(s.depthMask(q),ne=q)},setFunc:function(q){if(oe&&(q=Pf[q]),xe!==q){switch(q){case Do:s.depthFunc(s.NEVER);break;case Lo:s.depthFunc(s.ALWAYS);break;case Io:s.depthFunc(s.LESS);break;case gs:s.depthFunc(s.LEQUAL);break;case No:s.depthFunc(s.EQUAL);break;case Uo:s.depthFunc(s.GEQUAL);break;case Fo:s.depthFunc(s.GREATER);break;case Oo:s.depthFunc(s.NOTEQUAL);break;default:s.depthFunc(s.LEQUAL)}xe=q}},setLocked:function(q){I=q},setClear:function(q){ie!==q&&(ie=q,oe&&(q=1-q),s.clearDepth(q))},reset:function(){I=!1,ne=null,xe=null,ie=null,oe=!1}}}function i(){let I=!1,oe=null,ne=null,xe=null,ie=null,q=null,be=null,Be=null,dt=null;return{setTest:function(nt){I||(nt?Z(s.STENCIL_TEST):ee(s.STENCIL_TEST))},setMask:function(nt){oe!==nt&&!I&&(s.stencilMask(nt),oe=nt)},setFunc:function(nt,kn,Vn){(ne!==nt||xe!==kn||ie!==Vn)&&(s.stencilFunc(nt,kn,Vn),ne=nt,xe=kn,ie=Vn)},setOp:function(nt,kn,Vn){(q!==nt||be!==kn||Be!==Vn)&&(s.stencilOp(nt,kn,Vn),q=nt,be=kn,Be=Vn)},setLocked:function(nt){I=nt},setClear:function(nt){dt!==nt&&(s.clearStencil(nt),dt=nt)},reset:function(){I=!1,oe=null,ne=null,xe=null,ie=null,q=null,be=null,Be=null,dt=null}}}const r=new t,a=new n,o=new i,l=new WeakMap,c=new WeakMap;let h={},u={},d=new WeakMap,f=[],g=null,x=!1,p=null,m=null,S=null,T=null,M=null,E=null,w=null,C=new Ie(0,0,0),v=0,b=!1,D=null,R=null,F=null,O=null,X=null;const V=s.getParameter(s.MAX_COMBINED_TEXTURE_IMAGE_UNITS);let k=!1,U=0;const Q=s.getParameter(s.VERSION);Q.indexOf("WebGL")!==-1?(U=parseFloat(/^WebGL (\d)/.exec(Q)[1]),k=U>=1):Q.indexOf("OpenGL ES")!==-1&&(U=parseFloat(/^OpenGL ES (\d)/.exec(Q)[1]),k=U>=2);let K=null,se={};const he=s.getParameter(s.SCISSOR_BOX),le=s.getParameter(s.VIEWPORT),$=new mt().fromArray(he),ce=new mt().fromArray(le);function Re(I,oe,ne,xe){const ie=new Uint8Array(4),q=s.createTexture();s.bindTexture(I,q),s.texParameteri(I,s.TEXTURE_MIN_FILTER,s.NEAREST),s.texParameteri(I,s.TEXTURE_MAG_FILTER,s.NEAREST);for(let be=0;be<ne;be++)I===s.TEXTURE_3D||I===s.TEXTURE_2D_ARRAY?s.texImage3D(oe,0,s.RGBA,1,1,xe,0,s.RGBA,s.UNSIGNED_BYTE,ie):s.texImage2D(oe+be,0,s.RGBA,1,1,0,s.RGBA,s.UNSIGNED_BYTE,ie);return q}const G={};G[s.TEXTURE_2D]=Re(s.TEXTURE_2D,s.TEXTURE_2D,1),G[s.TEXTURE_CUBE_MAP]=Re(s.TEXTURE_CUBE_MAP,s.TEXTURE_CUBE_MAP_POSITIVE_X,6),G[s.TEXTURE_2D_ARRAY]=Re(s.TEXTURE_2D_ARRAY,s.TEXTURE_2D_ARRAY,1,1),G[s.TEXTURE_3D]=Re(s.TEXTURE_3D,s.TEXTURE_3D,1,1),r.setClear(0,0,0,1),a.setClear(1),o.setClear(0),Z(s.DEPTH_TEST),a.setFunc(gs),ke(!1),pt(Tc),Z(s.CULL_FACE),Ze(Bt);function Z(I){h[I]!==!0&&(s.enable(I),h[I]=!0)}function ee(I){h[I]!==!1&&(s.disable(I),h[I]=!1)}function we(I,oe){return u[I]!==oe?(s.bindFramebuffer(I,oe),u[I]=oe,I===s.DRAW_FRAMEBUFFER&&(u[s.FRAMEBUFFER]=oe),I===s.FRAMEBUFFER&&(u[s.DRAW_FRAMEBUFFER]=oe),!0):!1}function ve(I,oe){let ne=f,xe=!1;if(I){ne=d.get(oe),ne===void 0&&(ne=[],d.set(oe,ne));const ie=I.textures;if(ne.length!==ie.length||ne[0]!==s.COLOR_ATTACHMENT0){for(let q=0,be=ie.length;q<be;q++)ne[q]=s.COLOR_ATTACHMENT0+q;ne.length=ie.length,xe=!0}}else ne[0]!==s.BACK&&(ne[0]=s.BACK,xe=!0);xe&&s.drawBuffers(ne)}function Fe(I){return g!==I?(s.useProgram(I),g=I,!0):!1}const Mt={[qn]:s.FUNC_ADD,[$d]:s.FUNC_SUBTRACT,[Zd]:s.FUNC_REVERSE_SUBTRACT};Mt[Jd]=s.MIN,Mt[Qd]=s.MAX;const qe={[Ro]:s.ZERO,[ef]:s.ONE,[tf]:s.SRC_COLOR,[Co]:s.SRC_ALPHA,[af]:s.SRC_ALPHA_SATURATE,[du]:s.DST_COLOR,[uu]:s.DST_ALPHA,[nf]:s.ONE_MINUS_SRC_COLOR,[Po]:s.ONE_MINUS_SRC_ALPHA,[rf]:s.ONE_MINUS_DST_COLOR,[sf]:s.ONE_MINUS_DST_ALPHA,[of]:s.CONSTANT_COLOR,[lf]:s.ONE_MINUS_CONSTANT_COLOR,[cf]:s.CONSTANT_ALPHA,[hf]:s.ONE_MINUS_CONSTANT_ALPHA};function Ze(I,oe,ne,xe,ie,q,be,Be,dt,nt){if(I===Bt){x===!0&&(ee(s.BLEND),x=!1);return}if(x===!1&&(Z(s.BLEND),x=!0),I!==hu){if(I!==p||nt!==b){if((m!==qn||M!==qn)&&(s.blendEquation(s.FUNC_ADD),m=qn,M=qn),nt)switch(I){case cs:s.blendFuncSeparate(s.ONE,s.ONE_MINUS_SRC_ALPHA,s.ONE,s.ONE_MINUS_SRC_ALPHA);break;case Ac:s.blendFunc(s.ONE,s.ONE);break;case wc:s.blendFuncSeparate(s.ZERO,s.ONE_MINUS_SRC_COLOR,s.ZERO,s.ONE);break;case Rc:s.blendFuncSeparate(s.DST_COLOR,s.ONE_MINUS_SRC_ALPHA,s.ZERO,s.ONE);break;default:Ue("WebGLState: Invalid blending: ",I);break}else switch(I){case cs:s.blendFuncSeparate(s.SRC_ALPHA,s.ONE_MINUS_SRC_ALPHA,s.ONE,s.ONE_MINUS_SRC_ALPHA);break;case Ac:s.blendFuncSeparate(s.SRC_ALPHA,s.ONE,s.ONE,s.ONE);break;case wc:Ue("WebGLState: SubtractiveBlending requires material.premultipliedAlpha = true");break;case Rc:Ue("WebGLState: MultiplyBlending requires material.premultipliedAlpha = true");break;default:Ue("WebGLState: Invalid blending: ",I);break}S=null,T=null,E=null,w=null,C.set(0,0,0),v=0,p=I,b=nt}return}ie=ie||oe,q=q||ne,be=be||xe,(oe!==m||ie!==M)&&(s.blendEquationSeparate(Mt[oe],Mt[ie]),m=oe,M=ie),(ne!==S||xe!==T||q!==E||be!==w)&&(s.blendFuncSeparate(qe[ne],qe[xe],qe[q],qe[be]),S=ne,T=xe,E=q,w=be),(Be.equals(C)===!1||dt!==v)&&(s.blendColor(Be.r,Be.g,Be.b,dt),C.copy(Be),v=dt),p=I,b=!1}function Qe(I,oe){I.side===Pn?ee(s.CULL_FACE):Z(s.CULL_FACE);let ne=I.side===qt;oe&&(ne=!ne),ke(ne),I.blending===cs&&I.transparent===!1?Ze(Bt):Ze(I.blending,I.blendEquation,I.blendSrc,I.blendDst,I.blendEquationAlpha,I.blendSrcAlpha,I.blendDstAlpha,I.blendColor,I.blendAlpha,I.premultipliedAlpha),a.setFunc(I.depthFunc),a.setTest(I.depthTest),a.setMask(I.depthWrite),r.setMask(I.colorWrite);const xe=I.stencilWrite;o.setTest(xe),xe&&(o.setMask(I.stencilWriteMask),o.setFunc(I.stencilFunc,I.stencilRef,I.stencilFuncMask),o.setOp(I.stencilFail,I.stencilZFail,I.stencilZPass)),gt(I.polygonOffset,I.polygonOffsetFactor,I.polygonOffsetUnits),I.alphaToCoverage===!0?Z(s.SAMPLE_ALPHA_TO_COVERAGE):ee(s.SAMPLE_ALPHA_TO_COVERAGE)}function ke(I){D!==I&&(I?s.frontFace(s.CW):s.frontFace(s.CCW),D=I)}function pt(I){I!==jd?(Z(s.CULL_FACE),I!==R&&(I===Tc?s.cullFace(s.BACK):I===Kd?s.cullFace(s.FRONT):s.cullFace(s.FRONT_AND_BACK))):ee(s.CULL_FACE),R=I}function P(I){I!==F&&(k&&s.lineWidth(I),F=I)}function gt(I,oe,ne){I?(Z(s.POLYGON_OFFSET_FILL),(O!==oe||X!==ne)&&(O=oe,X=ne,a.getReversed()&&(oe=-oe),s.polygonOffset(oe,ne))):ee(s.POLYGON_OFFSET_FILL)}function $e(I){I?Z(s.SCISSOR_TEST):ee(s.SCISSOR_TEST)}function et(I){I===void 0&&(I=s.TEXTURE0+V-1),K!==I&&(s.activeTexture(I),K=I)}function Me(I,oe,ne){ne===void 0&&(K===null?ne=s.TEXTURE0+V-1:ne=K);let xe=se[ne];xe===void 0&&(xe={type:void 0,texture:void 0},se[ne]=xe),(xe.type!==I||xe.texture!==oe)&&(K!==ne&&(s.activeTexture(ne),K=ne),s.bindTexture(I,oe||G[I]),xe.type=I,xe.texture=oe)}function A(){const I=se[K];I!==void 0&&I.type!==void 0&&(s.bindTexture(I.type,null),I.type=void 0,I.texture=void 0)}function _(){try{s.compressedTexImage2D(...arguments)}catch(I){Ue("WebGLState:",I)}}function N(){try{s.compressedTexImage3D(...arguments)}catch(I){Ue("WebGLState:",I)}}function j(){try{s.texSubImage2D(...arguments)}catch(I){Ue("WebGLState:",I)}}function J(){try{s.texSubImage3D(...arguments)}catch(I){Ue("WebGLState:",I)}}function Y(){try{s.compressedTexSubImage2D(...arguments)}catch(I){Ue("WebGLState:",I)}}function ge(){try{s.compressedTexSubImage3D(...arguments)}catch(I){Ue("WebGLState:",I)}}function re(){try{s.texStorage2D(...arguments)}catch(I){Ue("WebGLState:",I)}}function Ee(){try{s.texStorage3D(...arguments)}catch(I){Ue("WebGLState:",I)}}function Ne(){try{s.texImage2D(...arguments)}catch(I){Ue("WebGLState:",I)}}function te(){try{s.texImage3D(...arguments)}catch(I){Ue("WebGLState:",I)}}function ae(I){$.equals(I)===!1&&(s.scissor(I.x,I.y,I.z,I.w),$.copy(I))}function ye(I){ce.equals(I)===!1&&(s.viewport(I.x,I.y,I.z,I.w),ce.copy(I))}function Se(I,oe){let ne=c.get(oe);ne===void 0&&(ne=new WeakMap,c.set(oe,ne));let xe=ne.get(I);xe===void 0&&(xe=s.getUniformBlockIndex(oe,I.name),ne.set(I,xe))}function fe(I,oe){const xe=c.get(oe).get(I);l.get(oe)!==xe&&(s.uniformBlockBinding(oe,xe,I.__bindingPointIndex),l.set(oe,xe))}function Oe(){s.disable(s.BLEND),s.disable(s.CULL_FACE),s.disable(s.DEPTH_TEST),s.disable(s.POLYGON_OFFSET_FILL),s.disable(s.SCISSOR_TEST),s.disable(s.STENCIL_TEST),s.disable(s.SAMPLE_ALPHA_TO_COVERAGE),s.blendEquation(s.FUNC_ADD),s.blendFunc(s.ONE,s.ZERO),s.blendFuncSeparate(s.ONE,s.ZERO,s.ONE,s.ZERO),s.blendColor(0,0,0,0),s.colorMask(!0,!0,!0,!0),s.clearColor(0,0,0,0),s.depthMask(!0),s.depthFunc(s.LESS),a.setReversed(!1),s.clearDepth(1),s.stencilMask(4294967295),s.stencilFunc(s.ALWAYS,0,4294967295),s.stencilOp(s.KEEP,s.KEEP,s.KEEP),s.clearStencil(0),s.cullFace(s.BACK),s.frontFace(s.CCW),s.polygonOffset(0,0),s.activeTexture(s.TEXTURE0),s.bindFramebuffer(s.FRAMEBUFFER,null),s.bindFramebuffer(s.DRAW_FRAMEBUFFER,null),s.bindFramebuffer(s.READ_FRAMEBUFFER,null),s.useProgram(null),s.lineWidth(1),s.scissor(0,0,s.canvas.width,s.canvas.height),s.viewport(0,0,s.canvas.width,s.canvas.height),h={},K=null,se={},u={},d=new WeakMap,f=[],g=null,x=!1,p=null,m=null,S=null,T=null,M=null,E=null,w=null,C=new Ie(0,0,0),v=0,b=!1,D=null,R=null,F=null,O=null,X=null,$.set(0,0,s.canvas.width,s.canvas.height),ce.set(0,0,s.canvas.width,s.canvas.height),r.reset(),a.reset(),o.reset()}return{buffers:{color:r,depth:a,stencil:o},enable:Z,disable:ee,bindFramebuffer:we,drawBuffers:ve,useProgram:Fe,setBlending:Ze,setMaterial:Qe,setFlipSided:ke,setCullFace:pt,setLineWidth:P,setPolygonOffset:gt,setScissorTest:$e,activeTexture:et,bindTexture:Me,unbindTexture:A,compressedTexImage2D:_,compressedTexImage3D:N,texImage2D:Ne,texImage3D:te,updateUBOMapping:Se,uniformBlockBinding:fe,texStorage2D:re,texStorage3D:Ee,texSubImage2D:j,texSubImage3D:J,compressedTexSubImage2D:Y,compressedTexSubImage3D:ge,scissor:ae,viewport:ye,reset:Oe}}function Yv(s,e,t,n,i,r,a){const o=e.has("WEBGL_multisampled_render_to_texture")?e.get("WEBGL_multisampled_render_to_texture"):null,l=typeof navigator>"u"?!1:/OculusBrowser/g.test(navigator.userAgent),c=new Le,h=new WeakMap;let u;const d=new WeakMap;let f=!1;try{f=typeof OffscreenCanvas<"u"&&new OffscreenCanvas(1,1).getContext("2d")!==null}catch{}function g(A,_){return f?new OffscreenCanvas(A,_):ir("canvas")}function x(A,_,N){let j=1;const J=Me(A);if((J.width>N||J.height>N)&&(j=N/Math.max(J.width,J.height)),j<1)if(typeof HTMLImageElement<"u"&&A instanceof HTMLImageElement||typeof HTMLCanvasElement<"u"&&A instanceof HTMLCanvasElement||typeof ImageBitmap<"u"&&A instanceof ImageBitmap||typeof VideoFrame<"u"&&A instanceof VideoFrame){const Y=Math.floor(j*J.width),ge=Math.floor(j*J.height);u===void 0&&(u=g(Y,ge));const re=_?g(Y,ge):u;return re.width=Y,re.height=ge,re.getContext("2d").drawImage(A,0,0,Y,ge),Pe("WebGLRenderer: Texture has been resized from ("+J.width+"x"+J.height+") to ("+Y+"x"+ge+")."),re}else return"data"in A&&Pe("WebGLRenderer: Image in DataTexture is too big ("+J.width+"x"+J.height+")."),A;return A}function p(A){return A.generateMipmaps}function m(A){s.generateMipmap(A)}function S(A){return A.isWebGLCubeRenderTarget?s.TEXTURE_CUBE_MAP:A.isWebGL3DRenderTarget?s.TEXTURE_3D:A.isWebGLArrayRenderTarget||A.isCompressedArrayTexture?s.TEXTURE_2D_ARRAY:s.TEXTURE_2D}function T(A,_,N,j,J=!1){if(A!==null){if(s[A]!==void 0)return s[A];Pe("WebGLRenderer: Attempt to use non-existing WebGL internal format '"+A+"'")}let Y=_;if(_===s.RED&&(N===s.FLOAT&&(Y=s.R32F),N===s.HALF_FLOAT&&(Y=s.R16F),N===s.UNSIGNED_BYTE&&(Y=s.R8)),_===s.RED_INTEGER&&(N===s.UNSIGNED_BYTE&&(Y=s.R8UI),N===s.UNSIGNED_SHORT&&(Y=s.R16UI),N===s.UNSIGNED_INT&&(Y=s.R32UI),N===s.BYTE&&(Y=s.R8I),N===s.SHORT&&(Y=s.R16I),N===s.INT&&(Y=s.R32I)),_===s.RG&&(N===s.FLOAT&&(Y=s.RG32F),N===s.HALF_FLOAT&&(Y=s.RG16F),N===s.UNSIGNED_BYTE&&(Y=s.RG8)),_===s.RG_INTEGER&&(N===s.UNSIGNED_BYTE&&(Y=s.RG8UI),N===s.UNSIGNED_SHORT&&(Y=s.RG16UI),N===s.UNSIGNED_INT&&(Y=s.RG32UI),N===s.BYTE&&(Y=s.RG8I),N===s.SHORT&&(Y=s.RG16I),N===s.INT&&(Y=s.RG32I)),_===s.RGB_INTEGER&&(N===s.UNSIGNED_BYTE&&(Y=s.RGB8UI),N===s.UNSIGNED_SHORT&&(Y=s.RGB16UI),N===s.UNSIGNED_INT&&(Y=s.RGB32UI),N===s.BYTE&&(Y=s.RGB8I),N===s.SHORT&&(Y=s.RGB16I),N===s.INT&&(Y=s.RGB32I)),_===s.RGBA_INTEGER&&(N===s.UNSIGNED_BYTE&&(Y=s.RGBA8UI),N===s.UNSIGNED_SHORT&&(Y=s.RGBA16UI),N===s.UNSIGNED_INT&&(Y=s.RGBA32UI),N===s.BYTE&&(Y=s.RGBA8I),N===s.SHORT&&(Y=s.RGBA16I),N===s.INT&&(Y=s.RGBA32I)),_===s.RGB&&(N===s.UNSIGNED_INT_5_9_9_9_REV&&(Y=s.RGB9_E5),N===s.UNSIGNED_INT_10F_11F_11F_REV&&(Y=s.R11F_G11F_B10F)),_===s.RGBA){const ge=J?ia:Ke.getTransfer(j);N===s.FLOAT&&(Y=s.RGBA32F),N===s.HALF_FLOAT&&(Y=s.RGBA16F),N===s.UNSIGNED_BYTE&&(Y=ge===tt?s.SRGB8_ALPHA8:s.RGBA8),N===s.UNSIGNED_SHORT_4_4_4_4&&(Y=s.RGBA4),N===s.UNSIGNED_SHORT_5_5_5_1&&(Y=s.RGB5_A1)}return(Y===s.R16F||Y===s.R32F||Y===s.RG16F||Y===s.RG32F||Y===s.RGBA16F||Y===s.RGBA32F)&&e.get("EXT_color_buffer_float"),Y}function M(A,_){let N;return A?_===null||_===Fn||_===vs?N=s.DEPTH24_STENCIL8:_===sn?N=s.DEPTH32F_STENCIL8:_===Qs&&(N=s.DEPTH24_STENCIL8,Pe("DepthTexture: 16 bit depth attachment is not supported with stencil. Using 24-bit attachment.")):_===null||_===Fn||_===vs?N=s.DEPTH_COMPONENT24:_===sn?N=s.DEPTH_COMPONENT32F:_===Qs&&(N=s.DEPTH_COMPONENT16),N}function E(A,_){return p(A)===!0||A.isFramebufferTexture&&A.minFilter!==xt&&A.minFilter!==Ct?Math.log2(Math.max(_.width,_.height))+1:A.mipmaps!==void 0&&A.mipmaps.length>0?A.mipmaps.length:A.isCompressedTexture&&Array.isArray(A.image)?_.mipmaps.length:1}function w(A){const _=A.target;_.removeEventListener("dispose",w),v(_),_.isVideoTexture&&h.delete(_)}function C(A){const _=A.target;_.removeEventListener("dispose",C),D(_)}function v(A){const _=n.get(A);if(_.__webglInit===void 0)return;const N=A.source,j=d.get(N);if(j){const J=j[_.__cacheKey];J.usedTimes--,J.usedTimes===0&&b(A),Object.keys(j).length===0&&d.delete(N)}n.remove(A)}function b(A){const _=n.get(A);s.deleteTexture(_.__webglTexture);const N=A.source,j=d.get(N);delete j[_.__cacheKey],a.memory.textures--}function D(A){const _=n.get(A);if(A.depthTexture&&(A.depthTexture.dispose(),n.remove(A.depthTexture)),A.isWebGLCubeRenderTarget)for(let j=0;j<6;j++){if(Array.isArray(_.__webglFramebuffer[j]))for(let J=0;J<_.__webglFramebuffer[j].length;J++)s.deleteFramebuffer(_.__webglFramebuffer[j][J]);else s.deleteFramebuffer(_.__webglFramebuffer[j]);_.__webglDepthbuffer&&s.deleteRenderbuffer(_.__webglDepthbuffer[j])}else{if(Array.isArray(_.__webglFramebuffer))for(let j=0;j<_.__webglFramebuffer.length;j++)s.deleteFramebuffer(_.__webglFramebuffer[j]);else s.deleteFramebuffer(_.__webglFramebuffer);if(_.__webglDepthbuffer&&s.deleteRenderbuffer(_.__webglDepthbuffer),_.__webglMultisampledFramebuffer&&s.deleteFramebuffer(_.__webglMultisampledFramebuffer),_.__webglColorRenderbuffer)for(let j=0;j<_.__webglColorRenderbuffer.length;j++)_.__webglColorRenderbuffer[j]&&s.deleteRenderbuffer(_.__webglColorRenderbuffer[j]);_.__webglDepthRenderbuffer&&s.deleteRenderbuffer(_.__webglDepthRenderbuffer)}const N=A.textures;for(let j=0,J=N.length;j<J;j++){const Y=n.get(N[j]);Y.__webglTexture&&(s.deleteTexture(Y.__webglTexture),a.memory.textures--),n.remove(N[j])}n.remove(A)}let R=0;function F(){R=0}function O(){const A=R;return A>=i.maxTextures&&Pe("WebGLTextures: Trying to use "+A+" texture units while this GPU supports only "+i.maxTextures),R+=1,A}function X(A){const _=[];return _.push(A.wrapS),_.push(A.wrapT),_.push(A.wrapR||0),_.push(A.magFilter),_.push(A.minFilter),_.push(A.anisotropy),_.push(A.internalFormat),_.push(A.format),_.push(A.type),_.push(A.generateMipmaps),_.push(A.premultiplyAlpha),_.push(A.flipY),_.push(A.unpackAlignment),_.push(A.colorSpace),_.join()}function V(A,_){const N=n.get(A);if(A.isVideoTexture&&$e(A),A.isRenderTargetTexture===!1&&A.isExternalTexture!==!0&&A.version>0&&N.__version!==A.version){const j=A.image;if(j===null)Pe("WebGLRenderer: Texture marked for update but no image data found.");else if(j.complete===!1)Pe("WebGLRenderer: Texture marked for update but image is incomplete");else{G(N,A,_);return}}else A.isExternalTexture&&(N.__webglTexture=A.sourceTexture?A.sourceTexture:null);t.bindTexture(s.TEXTURE_2D,N.__webglTexture,s.TEXTURE0+_)}function k(A,_){const N=n.get(A);if(A.isRenderTargetTexture===!1&&A.version>0&&N.__version!==A.version){G(N,A,_);return}else A.isExternalTexture&&(N.__webglTexture=A.sourceTexture?A.sourceTexture:null);t.bindTexture(s.TEXTURE_2D_ARRAY,N.__webglTexture,s.TEXTURE0+_)}function U(A,_){const N=n.get(A);if(A.isRenderTargetTexture===!1&&A.version>0&&N.__version!==A.version){G(N,A,_);return}t.bindTexture(s.TEXTURE_3D,N.__webglTexture,s.TEXTURE0+_)}function Q(A,_){const N=n.get(A);if(A.isCubeDepthTexture!==!0&&A.version>0&&N.__version!==A.version){Z(N,A,_);return}t.bindTexture(s.TEXTURE_CUBE_MAP,N.__webglTexture,s.TEXTURE0+_)}const K={[vi]:s.REPEAT,[Dn]:s.CLAMP_TO_EDGE,[na]:s.MIRRORED_REPEAT},se={[xt]:s.NEAREST,[pu]:s.NEAREST_MIPMAP_NEAREST,[qs]:s.NEAREST_MIPMAP_LINEAR,[Ct]:s.LINEAR,[jr]:s.LINEAR_MIPMAP_NEAREST,[jn]:s.LINEAR_MIPMAP_LINEAR},he={[xf]:s.NEVER,[Ef]:s.ALWAYS,[Mf]:s.LESS,[Yl]:s.LEQUAL,[yf]:s.EQUAL,[ql]:s.GEQUAL,[Sf]:s.GREATER,[bf]:s.NOTEQUAL};function le(A,_){if(_.type===sn&&e.has("OES_texture_float_linear")===!1&&(_.magFilter===Ct||_.magFilter===jr||_.magFilter===qs||_.magFilter===jn||_.minFilter===Ct||_.minFilter===jr||_.minFilter===qs||_.minFilter===jn)&&Pe("WebGLRenderer: Unable to use linear filtering with floating point textures. OES_texture_float_linear not supported on this device."),s.texParameteri(A,s.TEXTURE_WRAP_S,K[_.wrapS]),s.texParameteri(A,s.TEXTURE_WRAP_T,K[_.wrapT]),(A===s.TEXTURE_3D||A===s.TEXTURE_2D_ARRAY)&&s.texParameteri(A,s.TEXTURE_WRAP_R,K[_.wrapR]),s.texParameteri(A,s.TEXTURE_MAG_FILTER,se[_.magFilter]),s.texParameteri(A,s.TEXTURE_MIN_FILTER,se[_.minFilter]),_.compareFunction&&(s.texParameteri(A,s.TEXTURE_COMPARE_MODE,s.COMPARE_REF_TO_TEXTURE),s.texParameteri(A,s.TEXTURE_COMPARE_FUNC,he[_.compareFunction])),e.has("EXT_texture_filter_anisotropic")===!0){if(_.magFilter===xt||_.minFilter!==qs&&_.minFilter!==jn||_.type===sn&&e.has("OES_texture_float_linear")===!1)return;if(_.anisotropy>1||n.get(_).__currentAnisotropy){const N=e.get("EXT_texture_filter_anisotropic");s.texParameterf(A,N.TEXTURE_MAX_ANISOTROPY_EXT,Math.min(_.anisotropy,i.getMaxAnisotropy())),n.get(_).__currentAnisotropy=_.anisotropy}}}function $(A,_){let N=!1;A.__webglInit===void 0&&(A.__webglInit=!0,_.addEventListener("dispose",w));const j=_.source;let J=d.get(j);J===void 0&&(J={},d.set(j,J));const Y=X(_);if(Y!==A.__cacheKey){J[Y]===void 0&&(J[Y]={texture:s.createTexture(),usedTimes:0},a.memory.textures++,N=!0),J[Y].usedTimes++;const ge=J[A.__cacheKey];ge!==void 0&&(J[A.__cacheKey].usedTimes--,ge.usedTimes===0&&b(_)),A.__cacheKey=Y,A.__webglTexture=J[Y].texture}return N}function ce(A,_,N){return Math.floor(Math.floor(A/N)/_)}function Re(A,_,N,j){const Y=A.updateRanges;if(Y.length===0)t.texSubImage2D(s.TEXTURE_2D,0,0,0,_.width,_.height,N,j,_.data);else{Y.sort((te,ae)=>te.start-ae.start);let ge=0;for(let te=1;te<Y.length;te++){const ae=Y[ge],ye=Y[te],Se=ae.start+ae.count,fe=ce(ye.start,_.width,4),Oe=ce(ae.start,_.width,4);ye.start<=Se+1&&fe===Oe&&ce(ye.start+ye.count-1,_.width,4)===fe?ae.count=Math.max(ae.count,ye.start+ye.count-ae.start):(++ge,Y[ge]=ye)}Y.length=ge+1;const re=s.getParameter(s.UNPACK_ROW_LENGTH),Ee=s.getParameter(s.UNPACK_SKIP_PIXELS),Ne=s.getParameter(s.UNPACK_SKIP_ROWS);s.pixelStorei(s.UNPACK_ROW_LENGTH,_.width);for(let te=0,ae=Y.length;te<ae;te++){const ye=Y[te],Se=Math.floor(ye.start/4),fe=Math.ceil(ye.count/4),Oe=Se%_.width,I=Math.floor(Se/_.width),oe=fe,ne=1;s.pixelStorei(s.UNPACK_SKIP_PIXELS,Oe),s.pixelStorei(s.UNPACK_SKIP_ROWS,I),t.texSubImage2D(s.TEXTURE_2D,0,Oe,I,oe,ne,N,j,_.data)}A.clearUpdateRanges(),s.pixelStorei(s.UNPACK_ROW_LENGTH,re),s.pixelStorei(s.UNPACK_SKIP_PIXELS,Ee),s.pixelStorei(s.UNPACK_SKIP_ROWS,Ne)}}function G(A,_,N){let j=s.TEXTURE_2D;(_.isDataArrayTexture||_.isCompressedArrayTexture)&&(j=s.TEXTURE_2D_ARRAY),_.isData3DTexture&&(j=s.TEXTURE_3D);const J=$(A,_),Y=_.source;t.bindTexture(j,A.__webglTexture,s.TEXTURE0+N);const ge=n.get(Y);if(Y.version!==ge.__version||J===!0){t.activeTexture(s.TEXTURE0+N);const re=Ke.getPrimaries(Ke.workingColorSpace),Ee=_.colorSpace===di?null:Ke.getPrimaries(_.colorSpace),Ne=_.colorSpace===di||re===Ee?s.NONE:s.BROWSER_DEFAULT_WEBGL;s.pixelStorei(s.UNPACK_FLIP_Y_WEBGL,_.flipY),s.pixelStorei(s.UNPACK_PREMULTIPLY_ALPHA_WEBGL,_.premultiplyAlpha),s.pixelStorei(s.UNPACK_ALIGNMENT,_.unpackAlignment),s.pixelStorei(s.UNPACK_COLORSPACE_CONVERSION_WEBGL,Ne);let te=x(_.image,!1,i.maxTextureSize);te=et(_,te);const ae=r.convert(_.format,_.colorSpace),ye=r.convert(_.type);let Se=T(_.internalFormat,ae,ye,_.colorSpace,_.isVideoTexture);le(j,_);let fe;const Oe=_.mipmaps,I=_.isVideoTexture!==!0,oe=ge.__version===void 0||J===!0,ne=Y.dataReady,xe=E(_,te);if(_.isDepthTexture)Se=M(_.format===pi,_.type),oe&&(I?t.texStorage2D(s.TEXTURE_2D,1,Se,te.width,te.height):t.texImage2D(s.TEXTURE_2D,0,Se,te.width,te.height,0,ae,ye,null));else if(_.isDataTexture)if(Oe.length>0){I&&oe&&t.texStorage2D(s.TEXTURE_2D,xe,Se,Oe[0].width,Oe[0].height);for(let ie=0,q=Oe.length;ie<q;ie++)fe=Oe[ie],I?ne&&t.texSubImage2D(s.TEXTURE_2D,ie,0,0,fe.width,fe.height,ae,ye,fe.data):t.texImage2D(s.TEXTURE_2D,ie,Se,fe.width,fe.height,0,ae,ye,fe.data);_.generateMipmaps=!1}else I?(oe&&t.texStorage2D(s.TEXTURE_2D,xe,Se,te.width,te.height),ne&&Re(_,te,ae,ye)):t.texImage2D(s.TEXTURE_2D,0,Se,te.width,te.height,0,ae,ye,te.data);else if(_.isCompressedTexture)if(_.isCompressedArrayTexture){I&&oe&&t.texStorage3D(s.TEXTURE_2D_ARRAY,xe,Se,Oe[0].width,Oe[0].height,te.depth);for(let ie=0,q=Oe.length;ie<q;ie++)if(fe=Oe[ie],_.format!==un)if(ae!==null)if(I){if(ne)if(_.layerUpdates.size>0){const be=yh(fe.width,fe.height,_.format,_.type);for(const Be of _.layerUpdates){const dt=fe.data.subarray(Be*be/fe.data.BYTES_PER_ELEMENT,(Be+1)*be/fe.data.BYTES_PER_ELEMENT);t.compressedTexSubImage3D(s.TEXTURE_2D_ARRAY,ie,0,0,Be,fe.width,fe.height,1,ae,dt)}_.clearLayerUpdates()}else t.compressedTexSubImage3D(s.TEXTURE_2D_ARRAY,ie,0,0,0,fe.width,fe.height,te.depth,ae,fe.data)}else t.compressedTexImage3D(s.TEXTURE_2D_ARRAY,ie,Se,fe.width,fe.height,te.depth,0,fe.data,0,0);else Pe("WebGLRenderer: Attempt to load unsupported compressed texture format in .uploadTexture()");else I?ne&&t.texSubImage3D(s.TEXTURE_2D_ARRAY,ie,0,0,0,fe.width,fe.height,te.depth,ae,ye,fe.data):t.texImage3D(s.TEXTURE_2D_ARRAY,ie,Se,fe.width,fe.height,te.depth,0,ae,ye,fe.data)}else{I&&oe&&t.texStorage2D(s.TEXTURE_2D,xe,Se,Oe[0].width,Oe[0].height);for(let ie=0,q=Oe.length;ie<q;ie++)fe=Oe[ie],_.format!==un?ae!==null?I?ne&&t.compressedTexSubImage2D(s.TEXTURE_2D,ie,0,0,fe.width,fe.height,ae,fe.data):t.compressedTexImage2D(s.TEXTURE_2D,ie,Se,fe.width,fe.height,0,fe.data):Pe("WebGLRenderer: Attempt to load unsupported compressed texture format in .uploadTexture()"):I?ne&&t.texSubImage2D(s.TEXTURE_2D,ie,0,0,fe.width,fe.height,ae,ye,fe.data):t.texImage2D(s.TEXTURE_2D,ie,Se,fe.width,fe.height,0,ae,ye,fe.data)}else if(_.isDataArrayTexture)if(I){if(oe&&t.texStorage3D(s.TEXTURE_2D_ARRAY,xe,Se,te.width,te.height,te.depth),ne)if(_.layerUpdates.size>0){const ie=yh(te.width,te.height,_.format,_.type);for(const q of _.layerUpdates){const be=te.data.subarray(q*ie/te.data.BYTES_PER_ELEMENT,(q+1)*ie/te.data.BYTES_PER_ELEMENT);t.texSubImage3D(s.TEXTURE_2D_ARRAY,0,0,0,q,te.width,te.height,1,ae,ye,be)}_.clearLayerUpdates()}else t.texSubImage3D(s.TEXTURE_2D_ARRAY,0,0,0,0,te.width,te.height,te.depth,ae,ye,te.data)}else t.texImage3D(s.TEXTURE_2D_ARRAY,0,Se,te.width,te.height,te.depth,0,ae,ye,te.data);else if(_.isData3DTexture)I?(oe&&t.texStorage3D(s.TEXTURE_3D,xe,Se,te.width,te.height,te.depth),ne&&t.texSubImage3D(s.TEXTURE_3D,0,0,0,0,te.width,te.height,te.depth,ae,ye,te.data)):t.texImage3D(s.TEXTURE_3D,0,Se,te.width,te.height,te.depth,0,ae,ye,te.data);else if(_.isFramebufferTexture){if(oe)if(I)t.texStorage2D(s.TEXTURE_2D,xe,Se,te.width,te.height);else{let ie=te.width,q=te.height;for(let be=0;be<xe;be++)t.texImage2D(s.TEXTURE_2D,be,Se,ie,q,0,ae,ye,null),ie>>=1,q>>=1}}else if(Oe.length>0){if(I&&oe){const ie=Me(Oe[0]);t.texStorage2D(s.TEXTURE_2D,xe,Se,ie.width,ie.height)}for(let ie=0,q=Oe.length;ie<q;ie++)fe=Oe[ie],I?ne&&t.texSubImage2D(s.TEXTURE_2D,ie,0,0,ae,ye,fe):t.texImage2D(s.TEXTURE_2D,ie,Se,ae,ye,fe);_.generateMipmaps=!1}else if(I){if(oe){const ie=Me(te);t.texStorage2D(s.TEXTURE_2D,xe,Se,ie.width,ie.height)}ne&&t.texSubImage2D(s.TEXTURE_2D,0,0,0,ae,ye,te)}else t.texImage2D(s.TEXTURE_2D,0,Se,ae,ye,te);p(_)&&m(j),ge.__version=Y.version,_.onUpdate&&_.onUpdate(_)}A.__version=_.version}function Z(A,_,N){if(_.image.length!==6)return;const j=$(A,_),J=_.source;t.bindTexture(s.TEXTURE_CUBE_MAP,A.__webglTexture,s.TEXTURE0+N);const Y=n.get(J);if(J.version!==Y.__version||j===!0){t.activeTexture(s.TEXTURE0+N);const ge=Ke.getPrimaries(Ke.workingColorSpace),re=_.colorSpace===di?null:Ke.getPrimaries(_.colorSpace),Ee=_.colorSpace===di||ge===re?s.NONE:s.BROWSER_DEFAULT_WEBGL;s.pixelStorei(s.UNPACK_FLIP_Y_WEBGL,_.flipY),s.pixelStorei(s.UNPACK_PREMULTIPLY_ALPHA_WEBGL,_.premultiplyAlpha),s.pixelStorei(s.UNPACK_ALIGNMENT,_.unpackAlignment),s.pixelStorei(s.UNPACK_COLORSPACE_CONVERSION_WEBGL,Ee);const Ne=_.isCompressedTexture||_.image[0].isCompressedTexture,te=_.image[0]&&_.image[0].isDataTexture,ae=[];for(let q=0;q<6;q++)!Ne&&!te?ae[q]=x(_.image[q],!0,i.maxCubemapSize):ae[q]=te?_.image[q].image:_.image[q],ae[q]=et(_,ae[q]);const ye=ae[0],Se=r.convert(_.format,_.colorSpace),fe=r.convert(_.type),Oe=T(_.internalFormat,Se,fe,_.colorSpace),I=_.isVideoTexture!==!0,oe=Y.__version===void 0||j===!0,ne=J.dataReady;let xe=E(_,ye);le(s.TEXTURE_CUBE_MAP,_);let ie;if(Ne){I&&oe&&t.texStorage2D(s.TEXTURE_CUBE_MAP,xe,Oe,ye.width,ye.height);for(let q=0;q<6;q++){ie=ae[q].mipmaps;for(let be=0;be<ie.length;be++){const Be=ie[be];_.format!==un?Se!==null?I?ne&&t.compressedTexSubImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,be,0,0,Be.width,Be.height,Se,Be.data):t.compressedTexImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,be,Oe,Be.width,Be.height,0,Be.data):Pe("WebGLRenderer: Attempt to load unsupported compressed texture format in .setTextureCube()"):I?ne&&t.texSubImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,be,0,0,Be.width,Be.height,Se,fe,Be.data):t.texImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,be,Oe,Be.width,Be.height,0,Se,fe,Be.data)}}}else{if(ie=_.mipmaps,I&&oe){ie.length>0&&xe++;const q=Me(ae[0]);t.texStorage2D(s.TEXTURE_CUBE_MAP,xe,Oe,q.width,q.height)}for(let q=0;q<6;q++)if(te){I?ne&&t.texSubImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,0,0,0,ae[q].width,ae[q].height,Se,fe,ae[q].data):t.texImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,0,Oe,ae[q].width,ae[q].height,0,Se,fe,ae[q].data);for(let be=0;be<ie.length;be++){const dt=ie[be].image[q].image;I?ne&&t.texSubImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,be+1,0,0,dt.width,dt.height,Se,fe,dt.data):t.texImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,be+1,Oe,dt.width,dt.height,0,Se,fe,dt.data)}}else{I?ne&&t.texSubImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,0,0,0,Se,fe,ae[q]):t.texImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,0,Oe,Se,fe,ae[q]);for(let be=0;be<ie.length;be++){const Be=ie[be];I?ne&&t.texSubImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,be+1,0,0,Se,fe,Be.image[q]):t.texImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+q,be+1,Oe,Se,fe,Be.image[q])}}}p(_)&&m(s.TEXTURE_CUBE_MAP),Y.__version=J.version,_.onUpdate&&_.onUpdate(_)}A.__version=_.version}function ee(A,_,N,j,J,Y){const ge=r.convert(N.format,N.colorSpace),re=r.convert(N.type),Ee=T(N.internalFormat,ge,re,N.colorSpace),Ne=n.get(_),te=n.get(N);if(te.__renderTarget=_,!Ne.__hasExternalTextures){const ae=Math.max(1,_.width>>Y),ye=Math.max(1,_.height>>Y);J===s.TEXTURE_3D||J===s.TEXTURE_2D_ARRAY?t.texImage3D(J,Y,Ee,ae,ye,_.depth,0,ge,re,null):t.texImage2D(J,Y,Ee,ae,ye,0,ge,re,null)}t.bindFramebuffer(s.FRAMEBUFFER,A),gt(_)?o.framebufferTexture2DMultisampleEXT(s.FRAMEBUFFER,j,J,te.__webglTexture,0,P(_)):(J===s.TEXTURE_2D||J>=s.TEXTURE_CUBE_MAP_POSITIVE_X&&J<=s.TEXTURE_CUBE_MAP_NEGATIVE_Z)&&s.framebufferTexture2D(s.FRAMEBUFFER,j,J,te.__webglTexture,Y),t.bindFramebuffer(s.FRAMEBUFFER,null)}function we(A,_,N){if(s.bindRenderbuffer(s.RENDERBUFFER,A),_.depthBuffer){const j=_.depthTexture,J=j&&j.isDepthTexture?j.type:null,Y=M(_.stencilBuffer,J),ge=_.stencilBuffer?s.DEPTH_STENCIL_ATTACHMENT:s.DEPTH_ATTACHMENT;gt(_)?o.renderbufferStorageMultisampleEXT(s.RENDERBUFFER,P(_),Y,_.width,_.height):N?s.renderbufferStorageMultisample(s.RENDERBUFFER,P(_),Y,_.width,_.height):s.renderbufferStorage(s.RENDERBUFFER,Y,_.width,_.height),s.framebufferRenderbuffer(s.FRAMEBUFFER,ge,s.RENDERBUFFER,A)}else{const j=_.textures;for(let J=0;J<j.length;J++){const Y=j[J],ge=r.convert(Y.format,Y.colorSpace),re=r.convert(Y.type),Ee=T(Y.internalFormat,ge,re,Y.colorSpace);gt(_)?o.renderbufferStorageMultisampleEXT(s.RENDERBUFFER,P(_),Ee,_.width,_.height):N?s.renderbufferStorageMultisample(s.RENDERBUFFER,P(_),Ee,_.width,_.height):s.renderbufferStorage(s.RENDERBUFFER,Ee,_.width,_.height)}}s.bindRenderbuffer(s.RENDERBUFFER,null)}function ve(A,_,N){const j=_.isWebGLCubeRenderTarget===!0;if(t.bindFramebuffer(s.FRAMEBUFFER,A),!(_.depthTexture&&_.depthTexture.isDepthTexture))throw new Error("renderTarget.depthTexture must be an instance of THREE.DepthTexture");const J=n.get(_.depthTexture);if(J.__renderTarget=_,(!J.__webglTexture||_.depthTexture.image.width!==_.width||_.depthTexture.image.height!==_.height)&&(_.depthTexture.image.width=_.width,_.depthTexture.image.height=_.height,_.depthTexture.needsUpdate=!0),j){if(J.__webglInit===void 0&&(J.__webglInit=!0,_.depthTexture.addEventListener("dispose",w)),J.__webglTexture===void 0){J.__webglTexture=s.createTexture(),t.bindTexture(s.TEXTURE_CUBE_MAP,J.__webglTexture),le(s.TEXTURE_CUBE_MAP,_.depthTexture);const Ne=r.convert(_.depthTexture.format),te=r.convert(_.depthTexture.type);let ae;_.depthTexture.format===Jn?ae=s.DEPTH_COMPONENT24:_.depthTexture.format===pi&&(ae=s.DEPTH24_STENCIL8);for(let ye=0;ye<6;ye++)s.texImage2D(s.TEXTURE_CUBE_MAP_POSITIVE_X+ye,0,ae,_.width,_.height,0,Ne,te,null)}}else V(_.depthTexture,0);const Y=J.__webglTexture,ge=P(_),re=j?s.TEXTURE_CUBE_MAP_POSITIVE_X+N:s.TEXTURE_2D,Ee=_.depthTexture.format===pi?s.DEPTH_STENCIL_ATTACHMENT:s.DEPTH_ATTACHMENT;if(_.depthTexture.format===Jn)gt(_)?o.framebufferTexture2DMultisampleEXT(s.FRAMEBUFFER,Ee,re,Y,0,ge):s.framebufferTexture2D(s.FRAMEBUFFER,Ee,re,Y,0);else if(_.depthTexture.format===pi)gt(_)?o.framebufferTexture2DMultisampleEXT(s.FRAMEBUFFER,Ee,re,Y,0,ge):s.framebufferTexture2D(s.FRAMEBUFFER,Ee,re,Y,0);else throw new Error("Unknown depthTexture format")}function Fe(A){const _=n.get(A),N=A.isWebGLCubeRenderTarget===!0;if(_.__boundDepthTexture!==A.depthTexture){const j=A.depthTexture;if(_.__depthDisposeCallback&&_.__depthDisposeCallback(),j){const J=()=>{delete _.__boundDepthTexture,delete _.__depthDisposeCallback,j.removeEventListener("dispose",J)};j.addEventListener("dispose",J),_.__depthDisposeCallback=J}_.__boundDepthTexture=j}if(A.depthTexture&&!_.__autoAllocateDepthBuffer)if(N)for(let j=0;j<6;j++)ve(_.__webglFramebuffer[j],A,j);else{const j=A.texture.mipmaps;j&&j.length>0?ve(_.__webglFramebuffer[0],A,0):ve(_.__webglFramebuffer,A,0)}else if(N){_.__webglDepthbuffer=[];for(let j=0;j<6;j++)if(t.bindFramebuffer(s.FRAMEBUFFER,_.__webglFramebuffer[j]),_.__webglDepthbuffer[j]===void 0)_.__webglDepthbuffer[j]=s.createRenderbuffer(),we(_.__webglDepthbuffer[j],A,!1);else{const J=A.stencilBuffer?s.DEPTH_STENCIL_ATTACHMENT:s.DEPTH_ATTACHMENT,Y=_.__webglDepthbuffer[j];s.bindRenderbuffer(s.RENDERBUFFER,Y),s.framebufferRenderbuffer(s.FRAMEBUFFER,J,s.RENDERBUFFER,Y)}}else{const j=A.texture.mipmaps;if(j&&j.length>0?t.bindFramebuffer(s.FRAMEBUFFER,_.__webglFramebuffer[0]):t.bindFramebuffer(s.FRAMEBUFFER,_.__webglFramebuffer),_.__webglDepthbuffer===void 0)_.__webglDepthbuffer=s.createRenderbuffer(),we(_.__webglDepthbuffer,A,!1);else{const J=A.stencilBuffer?s.DEPTH_STENCIL_ATTACHMENT:s.DEPTH_ATTACHMENT,Y=_.__webglDepthbuffer;s.bindRenderbuffer(s.RENDERBUFFER,Y),s.framebufferRenderbuffer(s.FRAMEBUFFER,J,s.RENDERBUFFER,Y)}}t.bindFramebuffer(s.FRAMEBUFFER,null)}function Mt(A,_,N){const j=n.get(A);_!==void 0&&ee(j.__webglFramebuffer,A,A.texture,s.COLOR_ATTACHMENT0,s.TEXTURE_2D,0),N!==void 0&&Fe(A)}function qe(A){const _=A.texture,N=n.get(A),j=n.get(_);A.addEventListener("dispose",C);const J=A.textures,Y=A.isWebGLCubeRenderTarget===!0,ge=J.length>1;if(ge||(j.__webglTexture===void 0&&(j.__webglTexture=s.createTexture()),j.__version=_.version,a.memory.textures++),Y){N.__webglFramebuffer=[];for(let re=0;re<6;re++)if(_.mipmaps&&_.mipmaps.length>0){N.__webglFramebuffer[re]=[];for(let Ee=0;Ee<_.mipmaps.length;Ee++)N.__webglFramebuffer[re][Ee]=s.createFramebuffer()}else N.__webglFramebuffer[re]=s.createFramebuffer()}else{if(_.mipmaps&&_.mipmaps.length>0){N.__webglFramebuffer=[];for(let re=0;re<_.mipmaps.length;re++)N.__webglFramebuffer[re]=s.createFramebuffer()}else N.__webglFramebuffer=s.createFramebuffer();if(ge)for(let re=0,Ee=J.length;re<Ee;re++){const Ne=n.get(J[re]);Ne.__webglTexture===void 0&&(Ne.__webglTexture=s.createTexture(),a.memory.textures++)}if(A.samples>0&&gt(A)===!1){N.__webglMultisampledFramebuffer=s.createFramebuffer(),N.__webglColorRenderbuffer=[],t.bindFramebuffer(s.FRAMEBUFFER,N.__webglMultisampledFramebuffer);for(let re=0;re<J.length;re++){const Ee=J[re];N.__webglColorRenderbuffer[re]=s.createRenderbuffer(),s.bindRenderbuffer(s.RENDERBUFFER,N.__webglColorRenderbuffer[re]);const Ne=r.convert(Ee.format,Ee.colorSpace),te=r.convert(Ee.type),ae=T(Ee.internalFormat,Ne,te,Ee.colorSpace,A.isXRRenderTarget===!0),ye=P(A);s.renderbufferStorageMultisample(s.RENDERBUFFER,ye,ae,A.width,A.height),s.framebufferRenderbuffer(s.FRAMEBUFFER,s.COLOR_ATTACHMENT0+re,s.RENDERBUFFER,N.__webglColorRenderbuffer[re])}s.bindRenderbuffer(s.RENDERBUFFER,null),A.depthBuffer&&(N.__webglDepthRenderbuffer=s.createRenderbuffer(),we(N.__webglDepthRenderbuffer,A,!0)),t.bindFramebuffer(s.FRAMEBUFFER,null)}}if(Y){t.bindTexture(s.TEXTURE_CUBE_MAP,j.__webglTexture),le(s.TEXTURE_CUBE_MAP,_);for(let re=0;re<6;re++)if(_.mipmaps&&_.mipmaps.length>0)for(let Ee=0;Ee<_.mipmaps.length;Ee++)ee(N.__webglFramebuffer[re][Ee],A,_,s.COLOR_ATTACHMENT0,s.TEXTURE_CUBE_MAP_POSITIVE_X+re,Ee);else ee(N.__webglFramebuffer[re],A,_,s.COLOR_ATTACHMENT0,s.TEXTURE_CUBE_MAP_POSITIVE_X+re,0);p(_)&&m(s.TEXTURE_CUBE_MAP),t.unbindTexture()}else if(ge){for(let re=0,Ee=J.length;re<Ee;re++){const Ne=J[re],te=n.get(Ne);let ae=s.TEXTURE_2D;(A.isWebGL3DRenderTarget||A.isWebGLArrayRenderTarget)&&(ae=A.isWebGL3DRenderTarget?s.TEXTURE_3D:s.TEXTURE_2D_ARRAY),t.bindTexture(ae,te.__webglTexture),le(ae,Ne),ee(N.__webglFramebuffer,A,Ne,s.COLOR_ATTACHMENT0+re,ae,0),p(Ne)&&m(ae)}t.unbindTexture()}else{let re=s.TEXTURE_2D;if((A.isWebGL3DRenderTarget||A.isWebGLArrayRenderTarget)&&(re=A.isWebGL3DRenderTarget?s.TEXTURE_3D:s.TEXTURE_2D_ARRAY),t.bindTexture(re,j.__webglTexture),le(re,_),_.mipmaps&&_.mipmaps.length>0)for(let Ee=0;Ee<_.mipmaps.length;Ee++)ee(N.__webglFramebuffer[Ee],A,_,s.COLOR_ATTACHMENT0,re,Ee);else ee(N.__webglFramebuffer,A,_,s.COLOR_ATTACHMENT0,re,0);p(_)&&m(re),t.unbindTexture()}A.depthBuffer&&Fe(A)}function Ze(A){const _=A.textures;for(let N=0,j=_.length;N<j;N++){const J=_[N];if(p(J)){const Y=S(A),ge=n.get(J).__webglTexture;t.bindTexture(Y,ge),m(Y),t.unbindTexture()}}}const Qe=[],ke=[];function pt(A){if(A.samples>0){if(gt(A)===!1){const _=A.textures,N=A.width,j=A.height;let J=s.COLOR_BUFFER_BIT;const Y=A.stencilBuffer?s.DEPTH_STENCIL_ATTACHMENT:s.DEPTH_ATTACHMENT,ge=n.get(A),re=_.length>1;if(re)for(let Ne=0;Ne<_.length;Ne++)t.bindFramebuffer(s.FRAMEBUFFER,ge.__webglMultisampledFramebuffer),s.framebufferRenderbuffer(s.FRAMEBUFFER,s.COLOR_ATTACHMENT0+Ne,s.RENDERBUFFER,null),t.bindFramebuffer(s.FRAMEBUFFER,ge.__webglFramebuffer),s.framebufferTexture2D(s.DRAW_FRAMEBUFFER,s.COLOR_ATTACHMENT0+Ne,s.TEXTURE_2D,null,0);t.bindFramebuffer(s.READ_FRAMEBUFFER,ge.__webglMultisampledFramebuffer);const Ee=A.texture.mipmaps;Ee&&Ee.length>0?t.bindFramebuffer(s.DRAW_FRAMEBUFFER,ge.__webglFramebuffer[0]):t.bindFramebuffer(s.DRAW_FRAMEBUFFER,ge.__webglFramebuffer);for(let Ne=0;Ne<_.length;Ne++){if(A.resolveDepthBuffer&&(A.depthBuffer&&(J|=s.DEPTH_BUFFER_BIT),A.stencilBuffer&&A.resolveStencilBuffer&&(J|=s.STENCIL_BUFFER_BIT)),re){s.framebufferRenderbuffer(s.READ_FRAMEBUFFER,s.COLOR_ATTACHMENT0,s.RENDERBUFFER,ge.__webglColorRenderbuffer[Ne]);const te=n.get(_[Ne]).__webglTexture;s.framebufferTexture2D(s.DRAW_FRAMEBUFFER,s.COLOR_ATTACHMENT0,s.TEXTURE_2D,te,0)}s.blitFramebuffer(0,0,N,j,0,0,N,j,J,s.NEAREST),l===!0&&(Qe.length=0,ke.length=0,Qe.push(s.COLOR_ATTACHMENT0+Ne),A.depthBuffer&&A.resolveDepthBuffer===!1&&(Qe.push(Y),ke.push(Y),s.invalidateFramebuffer(s.DRAW_FRAMEBUFFER,ke)),s.invalidateFramebuffer(s.READ_FRAMEBUFFER,Qe))}if(t.bindFramebuffer(s.READ_FRAMEBUFFER,null),t.bindFramebuffer(s.DRAW_FRAMEBUFFER,null),re)for(let Ne=0;Ne<_.length;Ne++){t.bindFramebuffer(s.FRAMEBUFFER,ge.__webglMultisampledFramebuffer),s.framebufferRenderbuffer(s.FRAMEBUFFER,s.COLOR_ATTACHMENT0+Ne,s.RENDERBUFFER,ge.__webglColorRenderbuffer[Ne]);const te=n.get(_[Ne]).__webglTexture;t.bindFramebuffer(s.FRAMEBUFFER,ge.__webglFramebuffer),s.framebufferTexture2D(s.DRAW_FRAMEBUFFER,s.COLOR_ATTACHMENT0+Ne,s.TEXTURE_2D,te,0)}t.bindFramebuffer(s.DRAW_FRAMEBUFFER,ge.__webglMultisampledFramebuffer)}else if(A.depthBuffer&&A.resolveDepthBuffer===!1&&l){const _=A.stencilBuffer?s.DEPTH_STENCIL_ATTACHMENT:s.DEPTH_ATTACHMENT;s.invalidateFramebuffer(s.DRAW_FRAMEBUFFER,[_])}}}function P(A){return Math.min(i.maxSamples,A.samples)}function gt(A){const _=n.get(A);return A.samples>0&&e.has("WEBGL_multisampled_render_to_texture")===!0&&_.__useRenderToTexture!==!1}function $e(A){const _=a.render.frame;h.get(A)!==_&&(h.set(A,_),A.update())}function et(A,_){const N=A.colorSpace,j=A.format,J=A.type;return A.isCompressedTexture===!0||A.isVideoTexture===!0||N!==Kt&&N!==di&&(Ke.getTransfer(N)===tt?(j!==un||J!==nn)&&Pe("WebGLTextures: sRGB encoded textures have to use RGBAFormat and UnsignedByteType."):Ue("WebGLTextures: Unsupported texture color space:",N)),_}function Me(A){return typeof HTMLImageElement<"u"&&A instanceof HTMLImageElement?(c.width=A.naturalWidth||A.width,c.height=A.naturalHeight||A.height):typeof VideoFrame<"u"&&A instanceof VideoFrame?(c.width=A.displayWidth,c.height=A.displayHeight):(c.width=A.width,c.height=A.height),c}this.allocateTextureUnit=O,this.resetTextureUnits=F,this.setTexture2D=V,this.setTexture2DArray=k,this.setTexture3D=U,this.setTextureCube=Q,this.rebindTextures=Mt,this.setupRenderTarget=qe,this.updateRenderTargetMipmap=Ze,this.updateMultisampleRenderTarget=pt,this.setupDepthRenderbuffer=Fe,this.setupFrameBufferTexture=ee,this.useMultisampledRTT=gt,this.isReversedDepthBuffer=function(){return t.buffers.depth.getReversed()}}function qv(s,e){function t(n,i=di){let r;const a=Ke.getTransfer(i);if(n===nn)return s.UNSIGNED_BYTE;if(n===zl)return s.UNSIGNED_SHORT_4_4_4_4;if(n===Hl)return s.UNSIGNED_SHORT_5_5_5_1;if(n===_u)return s.UNSIGNED_INT_5_9_9_9_REV;if(n===vu)return s.UNSIGNED_INT_10F_11F_11F_REV;if(n===mu)return s.BYTE;if(n===gu)return s.SHORT;if(n===Qs)return s.UNSIGNED_SHORT;if(n===Vl)return s.INT;if(n===Fn)return s.UNSIGNED_INT;if(n===sn)return s.FLOAT;if(n===on)return s.HALF_FLOAT;if(n===xu)return s.ALPHA;if(n===Mu)return s.RGB;if(n===un)return s.RGBA;if(n===Jn)return s.DEPTH_COMPONENT;if(n===pi)return s.DEPTH_STENCIL;if(n===ma)return s.RED;if(n===Gl)return s.RED_INTEGER;if(n===xs)return s.RG;if(n===Wl)return s.RG_INTEGER;if(n===Xl)return s.RGBA_INTEGER;if(n===Kr||n===$r||n===Zr||n===Jr)if(a===tt)if(r=e.get("WEBGL_compressed_texture_s3tc_srgb"),r!==null){if(n===Kr)return r.COMPRESSED_SRGB_S3TC_DXT1_EXT;if(n===$r)return r.COMPRESSED_SRGB_ALPHA_S3TC_DXT1_EXT;if(n===Zr)return r.COMPRESSED_SRGB_ALPHA_S3TC_DXT3_EXT;if(n===Jr)return r.COMPRESSED_SRGB_ALPHA_S3TC_DXT5_EXT}else return null;else if(r=e.get("WEBGL_compressed_texture_s3tc"),r!==null){if(n===Kr)return r.COMPRESSED_RGB_S3TC_DXT1_EXT;if(n===$r)return r.COMPRESSED_RGBA_S3TC_DXT1_EXT;if(n===Zr)return r.COMPRESSED_RGBA_S3TC_DXT3_EXT;if(n===Jr)return r.COMPRESSED_RGBA_S3TC_DXT5_EXT}else return null;if(n===Bo||n===ko||n===Vo||n===zo)if(r=e.get("WEBGL_compressed_texture_pvrtc"),r!==null){if(n===Bo)return r.COMPRESSED_RGB_PVRTC_4BPPV1_IMG;if(n===ko)return r.COMPRESSED_RGB_PVRTC_2BPPV1_IMG;if(n===Vo)return r.COMPRESSED_RGBA_PVRTC_4BPPV1_IMG;if(n===zo)return r.COMPRESSED_RGBA_PVRTC_2BPPV1_IMG}else return null;if(n===Ho||n===Go||n===Wo||n===Xo||n===Yo||n===qo||n===jo)if(r=e.get("WEBGL_compressed_texture_etc"),r!==null){if(n===Ho||n===Go)return a===tt?r.COMPRESSED_SRGB8_ETC2:r.COMPRESSED_RGB8_ETC2;if(n===Wo)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ETC2_EAC:r.COMPRESSED_RGBA8_ETC2_EAC;if(n===Xo)return r.COMPRESSED_R11_EAC;if(n===Yo)return r.COMPRESSED_SIGNED_R11_EAC;if(n===qo)return r.COMPRESSED_RG11_EAC;if(n===jo)return r.COMPRESSED_SIGNED_RG11_EAC}else return null;if(n===Ko||n===$o||n===Zo||n===Jo||n===Qo||n===el||n===tl||n===nl||n===il||n===sl||n===rl||n===al||n===ol||n===ll)if(r=e.get("WEBGL_compressed_texture_astc"),r!==null){if(n===Ko)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_4x4_KHR:r.COMPRESSED_RGBA_ASTC_4x4_KHR;if(n===$o)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_5x4_KHR:r.COMPRESSED_RGBA_ASTC_5x4_KHR;if(n===Zo)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_5x5_KHR:r.COMPRESSED_RGBA_ASTC_5x5_KHR;if(n===Jo)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_6x5_KHR:r.COMPRESSED_RGBA_ASTC_6x5_KHR;if(n===Qo)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_6x6_KHR:r.COMPRESSED_RGBA_ASTC_6x6_KHR;if(n===el)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_8x5_KHR:r.COMPRESSED_RGBA_ASTC_8x5_KHR;if(n===tl)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_8x6_KHR:r.COMPRESSED_RGBA_ASTC_8x6_KHR;if(n===nl)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_8x8_KHR:r.COMPRESSED_RGBA_ASTC_8x8_KHR;if(n===il)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_10x5_KHR:r.COMPRESSED_RGBA_ASTC_10x5_KHR;if(n===sl)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_10x6_KHR:r.COMPRESSED_RGBA_ASTC_10x6_KHR;if(n===rl)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_10x8_KHR:r.COMPRESSED_RGBA_ASTC_10x8_KHR;if(n===al)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_10x10_KHR:r.COMPRESSED_RGBA_ASTC_10x10_KHR;if(n===ol)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_12x10_KHR:r.COMPRESSED_RGBA_ASTC_12x10_KHR;if(n===ll)return a===tt?r.COMPRESSED_SRGB8_ALPHA8_ASTC_12x12_KHR:r.COMPRESSED_RGBA_ASTC_12x12_KHR}else return null;if(n===cl||n===hl||n===ul)if(r=e.get("EXT_texture_compression_bptc"),r!==null){if(n===cl)return a===tt?r.COMPRESSED_SRGB_ALPHA_BPTC_UNORM_EXT:r.COMPRESSED_RGBA_BPTC_UNORM_EXT;if(n===hl)return r.COMPRESSED_RGB_BPTC_SIGNED_FLOAT_EXT;if(n===ul)return r.COMPRESSED_RGB_BPTC_UNSIGNED_FLOAT_EXT}else return null;if(n===dl||n===fl||n===pl||n===ml)if(r=e.get("EXT_texture_compression_rgtc"),r!==null){if(n===dl)return r.COMPRESSED_RED_RGTC1_EXT;if(n===fl)return r.COMPRESSED_SIGNED_RED_RGTC1_EXT;if(n===pl)return r.COMPRESSED_RED_GREEN_RGTC2_EXT;if(n===ml)return r.COMPRESSED_SIGNED_RED_GREEN_RGTC2_EXT}else return null;return n===vs?s.UNSIGNED_INT_24_8:s[n]!==void 0?s[n]:null}return{convert:t}}const jv=`
void main() {

	gl_Position = vec4( position, 1.0 );

}`,Kv=`
uniform sampler2DArray depthColor;
uniform float depthWidth;
uniform float depthHeight;

void main() {

	vec2 coord = vec2( gl_FragCoord.x / depthWidth, gl_FragCoord.y / depthHeight );

	if ( coord.x >= 1.0 ) {

		gl_FragDepth = texture( depthColor, vec3( coord.x - 1.0, coord.y, 1 ) ).r;

	} else {

		gl_FragDepth = texture( depthColor, vec3( coord.x, coord.y, 0 ) ).r;

	}

}`;class $v{constructor(){this.texture=null,this.mesh=null,this.depthNear=0,this.depthFar=0}init(e,t){if(this.texture===null){const n=new Du(e.texture);(e.depthNear!==t.depthNear||e.depthFar!==t.depthFar)&&(this.depthNear=e.depthNear,this.depthFar=e.depthFar),this.texture=n}}getMesh(e){if(this.texture!==null&&this.mesh===null){const t=e.cameras[0].viewport,n=new kt({vertexShader:jv,fragmentShader:Kv,uniforms:{depthColor:{value:this.texture},depthWidth:{value:t.z},depthHeight:{value:t.w}}});this.mesh=new lt(new Pi(20,20),n)}return this.mesh}reset(){this.texture=null,this.mesh=null}getDepthTexture(){return this.texture}}class Zv extends Ni{constructor(e,t){super();const n=this;let i=null,r=1,a=null,o="local-floor",l=1,c=null,h=null,u=null,d=null,f=null,g=null;const x=typeof XRWebGLBinding<"u",p=new $v,m={},S=t.getContextAttributes();let T=null,M=null;const E=[],w=[],C=new Le;let v=null;const b=new Wt;b.viewport=new mt;const D=new Wt;D.viewport=new mt;const R=[b,D],F=new $p;let O=null,X=null;this.cameraAutoUpdate=!0,this.enabled=!1,this.isPresenting=!1,this.getController=function(G){let Z=E[G];return Z===void 0&&(Z=new za,E[G]=Z),Z.getTargetRaySpace()},this.getControllerGrip=function(G){let Z=E[G];return Z===void 0&&(Z=new za,E[G]=Z),Z.getGripSpace()},this.getHand=function(G){let Z=E[G];return Z===void 0&&(Z=new za,E[G]=Z),Z.getHandSpace()};function V(G){const Z=w.indexOf(G.inputSource);if(Z===-1)return;const ee=E[Z];ee!==void 0&&(ee.update(G.inputSource,G.frame,c||a),ee.dispatchEvent({type:G.type,data:G.inputSource}))}function k(){i.removeEventListener("select",V),i.removeEventListener("selectstart",V),i.removeEventListener("selectend",V),i.removeEventListener("squeeze",V),i.removeEventListener("squeezestart",V),i.removeEventListener("squeezeend",V),i.removeEventListener("end",k),i.removeEventListener("inputsourceschange",U);for(let G=0;G<E.length;G++){const Z=w[G];Z!==null&&(w[G]=null,E[G].disconnect(Z))}O=null,X=null,p.reset();for(const G in m)delete m[G];e.setRenderTarget(T),f=null,d=null,u=null,i=null,M=null,Re.stop(),n.isPresenting=!1,e.setPixelRatio(v),e.setSize(C.width,C.height,!1),n.dispatchEvent({type:"sessionend"})}this.setFramebufferScaleFactor=function(G){r=G,n.isPresenting===!0&&Pe("WebXRManager: Cannot change framebuffer scale while presenting.")},this.setReferenceSpaceType=function(G){o=G,n.isPresenting===!0&&Pe("WebXRManager: Cannot change reference space type while presenting.")},this.getReferenceSpace=function(){return c||a},this.setReferenceSpace=function(G){c=G},this.getBaseLayer=function(){return d!==null?d:f},this.getBinding=function(){return u===null&&x&&(u=new XRWebGLBinding(i,t)),u},this.getFrame=function(){return g},this.getSession=function(){return i},this.setSession=async function(G){if(i=G,i!==null){if(T=e.getRenderTarget(),i.addEventListener("select",V),i.addEventListener("selectstart",V),i.addEventListener("selectend",V),i.addEventListener("squeeze",V),i.addEventListener("squeezestart",V),i.addEventListener("squeezeend",V),i.addEventListener("end",k),i.addEventListener("inputsourceschange",U),S.xrCompatible!==!0&&await t.makeXRCompatible(),v=e.getPixelRatio(),e.getSize(C),x&&"createProjectionLayer"in XRWebGLBinding.prototype){let ee=null,we=null,ve=null;S.depth&&(ve=S.stencil?t.DEPTH24_STENCIL8:t.DEPTH_COMPONENT24,ee=S.stencil?pi:Jn,we=S.stencil?vs:Fn);const Fe={colorFormat:t.RGBA8,depthFormat:ve,scaleFactor:r};u=this.getBinding(),d=u.createProjectionLayer(Fe),i.updateRenderState({layers:[d]}),e.setPixelRatio(1),e.setSize(d.textureWidth,d.textureHeight,!1),M=new Jt(d.textureWidth,d.textureHeight,{format:un,type:nn,depthTexture:new ys(d.textureWidth,d.textureHeight,we,void 0,void 0,void 0,void 0,void 0,void 0,ee),stencilBuffer:S.stencil,colorSpace:e.outputColorSpace,samples:S.antialias?4:0,resolveDepthBuffer:d.ignoreDepthValues===!1,resolveStencilBuffer:d.ignoreDepthValues===!1})}else{const ee={antialias:S.antialias,alpha:!0,depth:S.depth,stencil:S.stencil,framebufferScaleFactor:r};f=new XRWebGLLayer(i,t,ee),i.updateRenderState({baseLayer:f}),e.setPixelRatio(1),e.setSize(f.framebufferWidth,f.framebufferHeight,!1),M=new Jt(f.framebufferWidth,f.framebufferHeight,{format:un,type:nn,colorSpace:e.outputColorSpace,stencilBuffer:S.stencil,resolveDepthBuffer:f.ignoreDepthValues===!1,resolveStencilBuffer:f.ignoreDepthValues===!1})}M.isXRRenderTarget=!0,this.setFoveation(l),c=null,a=await i.requestReferenceSpace(o),Re.setContext(i),Re.start(),n.isPresenting=!0,n.dispatchEvent({type:"sessionstart"})}},this.getEnvironmentBlendMode=function(){if(i!==null)return i.environmentBlendMode},this.getDepthTexture=function(){return p.getDepthTexture()};function U(G){for(let Z=0;Z<G.removed.length;Z++){const ee=G.removed[Z],we=w.indexOf(ee);we>=0&&(w[we]=null,E[we].disconnect(ee))}for(let Z=0;Z<G.added.length;Z++){const ee=G.added[Z];let we=w.indexOf(ee);if(we===-1){for(let Fe=0;Fe<E.length;Fe++)if(Fe>=w.length){w.push(ee),we=Fe;break}else if(w[Fe]===null){w[Fe]=ee,we=Fe;break}if(we===-1)break}const ve=E[we];ve&&ve.connect(ee)}}const Q=new L,K=new L;function se(G,Z,ee){Q.setFromMatrixPosition(Z.matrixWorld),K.setFromMatrixPosition(ee.matrixWorld);const we=Q.distanceTo(K),ve=Z.projectionMatrix.elements,Fe=ee.projectionMatrix.elements,Mt=ve[14]/(ve[10]-1),qe=ve[14]/(ve[10]+1),Ze=(ve[9]+1)/ve[5],Qe=(ve[9]-1)/ve[5],ke=(ve[8]-1)/ve[0],pt=(Fe[8]+1)/Fe[0],P=Mt*ke,gt=Mt*pt,$e=we/(-ke+pt),et=$e*-ke;if(Z.matrixWorld.decompose(G.position,G.quaternion,G.scale),G.translateX(et),G.translateZ($e),G.matrixWorld.compose(G.position,G.quaternion,G.scale),G.matrixWorldInverse.copy(G.matrixWorld).invert(),ve[10]===-1)G.projectionMatrix.copy(Z.projectionMatrix),G.projectionMatrixInverse.copy(Z.projectionMatrixInverse);else{const Me=Mt+$e,A=qe+$e,_=P-et,N=gt+(we-et),j=Ze*qe/A*Me,J=Qe*qe/A*Me;G.projectionMatrix.makePerspective(_,N,j,J,Me,A),G.projectionMatrixInverse.copy(G.projectionMatrix).invert()}}function he(G,Z){Z===null?G.matrixWorld.copy(G.matrix):G.matrixWorld.multiplyMatrices(Z.matrixWorld,G.matrix),G.matrixWorldInverse.copy(G.matrixWorld).invert()}this.updateCamera=function(G){if(i===null)return;let Z=G.near,ee=G.far;p.texture!==null&&(p.depthNear>0&&(Z=p.depthNear),p.depthFar>0&&(ee=p.depthFar)),F.near=D.near=b.near=Z,F.far=D.far=b.far=ee,(O!==F.near||X!==F.far)&&(i.updateRenderState({depthNear:F.near,depthFar:F.far}),O=F.near,X=F.far),F.layers.mask=G.layers.mask|6,b.layers.mask=F.layers.mask&-5,D.layers.mask=F.layers.mask&-3;const we=G.parent,ve=F.cameras;he(F,we);for(let Fe=0;Fe<ve.length;Fe++)he(ve[Fe],we);ve.length===2?se(F,b,D):F.projectionMatrix.copy(b.projectionMatrix),le(G,F,we)};function le(G,Z,ee){ee===null?G.matrix.copy(Z.matrixWorld):(G.matrix.copy(ee.matrixWorld),G.matrix.invert(),G.matrix.multiply(Z.matrixWorld)),G.matrix.decompose(G.position,G.quaternion,G.scale),G.updateMatrixWorld(!0),G.projectionMatrix.copy(Z.projectionMatrix),G.projectionMatrixInverse.copy(Z.projectionMatrixInverse),G.isPerspectiveCamera&&(G.fov=Ms*2*Math.atan(1/G.projectionMatrix.elements[5]),G.zoom=1)}this.getCamera=function(){return F},this.getFoveation=function(){if(!(d===null&&f===null))return l},this.setFoveation=function(G){l=G,d!==null&&(d.fixedFoveation=G),f!==null&&f.fixedFoveation!==void 0&&(f.fixedFoveation=G)},this.hasDepthSensing=function(){return p.texture!==null},this.getDepthSensingMesh=function(){return p.getMesh(F)},this.getCameraTexture=function(G){return m[G]};let $=null;function ce(G,Z){if(h=Z.getViewerPose(c||a),g=Z,h!==null){const ee=h.views;f!==null&&(e.setRenderTargetFramebuffer(M,f.framebuffer),e.setRenderTarget(M));let we=!1;ee.length!==F.cameras.length&&(F.cameras.length=0,we=!0);for(let qe=0;qe<ee.length;qe++){const Ze=ee[qe];let Qe=null;if(f!==null)Qe=f.getViewport(Ze);else{const pt=u.getViewSubImage(d,Ze);Qe=pt.viewport,qe===0&&(e.setRenderTargetTextures(M,pt.colorTexture,pt.depthStencilTexture),e.setRenderTarget(M))}let ke=R[qe];ke===void 0&&(ke=new Wt,ke.layers.enable(qe),ke.viewport=new mt,R[qe]=ke),ke.matrix.fromArray(Ze.transform.matrix),ke.matrix.decompose(ke.position,ke.quaternion,ke.scale),ke.projectionMatrix.fromArray(Ze.projectionMatrix),ke.projectionMatrixInverse.copy(ke.projectionMatrix).invert(),ke.viewport.set(Qe.x,Qe.y,Qe.width,Qe.height),qe===0&&(F.matrix.copy(ke.matrix),F.matrix.decompose(F.position,F.quaternion,F.scale)),we===!0&&F.cameras.push(ke)}const ve=i.enabledFeatures;if(ve&&ve.includes("depth-sensing")&&i.depthUsage=="gpu-optimized"&&x){u=n.getBinding();const qe=u.getDepthInformation(ee[0]);qe&&qe.isValid&&qe.texture&&p.init(qe,i.renderState)}if(ve&&ve.includes("camera-access")&&x){e.state.unbindTexture(),u=n.getBinding();for(let qe=0;qe<ee.length;qe++){const Ze=ee[qe].camera;if(Ze){let Qe=m[Ze];Qe||(Qe=new Du,m[Ze]=Qe);const ke=u.getCameraImage(Ze);Qe.sourceTexture=ke}}}}for(let ee=0;ee<E.length;ee++){const we=w[ee],ve=E[ee];we!==null&&ve!==void 0&&ve.update(we,Z,c||a)}$&&$(G,Z),Z.detectedPlanes&&n.dispatchEvent({type:"planesdetected",data:Z}),g=null}const Re=new Vu;Re.setAnimationLoop(ce),this.setAnimationLoop=function(G){$=G},this.dispose=function(){}}}const Ai=new Sn,Jv=new Ve;function Qv(s,e){function t(p,m){p.matrixAutoUpdate===!0&&p.updateMatrix(),m.value.copy(p.matrix)}function n(p,m){m.color.getRGB(p.fogColor.value,Lu(s)),m.isFog?(p.fogNear.value=m.near,p.fogFar.value=m.far):m.isFogExp2&&(p.fogDensity.value=m.density)}function i(p,m,S,T,M){m.isMeshBasicMaterial?r(p,m):m.isMeshLambertMaterial?(r(p,m),m.envMap&&(p.envMapIntensity.value=m.envMapIntensity)):m.isMeshToonMaterial?(r(p,m),u(p,m)):m.isMeshPhongMaterial?(r(p,m),h(p,m),m.envMap&&(p.envMapIntensity.value=m.envMapIntensity)):m.isMeshStandardMaterial?(r(p,m),d(p,m),m.isMeshPhysicalMaterial&&f(p,m,M)):m.isMeshMatcapMaterial?(r(p,m),g(p,m)):m.isMeshDepthMaterial?r(p,m):m.isMeshDistanceMaterial?(r(p,m),x(p,m)):m.isMeshNormalMaterial?r(p,m):m.isLineBasicMaterial?(a(p,m),m.isLineDashedMaterial&&o(p,m)):m.isPointsMaterial?l(p,m,S,T):m.isSpriteMaterial?c(p,m):m.isShadowMaterial?(p.color.value.copy(m.color),p.opacity.value=m.opacity):m.isShaderMaterial&&(m.uniformsNeedUpdate=!1)}function r(p,m){p.opacity.value=m.opacity,m.color&&p.diffuse.value.copy(m.color),m.emissive&&p.emissive.value.copy(m.emissive).multiplyScalar(m.emissiveIntensity),m.map&&(p.map.value=m.map,t(m.map,p.mapTransform)),m.alphaMap&&(p.alphaMap.value=m.alphaMap,t(m.alphaMap,p.alphaMapTransform)),m.bumpMap&&(p.bumpMap.value=m.bumpMap,t(m.bumpMap,p.bumpMapTransform),p.bumpScale.value=m.bumpScale,m.side===qt&&(p.bumpScale.value*=-1)),m.normalMap&&(p.normalMap.value=m.normalMap,t(m.normalMap,p.normalMapTransform),p.normalScale.value.copy(m.normalScale),m.side===qt&&p.normalScale.value.negate()),m.displacementMap&&(p.displacementMap.value=m.displacementMap,t(m.displacementMap,p.displacementMapTransform),p.displacementScale.value=m.displacementScale,p.displacementBias.value=m.displacementBias),m.emissiveMap&&(p.emissiveMap.value=m.emissiveMap,t(m.emissiveMap,p.emissiveMapTransform)),m.specularMap&&(p.specularMap.value=m.specularMap,t(m.specularMap,p.specularMapTransform)),m.alphaTest>0&&(p.alphaTest.value=m.alphaTest);const S=e.get(m),T=S.envMap,M=S.envMapRotation;T&&(p.envMap.value=T,Ai.copy(M),Ai.x*=-1,Ai.y*=-1,Ai.z*=-1,T.isCubeTexture&&T.isRenderTargetTexture===!1&&(Ai.y*=-1,Ai.z*=-1),p.envMapRotation.value.setFromMatrix4(Jv.makeRotationFromEuler(Ai)),p.flipEnvMap.value=T.isCubeTexture&&T.isRenderTargetTexture===!1?-1:1,p.reflectivity.value=m.reflectivity,p.ior.value=m.ior,p.refractionRatio.value=m.refractionRatio),m.lightMap&&(p.lightMap.value=m.lightMap,p.lightMapIntensity.value=m.lightMapIntensity,t(m.lightMap,p.lightMapTransform)),m.aoMap&&(p.aoMap.value=m.aoMap,p.aoMapIntensity.value=m.aoMapIntensity,t(m.aoMap,p.aoMapTransform))}function a(p,m){p.diffuse.value.copy(m.color),p.opacity.value=m.opacity,m.map&&(p.map.value=m.map,t(m.map,p.mapTransform))}function o(p,m){p.dashSize.value=m.dashSize,p.totalSize.value=m.dashSize+m.gapSize,p.scale.value=m.scale}function l(p,m,S,T){p.diffuse.value.copy(m.color),p.opacity.value=m.opacity,p.size.value=m.size*S,p.scale.value=T*.5,m.map&&(p.map.value=m.map,t(m.map,p.uvTransform)),m.alphaMap&&(p.alphaMap.value=m.alphaMap,t(m.alphaMap,p.alphaMapTransform)),m.alphaTest>0&&(p.alphaTest.value=m.alphaTest)}function c(p,m){p.diffuse.value.copy(m.color),p.opacity.value=m.opacity,p.rotation.value=m.rotation,m.map&&(p.map.value=m.map,t(m.map,p.mapTransform)),m.alphaMap&&(p.alphaMap.value=m.alphaMap,t(m.alphaMap,p.alphaMapTransform)),m.alphaTest>0&&(p.alphaTest.value=m.alphaTest)}function h(p,m){p.specular.value.copy(m.specular),p.shininess.value=Math.max(m.shininess,1e-4)}function u(p,m){m.gradientMap&&(p.gradientMap.value=m.gradientMap)}function d(p,m){p.metalness.value=m.metalness,m.metalnessMap&&(p.metalnessMap.value=m.metalnessMap,t(m.metalnessMap,p.metalnessMapTransform)),p.roughness.value=m.roughness,m.roughnessMap&&(p.roughnessMap.value=m.roughnessMap,t(m.roughnessMap,p.roughnessMapTransform)),m.envMap&&(p.envMapIntensity.value=m.envMapIntensity)}function f(p,m,S){p.ior.value=m.ior,m.sheen>0&&(p.sheenColor.value.copy(m.sheenColor).multiplyScalar(m.sheen),p.sheenRoughness.value=m.sheenRoughness,m.sheenColorMap&&(p.sheenColorMap.value=m.sheenColorMap,t(m.sheenColorMap,p.sheenColorMapTransform)),m.sheenRoughnessMap&&(p.sheenRoughnessMap.value=m.sheenRoughnessMap,t(m.sheenRoughnessMap,p.sheenRoughnessMapTransform))),m.clearcoat>0&&(p.clearcoat.value=m.clearcoat,p.clearcoatRoughness.value=m.clearcoatRoughness,m.clearcoatMap&&(p.clearcoatMap.value=m.clearcoatMap,t(m.clearcoatMap,p.clearcoatMapTransform)),m.clearcoatRoughnessMap&&(p.clearcoatRoughnessMap.value=m.clearcoatRoughnessMap,t(m.clearcoatRoughnessMap,p.clearcoatRoughnessMapTransform)),m.clearcoatNormalMap&&(p.clearcoatNormalMap.value=m.clearcoatNormalMap,t(m.clearcoatNormalMap,p.clearcoatNormalMapTransform),p.clearcoatNormalScale.value.copy(m.clearcoatNormalScale),m.side===qt&&p.clearcoatNormalScale.value.negate())),m.dispersion>0&&(p.dispersion.value=m.dispersion),m.iridescence>0&&(p.iridescence.value=m.iridescence,p.iridescenceIOR.value=m.iridescenceIOR,p.iridescenceThicknessMinimum.value=m.iridescenceThicknessRange[0],p.iridescenceThicknessMaximum.value=m.iridescenceThicknessRange[1],m.iridescenceMap&&(p.iridescenceMap.value=m.iridescenceMap,t(m.iridescenceMap,p.iridescenceMapTransform)),m.iridescenceThicknessMap&&(p.iridescenceThicknessMap.value=m.iridescenceThicknessMap,t(m.iridescenceThicknessMap,p.iridescenceThicknessMapTransform))),m.transmission>0&&(p.transmission.value=m.transmission,p.transmissionSamplerMap.value=S.texture,p.transmissionSamplerSize.value.set(S.width,S.height),m.transmissionMap&&(p.transmissionMap.value=m.transmissionMap,t(m.transmissionMap,p.transmissionMapTransform)),p.thickness.value=m.thickness,m.thicknessMap&&(p.thicknessMap.value=m.thicknessMap,t(m.thicknessMap,p.thicknessMapTransform)),p.attenuationDistance.value=m.attenuationDistance,p.attenuationColor.value.copy(m.attenuationColor)),m.anisotropy>0&&(p.anisotropyVector.value.set(m.anisotropy*Math.cos(m.anisotropyRotation),m.anisotropy*Math.sin(m.anisotropyRotation)),m.anisotropyMap&&(p.anisotropyMap.value=m.anisotropyMap,t(m.anisotropyMap,p.anisotropyMapTransform))),p.specularIntensity.value=m.specularIntensity,p.specularColor.value.copy(m.specularColor),m.specularColorMap&&(p.specularColorMap.value=m.specularColorMap,t(m.specularColorMap,p.specularColorMapTransform)),m.specularIntensityMap&&(p.specularIntensityMap.value=m.specularIntensityMap,t(m.specularIntensityMap,p.specularIntensityMapTransform))}function g(p,m){m.matcap&&(p.matcap.value=m.matcap)}function x(p,m){const S=e.get(m).light;p.referencePosition.value.setFromMatrixPosition(S.matrixWorld),p.nearDistance.value=S.shadow.camera.near,p.farDistance.value=S.shadow.camera.far}return{refreshFogUniforms:n,refreshMaterialUniforms:i}}function ex(s,e,t,n){let i={},r={},a=[];const o=s.getParameter(s.MAX_UNIFORM_BUFFER_BINDINGS);function l(S,T){const M=T.program;n.uniformBlockBinding(S,M)}function c(S,T){let M=i[S.id];M===void 0&&(g(S),M=h(S),i[S.id]=M,S.addEventListener("dispose",p));const E=T.program;n.updateUBOMapping(S,E);const w=e.render.frame;r[S.id]!==w&&(d(S),r[S.id]=w)}function h(S){const T=u();S.__bindingPointIndex=T;const M=s.createBuffer(),E=S.__size,w=S.usage;return s.bindBuffer(s.UNIFORM_BUFFER,M),s.bufferData(s.UNIFORM_BUFFER,E,w),s.bindBuffer(s.UNIFORM_BUFFER,null),s.bindBufferBase(s.UNIFORM_BUFFER,T,M),M}function u(){for(let S=0;S<o;S++)if(a.indexOf(S)===-1)return a.push(S),S;return Ue("WebGLRenderer: Maximum number of simultaneously usable uniforms groups reached."),0}function d(S){const T=i[S.id],M=S.uniforms,E=S.__cache;s.bindBuffer(s.UNIFORM_BUFFER,T);for(let w=0,C=M.length;w<C;w++){const v=Array.isArray(M[w])?M[w]:[M[w]];for(let b=0,D=v.length;b<D;b++){const R=v[b];if(f(R,w,b,E)===!0){const F=R.__offset,O=Array.isArray(R.value)?R.value:[R.value];let X=0;for(let V=0;V<O.length;V++){const k=O[V],U=x(k);typeof k=="number"||typeof k=="boolean"?(R.__data[0]=k,s.bufferSubData(s.UNIFORM_BUFFER,F+X,R.__data)):k.isMatrix3?(R.__data[0]=k.elements[0],R.__data[1]=k.elements[1],R.__data[2]=k.elements[2],R.__data[3]=0,R.__data[4]=k.elements[3],R.__data[5]=k.elements[4],R.__data[6]=k.elements[5],R.__data[7]=0,R.__data[8]=k.elements[6],R.__data[9]=k.elements[7],R.__data[10]=k.elements[8],R.__data[11]=0):(k.toArray(R.__data,X),X+=U.storage/Float32Array.BYTES_PER_ELEMENT)}s.bufferSubData(s.UNIFORM_BUFFER,F,R.__data)}}}s.bindBuffer(s.UNIFORM_BUFFER,null)}function f(S,T,M,E){const w=S.value,C=T+"_"+M;if(E[C]===void 0)return typeof w=="number"||typeof w=="boolean"?E[C]=w:E[C]=w.clone(),!0;{const v=E[C];if(typeof w=="number"||typeof w=="boolean"){if(v!==w)return E[C]=w,!0}else if(v.equals(w)===!1)return v.copy(w),!0}return!1}function g(S){const T=S.uniforms;let M=0;const E=16;for(let C=0,v=T.length;C<v;C++){const b=Array.isArray(T[C])?T[C]:[T[C]];for(let D=0,R=b.length;D<R;D++){const F=b[D],O=Array.isArray(F.value)?F.value:[F.value];for(let X=0,V=O.length;X<V;X++){const k=O[X],U=x(k),Q=M%E,K=Q%U.boundary,se=Q+K;M+=K,se!==0&&E-se<U.storage&&(M+=E-se),F.__data=new Float32Array(U.storage/Float32Array.BYTES_PER_ELEMENT),F.__offset=M,M+=U.storage}}}const w=M%E;return w>0&&(M+=E-w),S.__size=M,S.__cache={},this}function x(S){const T={boundary:0,storage:0};return typeof S=="number"||typeof S=="boolean"?(T.boundary=4,T.storage=4):S.isVector2?(T.boundary=8,T.storage=8):S.isVector3||S.isColor?(T.boundary=16,T.storage=12):S.isVector4?(T.boundary=16,T.storage=16):S.isMatrix3?(T.boundary=48,T.storage=48):S.isMatrix4?(T.boundary=64,T.storage=64):S.isTexture?Pe("WebGLRenderer: Texture samplers can not be part of an uniforms group."):Pe("WebGLRenderer: Unsupported uniform value type.",S),T}function p(S){const T=S.target;T.removeEventListener("dispose",p);const M=a.indexOf(T.__bindingPointIndex);a.splice(M,1),s.deleteBuffer(i[T.id]),delete i[T.id],delete r[T.id]}function m(){for(const S in i)s.deleteBuffer(i[S]);a=[],i={},r={}}return{bind:l,update:c,dispose:m}}const tx=new Uint16Array([12469,15057,12620,14925,13266,14620,13807,14376,14323,13990,14545,13625,14713,13328,14840,12882,14931,12528,14996,12233,15039,11829,15066,11525,15080,11295,15085,10976,15082,10705,15073,10495,13880,14564,13898,14542,13977,14430,14158,14124,14393,13732,14556,13410,14702,12996,14814,12596,14891,12291,14937,11834,14957,11489,14958,11194,14943,10803,14921,10506,14893,10278,14858,9960,14484,14039,14487,14025,14499,13941,14524,13740,14574,13468,14654,13106,14743,12678,14818,12344,14867,11893,14889,11509,14893,11180,14881,10751,14852,10428,14812,10128,14765,9754,14712,9466,14764,13480,14764,13475,14766,13440,14766,13347,14769,13070,14786,12713,14816,12387,14844,11957,14860,11549,14868,11215,14855,10751,14825,10403,14782,10044,14729,9651,14666,9352,14599,9029,14967,12835,14966,12831,14963,12804,14954,12723,14936,12564,14917,12347,14900,11958,14886,11569,14878,11247,14859,10765,14828,10401,14784,10011,14727,9600,14660,9289,14586,8893,14508,8533,15111,12234,15110,12234,15104,12216,15092,12156,15067,12010,15028,11776,14981,11500,14942,11205,14902,10752,14861,10393,14812,9991,14752,9570,14682,9252,14603,8808,14519,8445,14431,8145,15209,11449,15208,11451,15202,11451,15190,11438,15163,11384,15117,11274,15055,10979,14994,10648,14932,10343,14871,9936,14803,9532,14729,9218,14645,8742,14556,8381,14461,8020,14365,7603,15273,10603,15272,10607,15267,10619,15256,10631,15231,10614,15182,10535,15118,10389,15042,10167,14963,9787,14883,9447,14800,9115,14710,8665,14615,8318,14514,7911,14411,7507,14279,7198,15314,9675,15313,9683,15309,9712,15298,9759,15277,9797,15229,9773,15166,9668,15084,9487,14995,9274,14898,8910,14800,8539,14697,8234,14590,7790,14479,7409,14367,7067,14178,6621,15337,8619,15337,8631,15333,8677,15325,8769,15305,8871,15264,8940,15202,8909,15119,8775,15022,8565,14916,8328,14804,8009,14688,7614,14569,7287,14448,6888,14321,6483,14088,6171,15350,7402,15350,7419,15347,7480,15340,7613,15322,7804,15287,7973,15229,8057,15148,8012,15046,7846,14933,7611,14810,7357,14682,7069,14552,6656,14421,6316,14251,5948,14007,5528,15356,5942,15356,5977,15353,6119,15348,6294,15332,6551,15302,6824,15249,7044,15171,7122,15070,7050,14949,6861,14818,6611,14679,6349,14538,6067,14398,5651,14189,5311,13935,4958,15359,4123,15359,4153,15356,4296,15353,4646,15338,5160,15311,5508,15263,5829,15188,6042,15088,6094,14966,6001,14826,5796,14678,5543,14527,5287,14377,4985,14133,4586,13869,4257,15360,1563,15360,1642,15358,2076,15354,2636,15341,3350,15317,4019,15273,4429,15203,4732,15105,4911,14981,4932,14836,4818,14679,4621,14517,4386,14359,4156,14083,3795,13808,3437,15360,122,15360,137,15358,285,15355,636,15344,1274,15322,2177,15281,2765,15215,3223,15120,3451,14995,3569,14846,3567,14681,3466,14511,3305,14344,3121,14037,2800,13753,2467,15360,0,15360,1,15359,21,15355,89,15346,253,15325,479,15287,796,15225,1148,15133,1492,15008,1749,14856,1882,14685,1886,14506,1783,14324,1608,13996,1398,13702,1183]);let An=null;function nx(){return An===null&&(An=new va(tx,16,16,xs,on),An.name="DFG_LUT",An.minFilter=Ct,An.magFilter=Ct,An.wrapS=Dn,An.wrapT=Dn,An.generateMipmaps=!1,An.needsUpdate=!0),An}class Yu{constructor(e={}){const{canvas:t=Rf(),context:n=null,depth:i=!0,stencil:r=!1,alpha:a=!1,antialias:o=!1,premultipliedAlpha:l=!0,preserveDrawingBuffer:c=!1,powerPreference:h="default",failIfMajorPerformanceCaveat:u=!1,reversedDepthBuffer:d=!1,outputBufferType:f=nn}=e;this.isWebGLRenderer=!0;let g;if(n!==null){if(typeof WebGLRenderingContext<"u"&&n instanceof WebGLRenderingContext)throw new Error("THREE.WebGLRenderer: WebGL 1 is not supported since r163.");g=n.getContextAttributes().alpha}else g=a;const x=f,p=new Set([Xl,Wl,Gl]),m=new Set([nn,Fn,Qs,vs,zl,Hl]),S=new Uint32Array(4),T=new Int32Array(4);let M=null,E=null;const w=[],C=[];let v=null;this.domElement=t,this.debug={checkShaderErrors:!0,onShaderError:null},this.autoClear=!0,this.autoClearColor=!0,this.autoClearDepth=!0,this.autoClearStencil=!0,this.sortObjects=!0,this.clippingPlanes=[],this.localClippingEnabled=!1,this.toneMapping=Un,this.toneMappingExposure=1,this.transmissionResolutionScale=1;const b=this;let D=!1;this._outputColorSpace=wt;let R=0,F=0,O=null,X=-1,V=null;const k=new mt,U=new mt;let Q=null;const K=new Ie(0);let se=0,he=t.width,le=t.height,$=1,ce=null,Re=null;const G=new mt(0,0,he,le),Z=new mt(0,0,he,le);let ee=!1;const we=new tc;let ve=!1,Fe=!1;const Mt=new Ve,qe=new L,Ze=new mt,Qe={background:null,fog:null,environment:null,overrideMaterial:null,isScene:!0};let ke=!1;function pt(){return O===null?$:1}let P=n;function gt(y,B){return t.getContext(y,B)}try{const y={alpha:!0,depth:i,stencil:r,antialias:o,premultipliedAlpha:l,preserveDrawingBuffer:c,powerPreference:h,failIfMajorPerformanceCaveat:u};if("setAttribute"in t&&t.setAttribute("data-engine",`three.js r${Ll}`),t.addEventListener("webglcontextlost",be,!1),t.addEventListener("webglcontextrestored",Be,!1),t.addEventListener("webglcontextcreationerror",dt,!1),P===null){const B="webgl2";if(P=gt(B,y),P===null)throw gt(B)?new Error("Error creating WebGL context with your selected attributes."):new Error("Error creating WebGL context.")}}catch(y){throw Ue("WebGLRenderer: "+y.message),y}let $e,et,Me,A,_,N,j,J,Y,ge,re,Ee,Ne,te,ae,ye,Se,fe,Oe,I,oe,ne,xe;function ie(){$e=new i_(P),$e.init(),oe=new qv(P,$e),et=new K0(P,$e,e,oe),Me=new Xv(P,$e),et.reversedDepthBuffer&&d&&Me.buffers.depth.setReversed(!0),A=new a_(P),_=new Dv,N=new Yv(P,$e,Me,_,et,oe,A),j=new n_(b),J=new um(P),ne=new q0(P,J),Y=new s_(P,J,A,ne),ge=new l_(P,Y,J,ne,A),fe=new o_(P,et,N),ae=new $0(_),re=new Pv(b,j,$e,et,ne,ae),Ee=new Qv(b,_),Ne=new Iv,te=new kv($e),Se=new Y0(b,j,Me,ge,g,l),ye=new Wv(b,ge,et),xe=new ex(P,A,et,Me),Oe=new j0(P,$e,A),I=new r_(P,$e,A),A.programs=re.programs,b.capabilities=et,b.extensions=$e,b.properties=_,b.renderLists=Ne,b.shadowMap=ye,b.state=Me,b.info=A}ie(),x!==nn&&(v=new h_(x,t.width,t.height,i,r));const q=new Zv(b,P);this.xr=q,this.getContext=function(){return P},this.getContextAttributes=function(){return P.getContextAttributes()},this.forceContextLoss=function(){const y=$e.get("WEBGL_lose_context");y&&y.loseContext()},this.forceContextRestore=function(){const y=$e.get("WEBGL_lose_context");y&&y.restoreContext()},this.getPixelRatio=function(){return $},this.setPixelRatio=function(y){y!==void 0&&($=y,this.setSize(he,le,!1))},this.getSize=function(y){return y.set(he,le)},this.setSize=function(y,B,W=!0){if(q.isPresenting){Pe("WebGLRenderer: Can't change size while VR device is presenting.");return}he=y,le=B,t.width=Math.floor(y*$),t.height=Math.floor(B*$),W===!0&&(t.style.width=y+"px",t.style.height=B+"px"),v!==null&&v.setSize(t.width,t.height),this.setViewport(0,0,y,B)},this.getDrawingBufferSize=function(y){return y.set(he*$,le*$).floor()},this.setDrawingBufferSize=function(y,B,W){he=y,le=B,$=W,t.width=Math.floor(y*W),t.height=Math.floor(B*W),this.setViewport(0,0,y,B)},this.setEffects=function(y){if(x===nn){console.error("THREE.WebGLRenderer: setEffects() requires outputBufferType set to HalfFloatType or FloatType.");return}if(y){for(let B=0;B<y.length;B++)if(y[B].isOutputPass===!0){console.warn("THREE.WebGLRenderer: OutputPass is not needed in setEffects(). Tone mapping and color space conversion are applied automatically.");break}}v.setEffects(y||[])},this.getCurrentViewport=function(y){return y.copy(k)},this.getViewport=function(y){return y.copy(G)},this.setViewport=function(y,B,W,H){y.isVector4?G.set(y.x,y.y,y.z,y.w):G.set(y,B,W,H),Me.viewport(k.copy(G).multiplyScalar($).round())},this.getScissor=function(y){return y.copy(Z)},this.setScissor=function(y,B,W,H){y.isVector4?Z.set(y.x,y.y,y.z,y.w):Z.set(y,B,W,H),Me.scissor(U.copy(Z).multiplyScalar($).round())},this.getScissorTest=function(){return ee},this.setScissorTest=function(y){Me.setScissorTest(ee=y)},this.setOpaqueSort=function(y){ce=y},this.setTransparentSort=function(y){Re=y},this.getClearColor=function(y){return y.copy(Se.getClearColor())},this.setClearColor=function(){Se.setClearColor(...arguments)},this.getClearAlpha=function(){return Se.getClearAlpha()},this.setClearAlpha=function(){Se.setClearAlpha(...arguments)},this.clear=function(y=!0,B=!0,W=!0){let H=0;if(y){let z=!1;if(O!==null){const pe=O.texture.format;z=p.has(pe)}if(z){const pe=O.texture.type,_e=m.has(pe),me=Se.getClearColor(),Te=Se.getClearAlpha(),Ce=me.r,ze=me.g,We=me.b;_e?(S[0]=Ce,S[1]=ze,S[2]=We,S[3]=Te,P.clearBufferuiv(P.COLOR,0,S)):(T[0]=Ce,T[1]=ze,T[2]=We,T[3]=Te,P.clearBufferiv(P.COLOR,0,T))}else H|=P.COLOR_BUFFER_BIT}B&&(H|=P.DEPTH_BUFFER_BIT),W&&(H|=P.STENCIL_BUFFER_BIT,this.state.buffers.stencil.setMask(4294967295)),H!==0&&P.clear(H)},this.clearColor=function(){this.clear(!0,!1,!1)},this.clearDepth=function(){this.clear(!1,!0,!1)},this.clearStencil=function(){this.clear(!1,!1,!0)},this.dispose=function(){t.removeEventListener("webglcontextlost",be,!1),t.removeEventListener("webglcontextrestored",Be,!1),t.removeEventListener("webglcontextcreationerror",dt,!1),Se.dispose(),Ne.dispose(),te.dispose(),_.dispose(),j.dispose(),ge.dispose(),ne.dispose(),xe.dispose(),re.dispose(),q.dispose(),q.removeEventListener("sessionstart",fc),q.removeEventListener("sessionend",pc),xi.stop()};function be(y){y.preventDefault(),sa("WebGLRenderer: Context Lost."),D=!0}function Be(){sa("WebGLRenderer: Context Restored."),D=!1;const y=A.autoReset,B=ye.enabled,W=ye.autoUpdate,H=ye.needsUpdate,z=ye.type;ie(),A.autoReset=y,ye.enabled=B,ye.autoUpdate=W,ye.needsUpdate=H,ye.type=z}function dt(y){Ue("WebGLRenderer: A WebGL context could not be created. Reason: ",y.statusMessage)}function nt(y){const B=y.target;B.removeEventListener("dispose",nt),kn(B)}function kn(y){Vn(y),_.remove(y)}function Vn(y){const B=_.get(y).programs;B!==void 0&&(B.forEach(function(W){re.releaseProgram(W)}),y.isShaderMaterial&&re.releaseShaderCache(y))}this.renderBufferDirect=function(y,B,W,H,z,pe){B===null&&(B=Qe);const _e=z.isMesh&&z.matrixWorld.determinant()<0,me=bd(y,B,W,H,z);Me.setMaterial(H,_e);let Te=W.index,Ce=1;if(H.wireframe===!0){if(Te=Y.getWireframeAttribute(W),Te===void 0)return;Ce=2}const ze=W.drawRange,We=W.attributes.position;let De=ze.start*Ce,rt=(ze.start+ze.count)*Ce;pe!==null&&(De=Math.max(De,pe.start*Ce),rt=Math.min(rt,(pe.start+pe.count)*Ce)),Te!==null?(De=Math.max(De,0),rt=Math.min(rt,Te.count)):We!=null&&(De=Math.max(De,0),rt=Math.min(rt,We.count));const bt=rt-De;if(bt<0||bt===1/0)return;ne.setup(z,H,me,W,Te);let yt,at=Oe;if(Te!==null&&(yt=J.get(Te),at=I,at.setIndex(yt)),z.isMesh)H.wireframe===!0?(Me.setLineWidth(H.wireframeLinewidth*pt()),at.setMode(P.LINES)):at.setMode(P.TRIANGLES);else if(z.isLine){let zt=H.linewidth;zt===void 0&&(zt=1),Me.setLineWidth(zt*pt()),z.isLineSegments?at.setMode(P.LINES):z.isLineLoop?at.setMode(P.LINE_LOOP):at.setMode(P.LINE_STRIP)}else z.isPoints?at.setMode(P.POINTS):z.isSprite&&at.setMode(P.TRIANGLES);if(z.isBatchedMesh)if(z._multiDrawInstances!==null)ra("WebGLRenderer: renderMultiDrawInstances has been deprecated and will be removed in r184. Append to renderMultiDraw arguments and use indirection."),at.renderMultiDrawInstances(z._multiDrawStarts,z._multiDrawCounts,z._multiDrawCount,z._multiDrawInstances);else if($e.get("WEBGL_multi_draw"))at.renderMultiDraw(z._multiDrawStarts,z._multiDrawCounts,z._multiDrawCount);else{const zt=z._multiDrawStarts,Ae=z._multiDrawCounts,Qt=z._multiDrawCount,Je=Te?J.get(Te).bytesPerElement:1,fn=_.get(H).currentProgram.getUniforms();for(let En=0;En<Qt;En++)fn.setValue(P,"_gl_DrawID",En),at.render(zt[En]/Je,Ae[En])}else if(z.isInstancedMesh)at.renderInstances(De,bt,z.count);else if(W.isInstancedBufferGeometry){const zt=W._maxInstanceCount!==void 0?W._maxInstanceCount:1/0,Ae=Math.min(W.instanceCount,zt);at.renderInstances(De,bt,Ae)}else at.render(De,bt)};function dc(y,B,W){y.transparent===!0&&y.side===Pn&&y.forceSinglePass===!1?(y.side=qt,y.needsUpdate=!0,cr(y,B,W),y.side=Zn,y.needsUpdate=!0,cr(y,B,W),y.side=Pn):cr(y,B,W)}this.compile=function(y,B,W=null){W===null&&(W=y),E=te.get(W),E.init(B),C.push(E),W.traverseVisible(function(z){z.isLight&&z.layers.test(B.layers)&&(E.pushLight(z),z.castShadow&&E.pushShadow(z))}),y!==W&&y.traverseVisible(function(z){z.isLight&&z.layers.test(B.layers)&&(E.pushLight(z),z.castShadow&&E.pushShadow(z))}),E.setupLights();const H=new Set;return y.traverse(function(z){if(!(z.isMesh||z.isPoints||z.isLine||z.isSprite))return;const pe=z.material;if(pe)if(Array.isArray(pe))for(let _e=0;_e<pe.length;_e++){const me=pe[_e];dc(me,W,z),H.add(me)}else dc(pe,W,z),H.add(pe)}),E=C.pop(),H},this.compileAsync=function(y,B,W=null){const H=this.compile(y,B,W);return new Promise(z=>{function pe(){if(H.forEach(function(_e){_.get(_e).currentProgram.isReady()&&H.delete(_e)}),H.size===0){z(y);return}setTimeout(pe,10)}$e.get("KHR_parallel_shader_compile")!==null?pe():setTimeout(pe,10)})};let Ea=null;function Sd(y){Ea&&Ea(y)}function fc(){xi.stop()}function pc(){xi.start()}const xi=new Vu;xi.setAnimationLoop(Sd),typeof self<"u"&&xi.setContext(self),this.setAnimationLoop=function(y){Ea=y,q.setAnimationLoop(y),y===null?xi.stop():xi.start()},q.addEventListener("sessionstart",fc),q.addEventListener("sessionend",pc),this.render=function(y,B){if(B!==void 0&&B.isCamera!==!0){Ue("WebGLRenderer.render: camera is not an instance of THREE.Camera.");return}if(D===!0)return;const W=q.enabled===!0&&q.isPresenting===!0,H=v!==null&&(O===null||W)&&v.begin(b,O);if(y.matrixWorldAutoUpdate===!0&&y.updateMatrixWorld(),B.parent===null&&B.matrixWorldAutoUpdate===!0&&B.updateMatrixWorld(),q.enabled===!0&&q.isPresenting===!0&&(v===null||v.isCompositing()===!1)&&(q.cameraAutoUpdate===!0&&q.updateCamera(B),B=q.getCamera()),y.isScene===!0&&y.onBeforeRender(b,y,B,O),E=te.get(y,C.length),E.init(B),C.push(E),Mt.multiplyMatrices(B.projectionMatrix,B.matrixWorldInverse),we.setFromProjectionMatrix(Mt,Ln,B.reversedDepth),Fe=this.localClippingEnabled,ve=ae.init(this.clippingPlanes,Fe),M=Ne.get(y,w.length),M.init(),w.push(M),q.enabled===!0&&q.isPresenting===!0){const _e=b.xr.getDepthSensingMesh();_e!==null&&Ta(_e,B,-1/0,b.sortObjects)}Ta(y,B,0,b.sortObjects),M.finish(),b.sortObjects===!0&&M.sort(ce,Re),ke=q.enabled===!1||q.isPresenting===!1||q.hasDepthSensing()===!1,ke&&Se.addToRenderList(M,y),this.info.render.frame++,ve===!0&&ae.beginShadows();const z=E.state.shadowsArray;if(ye.render(z,y,B),ve===!0&&ae.endShadows(),this.info.autoReset===!0&&this.info.reset(),(H&&v.hasRenderPass())===!1){const _e=M.opaque,me=M.transmissive;if(E.setupLights(),B.isArrayCamera){const Te=B.cameras;if(me.length>0)for(let Ce=0,ze=Te.length;Ce<ze;Ce++){const We=Te[Ce];gc(_e,me,y,We)}ke&&Se.render(y);for(let Ce=0,ze=Te.length;Ce<ze;Ce++){const We=Te[Ce];mc(M,y,We,We.viewport)}}else me.length>0&&gc(_e,me,y,B),ke&&Se.render(y),mc(M,y,B)}O!==null&&F===0&&(N.updateMultisampleRenderTarget(O),N.updateRenderTargetMipmap(O)),H&&v.end(b),y.isScene===!0&&y.onAfterRender(b,y,B),ne.resetDefaultState(),X=-1,V=null,C.pop(),C.length>0?(E=C[C.length-1],ve===!0&&ae.setGlobalState(b.clippingPlanes,E.state.camera)):E=null,w.pop(),w.length>0?M=w[w.length-1]:M=null};function Ta(y,B,W,H){if(y.visible===!1)return;if(y.layers.test(B.layers)){if(y.isGroup)W=y.renderOrder;else if(y.isLOD)y.autoUpdate===!0&&y.update(B);else if(y.isLight)E.pushLight(y),y.castShadow&&E.pushShadow(y);else if(y.isSprite){if(!y.frustumCulled||we.intersectsSprite(y)){H&&Ze.setFromMatrixPosition(y.matrixWorld).applyMatrix4(Mt);const _e=ge.update(y),me=y.material;me.visible&&M.push(y,_e,me,W,Ze.z,null)}}else if((y.isMesh||y.isLine||y.isPoints)&&(!y.frustumCulled||we.intersectsObject(y))){const _e=ge.update(y),me=y.material;if(H&&(y.boundingSphere!==void 0?(y.boundingSphere===null&&y.computeBoundingSphere(),Ze.copy(y.boundingSphere.center)):(_e.boundingSphere===null&&_e.computeBoundingSphere(),Ze.copy(_e.boundingSphere.center)),Ze.applyMatrix4(y.matrixWorld).applyMatrix4(Mt)),Array.isArray(me)){const Te=_e.groups;for(let Ce=0,ze=Te.length;Ce<ze;Ce++){const We=Te[Ce],De=me[We.materialIndex];De&&De.visible&&M.push(y,_e,De,W,Ze.z,We)}}else me.visible&&M.push(y,_e,me,W,Ze.z,null)}}const pe=y.children;for(let _e=0,me=pe.length;_e<me;_e++)Ta(pe[_e],B,W,H)}function mc(y,B,W,H){const{opaque:z,transmissive:pe,transparent:_e}=y;E.setupLightsView(W),ve===!0&&ae.setGlobalState(b.clippingPlanes,W),H&&Me.viewport(k.copy(H)),z.length>0&&lr(z,B,W),pe.length>0&&lr(pe,B,W),_e.length>0&&lr(_e,B,W),Me.buffers.depth.setTest(!0),Me.buffers.depth.setMask(!0),Me.buffers.color.setMask(!0),Me.setPolygonOffset(!1)}function gc(y,B,W,H){if((W.isScene===!0?W.overrideMaterial:null)!==null)return;if(E.state.transmissionRenderTarget[H.id]===void 0){const De=$e.has("EXT_color_buffer_half_float")||$e.has("EXT_color_buffer_float");E.state.transmissionRenderTarget[H.id]=new Jt(1,1,{generateMipmaps:!0,type:De?on:nn,minFilter:jn,samples:Math.max(4,et.samples),stencilBuffer:r,resolveDepthBuffer:!1,resolveStencilBuffer:!1,colorSpace:Ke.workingColorSpace})}const pe=E.state.transmissionRenderTarget[H.id],_e=H.viewport||k;pe.setSize(_e.z*b.transmissionResolutionScale,_e.w*b.transmissionResolutionScale);const me=b.getRenderTarget(),Te=b.getActiveCubeFace(),Ce=b.getActiveMipmapLevel();b.setRenderTarget(pe),b.getClearColor(K),se=b.getClearAlpha(),se<1&&b.setClearColor(16777215,.5),b.clear(),ke&&Se.render(W);const ze=b.toneMapping;b.toneMapping=Un;const We=H.viewport;if(H.viewport!==void 0&&(H.viewport=void 0),E.setupLightsView(H),ve===!0&&ae.setGlobalState(b.clippingPlanes,H),lr(y,W,H),N.updateMultisampleRenderTarget(pe),N.updateRenderTargetMipmap(pe),$e.has("WEBGL_multisampled_render_to_texture")===!1){let De=!1;for(let rt=0,bt=B.length;rt<bt;rt++){const yt=B[rt],{object:at,geometry:zt,material:Ae,group:Qt}=yt;if(Ae.side===Pn&&at.layers.test(H.layers)){const Je=Ae.side;Ae.side=qt,Ae.needsUpdate=!0,_c(at,W,H,zt,Ae,Qt),Ae.side=Je,Ae.needsUpdate=!0,De=!0}}De===!0&&(N.updateMultisampleRenderTarget(pe),N.updateRenderTargetMipmap(pe))}b.setRenderTarget(me,Te,Ce),b.setClearColor(K,se),We!==void 0&&(H.viewport=We),b.toneMapping=ze}function lr(y,B,W){const H=B.isScene===!0?B.overrideMaterial:null;for(let z=0,pe=y.length;z<pe;z++){const _e=y[z],{object:me,geometry:Te,group:Ce}=_e;let ze=_e.material;ze.allowOverride===!0&&H!==null&&(ze=H),me.layers.test(W.layers)&&_c(me,B,W,Te,ze,Ce)}}function _c(y,B,W,H,z,pe){y.onBeforeRender(b,B,W,H,z,pe),y.modelViewMatrix.multiplyMatrices(W.matrixWorldInverse,y.matrixWorld),y.normalMatrix.getNormalMatrix(y.modelViewMatrix),z.onBeforeRender(b,B,W,H,y,pe),z.transparent===!0&&z.side===Pn&&z.forceSinglePass===!1?(z.side=qt,z.needsUpdate=!0,b.renderBufferDirect(W,B,H,z,y,pe),z.side=Zn,z.needsUpdate=!0,b.renderBufferDirect(W,B,H,z,y,pe),z.side=Pn):b.renderBufferDirect(W,B,H,z,y,pe),y.onAfterRender(b,B,W,H,z,pe)}function cr(y,B,W){B.isScene!==!0&&(B=Qe);const H=_.get(y),z=E.state.lights,pe=E.state.shadowsArray,_e=z.state.version,me=re.getParameters(y,z.state,pe,B,W),Te=re.getProgramCacheKey(me);let Ce=H.programs;H.environment=y.isMeshStandardMaterial||y.isMeshLambertMaterial||y.isMeshPhongMaterial?B.environment:null,H.fog=B.fog;const ze=y.isMeshStandardMaterial||y.isMeshLambertMaterial&&!y.envMap||y.isMeshPhongMaterial&&!y.envMap;H.envMap=j.get(y.envMap||H.environment,ze),H.envMapRotation=H.environment!==null&&y.envMap===null?B.environmentRotation:y.envMapRotation,Ce===void 0&&(y.addEventListener("dispose",nt),Ce=new Map,H.programs=Ce);let We=Ce.get(Te);if(We!==void 0){if(H.currentProgram===We&&H.lightsStateVersion===_e)return xc(y,me),We}else me.uniforms=re.getUniforms(y),y.onBeforeCompile(me,b),We=re.acquireProgram(me,Te),Ce.set(Te,We),H.uniforms=me.uniforms;const De=H.uniforms;return(!y.isShaderMaterial&&!y.isRawShaderMaterial||y.clipping===!0)&&(De.clippingPlanes=ae.uniform),xc(y,me),H.needsLights=Td(y),H.lightsStateVersion=_e,H.needsLights&&(De.ambientLightColor.value=z.state.ambient,De.lightProbe.value=z.state.probe,De.directionalLights.value=z.state.directional,De.directionalLightShadows.value=z.state.directionalShadow,De.spotLights.value=z.state.spot,De.spotLightShadows.value=z.state.spotShadow,De.rectAreaLights.value=z.state.rectArea,De.ltc_1.value=z.state.rectAreaLTC1,De.ltc_2.value=z.state.rectAreaLTC2,De.pointLights.value=z.state.point,De.pointLightShadows.value=z.state.pointShadow,De.hemisphereLights.value=z.state.hemi,De.directionalShadowMatrix.value=z.state.directionalShadowMatrix,De.spotLightMatrix.value=z.state.spotLightMatrix,De.spotLightMap.value=z.state.spotLightMap,De.pointShadowMatrix.value=z.state.pointShadowMatrix),H.currentProgram=We,H.uniformsList=null,We}function vc(y){if(y.uniformsList===null){const B=y.currentProgram.getUniforms();y.uniformsList=Qr.seqWithValue(B.seq,y.uniforms)}return y.uniformsList}function xc(y,B){const W=_.get(y);W.outputColorSpace=B.outputColorSpace,W.batching=B.batching,W.batchingColor=B.batchingColor,W.instancing=B.instancing,W.instancingColor=B.instancingColor,W.instancingMorph=B.instancingMorph,W.skinning=B.skinning,W.morphTargets=B.morphTargets,W.morphNormals=B.morphNormals,W.morphColors=B.morphColors,W.morphTargetsCount=B.morphTargetsCount,W.numClippingPlanes=B.numClippingPlanes,W.numIntersection=B.numClipIntersection,W.vertexAlphas=B.vertexAlphas,W.vertexTangents=B.vertexTangents,W.toneMapping=B.toneMapping}function bd(y,B,W,H,z){B.isScene!==!0&&(B=Qe),N.resetTextureUnits();const pe=B.fog,_e=H.isMeshStandardMaterial||H.isMeshLambertMaterial||H.isMeshPhongMaterial?B.environment:null,me=O===null?b.outputColorSpace:O.isXRRenderTarget===!0?O.texture.colorSpace:Kt,Te=H.isMeshStandardMaterial||H.isMeshLambertMaterial&&!H.envMap||H.isMeshPhongMaterial&&!H.envMap,Ce=j.get(H.envMap||_e,Te),ze=H.vertexColors===!0&&!!W.attributes.color&&W.attributes.color.itemSize===4,We=!!W.attributes.tangent&&(!!H.normalMap||H.anisotropy>0),De=!!W.morphAttributes.position,rt=!!W.morphAttributes.normal,bt=!!W.morphAttributes.color;let yt=Un;H.toneMapped&&(O===null||O.isXRRenderTarget===!0)&&(yt=b.toneMapping);const at=W.morphAttributes.position||W.morphAttributes.normal||W.morphAttributes.color,zt=at!==void 0?at.length:0,Ae=_.get(H),Qt=E.state.lights;if(ve===!0&&(Fe===!0||y!==V)){const It=y===V&&H.id===X;ae.setState(H,y,It)}let Je=!1;H.version===Ae.__version?(Ae.needsLights&&Ae.lightsStateVersion!==Qt.state.version||Ae.outputColorSpace!==me||z.isBatchedMesh&&Ae.batching===!1||!z.isBatchedMesh&&Ae.batching===!0||z.isBatchedMesh&&Ae.batchingColor===!0&&z.colorTexture===null||z.isBatchedMesh&&Ae.batchingColor===!1&&z.colorTexture!==null||z.isInstancedMesh&&Ae.instancing===!1||!z.isInstancedMesh&&Ae.instancing===!0||z.isSkinnedMesh&&Ae.skinning===!1||!z.isSkinnedMesh&&Ae.skinning===!0||z.isInstancedMesh&&Ae.instancingColor===!0&&z.instanceColor===null||z.isInstancedMesh&&Ae.instancingColor===!1&&z.instanceColor!==null||z.isInstancedMesh&&Ae.instancingMorph===!0&&z.morphTexture===null||z.isInstancedMesh&&Ae.instancingMorph===!1&&z.morphTexture!==null||Ae.envMap!==Ce||H.fog===!0&&Ae.fog!==pe||Ae.numClippingPlanes!==void 0&&(Ae.numClippingPlanes!==ae.numPlanes||Ae.numIntersection!==ae.numIntersection)||Ae.vertexAlphas!==ze||Ae.vertexTangents!==We||Ae.morphTargets!==De||Ae.morphNormals!==rt||Ae.morphColors!==bt||Ae.toneMapping!==yt||Ae.morphTargetsCount!==zt)&&(Je=!0):(Je=!0,Ae.__version=H.version);let fn=Ae.currentProgram;Je===!0&&(fn=cr(H,B,z));let En=!1,Mi=!1,Bi=!1;const ct=fn.getUniforms(),Ft=Ae.uniforms;if(Me.useProgram(fn.program)&&(En=!0,Mi=!0,Bi=!0),H.id!==X&&(X=H.id,Mi=!0),En||V!==y){Me.buffers.depth.getReversed()&&y.reversedDepth!==!0&&(y._reversedDepth=!0,y.updateProjectionMatrix()),ct.setValue(P,"projectionMatrix",y.projectionMatrix),ct.setValue(P,"viewMatrix",y.matrixWorldInverse);const ti=ct.map.cameraPosition;ti!==void 0&&ti.setValue(P,qe.setFromMatrixPosition(y.matrixWorld)),et.logarithmicDepthBuffer&&ct.setValue(P,"logDepthBufFC",2/(Math.log(y.far+1)/Math.LN2)),(H.isMeshPhongMaterial||H.isMeshToonMaterial||H.isMeshLambertMaterial||H.isMeshBasicMaterial||H.isMeshStandardMaterial||H.isShaderMaterial)&&ct.setValue(P,"isOrthographic",y.isOrthographicCamera===!0),V!==y&&(V=y,Mi=!0,Bi=!0)}if(Ae.needsLights&&(Qt.state.directionalShadowMap.length>0&&ct.setValue(P,"directionalShadowMap",Qt.state.directionalShadowMap,N),Qt.state.spotShadowMap.length>0&&ct.setValue(P,"spotShadowMap",Qt.state.spotShadowMap,N),Qt.state.pointShadowMap.length>0&&ct.setValue(P,"pointShadowMap",Qt.state.pointShadowMap,N)),z.isSkinnedMesh){ct.setOptional(P,z,"bindMatrix"),ct.setOptional(P,z,"bindMatrixInverse");const It=z.skeleton;It&&(It.boneTexture===null&&It.computeBoneTexture(),ct.setValue(P,"boneTexture",It.boneTexture,N))}z.isBatchedMesh&&(ct.setOptional(P,z,"batchingTexture"),ct.setValue(P,"batchingTexture",z._matricesTexture,N),ct.setOptional(P,z,"batchingIdTexture"),ct.setValue(P,"batchingIdTexture",z._indirectTexture,N),ct.setOptional(P,z,"batchingColorTexture"),z._colorsTexture!==null&&ct.setValue(P,"batchingColorTexture",z._colorsTexture,N));const ei=W.morphAttributes;if((ei.position!==void 0||ei.normal!==void 0||ei.color!==void 0)&&fe.update(z,W,fn),(Mi||Ae.receiveShadow!==z.receiveShadow)&&(Ae.receiveShadow=z.receiveShadow,ct.setValue(P,"receiveShadow",z.receiveShadow)),(H.isMeshStandardMaterial||H.isMeshLambertMaterial||H.isMeshPhongMaterial)&&H.envMap===null&&B.environment!==null&&(Ft.envMapIntensity.value=B.environmentIntensity),Ft.dfgLUT!==void 0&&(Ft.dfgLUT.value=nx()),Mi&&(ct.setValue(P,"toneMappingExposure",b.toneMappingExposure),Ae.needsLights&&Ed(Ft,Bi),pe&&H.fog===!0&&Ee.refreshFogUniforms(Ft,pe),Ee.refreshMaterialUniforms(Ft,H,$,le,E.state.transmissionRenderTarget[y.id]),Qr.upload(P,vc(Ae),Ft,N)),H.isShaderMaterial&&H.uniformsNeedUpdate===!0&&(Qr.upload(P,vc(Ae),Ft,N),H.uniformsNeedUpdate=!1),H.isSpriteMaterial&&ct.setValue(P,"center",z.center),ct.setValue(P,"modelViewMatrix",z.modelViewMatrix),ct.setValue(P,"normalMatrix",z.normalMatrix),ct.setValue(P,"modelMatrix",z.matrixWorld),H.isShaderMaterial||H.isRawShaderMaterial){const It=H.uniformsGroups;for(let ti=0,ki=It.length;ti<ki;ti++){const Mc=It[ti];xe.update(Mc,fn),xe.bind(Mc,fn)}}return fn}function Ed(y,B){y.ambientLightColor.needsUpdate=B,y.lightProbe.needsUpdate=B,y.directionalLights.needsUpdate=B,y.directionalLightShadows.needsUpdate=B,y.pointLights.needsUpdate=B,y.pointLightShadows.needsUpdate=B,y.spotLights.needsUpdate=B,y.spotLightShadows.needsUpdate=B,y.rectAreaLights.needsUpdate=B,y.hemisphereLights.needsUpdate=B}function Td(y){return y.isMeshLambertMaterial||y.isMeshToonMaterial||y.isMeshPhongMaterial||y.isMeshStandardMaterial||y.isShadowMaterial||y.isShaderMaterial&&y.lights===!0}this.getActiveCubeFace=function(){return R},this.getActiveMipmapLevel=function(){return F},this.getRenderTarget=function(){return O},this.setRenderTargetTextures=function(y,B,W){const H=_.get(y);H.__autoAllocateDepthBuffer=y.resolveDepthBuffer===!1,H.__autoAllocateDepthBuffer===!1&&(H.__useRenderToTexture=!1),_.get(y.texture).__webglTexture=B,_.get(y.depthTexture).__webglTexture=H.__autoAllocateDepthBuffer?void 0:W,H.__hasExternalTextures=!0},this.setRenderTargetFramebuffer=function(y,B){const W=_.get(y);W.__webglFramebuffer=B,W.__useDefaultFramebuffer=B===void 0};const Ad=P.createFramebuffer();this.setRenderTarget=function(y,B=0,W=0){O=y,R=B,F=W;let H=null,z=!1,pe=!1;if(y){const me=_.get(y);if(me.__useDefaultFramebuffer!==void 0){Me.bindFramebuffer(P.FRAMEBUFFER,me.__webglFramebuffer),k.copy(y.viewport),U.copy(y.scissor),Q=y.scissorTest,Me.viewport(k),Me.scissor(U),Me.setScissorTest(Q),X=-1;return}else if(me.__webglFramebuffer===void 0)N.setupRenderTarget(y);else if(me.__hasExternalTextures)N.rebindTextures(y,_.get(y.texture).__webglTexture,_.get(y.depthTexture).__webglTexture);else if(y.depthBuffer){const ze=y.depthTexture;if(me.__boundDepthTexture!==ze){if(ze!==null&&_.has(ze)&&(y.width!==ze.image.width||y.height!==ze.image.height))throw new Error("WebGLRenderTarget: Attached DepthTexture is initialized to the incorrect size.");N.setupDepthRenderbuffer(y)}}const Te=y.texture;(Te.isData3DTexture||Te.isDataArrayTexture||Te.isCompressedArrayTexture)&&(pe=!0);const Ce=_.get(y).__webglFramebuffer;y.isWebGLCubeRenderTarget?(Array.isArray(Ce[B])?H=Ce[B][W]:H=Ce[B],z=!0):y.samples>0&&N.useMultisampledRTT(y)===!1?H=_.get(y).__webglMultisampledFramebuffer:Array.isArray(Ce)?H=Ce[W]:H=Ce,k.copy(y.viewport),U.copy(y.scissor),Q=y.scissorTest}else k.copy(G).multiplyScalar($).floor(),U.copy(Z).multiplyScalar($).floor(),Q=ee;if(W!==0&&(H=Ad),Me.bindFramebuffer(P.FRAMEBUFFER,H)&&Me.drawBuffers(y,H),Me.viewport(k),Me.scissor(U),Me.setScissorTest(Q),z){const me=_.get(y.texture);P.framebufferTexture2D(P.FRAMEBUFFER,P.COLOR_ATTACHMENT0,P.TEXTURE_CUBE_MAP_POSITIVE_X+B,me.__webglTexture,W)}else if(pe){const me=B;for(let Te=0;Te<y.textures.length;Te++){const Ce=_.get(y.textures[Te]);P.framebufferTextureLayer(P.FRAMEBUFFER,P.COLOR_ATTACHMENT0+Te,Ce.__webglTexture,W,me)}}else if(y!==null&&W!==0){const me=_.get(y.texture);P.framebufferTexture2D(P.FRAMEBUFFER,P.COLOR_ATTACHMENT0,P.TEXTURE_2D,me.__webglTexture,W)}X=-1},this.readRenderTargetPixels=function(y,B,W,H,z,pe,_e,me=0){if(!(y&&y.isWebGLRenderTarget)){Ue("WebGLRenderer.readRenderTargetPixels: renderTarget is not THREE.WebGLRenderTarget.");return}let Te=_.get(y).__webglFramebuffer;if(y.isWebGLCubeRenderTarget&&_e!==void 0&&(Te=Te[_e]),Te){Me.bindFramebuffer(P.FRAMEBUFFER,Te);try{const Ce=y.textures[me],ze=Ce.format,We=Ce.type;if(y.textures.length>1&&P.readBuffer(P.COLOR_ATTACHMENT0+me),!et.textureFormatReadable(ze)){Ue("WebGLRenderer.readRenderTargetPixels: renderTarget is not in RGBA or implementation defined format.");return}if(!et.textureTypeReadable(We)){Ue("WebGLRenderer.readRenderTargetPixels: renderTarget is not in UnsignedByteType or implementation defined type.");return}B>=0&&B<=y.width-H&&W>=0&&W<=y.height-z&&P.readPixels(B,W,H,z,oe.convert(ze),oe.convert(We),pe)}finally{const Ce=O!==null?_.get(O).__webglFramebuffer:null;Me.bindFramebuffer(P.FRAMEBUFFER,Ce)}}},this.readRenderTargetPixelsAsync=async function(y,B,W,H,z,pe,_e,me=0){if(!(y&&y.isWebGLRenderTarget))throw new Error("THREE.WebGLRenderer.readRenderTargetPixels: renderTarget is not THREE.WebGLRenderTarget.");let Te=_.get(y).__webglFramebuffer;if(y.isWebGLCubeRenderTarget&&_e!==void 0&&(Te=Te[_e]),Te)if(B>=0&&B<=y.width-H&&W>=0&&W<=y.height-z){Me.bindFramebuffer(P.FRAMEBUFFER,Te);const Ce=y.textures[me],ze=Ce.format,We=Ce.type;if(y.textures.length>1&&P.readBuffer(P.COLOR_ATTACHMENT0+me),!et.textureFormatReadable(ze))throw new Error("THREE.WebGLRenderer.readRenderTargetPixelsAsync: renderTarget is not in RGBA or implementation defined format.");if(!et.textureTypeReadable(We))throw new Error("THREE.WebGLRenderer.readRenderTargetPixelsAsync: renderTarget is not in UnsignedByteType or implementation defined type.");const De=P.createBuffer();P.bindBuffer(P.PIXEL_PACK_BUFFER,De),P.bufferData(P.PIXEL_PACK_BUFFER,pe.byteLength,P.STREAM_READ),P.readPixels(B,W,H,z,oe.convert(ze),oe.convert(We),0);const rt=O!==null?_.get(O).__webglFramebuffer:null;Me.bindFramebuffer(P.FRAMEBUFFER,rt);const bt=P.fenceSync(P.SYNC_GPU_COMMANDS_COMPLETE,0);return P.flush(),await Cf(P,bt,4),P.bindBuffer(P.PIXEL_PACK_BUFFER,De),P.getBufferSubData(P.PIXEL_PACK_BUFFER,0,pe),P.deleteBuffer(De),P.deleteSync(bt),pe}else throw new Error("THREE.WebGLRenderer.readRenderTargetPixelsAsync: requested read bounds are out of range.")},this.copyFramebufferToTexture=function(y,B=null,W=0){const H=Math.pow(2,-W),z=Math.floor(y.image.width*H),pe=Math.floor(y.image.height*H),_e=B!==null?B.x:0,me=B!==null?B.y:0;N.setTexture2D(y,0),P.copyTexSubImage2D(P.TEXTURE_2D,W,0,0,_e,me,z,pe),Me.unbindTexture()};const wd=P.createFramebuffer(),Rd=P.createFramebuffer();this.copyTextureToTexture=function(y,B,W=null,H=null,z=0,pe=0){let _e,me,Te,Ce,ze,We,De,rt,bt;const yt=y.isCompressedTexture?y.mipmaps[pe]:y.image;if(W!==null)_e=W.max.x-W.min.x,me=W.max.y-W.min.y,Te=W.isBox3?W.max.z-W.min.z:1,Ce=W.min.x,ze=W.min.y,We=W.isBox3?W.min.z:0;else{const Ft=Math.pow(2,-z);_e=Math.floor(yt.width*Ft),me=Math.floor(yt.height*Ft),y.isDataArrayTexture?Te=yt.depth:y.isData3DTexture?Te=Math.floor(yt.depth*Ft):Te=1,Ce=0,ze=0,We=0}H!==null?(De=H.x,rt=H.y,bt=H.z):(De=0,rt=0,bt=0);const at=oe.convert(B.format),zt=oe.convert(B.type);let Ae;B.isData3DTexture?(N.setTexture3D(B,0),Ae=P.TEXTURE_3D):B.isDataArrayTexture||B.isCompressedArrayTexture?(N.setTexture2DArray(B,0),Ae=P.TEXTURE_2D_ARRAY):(N.setTexture2D(B,0),Ae=P.TEXTURE_2D),P.pixelStorei(P.UNPACK_FLIP_Y_WEBGL,B.flipY),P.pixelStorei(P.UNPACK_PREMULTIPLY_ALPHA_WEBGL,B.premultiplyAlpha),P.pixelStorei(P.UNPACK_ALIGNMENT,B.unpackAlignment);const Qt=P.getParameter(P.UNPACK_ROW_LENGTH),Je=P.getParameter(P.UNPACK_IMAGE_HEIGHT),fn=P.getParameter(P.UNPACK_SKIP_PIXELS),En=P.getParameter(P.UNPACK_SKIP_ROWS),Mi=P.getParameter(P.UNPACK_SKIP_IMAGES);P.pixelStorei(P.UNPACK_ROW_LENGTH,yt.width),P.pixelStorei(P.UNPACK_IMAGE_HEIGHT,yt.height),P.pixelStorei(P.UNPACK_SKIP_PIXELS,Ce),P.pixelStorei(P.UNPACK_SKIP_ROWS,ze),P.pixelStorei(P.UNPACK_SKIP_IMAGES,We);const Bi=y.isDataArrayTexture||y.isData3DTexture,ct=B.isDataArrayTexture||B.isData3DTexture;if(y.isDepthTexture){const Ft=_.get(y),ei=_.get(B),It=_.get(Ft.__renderTarget),ti=_.get(ei.__renderTarget);Me.bindFramebuffer(P.READ_FRAMEBUFFER,It.__webglFramebuffer),Me.bindFramebuffer(P.DRAW_FRAMEBUFFER,ti.__webglFramebuffer);for(let ki=0;ki<Te;ki++)Bi&&(P.framebufferTextureLayer(P.READ_FRAMEBUFFER,P.COLOR_ATTACHMENT0,_.get(y).__webglTexture,z,We+ki),P.framebufferTextureLayer(P.DRAW_FRAMEBUFFER,P.COLOR_ATTACHMENT0,_.get(B).__webglTexture,pe,bt+ki)),P.blitFramebuffer(Ce,ze,_e,me,De,rt,_e,me,P.DEPTH_BUFFER_BIT,P.NEAREST);Me.bindFramebuffer(P.READ_FRAMEBUFFER,null),Me.bindFramebuffer(P.DRAW_FRAMEBUFFER,null)}else if(z!==0||y.isRenderTargetTexture||_.has(y)){const Ft=_.get(y),ei=_.get(B);Me.bindFramebuffer(P.READ_FRAMEBUFFER,wd),Me.bindFramebuffer(P.DRAW_FRAMEBUFFER,Rd);for(let It=0;It<Te;It++)Bi?P.framebufferTextureLayer(P.READ_FRAMEBUFFER,P.COLOR_ATTACHMENT0,Ft.__webglTexture,z,We+It):P.framebufferTexture2D(P.READ_FRAMEBUFFER,P.COLOR_ATTACHMENT0,P.TEXTURE_2D,Ft.__webglTexture,z),ct?P.framebufferTextureLayer(P.DRAW_FRAMEBUFFER,P.COLOR_ATTACHMENT0,ei.__webglTexture,pe,bt+It):P.framebufferTexture2D(P.DRAW_FRAMEBUFFER,P.COLOR_ATTACHMENT0,P.TEXTURE_2D,ei.__webglTexture,pe),z!==0?P.blitFramebuffer(Ce,ze,_e,me,De,rt,_e,me,P.COLOR_BUFFER_BIT,P.NEAREST):ct?P.copyTexSubImage3D(Ae,pe,De,rt,bt+It,Ce,ze,_e,me):P.copyTexSubImage2D(Ae,pe,De,rt,Ce,ze,_e,me);Me.bindFramebuffer(P.READ_FRAMEBUFFER,null),Me.bindFramebuffer(P.DRAW_FRAMEBUFFER,null)}else ct?y.isDataTexture||y.isData3DTexture?P.texSubImage3D(Ae,pe,De,rt,bt,_e,me,Te,at,zt,yt.data):B.isCompressedArrayTexture?P.compressedTexSubImage3D(Ae,pe,De,rt,bt,_e,me,Te,at,yt.data):P.texSubImage3D(Ae,pe,De,rt,bt,_e,me,Te,at,zt,yt):y.isDataTexture?P.texSubImage2D(P.TEXTURE_2D,pe,De,rt,_e,me,at,zt,yt.data):y.isCompressedTexture?P.compressedTexSubImage2D(P.TEXTURE_2D,pe,De,rt,yt.width,yt.height,at,yt.data):P.texSubImage2D(P.TEXTURE_2D,pe,De,rt,_e,me,at,zt,yt);P.pixelStorei(P.UNPACK_ROW_LENGTH,Qt),P.pixelStorei(P.UNPACK_IMAGE_HEIGHT,Je),P.pixelStorei(P.UNPACK_SKIP_PIXELS,fn),P.pixelStorei(P.UNPACK_SKIP_ROWS,En),P.pixelStorei(P.UNPACK_SKIP_IMAGES,Mi),pe===0&&B.generateMipmaps&&P.generateMipmap(Ae),Me.unbindTexture()},this.initRenderTarget=function(y){_.get(y).__webglFramebuffer===void 0&&N.setupRenderTarget(y)},this.initTexture=function(y){y.isCubeTexture?N.setTextureCube(y,0):y.isData3DTexture?N.setTexture3D(y,0):y.isDataArrayTexture||y.isCompressedArrayTexture?N.setTexture2DArray(y,0):N.setTexture2D(y,0),Me.unbindTexture()},this.resetState=function(){R=0,F=0,O=null,Me.reset(),ne.reset()},typeof __THREE_DEVTOOLS__<"u"&&__THREE_DEVTOOLS__.dispatchEvent(new CustomEvent("observe",{detail:this}))}get coordinateSystem(){return Ln}get outputColorSpace(){return this._outputColorSpace}set outputColorSpace(e){this._outputColorSpace=e;const t=this.getContext();t.drawingBufferColorSpace=Ke._getDrawingBufferColorSpace(e),t.unpackColorSpace=Ke._getUnpackColorSpace()}}function Wh(s,e){if(e===mf)return console.warn("THREE.BufferGeometryUtils.toTrianglesDrawMode(): Geometry already defined as triangles."),s;if(e===gl||e===yu){let t=s.getIndex();if(t===null){const a=[],o=s.getAttribute("position");if(o!==void 0){for(let l=0;l<o.count;l++)a.push(l);s.setIndex(a),t=s.getIndex()}else return console.error("THREE.BufferGeometryUtils.toTrianglesDrawMode(): Undefined position attribute. Processing not possible."),s}const n=t.count-2,i=[];if(e===gl)for(let a=1;a<=n;a++)i.push(t.getX(0)),i.push(t.getX(a)),i.push(t.getX(a+1));else for(let a=0;a<n;a++)a%2===0?(i.push(t.getX(a)),i.push(t.getX(a+1)),i.push(t.getX(a+2))):(i.push(t.getX(a+2)),i.push(t.getX(a+1)),i.push(t.getX(a)));i.length/3!==n&&console.error("THREE.BufferGeometryUtils.toTrianglesDrawMode(): Unable to generate correct amount of triangles.");const r=s.clone();return r.setIndex(i),r.clearGroups(),r}else return console.error("THREE.BufferGeometryUtils.toTrianglesDrawMode(): Unknown draw mode:",e),s}function ix(s){const e=new Map,t=new Map,n=s.clone();return qu(s,n,function(i,r){e.set(r,i),t.set(i,r)}),n.traverse(function(i){if(!i.isSkinnedMesh)return;const r=i,a=e.get(i),o=a.skeleton.bones;r.skeleton=a.skeleton.clone(),r.bindMatrix.copy(a.bindMatrix),r.skeleton.bones=o.map(function(l){return t.get(l)}),r.bind(r.skeleton,r.bindMatrix)}),n}function qu(s,e,t){t(s,e);for(let n=0;n<s.children.length;n++)qu(s.children[n],e.children[n],t)}class Xh extends Is{constructor(e){super(e),this.dracoLoader=null,this.ktx2Loader=null,this.meshoptDecoder=null,this.pluginCallbacks=[],this.register(function(t){return new lx(t)}),this.register(function(t){return new cx(t)}),this.register(function(t){return new vx(t)}),this.register(function(t){return new xx(t)}),this.register(function(t){return new Mx(t)}),this.register(function(t){return new ux(t)}),this.register(function(t){return new dx(t)}),this.register(function(t){return new fx(t)}),this.register(function(t){return new px(t)}),this.register(function(t){return new ox(t)}),this.register(function(t){return new mx(t)}),this.register(function(t){return new hx(t)}),this.register(function(t){return new _x(t)}),this.register(function(t){return new gx(t)}),this.register(function(t){return new rx(t)}),this.register(function(t){return new Yh(t,Ye.EXT_MESHOPT_COMPRESSION)}),this.register(function(t){return new Yh(t,Ye.KHR_MESHOPT_COMPRESSION)}),this.register(function(t){return new yx(t)})}load(e,t,n,i){const r=this;let a;if(this.resourcePath!=="")a=this.resourcePath;else if(this.path!==""){const c=Js.extractUrlBase(e);a=Js.resolveURL(c,this.path)}else a=Js.extractUrlBase(e);this.manager.itemStart(e);const o=function(c){i?i(c):console.error(c),r.manager.itemError(e),r.manager.itemEnd(e)},l=new Ou(this.manager);l.setPath(this.path),l.setResponseType("arraybuffer"),l.setRequestHeader(this.requestHeader),l.setWithCredentials(this.withCredentials),l.load(e,function(c){try{r.parse(c,a,function(h){t(h),r.manager.itemEnd(e)},o)}catch(h){o(h)}},n,o)}setDRACOLoader(e){return this.dracoLoader=e,this}setKTX2Loader(e){return this.ktx2Loader=e,this}setMeshoptDecoder(e){return this.meshoptDecoder=e,this}register(e){return this.pluginCallbacks.indexOf(e)===-1&&this.pluginCallbacks.push(e),this}unregister(e){return this.pluginCallbacks.indexOf(e)!==-1&&this.pluginCallbacks.splice(this.pluginCallbacks.indexOf(e),1),this}parse(e,t,n,i){let r;const a={},o={},l=new TextDecoder;if(typeof e=="string")r=JSON.parse(e);else if(e instanceof ArrayBuffer)if(l.decode(new Uint8Array(e,0,4))===ju){try{a[Ye.KHR_BINARY_GLTF]=new Sx(e)}catch(u){i&&i(u);return}r=JSON.parse(a[Ye.KHR_BINARY_GLTF].content)}else r=JSON.parse(l.decode(e));else r=e;if(r.asset===void 0||r.asset.version[0]<2){i&&i(new Error("THREE.GLTFLoader: Unsupported asset. glTF versions >=2.0 are supported."));return}const c=new Ux(r,{path:t||this.resourcePath||"",crossOrigin:this.crossOrigin,requestHeader:this.requestHeader,manager:this.manager,ktx2Loader:this.ktx2Loader,meshoptDecoder:this.meshoptDecoder});c.fileLoader.setRequestHeader(this.requestHeader);for(let h=0;h<this.pluginCallbacks.length;h++){const u=this.pluginCallbacks[h](c);u.name||console.error("THREE.GLTFLoader: Invalid plugin found: missing name"),o[u.name]=u,a[u.name]=!0}if(r.extensionsUsed)for(let h=0;h<r.extensionsUsed.length;++h){const u=r.extensionsUsed[h],d=r.extensionsRequired||[];switch(u){case Ye.KHR_MATERIALS_UNLIT:a[u]=new ax;break;case Ye.KHR_DRACO_MESH_COMPRESSION:a[u]=new bx(r,this.dracoLoader);break;case Ye.KHR_TEXTURE_TRANSFORM:a[u]=new Ex;break;case Ye.KHR_MESH_QUANTIZATION:a[u]=new Tx;break;default:d.indexOf(u)>=0&&o[u]===void 0&&console.warn('THREE.GLTFLoader: Unknown extension "'+u+'".')}}c.setExtensions(a),c.setPlugins(o),c.parse(n,i)}parseAsync(e,t){const n=this;return new Promise(function(i,r){n.parse(e,t,i,r)})}}function sx(){let s={};return{get:function(e){return s[e]},add:function(e,t){s[e]=t},remove:function(e){delete s[e]},removeAll:function(){s={}}}}function Et(s,e,t){const n=s.json.materials[e];return n.extensions&&n.extensions[t]?n.extensions[t]:null}const Ye={KHR_BINARY_GLTF:"KHR_binary_glTF",KHR_DRACO_MESH_COMPRESSION:"KHR_draco_mesh_compression",KHR_LIGHTS_PUNCTUAL:"KHR_lights_punctual",KHR_MATERIALS_CLEARCOAT:"KHR_materials_clearcoat",KHR_MATERIALS_DISPERSION:"KHR_materials_dispersion",KHR_MATERIALS_IOR:"KHR_materials_ior",KHR_MATERIALS_SHEEN:"KHR_materials_sheen",KHR_MATERIALS_SPECULAR:"KHR_materials_specular",KHR_MATERIALS_TRANSMISSION:"KHR_materials_transmission",KHR_MATERIALS_IRIDESCENCE:"KHR_materials_iridescence",KHR_MATERIALS_ANISOTROPY:"KHR_materials_anisotropy",KHR_MATERIALS_UNLIT:"KHR_materials_unlit",KHR_MATERIALS_VOLUME:"KHR_materials_volume",KHR_TEXTURE_BASISU:"KHR_texture_basisu",KHR_TEXTURE_TRANSFORM:"KHR_texture_transform",KHR_MESH_QUANTIZATION:"KHR_mesh_quantization",KHR_MATERIALS_EMISSIVE_STRENGTH:"KHR_materials_emissive_strength",EXT_MATERIALS_BUMP:"EXT_materials_bump",EXT_TEXTURE_WEBP:"EXT_texture_webp",EXT_TEXTURE_AVIF:"EXT_texture_avif",EXT_MESHOPT_COMPRESSION:"EXT_meshopt_compression",KHR_MESHOPT_COMPRESSION:"KHR_meshopt_compression",EXT_MESH_GPU_INSTANCING:"EXT_mesh_gpu_instancing"};class rx{constructor(e){this.parser=e,this.name=Ye.KHR_LIGHTS_PUNCTUAL,this.cache={refs:{},uses:{}}}_markDefs(){const e=this.parser,t=this.parser.json.nodes||[];for(let n=0,i=t.length;n<i;n++){const r=t[n];r.extensions&&r.extensions[this.name]&&r.extensions[this.name].light!==void 0&&e._addNodeRef(this.cache,r.extensions[this.name].light)}}_loadLight(e){const t=this.parser,n="light:"+e;let i=t.cache.get(n);if(i)return i;const r=t.json,l=((r.extensions&&r.extensions[this.name]||{}).lights||[])[e];let c;const h=new Ie(16777215);l.color!==void 0&&h.setRGB(l.color[0],l.color[1],l.color[2],Kt);const u=l.range!==void 0?l.range:0;switch(l.type){case"directional":c=new Ml(h),c.target.position.set(0,0,-1),c.add(c.target);break;case"point":c=new ku(h),c.distance=u;break;case"spot":c=new Xp(h),c.distance=u,l.spot=l.spot||{},l.spot.innerConeAngle=l.spot.innerConeAngle!==void 0?l.spot.innerConeAngle:0,l.spot.outerConeAngle=l.spot.outerConeAngle!==void 0?l.spot.outerConeAngle:Math.PI/4,c.angle=l.spot.outerConeAngle,c.penumbra=1-l.spot.innerConeAngle/l.spot.outerConeAngle,c.target.position.set(0,0,-1),c.add(c.target);break;default:throw new Error("THREE.GLTFLoader: Unexpected light type: "+l.type)}return c.position.set(0,0,0),wn(c,l),l.intensity!==void 0&&(c.intensity=l.intensity),c.name=t.createUniqueName(l.name||"light_"+e),i=Promise.resolve(c),t.cache.add(n,i),i}getDependency(e,t){if(e==="light")return this._loadLight(t)}createNodeAttachment(e){const t=this,n=this.parser,r=n.json.nodes[e],o=(r.extensions&&r.extensions[this.name]||{}).light;return o===void 0?null:this._loadLight(o).then(function(l){return n._getNodeRef(t.cache,o,l)})}}class ax{constructor(){this.name=Ye.KHR_MATERIALS_UNLIT}getMaterialType(){return Nn}extendParams(e,t,n){const i=[];e.color=new Ie(1,1,1),e.opacity=1;const r=t.pbrMetallicRoughness;if(r){if(Array.isArray(r.baseColorFactor)){const a=r.baseColorFactor;e.color.setRGB(a[0],a[1],a[2],Kt),e.opacity=a[3]}r.baseColorTexture!==void 0&&i.push(n.assignTexture(e,"map",r.baseColorTexture,wt))}return Promise.all(i)}}class ox{constructor(e){this.parser=e,this.name=Ye.KHR_MATERIALS_EMISSIVE_STRENGTH}extendMaterialParams(e,t){const n=Et(this.parser,e,this.name);return n===null||n.emissiveStrength!==void 0&&(t.emissiveIntensity=n.emissiveStrength),Promise.resolve()}}class lx{constructor(e){this.parser=e,this.name=Ye.KHR_MATERIALS_CLEARCOAT}getMaterialType(e){return Et(this.parser,e,this.name)!==null?Bn:null}extendMaterialParams(e,t){const n=Et(this.parser,e,this.name);if(n===null)return Promise.resolve();const i=[];if(n.clearcoatFactor!==void 0&&(t.clearcoat=n.clearcoatFactor),n.clearcoatTexture!==void 0&&i.push(this.parser.assignTexture(t,"clearcoatMap",n.clearcoatTexture)),n.clearcoatRoughnessFactor!==void 0&&(t.clearcoatRoughness=n.clearcoatRoughnessFactor),n.clearcoatRoughnessTexture!==void 0&&i.push(this.parser.assignTexture(t,"clearcoatRoughnessMap",n.clearcoatRoughnessTexture)),n.clearcoatNormalTexture!==void 0&&(i.push(this.parser.assignTexture(t,"clearcoatNormalMap",n.clearcoatNormalTexture)),n.clearcoatNormalTexture.scale!==void 0)){const r=n.clearcoatNormalTexture.scale;t.clearcoatNormalScale=new Le(r,r)}return Promise.all(i)}}class cx{constructor(e){this.parser=e,this.name=Ye.KHR_MATERIALS_DISPERSION}getMaterialType(e){return Et(this.parser,e,this.name)!==null?Bn:null}extendMaterialParams(e,t){const n=Et(this.parser,e,this.name);return n===null||(t.dispersion=n.dispersion!==void 0?n.dispersion:0),Promise.resolve()}}class hx{constructor(e){this.parser=e,this.name=Ye.KHR_MATERIALS_IRIDESCENCE}getMaterialType(e){return Et(this.parser,e,this.name)!==null?Bn:null}extendMaterialParams(e,t){const n=Et(this.parser,e,this.name);if(n===null)return Promise.resolve();const i=[];return n.iridescenceFactor!==void 0&&(t.iridescence=n.iridescenceFactor),n.iridescenceTexture!==void 0&&i.push(this.parser.assignTexture(t,"iridescenceMap",n.iridescenceTexture)),n.iridescenceIor!==void 0&&(t.iridescenceIOR=n.iridescenceIor),t.iridescenceThicknessRange===void 0&&(t.iridescenceThicknessRange=[100,400]),n.iridescenceThicknessMinimum!==void 0&&(t.iridescenceThicknessRange[0]=n.iridescenceThicknessMinimum),n.iridescenceThicknessMaximum!==void 0&&(t.iridescenceThicknessRange[1]=n.iridescenceThicknessMaximum),n.iridescenceThicknessTexture!==void 0&&i.push(this.parser.assignTexture(t,"iridescenceThicknessMap",n.iridescenceThicknessTexture)),Promise.all(i)}}class ux{constructor(e){this.parser=e,this.name=Ye.KHR_MATERIALS_SHEEN}getMaterialType(e){return Et(this.parser,e,this.name)!==null?Bn:null}extendMaterialParams(e,t){const n=Et(this.parser,e,this.name);if(n===null)return Promise.resolve();const i=[];if(t.sheenColor=new Ie(0,0,0),t.sheenRoughness=0,t.sheen=1,n.sheenColorFactor!==void 0){const r=n.sheenColorFactor;t.sheenColor.setRGB(r[0],r[1],r[2],Kt)}return n.sheenRoughnessFactor!==void 0&&(t.sheenRoughness=n.sheenRoughnessFactor),n.sheenColorTexture!==void 0&&i.push(this.parser.assignTexture(t,"sheenColorMap",n.sheenColorTexture,wt)),n.sheenRoughnessTexture!==void 0&&i.push(this.parser.assignTexture(t,"sheenRoughnessMap",n.sheenRoughnessTexture)),Promise.all(i)}}class dx{constructor(e){this.parser=e,this.name=Ye.KHR_MATERIALS_TRANSMISSION}getMaterialType(e){return Et(this.parser,e,this.name)!==null?Bn:null}extendMaterialParams(e,t){const n=Et(this.parser,e,this.name);if(n===null)return Promise.resolve();const i=[];return n.transmissionFactor!==void 0&&(t.transmission=n.transmissionFactor),n.transmissionTexture!==void 0&&i.push(this.parser.assignTexture(t,"transmissionMap",n.transmissionTexture)),Promise.all(i)}}class fx{constructor(e){this.parser=e,this.name=Ye.KHR_MATERIALS_VOLUME}getMaterialType(e){return Et(this.parser,e,this.name)!==null?Bn:null}extendMaterialParams(e,t){const n=Et(this.parser,e,this.name);if(n===null)return Promise.resolve();const i=[];t.thickness=n.thicknessFactor!==void 0?n.thicknessFactor:0,n.thicknessTexture!==void 0&&i.push(this.parser.assignTexture(t,"thicknessMap",n.thicknessTexture)),t.attenuationDistance=n.attenuationDistance||1/0;const r=n.attenuationColor||[1,1,1];return t.attenuationColor=new Ie().setRGB(r[0],r[1],r[2],Kt),Promise.all(i)}}class px{constructor(e){this.parser=e,this.name=Ye.KHR_MATERIALS_IOR}getMaterialType(e){return Et(this.parser,e,this.name)!==null?Bn:null}extendMaterialParams(e,t){const n=Et(this.parser,e,this.name);return n===null||(t.ior=n.ior!==void 0?n.ior:1.5),Promise.resolve()}}class mx{constructor(e){this.parser=e,this.name=Ye.KHR_MATERIALS_SPECULAR}getMaterialType(e){return Et(this.parser,e,this.name)!==null?Bn:null}extendMaterialParams(e,t){const n=Et(this.parser,e,this.name);if(n===null)return Promise.resolve();const i=[];t.specularIntensity=n.specularFactor!==void 0?n.specularFactor:1,n.specularTexture!==void 0&&i.push(this.parser.assignTexture(t,"specularIntensityMap",n.specularTexture));const r=n.specularColorFactor||[1,1,1];return t.specularColor=new Ie().setRGB(r[0],r[1],r[2],Kt),n.specularColorTexture!==void 0&&i.push(this.parser.assignTexture(t,"specularColorMap",n.specularColorTexture,wt)),Promise.all(i)}}class gx{constructor(e){this.parser=e,this.name=Ye.EXT_MATERIALS_BUMP}getMaterialType(e){return Et(this.parser,e,this.name)!==null?Bn:null}extendMaterialParams(e,t){const n=Et(this.parser,e,this.name);if(n===null)return Promise.resolve();const i=[];return t.bumpScale=n.bumpFactor!==void 0?n.bumpFactor:1,n.bumpTexture!==void 0&&i.push(this.parser.assignTexture(t,"bumpMap",n.bumpTexture)),Promise.all(i)}}class _x{constructor(e){this.parser=e,this.name=Ye.KHR_MATERIALS_ANISOTROPY}getMaterialType(e){return Et(this.parser,e,this.name)!==null?Bn:null}extendMaterialParams(e,t){const n=Et(this.parser,e,this.name);if(n===null)return Promise.resolve();const i=[];return n.anisotropyStrength!==void 0&&(t.anisotropy=n.anisotropyStrength),n.anisotropyRotation!==void 0&&(t.anisotropyRotation=n.anisotropyRotation),n.anisotropyTexture!==void 0&&i.push(this.parser.assignTexture(t,"anisotropyMap",n.anisotropyTexture)),Promise.all(i)}}class vx{constructor(e){this.parser=e,this.name=Ye.KHR_TEXTURE_BASISU}loadTexture(e){const t=this.parser,n=t.json,i=n.textures[e];if(!i.extensions||!i.extensions[this.name])return null;const r=i.extensions[this.name],a=t.options.ktx2Loader;if(!a){if(n.extensionsRequired&&n.extensionsRequired.indexOf(this.name)>=0)throw new Error("THREE.GLTFLoader: setKTX2Loader must be called before loading KTX2 textures");return null}return t.loadTextureImage(e,r.source,a)}}class xx{constructor(e){this.parser=e,this.name=Ye.EXT_TEXTURE_WEBP}loadTexture(e){const t=this.name,n=this.parser,i=n.json,r=i.textures[e];if(!r.extensions||!r.extensions[t])return null;const a=r.extensions[t],o=i.images[a.source];let l=n.textureLoader;if(o.uri){const c=n.options.manager.getHandler(o.uri);c!==null&&(l=c)}return n.loadTextureImage(e,a.source,l)}}class Mx{constructor(e){this.parser=e,this.name=Ye.EXT_TEXTURE_AVIF}loadTexture(e){const t=this.name,n=this.parser,i=n.json,r=i.textures[e];if(!r.extensions||!r.extensions[t])return null;const a=r.extensions[t],o=i.images[a.source];let l=n.textureLoader;if(o.uri){const c=n.options.manager.getHandler(o.uri);c!==null&&(l=c)}return n.loadTextureImage(e,a.source,l)}}class Yh{constructor(e,t){this.name=t,this.parser=e}loadBufferView(e){const t=this.parser.json,n=t.bufferViews[e];if(n.extensions&&n.extensions[this.name]){const i=n.extensions[this.name],r=this.parser.getDependency("buffer",i.buffer),a=this.parser.options.meshoptDecoder;if(!a||!a.supported){if(t.extensionsRequired&&t.extensionsRequired.indexOf(this.name)>=0)throw new Error("THREE.GLTFLoader: setMeshoptDecoder must be called before loading compressed files");return null}return r.then(function(o){const l=i.byteOffset||0,c=i.byteLength||0,h=i.count,u=i.byteStride,d=new Uint8Array(o,l,c);return a.decodeGltfBufferAsync?a.decodeGltfBufferAsync(h,u,d,i.mode,i.filter).then(function(f){return f.buffer}):a.ready.then(function(){const f=new ArrayBuffer(h*u);return a.decodeGltfBuffer(new Uint8Array(f),h,u,d,i.mode,i.filter),f})})}else return null}}class yx{constructor(e){this.name=Ye.EXT_MESH_GPU_INSTANCING,this.parser=e}createNodeMesh(e){const t=this.parser.json,n=t.nodes[e];if(!n.extensions||!n.extensions[this.name]||n.mesh===void 0)return null;const i=t.meshes[n.mesh];for(const c of i.primitives)if(c.mode!==hn.TRIANGLES&&c.mode!==hn.TRIANGLE_STRIP&&c.mode!==hn.TRIANGLE_FAN&&c.mode!==void 0)return null;const a=n.extensions[this.name].attributes,o=[],l={};for(const c in a)o.push(this.parser.getDependency("accessor",a[c]).then(h=>(l[c]=h,l[c])));return o.length<1?null:(o.push(this.parser.createNodeMesh(e)),Promise.all(o).then(c=>{const h=c.pop(),u=h.isGroup?h.children:[h],d=c[0].count,f=[];for(const g of u){const x=new Ve,p=new L,m=new yn,S=new L(1,1,1),T=new ec(g.geometry,g.material,d);for(let M=0;M<d;M++)l.TRANSLATION&&p.fromBufferAttribute(l.TRANSLATION,M),l.ROTATION&&m.fromBufferAttribute(l.ROTATION,M),l.SCALE&&S.fromBufferAttribute(l.SCALE,M),T.setMatrixAt(M,x.compose(p,m,S));for(const M in l)if(M==="_COLOR_0"){const E=l[M];T.instanceColor=new vl(E.array,E.itemSize,E.normalized)}else M!=="TRANSLATION"&&M!=="ROTATION"&&M!=="SCALE"&&g.geometry.setAttribute(M,l[M]);ft.prototype.copy.call(T,g),this.parser.assignFinalMaterial(T),f.push(T)}return h.isGroup?(h.clear(),h.add(...f),h):f[0]}))}}const ju="glTF",Xs=12,qh={JSON:1313821514,BIN:5130562};class Sx{constructor(e){this.name=Ye.KHR_BINARY_GLTF,this.content=null,this.body=null;const t=new DataView(e,0,Xs),n=new TextDecoder;if(this.header={magic:n.decode(new Uint8Array(e.slice(0,4))),version:t.getUint32(4,!0),length:t.getUint32(8,!0)},this.header.magic!==ju)throw new Error("THREE.GLTFLoader: Unsupported glTF-Binary header.");if(this.header.version<2)throw new Error("THREE.GLTFLoader: Legacy binary file detected.");const i=this.header.length-Xs,r=new DataView(e,Xs);let a=0;for(;a<i;){const o=r.getUint32(a,!0);a+=4;const l=r.getUint32(a,!0);if(a+=4,l===qh.JSON){const c=new Uint8Array(e,Xs+a,o);this.content=n.decode(c)}else if(l===qh.BIN){const c=Xs+a;this.body=e.slice(c,c+o)}a+=o}if(this.content===null)throw new Error("THREE.GLTFLoader: JSON content not found.")}}class bx{constructor(e,t){if(!t)throw new Error("THREE.GLTFLoader: No DRACOLoader instance provided.");this.name=Ye.KHR_DRACO_MESH_COMPRESSION,this.json=e,this.dracoLoader=t,this.dracoLoader.preload()}decodePrimitive(e,t){const n=this.json,i=this.dracoLoader,r=e.extensions[this.name].bufferView,a=e.extensions[this.name].attributes,o={},l={},c={};for(const h in a){const u=Tl[h]||h.toLowerCase();o[u]=a[h]}for(const h in e.attributes){const u=Tl[h]||h.toLowerCase();if(a[h]!==void 0){const d=n.accessors[e.attributes[h]],f=us[d.componentType];c[u]=f.name,l[u]=d.normalized===!0}}return t.getDependency("bufferView",r).then(function(h){return new Promise(function(u,d){i.decodeDracoFile(h,function(f){for(const g in f.attributes){const x=f.attributes[g],p=l[g];p!==void 0&&(x.normalized=p)}u(f)},o,c,Kt,d)})})}}class Ex{constructor(){this.name=Ye.KHR_TEXTURE_TRANSFORM}extendTexture(e,t){return(t.texCoord===void 0||t.texCoord===e.channel)&&t.offset===void 0&&t.rotation===void 0&&t.scale===void 0||(e=e.clone(),t.texCoord!==void 0&&(e.channel=t.texCoord),t.offset!==void 0&&e.offset.fromArray(t.offset),t.rotation!==void 0&&(e.rotation=t.rotation),t.scale!==void 0&&e.repeat.fromArray(t.scale),e.needsUpdate=!0),e}}class Tx{constructor(){this.name=Ye.KHR_MESH_QUANTIZATION}}class Ku extends Ps{constructor(e,t,n,i){super(e,t,n,i)}copySampleValue_(e){const t=this.resultBuffer,n=this.sampleValues,i=this.valueSize,r=e*i*3+i;for(let a=0;a!==i;a++)t[a]=n[r+a];return t}interpolate_(e,t,n,i){const r=this.resultBuffer,a=this.sampleValues,o=this.valueSize,l=o*2,c=o*3,h=i-t,u=(n-t)/h,d=u*u,f=d*u,g=e*c,x=g-c,p=-2*f+3*d,m=f-d,S=1-p,T=m-d+u;for(let M=0;M!==o;M++){const E=a[x+M+o],w=a[x+M+l]*h,C=a[g+M+o],v=a[g+M]*h;r[M]=S*E+T*w+p*C+m*v}return r}}const Ax=new yn;class wx extends Ku{interpolate_(e,t,n,i){const r=super.interpolate_(e,t,n,i);return Ax.fromArray(r).normalize().toArray(r),r}}const hn={POINTS:0,LINES:1,LINE_LOOP:2,LINE_STRIP:3,TRIANGLES:4,TRIANGLE_STRIP:5,TRIANGLE_FAN:6},us={5120:Int8Array,5121:Uint8Array,5122:Int16Array,5123:Uint16Array,5125:Uint32Array,5126:Float32Array},jh={9728:xt,9729:Ct,9984:pu,9985:jr,9986:qs,9987:jn},Kh={33071:Dn,33648:na,10497:vi},_o={SCALAR:1,VEC2:2,VEC3:3,VEC4:4,MAT2:4,MAT3:9,MAT4:16},Tl={POSITION:"position",NORMAL:"normal",TANGENT:"tangent",TEXCOORD_0:"uv",TEXCOORD_1:"uv1",TEXCOORD_2:"uv2",TEXCOORD_3:"uv3",COLOR_0:"color",WEIGHTS_0:"skinWeight",JOINTS_0:"skinIndex"},ci={scale:"scale",translation:"position",rotation:"quaternion",weights:"morphTargetInfluences"},Rx={CUBICSPLINE:void 0,LINEAR:tr,STEP:er},vo={OPAQUE:"OPAQUE",MASK:"MASK",BLEND:"BLEND"};function Cx(s){return s.DefaultMaterial===void 0&&(s.DefaultMaterial=new bs({color:16777215,emissive:0,metalness:1,roughness:1,transparent:!1,depthTest:!0,side:Zn})),s.DefaultMaterial}function wi(s,e,t){for(const n in t.extensions)s[n]===void 0&&(e.userData.gltfExtensions=e.userData.gltfExtensions||{},e.userData.gltfExtensions[n]=t.extensions[n])}function wn(s,e){e.extras!==void 0&&(typeof e.extras=="object"?Object.assign(s.userData,e.extras):console.warn("THREE.GLTFLoader: Ignoring primitive type .extras, "+e.extras))}function Px(s,e,t){let n=!1,i=!1,r=!1;for(let c=0,h=e.length;c<h;c++){const u=e[c];if(u.POSITION!==void 0&&(n=!0),u.NORMAL!==void 0&&(i=!0),u.COLOR_0!==void 0&&(r=!0),n&&i&&r)break}if(!n&&!i&&!r)return Promise.resolve(s);const a=[],o=[],l=[];for(let c=0,h=e.length;c<h;c++){const u=e[c];if(n){const d=u.POSITION!==void 0?t.getDependency("accessor",u.POSITION):s.attributes.position;a.push(d)}if(i){const d=u.NORMAL!==void 0?t.getDependency("accessor",u.NORMAL):s.attributes.normal;o.push(d)}if(r){const d=u.COLOR_0!==void 0?t.getDependency("accessor",u.COLOR_0):s.attributes.color;l.push(d)}}return Promise.all([Promise.all(a),Promise.all(o),Promise.all(l)]).then(function(c){const h=c[0],u=c[1],d=c[2];return n&&(s.morphAttributes.position=h),i&&(s.morphAttributes.normal=u),r&&(s.morphAttributes.color=d),s.morphTargetsRelative=!0,s})}function Dx(s,e){if(s.updateMorphTargets(),e.weights!==void 0)for(let t=0,n=e.weights.length;t<n;t++)s.morphTargetInfluences[t]=e.weights[t];if(e.extras&&Array.isArray(e.extras.targetNames)){const t=e.extras.targetNames;if(s.morphTargetInfluences.length===t.length){s.morphTargetDictionary={};for(let n=0,i=t.length;n<i;n++)s.morphTargetDictionary[t[n]]=n}else console.warn("THREE.GLTFLoader: Invalid extras.targetNames length. Ignoring names.")}}function Lx(s){let e;const t=s.extensions&&s.extensions[Ye.KHR_DRACO_MESH_COMPRESSION];if(t?e="draco:"+t.bufferView+":"+t.indices+":"+xo(t.attributes):e=s.indices+":"+xo(s.attributes)+":"+s.mode,s.targets!==void 0)for(let n=0,i=s.targets.length;n<i;n++)e+=":"+xo(s.targets[n]);return e}function xo(s){let e="";const t=Object.keys(s).sort();for(let n=0,i=t.length;n<i;n++)e+=t[n]+":"+s[t[n]]+";";return e}function Al(s){switch(s){case Int8Array:return 1/127;case Uint8Array:return 1/255;case Int16Array:return 1/32767;case Uint16Array:return 1/65535;default:throw new Error("THREE.GLTFLoader: Unsupported normalized accessor component type.")}}function Ix(s){return s.search(/\.jpe?g($|\?)/i)>0||s.search(/^data\:image\/jpeg/)===0?"image/jpeg":s.search(/\.webp($|\?)/i)>0||s.search(/^data\:image\/webp/)===0?"image/webp":s.search(/\.ktx2($|\?)/i)>0||s.search(/^data\:image\/ktx2/)===0?"image/ktx2":"image/png"}const Nx=new Ve;class Ux{constructor(e={},t={}){this.json=e,this.extensions={},this.plugins={},this.options=t,this.cache=new sx,this.associations=new Map,this.primitiveCache={},this.nodeCache={},this.meshCache={refs:{},uses:{}},this.cameraCache={refs:{},uses:{}},this.lightCache={refs:{},uses:{}},this.sourceCache={},this.textureCache={},this.nodeNamesUsed={};let n=!1,i=-1,r=!1,a=-1;if(typeof navigator<"u"&&typeof navigator.userAgent<"u"){const o=navigator.userAgent;n=/^((?!chrome|android).)*safari/i.test(o)===!0;const l=o.match(/Version\/(\d+)/);i=n&&l?parseInt(l[1],10):-1,r=o.indexOf("Firefox")>-1,a=r?o.match(/Firefox\/([0-9]+)\./)[1]:-1}typeof createImageBitmap>"u"||n&&i<17||r&&a<98?this.textureLoader=new Hp(this.options.manager):this.textureLoader=new jp(this.options.manager),this.textureLoader.setCrossOrigin(this.options.crossOrigin),this.textureLoader.setRequestHeader(this.options.requestHeader),this.fileLoader=new Ou(this.options.manager),this.fileLoader.setResponseType("arraybuffer"),this.options.crossOrigin==="use-credentials"&&this.fileLoader.setWithCredentials(!0)}setExtensions(e){this.extensions=e}setPlugins(e){this.plugins=e}parse(e,t){const n=this,i=this.json,r=this.extensions;this.cache.removeAll(),this.nodeCache={},this._invokeAll(function(a){return a._markDefs&&a._markDefs()}),Promise.all(this._invokeAll(function(a){return a.beforeRoot&&a.beforeRoot()})).then(function(){return Promise.all([n.getDependencies("scene"),n.getDependencies("animation"),n.getDependencies("camera")])}).then(function(a){const o={scene:a[0][i.scene||0],scenes:a[0],animations:a[1],cameras:a[2],asset:i.asset,parser:n,userData:{}};return wi(r,o,i),wn(o,i),Promise.all(n._invokeAll(function(l){return l.afterRoot&&l.afterRoot(o)})).then(function(){for(const l of o.scenes)l.updateMatrixWorld();e(o)})}).catch(t)}_markDefs(){const e=this.json.nodes||[],t=this.json.skins||[],n=this.json.meshes||[];for(let i=0,r=t.length;i<r;i++){const a=t[i].joints;for(let o=0,l=a.length;o<l;o++)e[a[o]].isBone=!0}for(let i=0,r=e.length;i<r;i++){const a=e[i];a.mesh!==void 0&&(this._addNodeRef(this.meshCache,a.mesh),a.skin!==void 0&&(n[a.mesh].isSkinnedMesh=!0)),a.camera!==void 0&&this._addNodeRef(this.cameraCache,a.camera)}}_addNodeRef(e,t){t!==void 0&&(e.refs[t]===void 0&&(e.refs[t]=e.uses[t]=0),e.refs[t]++)}_getNodeRef(e,t,n){if(e.refs[t]<=1)return n;const i=n.clone(),r=(a,o)=>{const l=this.associations.get(a);l!=null&&this.associations.set(o,l);for(const[c,h]of a.children.entries())r(h,o.children[c])};return r(n,i),i.name+="_instance_"+e.uses[t]++,i}_invokeOne(e){const t=Object.values(this.plugins);t.push(this);for(let n=0;n<t.length;n++){const i=e(t[n]);if(i)return i}return null}_invokeAll(e){const t=Object.values(this.plugins);t.unshift(this);const n=[];for(let i=0;i<t.length;i++){const r=e(t[i]);r&&n.push(r)}return n}getDependency(e,t){const n=e+":"+t;let i=this.cache.get(n);if(!i){switch(e){case"scene":i=this.loadScene(t);break;case"node":i=this._invokeOne(function(r){return r.loadNode&&r.loadNode(t)});break;case"mesh":i=this._invokeOne(function(r){return r.loadMesh&&r.loadMesh(t)});break;case"accessor":i=this.loadAccessor(t);break;case"bufferView":i=this._invokeOne(function(r){return r.loadBufferView&&r.loadBufferView(t)});break;case"buffer":i=this.loadBuffer(t);break;case"material":i=this._invokeOne(function(r){return r.loadMaterial&&r.loadMaterial(t)});break;case"texture":i=this._invokeOne(function(r){return r.loadTexture&&r.loadTexture(t)});break;case"skin":i=this.loadSkin(t);break;case"animation":i=this._invokeOne(function(r){return r.loadAnimation&&r.loadAnimation(t)});break;case"camera":i=this.loadCamera(t);break;default:if(i=this._invokeOne(function(r){return r!=this&&r.getDependency&&r.getDependency(e,t)}),!i)throw new Error("Unknown type: "+e);break}this.cache.add(n,i)}return i}getDependencies(e){let t=this.cache.get(e);if(!t){const n=this,i=this.json[e+(e==="mesh"?"es":"s")]||[];t=Promise.all(i.map(function(r,a){return n.getDependency(e,a)})),this.cache.add(e,t)}return t}loadBuffer(e){const t=this.json.buffers[e],n=this.fileLoader;if(t.type&&t.type!=="arraybuffer")throw new Error("THREE.GLTFLoader: "+t.type+" buffer type is not supported.");if(t.uri===void 0&&e===0)return Promise.resolve(this.extensions[Ye.KHR_BINARY_GLTF].body);const i=this.options;return new Promise(function(r,a){n.load(Js.resolveURL(t.uri,i.path),r,void 0,function(){a(new Error('THREE.GLTFLoader: Failed to load buffer "'+t.uri+'".'))})})}loadBufferView(e){const t=this.json.bufferViews[e];return this.getDependency("buffer",t.buffer).then(function(n){const i=t.byteLength||0,r=t.byteOffset||0;return n.slice(r,r+i)})}loadAccessor(e){const t=this,n=this.json,i=this.json.accessors[e];if(i.bufferView===void 0&&i.sparse===void 0){const a=_o[i.type],o=us[i.componentType],l=i.normalized===!0,c=new o(i.count*a);return Promise.resolve(new jt(c,a,l))}const r=[];return i.bufferView!==void 0?r.push(this.getDependency("bufferView",i.bufferView)):r.push(null),i.sparse!==void 0&&(r.push(this.getDependency("bufferView",i.sparse.indices.bufferView)),r.push(this.getDependency("bufferView",i.sparse.values.bufferView))),Promise.all(r).then(function(a){const o=a[0],l=_o[i.type],c=us[i.componentType],h=c.BYTES_PER_ELEMENT,u=h*l,d=i.byteOffset||0,f=i.bufferView!==void 0?n.bufferViews[i.bufferView].byteStride:void 0,g=i.normalized===!0;let x,p;if(f&&f!==u){const m=Math.floor(d/f),S="InterleavedBuffer:"+i.bufferView+":"+i.componentType+":"+m+":"+i.count;let T=t.cache.get(S);T||(x=new c(o,m*f,i.count*f/h),T=new cp(x,f/h),t.cache.add(S,T)),p=new Jl(T,l,d%f/h,g)}else o===null?x=new c(i.count*l):x=new c(o,d,i.count*l),p=new jt(x,l,g);if(i.sparse!==void 0){const m=_o.SCALAR,S=us[i.sparse.indices.componentType],T=i.sparse.indices.byteOffset||0,M=i.sparse.values.byteOffset||0,E=new S(a[1],T,i.sparse.count*m),w=new c(a[2],M,i.sparse.count*l);o!==null&&(p=new jt(p.array.slice(),p.itemSize,p.normalized)),p.normalized=!1;for(let C=0,v=E.length;C<v;C++){const b=E[C];if(p.setX(b,w[C*l]),l>=2&&p.setY(b,w[C*l+1]),l>=3&&p.setZ(b,w[C*l+2]),l>=4&&p.setW(b,w[C*l+3]),l>=5)throw new Error("THREE.GLTFLoader: Unsupported itemSize in sparse BufferAttribute.")}p.normalized=g}return p})}loadTexture(e){const t=this.json,n=this.options,r=t.textures[e].source,a=t.images[r];let o=this.textureLoader;if(a.uri){const l=n.manager.getHandler(a.uri);l!==null&&(o=l)}return this.loadTextureImage(e,r,o)}loadTextureImage(e,t,n){const i=this,r=this.json,a=r.textures[e],o=r.images[t],l=(o.uri||o.bufferView)+":"+a.sampler;if(this.textureCache[l])return this.textureCache[l];const c=this.loadImageSource(t,n).then(function(h){h.flipY=!1,h.name=a.name||o.name||"",h.name===""&&typeof o.uri=="string"&&o.uri.startsWith("data:image/")===!1&&(h.name=o.uri);const d=(r.samplers||{})[a.sampler]||{};return h.magFilter=jh[d.magFilter]||Ct,h.minFilter=jh[d.minFilter]||jn,h.wrapS=Kh[d.wrapS]||vi,h.wrapT=Kh[d.wrapT]||vi,h.generateMipmaps=!h.isCompressedTexture&&h.minFilter!==xt&&h.minFilter!==Ct,i.associations.set(h,{textures:e}),h}).catch(function(){return null});return this.textureCache[l]=c,c}loadImageSource(e,t){const n=this,i=this.json,r=this.options;if(this.sourceCache[e]!==void 0)return this.sourceCache[e].then(u=>u.clone());const a=i.images[e],o=self.URL||self.webkitURL;let l=a.uri||"",c=!1;if(a.bufferView!==void 0)l=n.getDependency("bufferView",a.bufferView).then(function(u){c=!0;const d=new Blob([u],{type:a.mimeType});return l=o.createObjectURL(d),l});else if(a.uri===void 0)throw new Error("THREE.GLTFLoader: Image "+e+" is missing URI and bufferView");const h=Promise.resolve(l).then(function(u){return new Promise(function(d,f){let g=d;t.isImageBitmapLoader===!0&&(g=function(x){const p=new Pt(x);p.needsUpdate=!0,d(p)}),t.load(Js.resolveURL(u,r.path),g,void 0,f)})}).then(function(u){return c===!0&&o.revokeObjectURL(l),wn(u,a),u.userData.mimeType=a.mimeType||Ix(a.uri),u}).catch(function(u){throw console.error("THREE.GLTFLoader: Couldn't load texture",l),u});return this.sourceCache[e]=h,h}assignTexture(e,t,n,i){const r=this;return this.getDependency("texture",n.index).then(function(a){if(!a)return null;if(n.texCoord!==void 0&&n.texCoord>0&&(a=a.clone(),a.channel=n.texCoord),r.extensions[Ye.KHR_TEXTURE_TRANSFORM]){const o=n.extensions!==void 0?n.extensions[Ye.KHR_TEXTURE_TRANSFORM]:void 0;if(o){const l=r.associations.get(a);a=r.extensions[Ye.KHR_TEXTURE_TRANSFORM].extendTexture(a,o),r.associations.set(a,l)}}return i!==void 0&&(a.colorSpace=i),e[t]=a,a})}assignFinalMaterial(e){const t=e.geometry;let n=e.material;const i=t.attributes.tangent===void 0,r=t.attributes.color!==void 0,a=t.attributes.normal===void 0;if(e.isPoints){const o="PointsMaterial:"+n.uuid;let l=this.cache.get(o);l||(l=new Cu,dn.prototype.copy.call(l,n),l.color.copy(n.color),l.map=n.map,l.sizeAttenuation=!1,this.cache.add(o,l)),n=l}else if(e.isLine){const o="LineBasicMaterial:"+n.uuid;let l=this.cache.get(o);l||(l=new Ru,dn.prototype.copy.call(l,n),l.color.copy(n.color),l.map=n.map,this.cache.add(o,l)),n=l}if(i||r||a){let o="ClonedMaterial:"+n.uuid+":";i&&(o+="derivative-tangents:"),r&&(o+="vertex-colors:"),a&&(o+="flat-shading:");let l=this.cache.get(o);l||(l=n.clone(),r&&(l.vertexColors=!0),a&&(l.flatShading=!0),i&&(l.normalScale&&(l.normalScale.y*=-1),l.clearcoatNormalScale&&(l.clearcoatNormalScale.y*=-1)),this.cache.add(o,l),this.associations.set(l,this.associations.get(n))),n=l}e.material=n}getMaterialType(){return bs}loadMaterial(e){const t=this,n=this.json,i=this.extensions,r=n.materials[e];let a;const o={},l=r.extensions||{},c=[];if(l[Ye.KHR_MATERIALS_UNLIT]){const u=i[Ye.KHR_MATERIALS_UNLIT];a=u.getMaterialType(),c.push(u.extendParams(o,r,t))}else{const u=r.pbrMetallicRoughness||{};if(o.color=new Ie(1,1,1),o.opacity=1,Array.isArray(u.baseColorFactor)){const d=u.baseColorFactor;o.color.setRGB(d[0],d[1],d[2],Kt),o.opacity=d[3]}u.baseColorTexture!==void 0&&c.push(t.assignTexture(o,"map",u.baseColorTexture,wt)),o.metalness=u.metallicFactor!==void 0?u.metallicFactor:1,o.roughness=u.roughnessFactor!==void 0?u.roughnessFactor:1,u.metallicRoughnessTexture!==void 0&&(c.push(t.assignTexture(o,"metalnessMap",u.metallicRoughnessTexture)),c.push(t.assignTexture(o,"roughnessMap",u.metallicRoughnessTexture))),a=this._invokeOne(function(d){return d.getMaterialType&&d.getMaterialType(e)}),c.push(Promise.all(this._invokeAll(function(d){return d.extendMaterialParams&&d.extendMaterialParams(e,o)})))}r.doubleSided===!0&&(o.side=Pn);const h=r.alphaMode||vo.OPAQUE;if(h===vo.BLEND?(o.transparent=!0,o.depthWrite=!1):(o.transparent=!1,h===vo.MASK&&(o.alphaTest=r.alphaCutoff!==void 0?r.alphaCutoff:.5)),r.normalTexture!==void 0&&a!==Nn&&(c.push(t.assignTexture(o,"normalMap",r.normalTexture)),o.normalScale=new Le(1,1),r.normalTexture.scale!==void 0)){const u=r.normalTexture.scale;o.normalScale.set(u,u)}if(r.occlusionTexture!==void 0&&a!==Nn&&(c.push(t.assignTexture(o,"aoMap",r.occlusionTexture)),r.occlusionTexture.strength!==void 0&&(o.aoMapIntensity=r.occlusionTexture.strength)),r.emissiveFactor!==void 0&&a!==Nn){const u=r.emissiveFactor;o.emissive=new Ie().setRGB(u[0],u[1],u[2],Kt)}return r.emissiveTexture!==void 0&&a!==Nn&&c.push(t.assignTexture(o,"emissiveMap",r.emissiveTexture,wt)),Promise.all(c).then(function(){const u=new a(o);return r.name&&(u.name=r.name),wn(u,r),t.associations.set(u,{materials:e}),r.extensions&&wi(i,u,r),u})}createUniqueName(e){const t=st.sanitizeNodeName(e||"");return t in this.nodeNamesUsed?t+"_"+ ++this.nodeNamesUsed[t]:(this.nodeNamesUsed[t]=0,t)}loadGeometries(e){const t=this,n=this.extensions,i=this.primitiveCache;function r(o){return n[Ye.KHR_DRACO_MESH_COMPRESSION].decodePrimitive(o,t).then(function(l){return $h(l,o,t)})}const a=[];for(let o=0,l=e.length;o<l;o++){const c=e[o],h=Lx(c),u=i[h];if(u)a.push(u.promise);else{let d;c.extensions&&c.extensions[Ye.KHR_DRACO_MESH_COMPRESSION]?d=r(c):d=$h(new ln,c,t),i[h]={primitive:c,promise:d},a.push(d)}}return Promise.all(a)}loadMesh(e){const t=this,n=this.json,i=this.extensions,r=n.meshes[e],a=r.primitives,o=[];for(let l=0,c=a.length;l<c;l++){const h=a[l].material===void 0?Cx(this.cache):this.getDependency("material",a[l].material);o.push(h)}return o.push(t.loadGeometries(a)),Promise.all(o).then(function(l){const c=l.slice(0,l.length-1),h=l[l.length-1],u=[];for(let f=0,g=h.length;f<g;f++){const x=h[f],p=a[f];let m;const S=c[f];if(p.mode===hn.TRIANGLES||p.mode===hn.TRIANGLE_STRIP||p.mode===hn.TRIANGLE_FAN||p.mode===void 0)m=r.isSkinnedMesh===!0?new fp(x,S):new lt(x,S),m.isSkinnedMesh===!0&&m.normalizeSkinWeights(),p.mode===hn.TRIANGLE_STRIP?m.geometry=Wh(m.geometry,yu):p.mode===hn.TRIANGLE_FAN&&(m.geometry=Wh(m.geometry,gl));else if(p.mode===hn.LINES)m=new xp(x,S);else if(p.mode===hn.LINE_STRIP)m=new nc(x,S);else if(p.mode===hn.LINE_LOOP)m=new Mp(x,S);else if(p.mode===hn.POINTS)m=new yp(x,S);else throw new Error("THREE.GLTFLoader: Primitive mode unsupported: "+p.mode);Object.keys(m.geometry.morphAttributes).length>0&&Dx(m,r),m.name=t.createUniqueName(r.name||"mesh_"+e),wn(m,r),p.extensions&&wi(i,m,p),t.assignFinalMaterial(m),u.push(m)}for(let f=0,g=u.length;f<g;f++)t.associations.set(u[f],{meshes:e,primitives:f});if(u.length===1)return r.extensions&&wi(i,u[0],r),u[0];const d=new In;r.extensions&&wi(i,d,r),t.associations.set(d,{meshes:e});for(let f=0,g=u.length;f<g;f++)d.add(u[f]);return d})}loadCamera(e){let t;const n=this.json.cameras[e],i=n[n.type];if(!i){console.warn("THREE.GLTFLoader: Missing camera parameters.");return}return n.type==="perspective"?t=new Wt(je.radToDeg(i.yfov),i.aspectRatio||1,i.znear||1,i.zfar||2e6):n.type==="orthographic"&&(t=new or(-i.xmag,i.xmag,i.ymag,-i.ymag,i.znear,i.zfar)),n.name&&(t.name=this.createUniqueName(n.name)),wn(t,n),Promise.resolve(t)}loadSkin(e){const t=this.json.skins[e],n=[];for(let i=0,r=t.joints.length;i<r;i++)n.push(this._loadNodeShallow(t.joints[i]));return t.inverseBindMatrices!==void 0?n.push(this.getDependency("accessor",t.inverseBindMatrices)):n.push(null),Promise.all(n).then(function(i){const r=i.pop(),a=i,o=[],l=[];for(let c=0,h=a.length;c<h;c++){const u=a[c];if(u){o.push(u);const d=new Ve;r!==null&&d.fromArray(r.array,c*16),l.push(d)}else console.warn('THREE.GLTFLoader: Joint "%s" could not be found.',t.joints[c])}return new Ql(o,l)})}loadAnimation(e){const t=this.json,n=this,i=t.animations[e],r=i.name?i.name:"animation_"+e,a=[],o=[],l=[],c=[],h=[];for(let u=0,d=i.channels.length;u<d;u++){const f=i.channels[u],g=i.samplers[f.sampler],x=f.target,p=x.node,m=i.parameters!==void 0?i.parameters[g.input]:g.input,S=i.parameters!==void 0?i.parameters[g.output]:g.output;x.node!==void 0&&(a.push(this.getDependency("node",p)),o.push(this.getDependency("accessor",m)),l.push(this.getDependency("accessor",S)),c.push(g),h.push(x))}return Promise.all([Promise.all(a),Promise.all(o),Promise.all(l),Promise.all(c),Promise.all(h)]).then(function(u){const d=u[0],f=u[1],g=u[2],x=u[3],p=u[4],m=[];for(let T=0,M=d.length;T<M;T++){const E=d[T],w=f[T],C=g[T],v=x[T],b=p[T];if(E===void 0)continue;E.updateMatrix&&E.updateMatrix();const D=n._createAnimationTracks(E,w,C,v,b);if(D)for(let R=0;R<D.length;R++)m.push(D[R])}const S=new Up(r,void 0,m);return wn(S,i),S})}createNodeMesh(e){const t=this.json,n=this,i=t.nodes[e];return i.mesh===void 0?null:n.getDependency("mesh",i.mesh).then(function(r){const a=n._getNodeRef(n.meshCache,i.mesh,r);return i.weights!==void 0&&a.traverse(function(o){if(o.isMesh)for(let l=0,c=i.weights.length;l<c;l++)o.morphTargetInfluences[l]=i.weights[l]}),a})}loadNode(e){const t=this.json,n=this,i=t.nodes[e],r=n._loadNodeShallow(e),a=[],o=i.children||[];for(let c=0,h=o.length;c<h;c++)a.push(n.getDependency("node",o[c]));const l=i.skin===void 0?Promise.resolve(null):n.getDependency("skin",i.skin);return Promise.all([r,Promise.all(a),l]).then(function(c){const h=c[0],u=c[1],d=c[2];d!==null&&h.traverse(function(f){f.isSkinnedMesh&&f.bind(d,Nx)});for(let f=0,g=u.length;f<g;f++)h.add(u[f]);if(h.userData.pivot!==void 0&&u.length>0){const f=h.userData.pivot,g=u[0];h.pivot=new L().fromArray(f),h.position.x-=f[0],h.position.y-=f[1],h.position.z-=f[2],g.position.set(0,0,0),delete h.userData.pivot}return h})}_loadNodeShallow(e){const t=this.json,n=this.extensions,i=this;if(this.nodeCache[e]!==void 0)return this.nodeCache[e];const r=t.nodes[e],a=r.name?i.createUniqueName(r.name):"",o=[],l=i._invokeOne(function(c){return c.createNodeMesh&&c.createNodeMesh(e)});return l&&o.push(l),r.camera!==void 0&&o.push(i.getDependency("camera",r.camera).then(function(c){return i._getNodeRef(i.cameraCache,r.camera,c)})),i._invokeAll(function(c){return c.createNodeAttachment&&c.createNodeAttachment(e)}).forEach(function(c){o.push(c)}),this.nodeCache[e]=Promise.all(o).then(function(c){let h;if(r.isBone===!0?h=new wu:c.length>1?h=new In:c.length===1?h=c[0]:h=new ft,h!==c[0])for(let u=0,d=c.length;u<d;u++)h.add(c[u]);if(r.name&&(h.userData.name=r.name,h.name=a),wn(h,r),r.extensions&&wi(n,h,r),r.matrix!==void 0){const u=new Ve;u.fromArray(r.matrix),h.applyMatrix4(u)}else r.translation!==void 0&&h.position.fromArray(r.translation),r.rotation!==void 0&&h.quaternion.fromArray(r.rotation),r.scale!==void 0&&h.scale.fromArray(r.scale);if(!i.associations.has(h))i.associations.set(h,{});else if(r.mesh!==void 0&&i.meshCache.refs[r.mesh]>1){const u=i.associations.get(h);i.associations.set(h,{...u})}return i.associations.get(h).nodes=e,h}),this.nodeCache[e]}loadScene(e){const t=this.extensions,n=this.json.scenes[e],i=this,r=new In;n.name&&(r.name=i.createUniqueName(n.name)),wn(r,n),n.extensions&&wi(t,r,n);const a=n.nodes||[],o=[];for(let l=0,c=a.length;l<c;l++)o.push(i.getDependency("node",a[l]));return Promise.all(o).then(function(l){for(let h=0,u=l.length;h<u;h++){const d=l[h];d.parent!==null?r.add(ix(d)):r.add(d)}const c=h=>{const u=new Map;for(const[d,f]of i.associations)(d instanceof dn||d instanceof Pt)&&u.set(d,f);return h.traverse(d=>{const f=i.associations.get(d);f!=null&&u.set(d,f)}),u};return i.associations=c(r),r})}_createAnimationTracks(e,t,n,i,r){const a=[],o=e.name?e.name:e.uuid,l=[];ci[r.path]===ci.weights?e.traverse(function(d){d.morphTargetInfluences&&l.push(d.name?d.name:d.uuid)}):l.push(o);let c;switch(ci[r.path]){case ci.weights:c=Es;break;case ci.rotation:c=Ts;break;case ci.translation:case ci.scale:c=As;break;default:n.itemSize===1?c=Es:c=As;break}const h=i.interpolation!==void 0?Rx[i.interpolation]:tr,u=this._getArrayFromAccessor(n);for(let d=0,f=l.length;d<f;d++){const g=new c(l[d]+"."+ci[r.path],t.array,u,h);i.interpolation==="CUBICSPLINE"&&this._createCubicSplineTrackInterpolant(g),a.push(g)}return a}_getArrayFromAccessor(e){let t=e.array;if(e.normalized){const n=Al(t.constructor),i=new Float32Array(t.length);for(let r=0,a=t.length;r<a;r++)i[r]=t[r]*n;t=i}return t}_createCubicSplineTrackInterpolant(e){e.createInterpolant=function(n){const i=this instanceof Ts?wx:Ku;return new i(this.times,this.values,this.getValueSize()/3,n)},e.createInterpolant.isInterpolantFactoryMethodGLTFCubicSpline=!0}}function Fx(s,e,t){const n=e.attributes,i=new Qn;if(n.POSITION!==void 0){const o=t.json.accessors[n.POSITION],l=o.min,c=o.max;if(l!==void 0&&c!==void 0){if(i.set(new L(l[0],l[1],l[2]),new L(c[0],c[1],c[2])),o.normalized){const h=Al(us[o.componentType]);i.min.multiplyScalar(h),i.max.multiplyScalar(h)}}else{console.warn("THREE.GLTFLoader: Missing min/max properties for accessor POSITION.");return}}else return;const r=e.targets;if(r!==void 0){const o=new L,l=new L;for(let c=0,h=r.length;c<h;c++){const u=r[c];if(u.POSITION!==void 0){const d=t.json.accessors[u.POSITION],f=d.min,g=d.max;if(f!==void 0&&g!==void 0){if(l.setX(Math.max(Math.abs(f[0]),Math.abs(g[0]))),l.setY(Math.max(Math.abs(f[1]),Math.abs(g[1]))),l.setZ(Math.max(Math.abs(f[2]),Math.abs(g[2]))),d.normalized){const x=Al(us[d.componentType]);l.multiplyScalar(x)}o.max(l)}else console.warn("THREE.GLTFLoader: Missing min/max properties for accessor POSITION.")}}i.expandByVector(o)}s.boundingBox=i;const a=new On;i.getCenter(a.center),a.radius=i.min.distanceTo(i.max)/2,s.boundingSphere=a}function $h(s,e,t){const n=e.attributes,i=[];function r(a,o){return t.getDependency("accessor",a).then(function(l){s.setAttribute(o,l)})}for(const a in n){const o=Tl[a]||a.toLowerCase();o in s.attributes||i.push(r(n[a],o))}if(e.indices!==void 0&&!s.index){const a=t.getDependency("accessor",e.indices).then(function(o){s.setIndex(o)});i.push(a)}return Ke.workingColorSpace!==Kt&&"COLOR_0"in n&&console.warn(`THREE.GLTFLoader: Converting vertex colors from "srgb-linear" to "${Ke.workingColorSpace}" not supported.`),wn(s,e),Fx(s,e,t),Promise.all(i).then(function(){return e.targets!==void 0?Px(s,e.targets,t):s})}class Ox extends Zl{constructor(){super(),this.name="RoomEnvironment",this.position.y=-3.5;const e=new Cs;e.deleteAttribute("uv");const t=new bs({side:qt}),n=new bs,i=new ku(16777215,900,28,2);i.position.set(.418,16.199,.3),this.add(i);const r=new lt(e,t);r.position.set(-.757,13.219,.717),r.scale.set(31.713,28.305,28.591),this.add(r);const a=new ec(e,n,6),o=new ft;o.position.set(-10.906,2.009,1.846),o.rotation.set(0,-.195,0),o.scale.set(2.328,7.905,4.651),o.updateMatrix(),a.setMatrixAt(0,o.matrix),o.position.set(-5.607,-.754,-.758),o.rotation.set(0,.994,0),o.scale.set(1.97,1.534,3.955),o.updateMatrix(),a.setMatrixAt(1,o.matrix),o.position.set(6.167,.857,7.803),o.rotation.set(0,.561,0),o.scale.set(3.927,6.285,3.687),o.updateMatrix(),a.setMatrixAt(2,o.matrix),o.position.set(-2.017,.018,6.124),o.rotation.set(0,.333,0),o.scale.set(2.002,4.566,2.064),o.updateMatrix(),a.setMatrixAt(3,o.matrix),o.position.set(2.291,-.756,-2.621),o.rotation.set(0,-.286,0),o.scale.set(1.546,1.552,1.496),o.updateMatrix(),a.setMatrixAt(4,o.matrix),o.position.set(-2.193,-.369,-5.547),o.rotation.set(0,.516,0),o.scale.set(3.875,3.487,2.986),o.updateMatrix(),a.setMatrixAt(5,o.matrix),this.add(a);const l=new lt(e,ns(50));l.position.set(-16.116,14.37,8.208),l.scale.set(.1,2.428,2.739),this.add(l);const c=new lt(e,ns(50));c.position.set(-16.109,18.021,-8.207),c.scale.set(.1,2.425,2.751),this.add(c);const h=new lt(e,ns(17));h.position.set(14.904,12.198,-1.832),h.scale.set(.15,4.265,6.331),this.add(h);const u=new lt(e,ns(43));u.position.set(-.462,8.89,14.52),u.scale.set(4.38,5.441,.088),this.add(u);const d=new lt(e,ns(20));d.position.set(3.235,11.486,-12.541),d.scale.set(2.5,2,.1),this.add(d);const f=new lt(e,ns(100));f.position.set(0,20,0),f.scale.set(1,.1,1),this.add(f)}dispose(){const e=new Set;this.traverse(t=>{t.isMesh&&(e.add(t.geometry),e.add(t.material))});for(const t of e)t.dispose()}}function ns(s){return new wp({color:0,emissive:16777215,emissiveIntensity:s})}function $u(s,e,t="baseline"){const n=t==="refined";s.toneMappingExposure=n?1:1.05;const i=new Sl(s),r=new Ox;e.environment=i.fromScene(r,.04).texture,r.dispose(),i.dispose(),e.environmentIntensity=n?.52:.48,e.add(new Gp("#fffaf5",n?"#b49b80":"#b4a18c",n?.5:.65));const a=new Ml(n?"#fff4e5":"#fff7ed",n?1.7:1.4);a.position.set(...n?[-8,14,4]:[-6,14,-5]);const o=new Ml("#ffffff",n?.3:.6);return o.position.set(7,8,-10),e.add(a,o),a}const ea={name:"CopyShader",uniforms:{tDiffuse:{value:null},opacity:{value:1}},vertexShader:`

		varying vec2 vUv;

		void main() {

			vUv = uv;
			gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

		}`,fragmentShader:`

		uniform float opacity;

		uniform sampler2D tDiffuse;

		varying vec2 vUv;

		void main() {

			vec4 texel = texture2D( tDiffuse, vUv );
			gl_FragColor = opacity * texel;


		}`};class Ui{constructor(){this.isPass=!0,this.enabled=!0,this.needsSwap=!0,this.clear=!1,this.renderToScreen=!1}setSize(){}render(){console.error("THREE.Pass: .render() must be implemented in derived pass.")}dispose(){}}const Bx=new or(-1,1,1,-1,0,1);class kx extends ln{constructor(){super(),this.setAttribute("position",new an([-1,3,0,-1,-1,0,3,-1,0],3)),this.setAttribute("uv",new an([0,2,0,0,2,0],2))}}const Vx=new kx;class Sa{constructor(e){this._mesh=new lt(Vx,e)}dispose(){this._mesh.geometry.dispose()}render(e){e.render(this._mesh,Bx)}get material(){return this._mesh.material}set material(e){this._mesh.material=e}}class zx extends Ui{constructor(e,t="tDiffuse"){super(),this.textureID=t,this.uniforms=null,this.material=null,e instanceof kt?(this.uniforms=e.uniforms,this.material=e):e&&(this.uniforms=mi.clone(e.uniforms),this.material=new kt({name:e.name!==void 0?e.name:"unspecified",defines:Object.assign({},e.defines),uniforms:this.uniforms,vertexShader:e.vertexShader,fragmentShader:e.fragmentShader})),this._fsQuad=new Sa(this.material)}render(e,t,n){this.uniforms[this.textureID]&&(this.uniforms[this.textureID].value=n.texture),this._fsQuad.material=this.material,this.renderToScreen?(e.setRenderTarget(null),this._fsQuad.render(e)):(e.setRenderTarget(t),this.clear&&e.clear(e.autoClearColor,e.autoClearDepth,e.autoClearStencil),this._fsQuad.render(e))}dispose(){this.material.dispose(),this._fsQuad.dispose()}}class Zh extends Ui{constructor(e,t){super(),this.scene=e,this.camera=t,this.clear=!0,this.needsSwap=!1,this.inverse=!1}render(e,t,n){const i=e.getContext(),r=e.state;r.buffers.color.setMask(!1),r.buffers.depth.setMask(!1),r.buffers.color.setLocked(!0),r.buffers.depth.setLocked(!0);let a,o;this.inverse?(a=0,o=1):(a=1,o=0),r.buffers.stencil.setTest(!0),r.buffers.stencil.setOp(i.REPLACE,i.REPLACE,i.REPLACE),r.buffers.stencil.setFunc(i.ALWAYS,a,4294967295),r.buffers.stencil.setClear(o),r.buffers.stencil.setLocked(!0),e.setRenderTarget(n),this.clear&&e.clear(),e.render(this.scene,this.camera),e.setRenderTarget(t),this.clear&&e.clear(),e.render(this.scene,this.camera),r.buffers.color.setLocked(!1),r.buffers.depth.setLocked(!1),r.buffers.color.setMask(!0),r.buffers.depth.setMask(!0),r.buffers.stencil.setLocked(!1),r.buffers.stencil.setFunc(i.EQUAL,1,4294967295),r.buffers.stencil.setOp(i.KEEP,i.KEEP,i.KEEP),r.buffers.stencil.setLocked(!0)}}class Hx extends Ui{constructor(){super(),this.needsSwap=!1}render(e){e.state.buffers.stencil.setLocked(!1),e.state.buffers.stencil.setTest(!1)}}class Gx{constructor(e,t){if(this.renderer=e,this._pixelRatio=e.getPixelRatio(),t===void 0){const n=e.getSize(new Le);this._width=n.width,this._height=n.height,t=new Jt(this._width*this._pixelRatio,this._height*this._pixelRatio,{type:on}),t.texture.name="EffectComposer.rt1"}else this._width=t.width,this._height=t.height;this.renderTarget1=t,this.renderTarget2=t.clone(),this.renderTarget2.texture.name="EffectComposer.rt2",this.writeBuffer=this.renderTarget1,this.readBuffer=this.renderTarget2,this.renderToScreen=!0,this.passes=[],this.copyPass=new zx(ea),this.copyPass.material.blending=Bt,this.timer=new Zp}swapBuffers(){const e=this.readBuffer;this.readBuffer=this.writeBuffer,this.writeBuffer=e}addPass(e){this.passes.push(e),e.setSize(this._width*this._pixelRatio,this._height*this._pixelRatio)}insertPass(e,t){this.passes.splice(t,0,e),e.setSize(this._width*this._pixelRatio,this._height*this._pixelRatio)}removePass(e){const t=this.passes.indexOf(e);t!==-1&&this.passes.splice(t,1)}isLastEnabledPass(e){for(let t=e+1;t<this.passes.length;t++)if(this.passes[t].enabled)return!1;return!0}render(e){this.timer.update(),e===void 0&&(e=this.timer.getDelta());const t=this.renderer.getRenderTarget();let n=!1;for(let i=0,r=this.passes.length;i<r;i++){const a=this.passes[i];if(a.enabled!==!1){if(a.renderToScreen=this.renderToScreen&&this.isLastEnabledPass(i),a.render(this.renderer,this.writeBuffer,this.readBuffer,e,n),a.needsSwap){if(n){const o=this.renderer.getContext(),l=this.renderer.state.buffers.stencil;l.setFunc(o.NOTEQUAL,1,4294967295),this.copyPass.render(this.renderer,this.writeBuffer,this.readBuffer,e),l.setFunc(o.EQUAL,1,4294967295)}this.swapBuffers()}Zh!==void 0&&(a instanceof Zh?n=!0:a instanceof Hx&&(n=!1))}}this.renderer.setRenderTarget(t)}reset(e){if(e===void 0){const t=this.renderer.getSize(new Le);this._pixelRatio=this.renderer.getPixelRatio(),this._width=t.width,this._height=t.height,e=this.renderTarget1.clone(),e.setSize(this._width*this._pixelRatio,this._height*this._pixelRatio)}this.renderTarget1.dispose(),this.renderTarget2.dispose(),this.renderTarget1=e,this.renderTarget2=e.clone(),this.writeBuffer=this.renderTarget1,this.readBuffer=this.renderTarget2}setSize(e,t){this._width=e,this._height=t;const n=this._width*this._pixelRatio,i=this._height*this._pixelRatio;this.renderTarget1.setSize(n,i),this.renderTarget2.setSize(n,i);for(let r=0;r<this.passes.length;r++)this.passes[r].setSize(n,i)}setPixelRatio(e){this._pixelRatio=e,this.setSize(this._width,this._height)}dispose(){this.renderTarget1.dispose(),this.renderTarget2.dispose(),this.copyPass.dispose()}}class Wx extends Ui{constructor(e,t,n=null,i=null,r=null){super(),this.scene=e,this.camera=t,this.overrideMaterial=n,this.clearColor=i,this.clearAlpha=r,this.clear=!0,this.clearDepth=!1,this.needsSwap=!1,this.isRenderPass=!0,this._oldClearColor=new Ie}render(e,t,n){const i=e.autoClear;e.autoClear=!1;let r,a;this.overrideMaterial!==null&&(a=this.scene.overrideMaterial,this.scene.overrideMaterial=this.overrideMaterial),this.clearColor!==null&&(e.getClearColor(this._oldClearColor),e.setClearColor(this.clearColor,e.getClearAlpha())),this.clearAlpha!==null&&(r=e.getClearAlpha(),e.setClearAlpha(this.clearAlpha)),this.clearDepth==!0&&e.clearDepth(),e.setRenderTarget(this.renderToScreen?null:n),this.clear===!0&&e.clear(e.autoClearColor,e.autoClearDepth,e.autoClearStencil),e.render(this.scene,this.camera),this.clearColor!==null&&e.setClearColor(this._oldClearColor),this.clearAlpha!==null&&e.setClearAlpha(r),this.overrideMaterial!==null&&(this.scene.overrideMaterial=a),e.autoClear=i}}class Xx{constructor(e=Math){this.grad3=[[1,1,0],[-1,1,0],[1,-1,0],[-1,-1,0],[1,0,1],[-1,0,1],[1,0,-1],[-1,0,-1],[0,1,1],[0,-1,1],[0,1,-1],[0,-1,-1]],this.grad4=[[0,1,1,1],[0,1,1,-1],[0,1,-1,1],[0,1,-1,-1],[0,-1,1,1],[0,-1,1,-1],[0,-1,-1,1],[0,-1,-1,-1],[1,0,1,1],[1,0,1,-1],[1,0,-1,1],[1,0,-1,-1],[-1,0,1,1],[-1,0,1,-1],[-1,0,-1,1],[-1,0,-1,-1],[1,1,0,1],[1,1,0,-1],[1,-1,0,1],[1,-1,0,-1],[-1,1,0,1],[-1,1,0,-1],[-1,-1,0,1],[-1,-1,0,-1],[1,1,1,0],[1,1,-1,0],[1,-1,1,0],[1,-1,-1,0],[-1,1,1,0],[-1,1,-1,0],[-1,-1,1,0],[-1,-1,-1,0]],this.p=[];for(let t=0;t<256;t++)this.p[t]=Math.floor(e.random()*256);this.perm=[];for(let t=0;t<512;t++)this.perm[t]=this.p[t&255];this.simplex=[[0,1,2,3],[0,1,3,2],[0,0,0,0],[0,2,3,1],[0,0,0,0],[0,0,0,0],[0,0,0,0],[1,2,3,0],[0,2,1,3],[0,0,0,0],[0,3,1,2],[0,3,2,1],[0,0,0,0],[0,0,0,0],[0,0,0,0],[1,3,2,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[1,2,0,3],[0,0,0,0],[1,3,0,2],[0,0,0,0],[0,0,0,0],[0,0,0,0],[2,3,0,1],[2,3,1,0],[1,0,2,3],[1,0,3,2],[0,0,0,0],[0,0,0,0],[0,0,0,0],[2,0,3,1],[0,0,0,0],[2,1,3,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[2,0,1,3],[0,0,0,0],[0,0,0,0],[0,0,0,0],[3,0,1,2],[3,0,2,1],[0,0,0,0],[3,1,2,0],[2,1,0,3],[0,0,0,0],[0,0,0,0],[0,0,0,0],[3,1,0,2],[0,0,0,0],[3,2,0,1],[3,2,1,0]]}noise(e,t){let n,i,r;const a=.5*(Math.sqrt(3)-1),o=(e+t)*a,l=Math.floor(e+o),c=Math.floor(t+o),h=(3-Math.sqrt(3))/6,u=(l+c)*h,d=l-u,f=c-u,g=e-d,x=t-f;let p,m;g>x?(p=1,m=0):(p=0,m=1);const S=g-p+h,T=x-m+h,M=g-1+2*h,E=x-1+2*h,w=l&255,C=c&255,v=this.perm[w+this.perm[C]]%12,b=this.perm[w+p+this.perm[C+m]]%12,D=this.perm[w+1+this.perm[C+1]]%12;let R=.5-g*g-x*x;R<0?n=0:(R*=R,n=R*R*this._dot(this.grad3[v],g,x));let F=.5-S*S-T*T;F<0?i=0:(F*=F,i=F*F*this._dot(this.grad3[b],S,T));let O=.5-M*M-E*E;return O<0?r=0:(O*=O,r=O*O*this._dot(this.grad3[D],M,E)),70*(n+i+r)}noise3d(e,t,n){let i,r,a,o;const c=(e+t+n)*.3333333333333333,h=Math.floor(e+c),u=Math.floor(t+c),d=Math.floor(n+c),f=1/6,g=(h+u+d)*f,x=h-g,p=u-g,m=d-g,S=e-x,T=t-p,M=n-m;let E,w,C,v,b,D;S>=T?T>=M?(E=1,w=0,C=0,v=1,b=1,D=0):S>=M?(E=1,w=0,C=0,v=1,b=0,D=1):(E=0,w=0,C=1,v=1,b=0,D=1):T<M?(E=0,w=0,C=1,v=0,b=1,D=1):S<M?(E=0,w=1,C=0,v=0,b=1,D=1):(E=0,w=1,C=0,v=1,b=1,D=0);const R=S-E+f,F=T-w+f,O=M-C+f,X=S-v+2*f,V=T-b+2*f,k=M-D+2*f,U=S-1+3*f,Q=T-1+3*f,K=M-1+3*f,se=h&255,he=u&255,le=d&255,$=this.perm[se+this.perm[he+this.perm[le]]]%12,ce=this.perm[se+E+this.perm[he+w+this.perm[le+C]]]%12,Re=this.perm[se+v+this.perm[he+b+this.perm[le+D]]]%12,G=this.perm[se+1+this.perm[he+1+this.perm[le+1]]]%12;let Z=.6-S*S-T*T-M*M;Z<0?i=0:(Z*=Z,i=Z*Z*this._dot3(this.grad3[$],S,T,M));let ee=.6-R*R-F*F-O*O;ee<0?r=0:(ee*=ee,r=ee*ee*this._dot3(this.grad3[ce],R,F,O));let we=.6-X*X-V*V-k*k;we<0?a=0:(we*=we,a=we*we*this._dot3(this.grad3[Re],X,V,k));let ve=.6-U*U-Q*Q-K*K;return ve<0?o=0:(ve*=ve,o=ve*ve*this._dot3(this.grad3[G],U,Q,K)),32*(i+r+a+o)}noise4d(e,t,n,i){const r=this.grad4,a=this.simplex,o=this.perm,l=(Math.sqrt(5)-1)/4,c=(5-Math.sqrt(5))/20;let h,u,d,f,g;const x=(e+t+n+i)*l,p=Math.floor(e+x),m=Math.floor(t+x),S=Math.floor(n+x),T=Math.floor(i+x),M=(p+m+S+T)*c,E=p-M,w=m-M,C=S-M,v=T-M,b=e-E,D=t-w,R=n-C,F=i-v,O=b>D?32:0,X=b>R?16:0,V=D>R?8:0,k=b>F?4:0,U=D>F?2:0,Q=R>F?1:0,K=O+X+V+k+U+Q,se=a[K][0]>=3?1:0,he=a[K][1]>=3?1:0,le=a[K][2]>=3?1:0,$=a[K][3]>=3?1:0,ce=a[K][0]>=2?1:0,Re=a[K][1]>=2?1:0,G=a[K][2]>=2?1:0,Z=a[K][3]>=2?1:0,ee=a[K][0]>=1?1:0,we=a[K][1]>=1?1:0,ve=a[K][2]>=1?1:0,Fe=a[K][3]>=1?1:0,Mt=b-se+c,qe=D-he+c,Ze=R-le+c,Qe=F-$+c,ke=b-ce+2*c,pt=D-Re+2*c,P=R-G+2*c,gt=F-Z+2*c,$e=b-ee+3*c,et=D-we+3*c,Me=R-ve+3*c,A=F-Fe+3*c,_=b-1+4*c,N=D-1+4*c,j=R-1+4*c,J=F-1+4*c,Y=p&255,ge=m&255,re=S&255,Ee=T&255,Ne=o[Y+o[ge+o[re+o[Ee]]]]%32,te=o[Y+se+o[ge+he+o[re+le+o[Ee+$]]]]%32,ae=o[Y+ce+o[ge+Re+o[re+G+o[Ee+Z]]]]%32,ye=o[Y+ee+o[ge+we+o[re+ve+o[Ee+Fe]]]]%32,Se=o[Y+1+o[ge+1+o[re+1+o[Ee+1]]]]%32;let fe=.6-b*b-D*D-R*R-F*F;fe<0?h=0:(fe*=fe,h=fe*fe*this._dot4(r[Ne],b,D,R,F));let Oe=.6-Mt*Mt-qe*qe-Ze*Ze-Qe*Qe;Oe<0?u=0:(Oe*=Oe,u=Oe*Oe*this._dot4(r[te],Mt,qe,Ze,Qe));let I=.6-ke*ke-pt*pt-P*P-gt*gt;I<0?d=0:(I*=I,d=I*I*this._dot4(r[ae],ke,pt,P,gt));let oe=.6-$e*$e-et*et-Me*Me-A*A;oe<0?f=0:(oe*=oe,f=oe*oe*this._dot4(r[ye],$e,et,Me,A));let ne=.6-_*_-N*N-j*j-J*J;return ne<0?g=0:(ne*=ne,g=ne*ne*this._dot4(r[Se],_,N,j,J)),27*(h+u+d+f+g)}_dot(e,t,n){return e[0]*t+e[1]*n}_dot3(e,t,n,i){return e[0]*t+e[1]*n+e[2]*i}_dot4(e,t,n,i,r){return e[0]*t+e[1]*n+e[2]*i+e[3]*r}}const kr={defines:{PERSPECTIVE_CAMERA:1,KERNEL_SIZE:32},uniforms:{tNormal:{value:null},tDepth:{value:null},tNoise:{value:null},kernel:{value:null},cameraNear:{value:null},cameraFar:{value:null},resolution:{value:new Le},cameraProjectionMatrix:{value:new Ve},cameraInverseProjectionMatrix:{value:new Ve},kernelRadius:{value:8},minDistance:{value:.005},maxDistance:{value:.05}},vertexShader:`

		varying vec2 vUv;

		void main() {

			vUv = uv;

			gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

		}`,fragmentShader:`
		uniform highp sampler2D tNormal;
		uniform highp sampler2D tDepth;
		uniform sampler2D tNoise;

		uniform vec3 kernel[ KERNEL_SIZE ];

		uniform vec2 resolution;

		uniform float cameraNear;
		uniform float cameraFar;
		uniform mat4 cameraProjectionMatrix;
		uniform mat4 cameraInverseProjectionMatrix;

		uniform float kernelRadius;
		uniform float minDistance; // avoid artifacts caused by neighbour fragments with minimal depth difference
		uniform float maxDistance; // avoid the influence of fragments which are too far away

		varying vec2 vUv;

		#include <packing>

		#ifdef USE_REVERSED_DEPTH_BUFFER

			const float depthThreshold = 0.0;

		#else

			const float depthThreshold = 1.0;

		#endif

		float getDepth( const in vec2 screenPosition ) {

			return texture2D( tDepth, screenPosition ).x;

		}

		float getLinearDepth( const in vec2 screenPosition ) {

			#if PERSPECTIVE_CAMERA == 1

				float fragCoordZ = texture2D( tDepth, screenPosition ).x;
				float viewZ = perspectiveDepthToViewZ( fragCoordZ, cameraNear, cameraFar );
				return viewZToOrthographicDepth( viewZ, cameraNear, cameraFar );

			#else

				return texture2D( tDepth, screenPosition ).x;

			#endif

		}

		float getViewZ( const in float depth ) {

			#if PERSPECTIVE_CAMERA == 1

				return perspectiveDepthToViewZ( depth, cameraNear, cameraFar );

			#else

				return orthographicDepthToViewZ( depth, cameraNear, cameraFar );

			#endif

		}

		vec3 getViewPosition( const in vec2 screenPosition, const in float depth, const in float viewZ ) {

			float clipW = cameraProjectionMatrix[2][3] * viewZ + cameraProjectionMatrix[3][3];

			vec4 clipPosition = vec4( ( vec3( screenPosition, depth ) - 0.5 ) * 2.0, 1.0 );

			clipPosition *= clipW; // unprojection.

			return ( cameraInverseProjectionMatrix * clipPosition ).xyz;

		}

		vec3 getViewNormal( const in vec2 screenPosition ) {

			return unpackRGBToNormal( texture2D( tNormal, screenPosition ).xyz );

		}

		void main() {

			float depth = getDepth( vUv );

			if ( depth == depthThreshold ) {

				gl_FragColor = vec4( 1.0 ); // don't influence background

			} else {

				float viewZ = getViewZ( depth );

				vec3 viewPosition = getViewPosition( vUv, depth, viewZ );
				vec3 viewNormal = getViewNormal( vUv );

				vec2 noiseScale = vec2( resolution.x / 4.0, resolution.y / 4.0 );
				vec3 random = vec3( texture2D( tNoise, vUv * noiseScale ).r );

				// compute matrix used to reorient a kernel vector

				vec3 tangent = normalize( random - viewNormal * dot( random, viewNormal ) );
				vec3 bitangent = cross( viewNormal, tangent );
				mat3 kernelMatrix = mat3( tangent, bitangent, viewNormal );

				float occlusion = 0.0;

				for ( int i = 0; i < KERNEL_SIZE; i ++ ) {

					vec3 sampleVector = kernelMatrix * kernel[ i ]; // reorient sample vector in view space
					vec3 samplePoint = viewPosition + ( sampleVector * kernelRadius ); // calculate sample point

					vec4 samplePointNDC = cameraProjectionMatrix * vec4( samplePoint, 1.0 ); // project point and calculate NDC
					samplePointNDC /= samplePointNDC.w;

					vec2 samplePointUv = samplePointNDC.xy * 0.5 + 0.5; // compute uv coordinates

					float realDepth = getLinearDepth( samplePointUv ); // get linear depth from depth texture
					float sampleDepth = viewZToOrthographicDepth( samplePoint.z, cameraNear, cameraFar ); // compute linear depth of the sample view Z value
					float delta = sampleDepth - realDepth;

					if ( delta > minDistance && delta < maxDistance ) { // if fragment is before sample point, increase occlusion

						occlusion += 1.0;

					}

				}

				occlusion = clamp( occlusion / float( KERNEL_SIZE ), 0.0, 1.0 );

				gl_FragColor = vec4( vec3( 1.0 - occlusion ), 1.0 );

			}

		}`},Vr={defines:{PERSPECTIVE_CAMERA:1},uniforms:{tDepth:{value:null},cameraNear:{value:null},cameraFar:{value:null}},vertexShader:`varying vec2 vUv;

		void main() {

			vUv = uv;
			gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

		}`,fragmentShader:`uniform sampler2D tDepth;

		uniform float cameraNear;
		uniform float cameraFar;

		varying vec2 vUv;

		#include <packing>

		float getLinearDepth( const in vec2 screenPosition ) {

			#if PERSPECTIVE_CAMERA == 1

				float fragCoordZ = texture2D( tDepth, screenPosition ).x;
				float viewZ = perspectiveDepthToViewZ( fragCoordZ, cameraNear, cameraFar );
				return viewZToOrthographicDepth( viewZ, cameraNear, cameraFar );

			#else

				return texture2D( tDepth, screenPosition ).x;

			#endif

		}

		void main() {

			float depth = getLinearDepth( vUv );
			gl_FragColor = vec4( vec3( 1.0 - depth ), 1.0 );

		}`},zr={uniforms:{tDiffuse:{value:null},resolution:{value:new Le}},vertexShader:`varying vec2 vUv;

		void main() {

			vUv = uv;
			gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

		}`,fragmentShader:`uniform sampler2D tDiffuse;

		uniform vec2 resolution;

		varying vec2 vUv;

		void main() {

			vec2 texelSize = ( 1.0 / resolution );
			float result = 0.0;

			for ( int i = - 2; i <= 2; i ++ ) {

				for ( int j = - 2; j <= 2; j ++ ) {

					vec2 offset = ( vec2( float( i ), float( j ) ) ) * texelSize;
					result += texture2D( tDiffuse, vUv + offset ).r;

				}

			}

			gl_FragColor = vec4( vec3( result / ( 5.0 * 5.0 ) ), 1.0 );

		}`};class fi extends Ui{constructor(e,t,n=512,i=512,r=32){super(),this.width=n,this.height=i,this.clear=!0,this.needsSwap=!1,this.camera=t,this.scene=e,this.kernelRadius=8,this.kernel=[],this.noiseTexture=null,this.output=0,this.minDistance=.005,this.maxDistance=.1,this._visibilityCache=[],this._generateSampleKernel(r),this._generateRandomKernelRotations();const a=new ys;a.format=pi,a.type=vs,this.normalRenderTarget=new Jt(this.width,this.height,{minFilter:xt,magFilter:xt,type:on,depthTexture:a}),this.ssaoRenderTarget=new Jt(this.width,this.height,{type:on}),this.blurRenderTarget=this.ssaoRenderTarget.clone(),this.ssaoMaterial=new kt({defines:Object.assign({},kr.defines),uniforms:mi.clone(kr.uniforms),vertexShader:kr.vertexShader,fragmentShader:kr.fragmentShader,blending:Bt}),this.ssaoMaterial.defines.KERNEL_SIZE=r,this.ssaoMaterial.uniforms.tNormal.value=this.normalRenderTarget.texture,this.ssaoMaterial.uniforms.tDepth.value=this.normalRenderTarget.depthTexture,this.ssaoMaterial.uniforms.tNoise.value=this.noiseTexture,this.ssaoMaterial.uniforms.kernel.value=this.kernel,this.ssaoMaterial.uniforms.cameraNear.value=this.camera.near,this.ssaoMaterial.uniforms.cameraFar.value=this.camera.far,this.ssaoMaterial.uniforms.resolution.value.set(this.width,this.height),this.ssaoMaterial.uniforms.cameraProjectionMatrix.value.copy(this.camera.projectionMatrix),this.ssaoMaterial.uniforms.cameraInverseProjectionMatrix.value.copy(this.camera.projectionMatrixInverse),this.normalMaterial=new Ap,this.normalMaterial.blending=Bt,this.blurMaterial=new kt({defines:Object.assign({},zr.defines),uniforms:mi.clone(zr.uniforms),vertexShader:zr.vertexShader,fragmentShader:zr.fragmentShader}),this.blurMaterial.uniforms.tDiffuse.value=this.ssaoRenderTarget.texture,this.blurMaterial.uniforms.resolution.value.set(this.width,this.height),this.depthRenderMaterial=new kt({defines:Object.assign({},Vr.defines),uniforms:mi.clone(Vr.uniforms),vertexShader:Vr.vertexShader,fragmentShader:Vr.fragmentShader,blending:Bt}),this.depthRenderMaterial.uniforms.tDepth.value=this.normalRenderTarget.depthTexture,this.depthRenderMaterial.uniforms.cameraNear.value=this.camera.near,this.depthRenderMaterial.uniforms.cameraFar.value=this.camera.far,this.copyMaterial=new kt({uniforms:mi.clone(ea.uniforms),vertexShader:ea.vertexShader,fragmentShader:ea.fragmentShader,transparent:!0,depthTest:!1,depthWrite:!1,blendSrc:du,blendDst:Ro,blendEquation:qn,blendSrcAlpha:uu,blendDstAlpha:Ro,blendEquationAlpha:qn}),this._fsQuad=new Sa(null),this._originalClearColor=new Ie}dispose(){this.normalRenderTarget.dispose(),this.ssaoRenderTarget.dispose(),this.blurRenderTarget.dispose(),this.normalMaterial.dispose(),this.blurMaterial.dispose(),this.copyMaterial.dispose(),this.depthRenderMaterial.dispose(),this._fsQuad.dispose()}render(e,t,n){switch(this._overrideVisibility(),this._renderOverride(e,this.normalMaterial,this.normalRenderTarget,7829503,1),this._restoreVisibility(),this.ssaoMaterial.uniforms.kernelRadius.value=this.kernelRadius,this.ssaoMaterial.uniforms.minDistance.value=this.minDistance,this.ssaoMaterial.uniforms.maxDistance.value=this.maxDistance,this._renderPass(e,this.ssaoMaterial,this.ssaoRenderTarget),this._renderPass(e,this.blurMaterial,this.blurRenderTarget),this.output){case fi.OUTPUT.SSAO:this.copyMaterial.uniforms.tDiffuse.value=this.ssaoRenderTarget.texture,this.copyMaterial.blending=Bt,this._renderPass(e,this.copyMaterial,this.renderToScreen?null:n);break;case fi.OUTPUT.Blur:this.copyMaterial.uniforms.tDiffuse.value=this.blurRenderTarget.texture,this.copyMaterial.blending=Bt,this._renderPass(e,this.copyMaterial,this.renderToScreen?null:n);break;case fi.OUTPUT.Depth:this._renderPass(e,this.depthRenderMaterial,this.renderToScreen?null:n);break;case fi.OUTPUT.Normal:this.copyMaterial.uniforms.tDiffuse.value=this.normalRenderTarget.texture,this.copyMaterial.blending=Bt,this._renderPass(e,this.copyMaterial,this.renderToScreen?null:n);break;case fi.OUTPUT.Default:this.copyMaterial.uniforms.tDiffuse.value=this.blurRenderTarget.texture,this.copyMaterial.blending=hu,this._renderPass(e,this.copyMaterial,this.renderToScreen?null:n);break;default:console.warn("THREE.SSAOPass: Unknown output type.")}}setSize(e,t){this.width=e,this.height=t,this.ssaoRenderTarget.setSize(e,t),this.normalRenderTarget.setSize(e,t),this.blurRenderTarget.setSize(e,t),this.ssaoMaterial.uniforms.resolution.value.set(e,t),this.ssaoMaterial.uniforms.cameraProjectionMatrix.value.copy(this.camera.projectionMatrix),this.ssaoMaterial.uniforms.cameraInverseProjectionMatrix.value.copy(this.camera.projectionMatrixInverse),this.blurMaterial.uniforms.resolution.value.set(e,t)}_renderPass(e,t,n,i,r){e.getClearColor(this._originalClearColor);const a=e.getClearAlpha(),o=e.autoClear;e.setRenderTarget(n),e.autoClear=!1,i!=null&&(e.setClearColor(i),e.setClearAlpha(r||0),e.clear()),this._fsQuad.material=t,this._fsQuad.render(e),e.autoClear=o,e.setClearColor(this._originalClearColor),e.setClearAlpha(a)}_renderOverride(e,t,n,i,r){e.getClearColor(this._originalClearColor);const a=e.getClearAlpha(),o=e.autoClear;e.setRenderTarget(n),e.autoClear=!1,i=t.clearColor||i,r=t.clearAlpha||r,i!=null&&(e.setClearColor(i),e.setClearAlpha(r||0),e.clear()),this.scene.overrideMaterial=t,e.render(this.scene,this.camera),this.scene.overrideMaterial=null,e.autoClear=o,e.setClearColor(this._originalClearColor),e.setClearAlpha(a)}_generateSampleKernel(e){const t=this.kernel;for(let n=0;n<e;n++){const i=new L;i.x=Math.random()*2-1,i.y=Math.random()*2-1,i.z=Math.random(),i.normalize();let r=n/e;r=je.lerp(.1,1,r*r),i.multiplyScalar(r),t.push(i)}}_generateRandomKernelRotations(){const n=new Xx,i=16,r=new Float32Array(i);for(let a=0;a<i;a++){const o=Math.random()*2-1,l=Math.random()*2-1,c=0;r[a]=n.noise3d(o,l,c)}this.noiseTexture=new va(r,4,4,ma,sn),this.noiseTexture.wrapS=vi,this.noiseTexture.wrapT=vi,this.noiseTexture.needsUpdate=!0}_overrideVisibility(){const e=this.scene,t=this._visibilityCache;e.traverse(function(n){(n.isPoints||n.isLine||n.isLine2)&&n.visible&&(n.visible=!1,t.push(n))})}_restoreVisibility(){const e=this._visibilityCache;for(let t=0;t<e.length;t++)e[t].visible=!0;e.length=0}}fi.OUTPUT={Default:0,SSAO:1,Blur:2,Depth:3,Normal:4};const Hr={name:"OutputShader",uniforms:{tDiffuse:{value:null},toneMappingExposure:{value:1}},vertexShader:`
		precision highp float;

		uniform mat4 modelViewMatrix;
		uniform mat4 projectionMatrix;

		attribute vec3 position;
		attribute vec2 uv;

		varying vec2 vUv;

		void main() {

			vUv = uv;
			gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

		}`,fragmentShader:`

		precision highp float;

		uniform sampler2D tDiffuse;

		#include <tonemapping_pars_fragment>
		#include <colorspace_pars_fragment>

		varying vec2 vUv;

		void main() {

			gl_FragColor = texture2D( tDiffuse, vUv );

			// tone mapping

			#ifdef LINEAR_TONE_MAPPING

				gl_FragColor.rgb = LinearToneMapping( gl_FragColor.rgb );

			#elif defined( REINHARD_TONE_MAPPING )

				gl_FragColor.rgb = ReinhardToneMapping( gl_FragColor.rgb );

			#elif defined( CINEON_TONE_MAPPING )

				gl_FragColor.rgb = CineonToneMapping( gl_FragColor.rgb );

			#elif defined( ACES_FILMIC_TONE_MAPPING )

				gl_FragColor.rgb = ACESFilmicToneMapping( gl_FragColor.rgb );

			#elif defined( AGX_TONE_MAPPING )

				gl_FragColor.rgb = AgXToneMapping( gl_FragColor.rgb );

			#elif defined( NEUTRAL_TONE_MAPPING )

				gl_FragColor.rgb = NeutralToneMapping( gl_FragColor.rgb );

			#elif defined( CUSTOM_TONE_MAPPING )

				gl_FragColor.rgb = CustomToneMapping( gl_FragColor.rgb );

			#endif

			// color space

			#ifdef SRGB_TRANSFER

				gl_FragColor = sRGBTransferOETF( gl_FragColor );

			#endif

		}`};class Yx extends Ui{constructor(){super(),this.isOutputPass=!0,this.uniforms=mi.clone(Hr.uniforms),this.material=new Iu({name:Hr.name,uniforms:this.uniforms,vertexShader:Hr.vertexShader,fragmentShader:Hr.fragmentShader}),this._fsQuad=new Sa(this.material),this._outputColorSpace=null,this._toneMapping=null}render(e,t,n){this.uniforms.tDiffuse.value=n.texture,this.uniforms.toneMappingExposure.value=e.toneMappingExposure,(this._outputColorSpace!==e.outputColorSpace||this._toneMapping!==e.toneMapping)&&(this._outputColorSpace=e.outputColorSpace,this._toneMapping=e.toneMapping,this.material.defines={},Ke.getTransfer(this._outputColorSpace)===tt&&(this.material.defines.SRGB_TRANSFER=""),this._toneMapping===Nl?this.material.defines.LINEAR_TONE_MAPPING="":this._toneMapping===Ul?this.material.defines.REINHARD_TONE_MAPPING="":this._toneMapping===Fl?this.material.defines.CINEON_TONE_MAPPING="":this._toneMapping===ar?this.material.defines.ACES_FILMIC_TONE_MAPPING="":this._toneMapping===Bl?this.material.defines.AGX_TONE_MAPPING="":this._toneMapping===kl?this.material.defines.NEUTRAL_TONE_MAPPING="":this._toneMapping===Ol&&(this.material.defines.CUSTOM_TONE_MAPPING=""),this.material.needsUpdate=!0),this.renderToScreen===!0?(e.setRenderTarget(null),this._fsQuad.render(e)):(e.setRenderTarget(t),this.clear&&e.clear(e.autoClearColor,e.autoClearDepth,e.autoClearStencil),this._fsQuad.render(e))}dispose(){this.material.dispose(),this._fsQuad.dispose()}}const Gr={defines:{DEPTH_PACKING:1,PERSPECTIVE_CAMERA:1},uniforms:{tColor:{value:null},tDepth:{value:null},focus:{value:1},aspect:{value:1},aperture:{value:.025},maxblur:{value:.01},nearClip:{value:1},farClip:{value:1e3}},vertexShader:`

		varying vec2 vUv;

		void main() {

			vUv = uv;
			gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

		}`,fragmentShader:`

		#include <common>

		varying vec2 vUv;

		uniform sampler2D tColor;
		uniform sampler2D tDepth;

		uniform float maxblur; // max blur amount
		uniform float aperture; // aperture - bigger values for shallower depth of field

		uniform float nearClip;
		uniform float farClip;

		uniform float focus;
		uniform float aspect;

		#include <packing>

		float getDepth( const in vec2 screenPosition ) {
			#if DEPTH_PACKING == 1
			return unpackRGBAToDepth( texture2D( tDepth, screenPosition ) );
			#else
			return texture2D( tDepth, screenPosition ).x;
			#endif
		}

		float getViewZ( const in float depth ) {
			#if PERSPECTIVE_CAMERA == 1
			return perspectiveDepthToViewZ( depth, nearClip, farClip );
			#else
			return orthographicDepthToViewZ( depth, nearClip, farClip );
			#endif
		}


		void main() {

			vec2 aspectcorrect = vec2( 1.0, aspect );

			float viewZ = getViewZ( getDepth( vUv ) );

			float factor = ( focus + viewZ ); // viewZ is <= 0, so this is a difference equation

			vec2 dofblur = vec2 ( clamp( factor * aperture, -maxblur, maxblur ) );

			vec2 dofblur9 = dofblur * 0.9;
			vec2 dofblur7 = dofblur * 0.7;
			vec2 dofblur4 = dofblur * 0.4;

			vec4 col = vec4( 0.0 );

			col += texture2D( tColor, vUv.xy );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.0,   0.4  ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.15,  0.37 ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.29,  0.29 ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.37,  0.15 ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.40,  0.0  ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.37, -0.15 ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.29, -0.29 ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.15, -0.37 ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.0,  -0.4  ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.15,  0.37 ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.29,  0.29 ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.37,  0.15 ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.4,   0.0  ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.37, -0.15 ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.29, -0.29 ) * aspectcorrect ) * dofblur );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.15, -0.37 ) * aspectcorrect ) * dofblur );

			col += texture2D( tColor, vUv.xy + ( vec2(  0.15,  0.37 ) * aspectcorrect ) * dofblur9 );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.37,  0.15 ) * aspectcorrect ) * dofblur9 );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.37, -0.15 ) * aspectcorrect ) * dofblur9 );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.15, -0.37 ) * aspectcorrect ) * dofblur9 );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.15,  0.37 ) * aspectcorrect ) * dofblur9 );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.37,  0.15 ) * aspectcorrect ) * dofblur9 );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.37, -0.15 ) * aspectcorrect ) * dofblur9 );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.15, -0.37 ) * aspectcorrect ) * dofblur9 );

			col += texture2D( tColor, vUv.xy + ( vec2(  0.29,  0.29 ) * aspectcorrect ) * dofblur7 );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.40,  0.0  ) * aspectcorrect ) * dofblur7 );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.29, -0.29 ) * aspectcorrect ) * dofblur7 );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.0,  -0.4  ) * aspectcorrect ) * dofblur7 );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.29,  0.29 ) * aspectcorrect ) * dofblur7 );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.4,   0.0  ) * aspectcorrect ) * dofblur7 );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.29, -0.29 ) * aspectcorrect ) * dofblur7 );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.0,   0.4  ) * aspectcorrect ) * dofblur7 );

			col += texture2D( tColor, vUv.xy + ( vec2(  0.29,  0.29 ) * aspectcorrect ) * dofblur4 );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.4,   0.0  ) * aspectcorrect ) * dofblur4 );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.29, -0.29 ) * aspectcorrect ) * dofblur4 );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.0,  -0.4  ) * aspectcorrect ) * dofblur4 );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.29,  0.29 ) * aspectcorrect ) * dofblur4 );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.4,   0.0  ) * aspectcorrect ) * dofblur4 );
			col += texture2D( tColor, vUv.xy + ( vec2( -0.29, -0.29 ) * aspectcorrect ) * dofblur4 );
			col += texture2D( tColor, vUv.xy + ( vec2(  0.0,   0.4  ) * aspectcorrect ) * dofblur4 );

			gl_FragColor = col / 41.0;
			gl_FragColor.a = 1.0;

		}`};class qx extends Ui{constructor(e,t,n){super(),this.scene=e,this.camera=t;const i=n.focus!==void 0?n.focus:1,r=n.aperture!==void 0?n.aperture:.025,a=n.maxblur!==void 0?n.maxblur:1;this._renderTargetDepth=new Jt(1,1,{minFilter:xt,magFilter:xt,type:on}),this._renderTargetDepth.texture.name="BokehPass.depth",this._materialDepth=new Nu,this._materialDepth.depthPacking=_f,this._materialDepth.blending=Bt;const o=mi.clone(Gr.uniforms);o.tDepth.value=this._renderTargetDepth.texture,o.focus.value=i,o.aspect.value=t.aspect,o.aperture.value=r,o.maxblur.value=a,o.nearClip.value=t.near,o.farClip.value=t.far,this.materialBokeh=new kt({defines:Object.assign({},Gr.defines),uniforms:o,vertexShader:Gr.vertexShader,fragmentShader:Gr.fragmentShader}),this.uniforms=o,this._fsQuad=new Sa(this.materialBokeh),this._oldClearColor=new Ie}render(e,t,n){this.scene.overrideMaterial=this._materialDepth,e.getClearColor(this._oldClearColor);const i=e.getClearAlpha(),r=e.autoClear;e.autoClear=!1,e.setClearColor(16777215),e.setClearAlpha(1),e.setRenderTarget(this._renderTargetDepth),e.clear(),e.render(this.scene,this.camera),this.uniforms.tColor.value=n.texture,this.uniforms.nearClip.value=this.camera.near,this.uniforms.farClip.value=this.camera.far,this.renderToScreen?(e.setRenderTarget(null),this._fsQuad.render(e)):(e.setRenderTarget(t),e.clear(),this._fsQuad.render(e)),this.scene.overrideMaterial=null,e.setClearColor(this._oldClearColor),e.setClearAlpha(i),e.autoClear=r}setSize(e,t){this.materialBokeh.uniforms.aspect.value=e/t,this._renderTargetDepth.setSize(e,t)}dispose(){this._renderTargetDepth.dispose(),this._materialDepth.dispose(),this.materialBokeh.dispose(),this._fsQuad.dispose()}}class jx{palettes=new Map;register(e,t,n){this.palettes.set(e,{high:t,low:n})}prepare(e){for(const t of e.children){const n=t,i=n.userData.surface,r=this.palettes.get(i);if(!r)continue;const a=r.high.clone(),o={value:0};n.material=a,n.userData.appearance=o,a.onBeforeCompile=l=>{l.uniforms.archiveQuality=o,l.fragmentShader=`uniform float archiveQuality;
`+l.fragmentShader,i==="Frosted_Polymer"?(l.vertexShader=`varying float vArchiveHeight;
`+l.vertexShader,l.vertexShader=l.vertexShader.replace("#include <begin_vertex>",`#include <begin_vertex>
vArchiveHeight = position.y / 3.7;`),l.fragmentShader=`varying float vArchiveHeight;
`+l.fragmentShader,l.fragmentShader=l.fragmentShader.replace("#include <color_fragment>",`#include <color_fragment>
diffuseColor.rgb *= mix(mix(vec3(0.40, 0.30, 0.20), vec3(1.0, 0.98, 0.94), smoothstep(0.1, 1.0, vArchiveHeight)), vec3(1.0), archiveQuality);`),l.fragmentShader=l.fragmentShader.replace("#include <roughnessmap_fragment>",`#include <roughnessmap_fragment>
roughnessFactor = mix(0.28, mix(0.48, 0.035, smoothstep(0.36, 0.68, vArchiveHeight)), archiveQuality);`)):r.low||(l.fragmentShader=l.fragmentShader.replace("#include <color_fragment>",`#include <color_fragment>
float coverage = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
if (archiveQuality <= coverage) discard;`))},a.customProgramCacheKey=()=>`archive-surface-${i}-${!!r.low}`}}apply(e,t){for(const n of e.children){const i=n,r=this.palettes.get(i.userData.surface);if(!r){i.material.opacity=t;continue}i.userData.appearance.value=t;const{high:a,low:o}=r;if(!o)continue;const l=i.material;l.color.copy(o.color).lerp(a.color,t),l.attenuationColor&&o.attenuationColor&&a.attenuationColor&&(l.attenuationColor.copy(o.attenuationColor).lerp(a.attenuationColor,t),l.attenuationDistance=Number.isFinite(o.attenuationDistance)&&Number.isFinite(a.attenuationDistance)?je.lerp(o.attenuationDistance,a.attenuationDistance,t):a.attenuationDistance);for(const c of["roughness","metalness","transmission","thickness","clearcoat","clearcoatRoughness"])l[c]=je.lerp(o[c]??0,a[c]??0,t);a.transmission>0&&(l.transmission=Math.max(1e-6,l.transmission))}}dispose(e){for(const t of e.children){const n=t,i=n.material;n.userData.surface||i.map?.dispose(),i.dispose()}}}const Ut=[{id:"X-001",title:"莱茵生命",en:"RHINE LAB, LLC.",department:"总辖构件科",category:"机构档案",date:"跨期资料汇编",lead:"Kristen Wright / Saria",clearance:"REFERENCE AREA",abstract:"莱茵生命从克丽斯腾与塞雷娅共同创办的研究室发展而来。这里聚集着研究生命、能源与未知技术的人，也承受着资金、权力和成果应用的压力。理解这家机构，需要同时阅读它的实验记录与研究者的选择。",findings:["研究方向跨越多个科属，重大项目往往依赖跨科协作。","一项成果的技术价值，与它最终被怎样使用，需要分别讨论。","机构沿革与个人履历交叉编目，保留不同阶段的立场变化。"],source:"https://arknights.wiki.gg/wiki/Rhine_Lab"},{id:"X-002",title:"结构与边界",en:"STRUCTURE & BOUNDARIES",department:"工程科",category:"工程研究",date:"跨期资料汇编",lead:"Engineering Section",clearance:"REFERENCE AREA",abstract:"把实验室中的设想变成可运行的设施，需要解决承重、维修和人员通行这些具体问题。莱茵生命的工程人员为大型研究项目提供设备支持。本卷以设施边界为主题，关注构想落地之后由谁维护、由谁承担失效后果。",findings:["承载结构与生命科学意义上的结构科分属不同问题。","比较试验装置与长期运行设施对检修空间的不同要求。","为异常停机保留通道，不能只记录设备正常工作的状态。"],source:"https://prts.wiki/w/莱茵生命高级工程科成员"},{id:"X-003",title:"生命的轮廓",en:"THE CONTOUR OF LIFE",department:"结构科",category:"生命科学",date:"跨期资料汇编",lead:"Silence",clearance:"REFERENCE AREA",abstract:"赫默在莱茵生命时期从事与源石有关的生命科学研究，后来成为罗德岛的医疗干员。她的经历让研究对象与患者之间的距离变得具体：一份看似完整的实验结果，未必回答了受试者将如何生活。",findings:["把组织变化、功能变化与个人感受放在同一观察框架中。","临床照护记录应与实验阶段的目标和假设相互核对。","研究中的未知应被保留下来，不能被漂亮的结论掩盖。"],source:"https://prts.wiki/w/赫默"},{id:"X-004",title:"能量转换",en:"ENERGY CONVERSION",department:"能量科",category:"能量研究",date:"跨期资料汇编",lead:"Ferdinand Clooney",clearance:"REFERENCE AREA",abstract:"斐尔迪南与莱茵生命能量科、重大项目的资源投入关系密切。大型能源工程也因此同时是一项科研工作和一场组织协作。本卷讨论能量从实验结果走向实际应用时，效率、供给与外部利益之间的关联。",findings:["记录能源来源、转换环节和最终用途之间的联系。","规模扩大后，单次实验的成功不能替代持续运行的验证。","项目的资金安排也会改变技术路线与成果使用的方向。"],source:"https://prts.wiki/w/多萝西"},{id:"X-005",title:"生态观测",en:"ECOLOGICAL OBSERVATION",department:"生态科",category:"生命科学",date:"跨期资料汇编",lead:"Muelsyse",clearance:"REFERENCE AREA",abstract:"缪尔赛思领导的生态科研究生命与环境之间的关系，也与罗德岛开展联合科研。洁净的实验环境对于她具有特殊意义。本卷从水体和植物的连续观察出发，追问实验室里的稳定条件能够解释多少真实环境中的变化。",findings:["对照水体、植物与环境记录，避免把关联直接当作因果。","记录采样地点和条件，保留无法在实验室中重现的差异。","环境净化既影响研究结果，也关系到研究者自身的需要。"],source:"https://prts.wiki/w/缪尔赛思"},{id:"X-006",title:"实验安全规范",en:"LABORATORY SAFETY",department:"防卫科",category:"机构档案",date:"跨期资料汇编",lead:"Saria",clearance:"REFERENCE AREA",abstract:"塞雷娅兼具科研背景与异常事件处置能力，曾担任莱茵生命防卫科主任。她的经历提示，实验安全不能只被理解为门禁与装备：当项目目标与具体生命发生冲突时，必须有人拥有叫停研究并保护现场人员的能力。",findings:["事前准备应包含撤离路径、联络关系与中止条件。","异常记录需要说明影响到谁，而不只是损坏了哪些设备。","安保与科研人员应共享必要信息，避免风险被科属边界隔断。"],source:"https://prts.wiki/w/塞雷娅"},{id:"X-007",title:"精密仪器校准",en:"INSTRUMENT CALIBRATION",department:"工程科",category:"工程研究",date:"跨期资料汇编",lead:"Mayer",clearance:"REFERENCE AREA",abstract:"梅尔曾为赫默参与的项目筹备和调试实验装置，也在鲁特拉工作室持续进行机械设计。仪器把研究者的想法变成可测量的信号；这个过程中的偏差，可能被之后的每一步计算放大。",findings:["保留测量基准、设备状态与原始读数之间的对应关系。","设备移交时，解释适用条件与维护方式同样必要。","调试人员掌握的局部经验，应成为项目记录的一部分。"],source:"https://prts.wiki/w/梅尔"},{id:"X-008",title:"边界之外",en:"BEYOND THE HORIZON",department:"总辖构件科",category:"特别项目",date:"跨期资料汇编",lead:"Kristen Wright",clearance:"REFERENCE AREA",abstract:"克丽斯腾把研究的方向指向泰拉天空之外。《孤星》中的探索，将关于天空的疑问变成了牵动整座特里蒙的事件。本卷收录这一主题的观察线索，也保留理想、隐瞒与代价之间难以消解的张力。",findings:["将对未知的追求与具体项目的执行方式分别审视。","从参与者能够看到的信息出发，比较他们对同一事件的判断。","突破边界之后，留下的人仍需要面对地面上的后果。"],source:"https://arknights.wiki.gg/wiki/Lone_Trail"},{id:"X-009",title:"材料记忆",en:"MATERIAL MEMORY",department:"工程科",category:"工程研究",date:"跨期资料汇编",lead:"Engineering Section",clearance:"REFERENCE AREA",abstract:"动力装甲把材料、动力与控制系统压缩在有限空间里。莱茵生命的 R 系列设备为观察这些约束提供了入口。本卷将反复受力后的材料变化作为研究主题，关注装置看似恢复正常时，内部是否仍保留着上一次使用的痕迹。",findings:["把外观完好与内部状态分开记录，避免只依赖目视判断。","比较可更换部件与整体承载部件的维护需求。","疲劳、磨损和重复装配应进入同一份设备履历。"],source:"https://prts.wiki/w/R-31重型动力装甲"},{id:"X-010",title:"观测者日志",en:"OBSERVER’S JOURNAL",department:"科考科",category:"生命科学",date:"跨期资料汇编",lead:"Magallan",clearance:"REFERENCE AREA",abstract:"麦哲伦长期在偏远地区开展探索，冰原是她反复前往的研究场所。一次外勤带回的可能只是一段影像或一件标本，却能为下一位研究者减少一处盲区。本卷关注现场记录如何逐渐累积成可传递的知识。",findings:["保留路线、天气与观察位置，说明资料取得时的实际条件。","把尚未解释的现象列为问题，留待后续观测比较。","归档不仅保存成功发现，也保存走错的路与未完成的调查。"],source:"https://prts.wiki/w/Magallan"},{id:"X-011",title:"信号与噪声",en:"SIGNAL & NOISE",department:"数据资料组",category:"工程研究",date:"跨期资料汇编",lead:"Ptilopsis",clearance:"REFERENCE AREA",abstract:"白面鸮曾是莱茵生命的数据维护人员，在罗德岛继续协助医疗记录与信息整理。可被检索的数据并不自动等于可靠的知识。本卷讨论记录、筛选与解释之间的边界，尤其关注异常信号被当作噪声丢弃的可能。",findings:["保留原始记录与处理结果，便于重新审视筛选条件。","数据缺失和异常都应明确标注，不能被默认填补。","检索结论需要回到记录发生的情境中解释。"],source:"https://prts.wiki/w/白面鸮"},{id:"X-012",title:"明日的坐标",en:"COORDINATES OF TOMORROW",department:"总辖构件科",category:"特别项目",date:"跨期资料汇编",lead:"Silence / Saria",clearance:"REFERENCE AREA",abstract:"重大事件之后，莱茵生命仍需要决定下一项研究要往哪里去。赫默推动的科学伦理讨论，为这种决定增加了新的尺度。本卷不把未来写成已经完成的答案，而把研究自由、责任和合作视为需要持续协商的问题。",findings:["比较技术目标与其希望改善的具体生活之间的距离。","为不同立场留下讨论的位置，记录尚未达成的共识。","项目结束之后，仍应追踪其对人员与环境的长期影响。"],source:"https://prts.wiki/w/淬羽赫默"},{id:"X-013",title:"共同的起点",en:"A SHARED BEGINNING",department:"机构沿革组",category:"机构档案",date:"跨期资料汇编",lead:"Kristen Wright / Saria",clearance:"REFERENCE AREA",abstract:"公开的莱茵生命调查资料将早期研究室追溯至克丽斯腾与塞雷娅的合作。两位创始人拥有相交的志向，也逐渐形成不同的判断。本卷把机构的起点与后来的选择并置，观察共同的理想如何承受现实压力。",findings:["以研究室与公司化组织两个阶段梳理机构发展。","区分事后回顾与当时能够掌握的信息。","共同创立机构，并不意味着之后对每一项研究都会达成一致。"],source:"https://arknights.wiki.gg/wiki/Rhine_Lab_Research_Report"},{id:"X-014",title:"科属之间",en:"BETWEEN SECTIONS",department:"总辖构件科",category:"机构档案",date:"跨期资料汇编",lead:"Rhine Lab",clearance:"REFERENCE AREA",abstract:"莱茵生命的工作通过多个科属展开：研究、设备、人员和防卫彼此依赖。赫默后来的岗位变化，也体现了科研决策与组织责任之间的联系。本卷以科属协作为线索，整理信息在机构内部如何传递，又可能在哪里中断。",findings:["区分正式职责与重大项目中临时形成的合作关系。","交接记录应说明尚未解决的问题，而不只是已完成的工作。","在项目跨越科属时，明确谁能够提出异议与追问。"],source:"https://prts.wiki/w/淬羽赫默"},{id:"X-015",title:"特里蒙的日常",en:"LIFE IN TRIMOUNTS",department:"地区资料组",category:"机构档案",date:"跨期资料汇编",lead:"Muelsyse",clearance:"REFERENCE AREA",abstract:"特里蒙不仅是科研事件发生的地点，也是研究者工作、社交与生活的城市。缪尔赛思的档案展示了实验室之外的兴趣与城市经验。本卷从这些日常片段观察一座科学都市：宏大的研究计划始终由具体的人参与。",findings:["把生活空间与研究空间一并纳入人物背景。","不同身份的人，对同一座城市会有不同的路线与记忆。","保留日常细节，避免人物只剩下职务与成果。"],source:"https://prts.wiki/w/缪尔赛思"},{id:"X-016",title:"基金会与研究室",en:"PATRONS & RESEARCH",department:"机构沿革组",category:"机构档案",date:"跨期资料汇编",lead:"Maylander Foundation",clearance:"REFERENCE AREA",abstract:"莱茵生命的发展与外部支持者并非彼此独立。调查资料提及梅兰德基金会等力量与机构早期成长的联系。本卷关注资源支持如何使研究成为可能，也关注接受资源之后，研究目标与决策空间可能发生的变化。",findings:["把资金、设备与人员支持放在同一张项目关系图中。","记录合作条件与研究目标之间可能存在的张力。","对成果用途的讨论，应早于成果正式交付。"],source:"https://arknights.wiki.gg/wiki/Rhine_Lab_Research_Report"},{id:"X-017",title:"合作的接口",en:"POINTS OF CONTACT",department:"合作事务组",category:"机构档案",date:"跨期资料汇编",lead:"Dorothy / Rhodes Island",clearance:"REFERENCE AREA",abstract:"多萝西以莱茵生命与罗德岛合作项目负责人的身份加入合作。机构之间的联系由此落实为具体人员、资料和研究任务。本卷关注合作如何建立信任，也关注双方保有不同立场时，怎样继续进行有限而明确的协作。",findings:["把共同研究范围与各自承担的责任写清楚。","人员派驻提供沟通渠道，但不代表机构立场完全一致。","合作关系应允许问题被提出，而不只展示已经达成的成果。"],source:"https://prts.wiki/w/多萝西"},{id:"X-018",title:"科学与人的位置",en:"SCIENCE & ITS PEOPLE",department:"总辖构件科",category:"机构档案",date:"跨期资料汇编",lead:"Silence",clearance:"REFERENCE AREA",abstract:"赫默发起《特里蒙科学伦理联合宣言》，并参与相关伦理事务。她把在实验室和临床中面对的问题带到了更广泛的讨论中。本卷围绕一个持续存在的难题展开：科学向前推进时，具体的人如何保有被倾听的位置。",findings:["讨论研究对象的处境，不能只讨论研究能够带来什么。","把同意、异议与中止作为持续过程记录。","规范需要在具体案例中反复检验，而非写定之后便不再追问。"],source:"https://prts.wiki/w/淬羽赫默"},{id:"X-019",title:"咪波的工作台",en:"MEEBOO WORKBENCH",department:"鲁特拉工作室",category:"工程研究",date:"跨期资料汇编",lead:"Mayer",clearance:"REFERENCE AREA",abstract:"咪波是梅尔设计和操控的机械装置，也是她倾注感情的作品。从工具到伙伴的距离，在维修、命名与保留旧部件这些动作中逐渐缩短。本卷以工作台为观察位置，讨论创造者如何理解自己制造的机器。",findings:["记录设计迭代时保留下来的部件和经验。","把操作者的熟悉程度纳入设备使用条件。","维修记录同时也是一件作品逐渐成形的历史。"],source:"https://prts.wiki/w/梅尔"},{id:"X-020",title:"龙腾式支援无人机",en:"SOARING DRAGON",department:"科研设备研发科",category:"工程研究",date:"跨期资料汇编",lead:"Magallan",clearance:"REFERENCE AREA",abstract:"麦哲伦使用的龙腾式支援无人机采用模块化设计，能够适应不同任务。测绘与支援需求在同一套设备上相遇。本卷关注模块化带来的灵活性，以及切换用途时必须重新确认的环境与操作条件。",findings:["将任务需求与模块选择对应，保留切换理由。","设备能力必须结合地形、续航和回收条件判断。","同一平台承担多种用途时，应避免把不同模式的表现混为一谈。"],source:"https://prts.wiki/w/Magallan"},{id:"X-021",title:"R 系列动力装甲",en:"R-SERIES PLATFORM",department:"工程科",category:"工程研究",date:"跨期资料汇编",lead:"Engineering Section",clearance:"REFERENCE AREA",abstract:"R 系列动力装甲出现在莱茵生命相关实验设施中。工程设备与武装用途在这里直接相接。本卷从维护与使用条件切入，观察复杂设备如何依赖人员协作，也追问研发成果离开工作台之后所获得的新身份。",findings:["区分设备待机、维护与投入使用时的不同状态。","将操作者、维修人员和装置作为关联的系统观察。","记录用途变化，避免用最初的研发目标解释所有后续行为。"],source:"https://prts.wiki/w/R-31重型动力装甲"},{id:"X-022",title:"倾斜的实验室",en:"A SHIFTING LABORATORY",department:"工程科",category:"工程研究",date:"跨期资料汇编",lead:"Trimounts Laboratory",clearance:"REFERENCE AREA",abstract:"《孤星》中的实验室具有会影响行动的重力环境，机关与可移动物体共同改变空间的使用方式。本卷把这类场景作为设施研究主题：当地面不再是稳定参照时，路径、固定方式和操作习惯都需要重新考虑。",findings:["记录环境切换前后，人员与设备能够安全停留的位置。","把移动物体的路径纳入通行与观察安排。","同一空间在不同状态下，应拥有清楚可辨的使用条件。"],source:"https://prts.wiki/w/孤星2024"},{id:"X-023",title:"伊芙利特的恢复",en:"IFRIT: RECOVERY",department:"医疗协作组",category:"生命科学",date:"跨期资料汇编",lead:"Ifrit / Silence",clearance:"REFERENCE AREA",abstract:"伊芙利特曾是莱茵生命的医疗对象，之后在罗德岛由赫默照护。她的故事不应停留在异常能力或实验经历上。本卷把恢复、学习与日常关系放到记录中心，关注她如何逐渐理解自己的力量，并建立自己的生活。",findings:["将身体状态与日常适应共同记录，避免只追踪能力表现。","保留当事人的表达，不让旁观者的描述取代她的声音。","区分历史事件造成的影响与正在发生的改变。"],source:"https://prts.wiki/w/Ifrit"},{id:"X-024",title:"白面鸮的记录方式",en:"PTILOPSIS: RECORDS",department:"医疗数据组",category:"生命科学",date:"跨期资料汇编",lead:"Ptilopsis",clearance:"REFERENCE AREA",abstract:"白面鸮以独特的表达方式交流，也继续承担医疗与资料整理工作。她的语言形式并不意味着缺乏情感。本卷关注信息表达与人的经验之间的关系，提醒读者在精确的记录格式之外，仍要理解正在与自己交流的个体。",findings:["记录交流所需的时间与条件，避免急于替对方作答。","将表达形式与意图分开理解。","资料维护中的可靠性，来自对细节与具体需求的持续关注。"],source:"https://prts.wiki/w/白面鸮"},{id:"X-025",title:"治疗抵达之前",en:"CARE IN TRANSIT",department:"医疗协作组",category:"生命科学",date:"跨期资料汇编",lead:"Silence",clearance:"REFERENCE AREA",abstract:"赫默提出的医疗无人机以提供治疗为核心目的。它让照护能够抵达人员难以及时靠近的位置，也受到环境与设备条件的限制。本卷从治疗如何被送达这一问题出发，讨论医疗工具与临床判断之间的配合。",findings:["区分设备能够抵达的位置与真正能够完成的任务。","把现场条件、响应时间与后续照护连续记录。","工具延伸医生的能力，也需要医生判断何时不能依赖工具。"],source:"https://prts.wiki/w/赫默"},{id:"X-026",title:"温室与故乡",en:"GREENHOUSE & HOME",department:"生态科",category:"生命科学",date:"跨期资料汇编",lead:"Muelsyse",clearance:"REFERENCE AREA",abstract:"缪尔赛思的精灵身份，让环境研究与她自身的处境紧密相连。温室既是研究场所，也承载着对适宜生活空间的追寻。本卷由此讨论保存与改变之间的关系：能够被维持的环境，怎样才能成为真正可以生活的地方。",findings:["把环境需求与个人经验同时纳入观察。","区分保存一个样本与延续一种生活所需的条件。","研究可以解释环境变化，却不能代替当事人决定归属。"],source:"https://prts.wiki/w/缪尔赛思"},{id:"X-027",title:"冰原中的生命线",en:"LIFE ON THE ICEFIELD",department:"科考科",category:"生命科学",date:"跨期资料汇编",lead:"Magallan",clearance:"REFERENCE AREA",abstract:"麦哲伦的冰原探索不断把远方资料带回研究机构。在人迹稀少的地方，标本、地貌与环境条件需要一起记录。本卷关注如何在信息有限的情况下保留现场细节，使后续研究仍能回到观察发生的地点与情境。",findings:["将标本与取得它的环境绑定编目。","为无法重复的观察保留影像、路线和描述。","对未知现象保持开放，同时明确证据能够支持到哪里。"],source:"https://prts.wiki/w/Magallan"},{id:"X-028",title:"钙质化的应用",en:"CALCIFICATION STUDIES",department:"源石技艺资料组",category:"能量研究",date:"跨期资料汇编",lead:"Saria",clearance:"REFERENCE AREA",abstract:"塞雷娅的技艺与钙及其化合物有关，并与她的医学知识相互配合。防护、支援与环境影响在这一能力中同时出现。本卷将其作为应用研究的案例，关注能力的目的如何决定同一技术被怎样使用。",findings:["将能力表现与使用目的、对象和范围联系起来。","比较防护与医疗支援对控制精度的不同要求。","避免仅以破坏力衡量一项源石技艺的价值。"],source:"https://prts.wiki/w/塞雷娅"},{id:"X-029",title:"源石制品的工序",en:"ORIGINIUM WORKFLOWS",department:"设备研发组",category:"能量研究",date:"跨期资料汇编",lead:"Mayer",clearance:"REFERENCE AREA",abstract:"源石相关制品把能源应用带入研究者的日常工作。梅尔的档案提及她在加工中重视安全工序。本卷围绕工作台上的秩序展开：材料如何进入、怎样被加工、使用后又如何被处理，决定了研究能否长期持续。",findings:["把材料接收、加工与回收视为连续过程。","设备改装时同步检查原有保护条件是否仍然适用。","记录实际操作中的困难，使工序能够被下一位使用者理解。"],source:"https://prts.wiki/w/梅尔"},{id:"X-030",title:"装备中的能量预算",en:"POWER WITHIN LIMITS",department:"工程科／能量科",category:"能量研究",date:"跨期资料汇编",lead:"Engineering Section",clearance:"REFERENCE AREA",abstract:"工程设备的能力受到可用能源与持续运行条件的共同限制。莱茵生命的装备研发因资源投入而扩展，也必须在实际环境中接受检验。本卷把能量预算作为研究主题，讨论峰值能力与长期可用性之间的取舍。",findings:["分别记录启动、持续运行和待机时的需求。","为散热、维护和故障处理保留资源余量。","设备之间共享能源时，应说明优先级与失效时的影响范围。"],source:"https://prts.wiki/w/莱茵生命高级工程科成员"},{id:"X-031",title:"远距传输链路",en:"DISTANT TRANSMISSION",department:"能量科",category:"能量研究",date:"跨期资料汇编",lead:"Trimounts Project",clearance:"REFERENCE AREA",abstract:"《孤星》中的聚焦发生器与地面能量传输相联系。距离增加之后，发射端、接收端与协调工作共同决定系统表现。本卷关注链路的各个环节如何相互依赖，并将中断、偏差与恢复列为同样需要观察的状态。",findings:["把发送、接收与控制信号放在同一时间顺序中核对。","链路中断时，区分设备问题与外部条件变化。","不能只用成功到达的结果评价整个传输过程。"],source:"https://prts.wiki/w/孤星2024"},{id:"X-032",title:"聚焦发生器",en:"FOCUS GENERATOR",department:"联合项目组",category:"能量研究",date:"跨期资料汇编",lead:"Kristen Wright",clearance:"REFERENCE AREA",abstract:"聚焦发生器是《孤星》中连接大型工程与高空计划的重要设施。它将远距离获取的能量集中到特定用途，也把设施设计与项目意图紧密结合。本卷从这一装置出发，观察公开目标与参与者所知信息之间的距离。",findings:["将装置功能与项目对外叙述分别编目。","追踪关键环节由哪些人员掌握和操作。","讨论单个设备时，同时保留它所属的整体工程背景。"],source:"https://prts.wiki/w/孤星2024"},{id:"X-033",title:"弧光一号",en:"ARCLIGHT ONE",department:"能量科／联合项目组",category:"能量研究",date:"跨期资料汇编",lead:"Ferdinand / Kristen",clearance:"REFERENCE AREA",abstract:"弧光一号把能源设施、空中平台与哥伦比亚的多方力量联系在一起。它的技术规模使单一科属无法独立完成全部工作。本卷关注重大工程中的目标分歧：相同的设备与资源，可能被不同参与者赋予完全不同的期待。",findings:["比较研究、军事与个人探索目标之间的重合与偏离。","关键决策应结合参与者当时掌握的信息理解。","保留计划名称之下各项设施与行动之间的具体关系。"],source:"https://prts.wiki/w/孤星2024"},{id:"X-034",title:"共振装置",en:"RESONANCE DEVICES",department:"源石技艺应用科",category:"能量研究",date:"跨期资料汇编",lead:"Dorothy Franks",clearance:"REFERENCE AREA",abstract:"多萝西擅长源石技艺的应用，共振装置是理解她研究方向的一条线索。她希望改善他人的处境，但善意并不能自动回答研究方法是否合适。本卷将技术表现与研究动机并列，保留两者之间需要继续追问的部分。",findings:["分别记录装置的可观察效果与研究者对它的期待。","参与者的感受与选择，不能被总体目标所覆盖。","对未知机制保持明确标注，避免把愿望写成已经得到验证的结果。"],source:"https://prts.wiki/w/多萝西"},{id:"X-035",title:"三五九号基地",en:"SITE 359",department:"项目沿革组",category:"特别项目",date:"跨期资料汇编",lead:"Dorothy / Ferdinand",clearance:"REFERENCE AREA",abstract:"三五九号基地相关事件，是理解《绿野幻梦》与《孤星》联系的重要入口。实验设施之内的研究，与拓荒者的处境和外部利益交织。本卷按参与者与项目关系整理线索，避免只从最终结果倒推每个人的动机。",findings:["对照研究者、受试者与资助方能够获取的信息。","将基地中的实验与场外的资源关系一并观察。","一个项目结束之后，其技术与人员关系仍可能延续。"],source:"https://arknights.wiki.gg/wiki/Lone_Trail"},{id:"X-036",title:"炎魔事件",en:"THE DIABOLIC INCIDENT",department:"历史事件组",category:"特别项目",date:"跨期资料汇编",lead:"Ifrit / Silence / Saria",clearance:"REFERENCE AREA",abstract:"炎魔事件改变了伊芙利特、赫默与塞雷娅之间的关系，也暴露出莱茵生命研究中的深刻问题。本卷以事件影响为中心，保留照护、误解与责任这些线索；受影响者之后的生活，同样属于事件记录的一部分。",findings:["将实验阶段的记录与之后的照护经历相互参照。","明确资料缺失之处，避免用单一解释补齐所有空白。","事件的后果不仅体现为设施损坏，也体现为关系与生活的改变。"],source:"https://prts.wiki/w/Ifrit"},{id:"X-037",title:"孤星航迹",en:"LONE TRAIL",department:"高空研究资料组",category:"特别项目",date:"跨期资料汇编",lead:"Kristen Wright",clearance:"REFERENCE AREA",abstract:"《孤星》将克丽斯腾的探索推向天空之外，也让留在地面的人重新判断自己与莱茵生命的关系。本卷以航迹为线索阅读这一事件：每一次向前推进，都伴随着某些联系的延续，也伴随着无法撤回的告别。",findings:["把空中的行动与地面的应对按时间相互对照。","保留不同人物对同一时刻的理解。","探索的意义既在于抵达，也在于它改变了后来者能够提出的问题。"],source:"https://arknights.wiki.gg/wiki/Lone_Trail"},{id:"X-038",title:"观测极限",en:"LIMITS OF OBSERVATION",department:"高空研究资料组",category:"特别项目",date:"跨期资料汇编",lead:"Rhine Lab",clearance:"REFERENCE AREA",abstract:"关于天空的知识，长期受制于观察者能够到达的位置与能够取得的证据。《孤星》的探索使这些限制成为可以被讨论的问题。本卷不急于替未知命名，而关注一次新的观察如何迫使旧有解释重新接受检验。",findings:["区分直接观察、推论与仍待验证的假设。","当新的资料与既有解释冲突时，同时保留双方的依据。","记录观察工具与位置，说明结论受到哪些条件限制。"],source:"https://arknights.wiki.gg/wiki/Lone_Trail"},{id:"X-039",title:"万星园",en:"GALLERIA STELLARIA",department:"观星设施资料组",category:"特别项目",date:"跨期资料汇编",lead:"Kristen Wright",clearance:"REFERENCE AREA",abstract:"万星园是克丽斯腾设计的观星空间，中央的星象仪呈现出值得追问的星空线索。它既是一处设施，也显露出设计者的个人追求。本卷关注空间如何承载研究者的想象，以及想象与可证实的观察如何彼此接近。",findings:["分别记录星象仪呈现的内容与观测获得的资料。","将设施布置与设计者的研究目标交叉阅读。","一个私人的观星空间，也可能连接着远超个人规模的计划。"],source:"https://prts.wiki/w/孤星2024"},{id:"X-040",title:"静滞所",en:"HALL OF STASIS",department:"遗存调查组",category:"特别项目",date:"跨期资料汇编",lead:"Investigation Team",clearance:"REFERENCE AREA",abstract:"静滞所留下的设施与封闭装置，让调查者面对大量无法解释的现象。资料的不完整本身构成了这个地点的重要特征。本卷保留现场、遗存与尚未解决的问题，避免在证据不足时把未知写成完整的历史。",findings:["将现场观察与对装置用途的推测分别记录。","无法开启或解释的对象仍应保留原始状态描述。","后续资料可以补充旧记录，但不应抹去最初的疑问。"],source:"https://arknights.wiki.gg/wiki/Lone_Trail/Investigation_Reports"}],Kx=["全部档案","机构档案","工程研究","生命科学","能量研究","特别项目"],Fi=["工程研究","生命科学","机构档案","能量研究","特别项目"];function Oi(s){return Ut.map((e,t)=>({record:e,index:t})).filter(({record:e})=>e.category===Fi[s]).map(({index:e})=>e)}function _i(s){const e=Fi.indexOf(Ut[s].category),t=12+Oi(e).indexOf(s);return{lane:e,row:t,slot:e*32+t}}function Mo(s){const e=Oi(Math.floor(s/32));return e[Math.max(0,Math.min(e.length-1,s%32-12))]}const Zu=9,ds=32,Wr=5.2,Xr=.62,Ju=[0,1,2,3,4,-2,-1,5,6];function wl(s,e){return(s%e+e)%e}function la(s,e,t){return s+Math.floor((e-s+t/2)/t)*t}function Jh({lane:s,row:e}){const t=Oi(wl(s,Fi.length));return t[wl(e-12,t.length)]}function $x(s,e,t){if(t&&"cell"in t)return{...t.cell};const n=_i(s),i=la(n.row,e.row,Oi(n.lane).length);return t?.axis==="row"?{lane:e.lane,row:e.row+t.direction}:{lane:t?.axis==="lane"?e.lane+t.direction:la(n.lane,e.lane,Fi.length),row:i}}function Qh(s){return{lane:Ju[Math.floor(s/ds)],row:s%ds}}function Zx(s,e){return{lane:la(Ju[Math.floor(s/ds)],e.lane,Zu),row:la(s%ds,e.row,ds)}}function yo(s){return`${s.lane}:${s.row}`}function eu(s,e){return s.lane===e.lane&&s.row===e.row}const Qu='<path d="M156 75C127 48 103 15 70 15C37 15 15 39 15 70S38 128 70 128C103 128 127 96 176 52M155 75C182 99 208 128 240 128C273 128 295 105 295 73S273 15 240 15C221 15 207 23 192 38" fill="none" stroke="currentColor" stroke-width="26"/><path d="M44 70h50M69 45v50M219 70h44" fill="none" stroke="currentColor" stroke-width="15"/>',Jx=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 310 145" color="#171713">${Qu}</svg>`,So=`<svg viewBox="0 0 310 185" aria-label="Rhine Lab" role="img">${Qu}<text x="165" y="174" text-anchor="middle" font-family="MiSans,sans-serif" font-size="16" font-weight="700" letter-spacing="22">RHINE·LAB</text></svg>`,Qx=["M295 73C295 41 273 15 240 15C221 15 207 23 192 38","M176 52C127 96 103 128 70 128C38 128 15 101 15 70C15 39 37 15 70 15C103 15 127 48 156 75","M155 75C182 99 208 128 240 128C273 128 295 105 295 73"],rn=s=>(s=Math.max(0,Math.min(1,s)),s*s*s*(10+s*(-15+6*s))),ca=(s,e)=>Math.exp(-.5*(s/e)**2);function ed(s,e,t){const n=t-22,i=s+(e-2)*.65,r=rn(n/.32),a=3+n*19,o=32-(n-2.3)*24,l=c=>2.5*ca(c,3.8)-.58*ca(c-6,3.5);return r*(l(i-a)*(1-rn((n-2.15)/.65))+l(i-o)*rn((n-2.17)/.32)*(1-rn((n-3.5)/.85)))}function eM(s){return .4*rn((s-25.58)/.82)+2.95*rn((s-27.55)/1.3)}function td(s,e){const t=e-25.05-Math.abs(s)*.065,n=Math.max(-.42,2.15-.17*(Math.sqrt(s*s+1)-1)),i=rn(t/.62),r=t>0?Math.sin(t*5.1)*Math.exp(-t*1.3):0;return n*(i+.18*r*rn(t/.16))}function tM(s,e){return e<0||e>3.2?0:.8*rn(e/.2)*Math.exp(-e*1.15)*Math.cos((s-e*8)*.58)*ca(s-e*8,3.4)}function nM(s,e){return rn(s/2.5)*Math.max(0,Math.cos((s-e*8)*.58))}function nd(s,e,t=1){return 1+(.25+.75*ca(s-e,.55)-1)*rn(t)}function iM(s,e,t){return .075*Math.sin(t*Math.PI*2/8+s*.3-e*.45)+.027*Math.sin(t*Math.PI*2/13-s*.17+e*.3)}function sM(s,e,t,n=12,i=2){const r=rn((t-24.95)/.45),a=rn((t-25.4)/.95),o=t+.3*r*(1-a);return ed(s,e,t)*(1-r)+td(s-n,o)*nd(e,i,(t-25.4)/.95)}const tu=4.05,rM=.001;function nu(s,e,t=!1){const n=s*Math.exp(-e*(t?35:7));return Math.abs(n)<=rM?0:n}function Ri(s,e,t,n){const i=s.value-e,r=s.velocity+t*i,a=Math.exp(-t*n);s.value=e+(i+r*n)*a,s.velocity=(s.velocity-t*r*n)*a}const St=s=>(s=je.clamp(s,0,1),s*s*s*(s*(s*6-15)+10));class aM{constructor(e,t=tM,n=!1,i="baseline"){this.container=e,this.selectionPulse=t,this.deferSelectionPulse=n,this.lightingLook=i,this.renderer=new Yu({antialias:!0,alpha:!1,powerPreference:"high-performance"}),this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.5)*Math.min(innerWidth/1920,innerHeight/1080)),this.renderer.setSize(e.clientWidth,e.clientHeight),this.renderer.info.autoReset=!1,this.renderer.shadowMap.enabled=!0,this.renderer.shadowMap.type=cu,this.renderer.toneMapping=ar,this.renderer.toneMappingExposure=1.05,this.renderer.domElement.setAttribute("aria-label","三维研究档案阵列，可点击选择档案"),e.appendChild(this.renderer.domElement),this.scene.background=new Ie("#eae5e1"),this.scene.fog=new _a("#eae5e1",22,47),this.light=$u(this.renderer,this.scene,i),this.light.castShadow=!0,Object.assign(this.light.shadow.camera,{left:-16,right:16,top:15,bottom:-15,near:.1,far:45}),this.light.shadow.mapSize.set(2048,2048),this.light.shadow.normalBias=i==="refined"?.018:.035,this.light.shadow.bias=i==="refined"?-12e-5:-3e-4,this.light.shadow.radius=4;const r=new lt(new Pi(200,200),new bs({color:"#d8c9b9",roughness:.95}));r.rotation.x=-Math.PI/2,r.position.y=-4.63,r.receiveShadow=!0,this.scene.add(r),this.camera.position.set(-62.26,35.98,43.28),this.cameraAim.set(-.5,1.1,.4),this.camera.fov=6.15,this.camera.lookAt(this.cameraAim),this.composer=new Gx(this.renderer),this.composer.addPass(new Wx(this.scene,this.camera)),this.ao=new fi(this.scene,this.camera,e.clientWidth,e.clientHeight),this.ao.kernelRadius=i==="refined"?.44:.38,this.ao.minDistance=.001,this.ao.maxDistance=.09,this.composer.addPass(this.ao),this.bokeh=new qx(this.scene,this.camera,{focus:25,aperture:.0018,maxblur:.011}),this.composer.addPass(this.bokeh),this.composer.addPass(new Yx),this.bindPointer()}container;selectionPulse;deferSelectionPulse;lightingLook;renderer;scene=new Zl;camera=new Wt(34,16/9,.1,300);composer;ao;bokeh;instances=[];model=new In;appearance=new jx;cursor=new Le;raycaster=new lm;dummy=new ft;positions=[];cells=[];selectedCell={lane:2,row:12};looping=!1;coordinateOrigin={lane:0,row:0};lift={value:0,velocity:0};rail={value:0,velocity:0};shoulder={value:12,velocity:0};laneFocus={value:2,velocity:0};columnCamera={value:0,velocity:0};returnY=null;canInspect=!1;clearance=0;pulseGain=1;idleGain=0;lastInteraction=0;scanTime=29.1;scanBlend=0;cameraAim=new L;outgoing=[];pulses=[];pendingPulse=null;selectedSlot=76;detail=0;targetDetail=0;reveal=0;targetReveal=0;last=0;pointer=new Le;dragging=!1;rotation=0;targetRotation=0;light;clock=0;loaded=!1;labelCanvas=document.createElement("canvas");labelTexture;labelMark=new Image;reduced=!1;highQuality=!0;onSelect;onHover;async load(){this.labelMark.src=`data:image/svg+xml;charset=utf-8,${encodeURIComponent(Jx)}`,await this.labelMark.decode();const e=await new Xh().loadAsync("/assets/archive-cassette.glb");e.scene.updateMatrixWorld(!0);const t=[];e.scene.traverse(r=>{r instanceof lt&&t.push(r)});const n=Zu*ds;for(let r=0;r<n;r++){const a=Qh(r);this.cells.push(a),this.positions.push(this.cellPosition(a))}for(const r of t){const a=r.geometry.clone().applyMatrix4(r.matrixWorld).scale(1,1,1),o=r.material,l=o.name.replace(/\.\d+$/,""),c=o.clone();if(c.envMapIntensity=.6,l==="Frosted_Polymer"&&(c.color.set("#fffdfa"),c.transmission=.9,c.thickness=.12,c.roughness=.21,c.ior=1.46,c.attenuationColor=new Ie("#eee6df"),c.attenuationDistance=2,c.onBeforeCompile=f=>{f.vertexShader=`varying float vArchiveHeight;
`+f.vertexShader,f.vertexShader=f.vertexShader.replace("#include <begin_vertex>",`#include <begin_vertex>
vArchiveHeight = position.y / 3.7;`),f.fragmentShader=`varying float vArchiveHeight;
`+f.fragmentShader,f.fragmentShader=f.fragmentShader.replace("#include <roughnessmap_fragment>",`#include <roughnessmap_fragment>
roughnessFactor = mix(0.48, 0.035, smoothstep(0.36, 0.68, vArchiveHeight));`)}),l==="Internal_Ceramic"&&(c.color.set(this.lightingLook==="refined"?"#c4baae":"#c7beb6"),c.roughness=.6),l==="Printed_Label"&&c.color.set("#eae5dc"),l==="Ivory_Edges"&&(c.color.set("#f0e7df"),c.roughness=.31,c.transmission=.65,c.thickness=.04),l==="Optical_Diffuser"&&(c.color.set("#e2dad4"),c.transmission=0,c.roughness=.7),l==="Subsurface_Optics"&&(c.color.set(this.lightingLook==="refined"?"#b9a796":"#b9aba1"),c.roughness=.48,c.metalness=.05),l==="Optical_Edges"&&(c.transmission=0,c.color.set(this.lightingLook==="refined"?"#d8c7b5":"#d4c7be"),c.roughness=.26,c.metalness=.08),l==="Amber_Lightguide"&&(c.polygonOffset=!0,c.polygonOffsetFactor=-1,c.polygonOffsetUnits=-2),l==="Carbon_Ink")continue;const h=new lt(a,c);if(h.userData.surface=l,h.castShadow=l==="Optical_Diffuser",h.receiveShadow=!0,this.model.add(h),!["Frosted_Polymer","Ivory_Edges","Titanium_Fasteners","Champagne_Index","Optical_Diffuser"].includes(l)){this.appearance.register(l,c);continue}const u=c.clone();l==="Frosted_Polymer"&&(u.transmission=.78,this.lightingLook==="refined"&&(u.thickness=.28,u.attenuationColor.set("#d4c7b4"),u.attenuationDistance=1.2),u.transparent=!1,u.color.set("#fff7ed"),u.onBeforeCompile=f=>{f.vertexShader=`varying float vPanelHeight;
`+f.vertexShader,f.vertexShader=f.vertexShader.replace("#include <begin_vertex>",`#include <begin_vertex>
vPanelHeight = position.y / 3.7;`),f.fragmentShader=`varying float vPanelHeight;
`+f.fragmentShader,f.fragmentShader=f.fragmentShader.replace("#include <color_fragment>",`#include <color_fragment>
diffuseColor.rgb *= mix(vec3(0.40, 0.30, 0.20), vec3(1.0, 0.98, 0.94), smoothstep(0.1, 1.0, vPanelHeight));`)},u.roughness=.28,u.clearcoat=.3,u.clearcoatRoughness=.25),l==="Optical_Diffuser"&&u.color.set("#806447"),l==="Ivory_Edges"&&(u.transmission=0,u.color.set(this.lightingLook==="refined"?"#dcc9b0":"#fff5e9"),u.roughness=.38),l==="Champagne_Index"&&(u.color.set("#e4d6c5"),u.metalness=.05),this.appearance.register(l,c,u);const d=new ec(a,u,n);d.instanceMatrix.setUsage(Tf),d.castShadow=l==="Optical_Diffuser",d.receiveShadow=!0,d.frustumCulled=!1,this.instances.push(d),this.scene.add(d)}this.labelCanvas.width=1024,this.labelCanvas.height=440,this.labelTexture=new oo(this.labelCanvas),this.labelTexture.colorSpace=wt,this.labelTexture.anisotropy=this.renderer.capabilities.getMaxAnisotropy();const i=new lt(new Pi(.99,.46),new Nn({map:this.labelTexture,toneMapped:!1,transparent:!0,depthWrite:!1}));i.position.set(-1.36,3.04,.255),this.model.add(i),this.appearance.prepare(this.model),this.appearance.apply(this.model,0),this.drawLabel(0),this.scene.add(this.model),this.model.position.copy(this.positions[this.selectedSlot]),this.loaded=!0}assemblyTemplate;async createAssemblyModel(){this.assemblyTemplate??=new Xh().loadAsync("/assets/archive-assembly.glb").then(o=>(o.scene.updateMatrixWorld(!0),o.scene)).catch(o=>{throw this.assemblyTemplate=void 0,o});const e=await this.assemblyTemplate,t=new In,n=[];e.traverse(o=>{if(!(o instanceof lt))return;const l=o.material.name.replace(/\.\d+$/,""),c=new lt(o.geometry.clone().applyMatrix4(o.matrixWorld),o.material);c.userData.surface=l,c.userData.assemblyPart=o.userData.assemblyPart,t.add(c),n.push(c)}),this.appearance.prepare(t),this.appearance.apply(t,1);const i=document.createElement("canvas");i.width=this.labelCanvas.width,i.height=this.labelCanvas.height,i.getContext("2d").drawImage(this.labelCanvas,0,0);const r=new oo(i);r.colorSpace=wt,r.anisotropy=this.renderer.capabilities.getMaxAnisotropy();const a=new lt(new Pi(.99,.46),new Nn({map:r,toneMapped:!1,transparent:!0,depthWrite:!1}));return a.position.set(-1.36,3.04,.255),a.userData.assemblyPart="cover",t.add(a),n.push(a),{model:t,dispose:()=>{for(const o of n)o.geometry.dispose(),o.material.dispose();r.dispose()}}}setMode(e){if(e!=="archive"&&(this.pendingPulse=null),this.looping=e!=="hidden",!this.looping){const t=_i(Mo(this.selectedSlot));this.selectedCell={lane:t.lane,row:t.row},this.coordinateOrigin={lane:0,row:0};for(const n of this.outgoing)this.scene.remove(n.group),this.appearance.dispose(n.group);this.outgoing=[]}this.lastInteraction=this.clock,this.targetReveal=e==="hidden"?0:1,this.targetDetail=e==="detail"?1:0,this.dragging=!1,e!=="detail"?(this.targetRotation=0,this.rotation!==0&&(this.returnY=this.model.position.y)):this.returnY=null}setReduced(e){this.reduced=e}setQuality(e){this.highQuality=e,this.ao.enabled=e,this.bokeh.enabled=e,this.resize()}cellPosition(e){return new L((e.lane-2)*Wr,-4.6,(e.row-15.5)*Xr)}rebaseCoordinates(){const e={lane:Math.abs(this.selectedCell.lane)>2048?Math.round((this.selectedCell.lane-2)/5)*5:0,row:Math.abs(this.selectedCell.row)>2048?Math.floor((this.selectedCell.row-12)/8)*8:0};if(!(!e.lane&&!e.row)){this.selectedCell.lane-=e.lane,this.selectedCell.row-=e.row,this.coordinateOrigin.lane+=e.lane,this.coordinateOrigin.row+=e.row,this.laneFocus.value-=e.lane,this.shoulder.value-=e.row,this.columnCamera.value-=e.lane*Wr,this.rail.value+=e.row*Xr;for(const t of this.outgoing)t.cell.lane-=e.lane,t.cell.row-=e.row;for(const t of this.pulses)t.lane-=e.lane,t.row-=e.row;this.pendingPulse&&(this.pendingPulse.lane-=e.lane,this.pendingPulse.row-=e.row)}}select(e,t){this.lastInteraction=this.clock;const n=_i(e).slot,i=_i(e),r=this.looping?$x(e,this.selectedCell,t):{lane:i.lane,row:i.row},a=!eu(r,this.selectedCell);if(this.looping&&a&&this.loaded&&this.lift.value>1e-4){const l=this.model.clone(!0);this.appearance.prepare(l);const c=l.children[l.children.length-1],h=document.createElement("canvas");h.width=1024,h.height=440,h.getContext("2d").drawImage(this.labelCanvas,0,0);const u=new oo(h);u.colorSpace=wt,c.material=new Nn({map:u,toneMapped:!1,transparent:!0,depthWrite:!1}),this.appearance.apply(l,St(this.lift.value/.4)),this.scene.add(l),this.outgoing.push({group:l,slot:this.selectedSlot,cell:{...this.selectedCell},lift:{...this.lift},returnY:l.rotation.y!==0?l.position.y:null}),this.lift.value=0,this.lift.velocity=0}this.selectedSlot=n,this.selectedCell=r,a&&(this.rotation=0,this.returnY=null);const o=this.outgoing.findIndex(l=>eu(l.cell,r));if(o>=0){const l=this.outgoing[o];this.lift={...l.lift},this.rotation=l.group.rotation.y,this.returnY=l.returnY,this.scene.remove(l.group),this.appearance.dispose(l.group),this.outgoing.splice(o,1)}this.deferSelectionPulse?this.pendingPulse=this.looping?{...r}:null:this.emitPulse(r),this.targetRotation=0,this.drawLabel(e)}emitPulse(e){this.pulses.push({...e,time:this.clock}),this.pulses=this.pulses.slice(-6)}drawLabel(e){if(!this.labelTexture)return;const t=this.labelCanvas.getContext("2d");t.fillStyle="#e6e2d9",t.fillRect(0,0,1024,440),t.fillStyle="#171713",t.fillRect(12,12,1e3,6),t.fillRect(12,419,1e3,3),t.font="bold 81px MiSans",t.fillText("RHINE LAB, LLC.",22,116),t.font="32px MiSans",t.fillStyle="#878476",t.fillText("INTERNAL DATABASE",25,174),t.fillStyle="#171713",t.font="bold 130px MiSans",t.fillText("NO."+String(e+1).padStart(3,"0"),22,360),t.fillRect(782,32,221,39),t.fillStyle="#eee9de",t.font="24px MiSans",t.fillText("R L / I S",809,61),t.fillStyle="#171713",t.font="bold 64px MiSans",t.fillText("INFO",830,143),t.drawImage(this.labelMark,790,242,210,98),this.labelTexture.needsUpdate=!0}resize(){const e=this.container.clientWidth,t=this.container.clientHeight;this.renderer.setPixelRatio(Math.min(devicePixelRatio,this.highQuality?1.5:1)*Math.min(innerWidth/1920,innerHeight/1080)),this.composer.setPixelRatio(this.renderer.getPixelRatio()),this.renderer.setSize(e,t),this.composer.setSize(e,t),this.camera.aspect=e/t,this.camera.updateProjectionMatrix()}bindPointer(){const e=this.renderer.domElement;let t=0,n=0;e.addEventListener("pointerdown",i=>{t=i.clientX,n=i.clientY,this.canInspect&&(this.dragging=!0,e.setPointerCapture(i.pointerId))}),e.addEventListener("pointermove",i=>{const r=e.getBoundingClientRect();if(this.pointer.set((i.clientX-r.left)/r.width-.5,(i.clientY-r.top)/r.height-.5),this.dragging){if(!this.canInspect){this.dragging=!1;return}this.targetRotation=je.clamp(this.targetRotation+i.movementX*.004,-.8,.8);return}if(this.reveal<.8||this.detail>.2||!this.loaded)return;this.cursor.set((i.clientX-r.left)/r.width*2-1,-(i.clientY-r.top)/r.height*2+1),this.raycaster.setFromCamera(this.cursor,this.camera);const a=this.raycaster.intersectObjects([this.instances[0],this.model],!0)[0];e.style.cursor=a?"pointer":"default",this.onHover?.(a?a.instanceId!==void 0?Jh(this.cells[a.instanceId]):Mo(this.selectedSlot):null)}),e.addEventListener("pointerup",i=>{if(this.dragging=!1,Math.hypot(i.clientX-t,i.clientY-n)>6||this.detail>.2||this.reveal<.8||!this.loaded)return;const r=e.getBoundingClientRect();this.cursor.set((i.clientX-r.left)/r.width*2-1,-(i.clientY-r.top)/r.height*2+1),this.raycaster.setFromCamera(this.cursor,this.camera);const a=this.raycaster.intersectObjects([this.instances[0],this.model],!0)[0];a&&this.onSelect?.(a.instanceId!==void 0?Jh(this.cells[a.instanceId]):Mo(this.selectedSlot),a.instanceId!==void 0?{...this.cells[a.instanceId]}:{...this.selectedCell})}),e.addEventListener("pointercancel",()=>this.dragging=!1),e.addEventListener("pointerleave",()=>{this.pointer.set(0,0),this.onHover?.(null)})}update(e,t){const n=Math.min(e-this.last||.016,.05);if(this.last=e,this.clock=e,!this.loaded)return;const i=1-Math.exp(-n*(this.reduced?35:2.8));this.reveal=t?t.reveal:je.lerp(this.reveal,this.targetReveal,i),this.rotation=this.targetDetail?je.lerp(this.rotation,this.targetRotation,i):nu(this.rotation,n,this.reduced);const r=t?.time??29.1;t?(this.scanTime=r,this.scanBlend=1):(this.scanTime+=n,this.scanBlend*=Math.exp(-n*3)),this.looping&&!t&&this.rebaseCoordinates();const a=this.cellPosition(this.selectedCell),o=this.selectedCell.row,l=this.selectedCell.lane;Ri(this.shoulder,o,this.reduced?35:5,n),Ri(this.laneFocus,l,this.reduced?35:4,n),Ri(this.columnCamera,a.x,this.reduced?35:3.7,n),Ri(this.rail,t?0:-2.17-a.z,this.reduced?35:3.7,n),t&&(this.rail.value=0,this.rail.velocity=0,this.lift.value=eM(r),this.lift.velocity=0,this.shoulder.value=o,this.laneFocus.value=l,this.laneFocus.velocity=0,this.columnCamera.value=a.x,this.columnCamera.velocity=0);const c=t?0:this.columnCamera.value,h={lane:this.columnCamera.value/Wr+2,row:(-this.rail.value-2.17)/Xr+15.5};for(let $=0;$<this.positions.length;$++)this.cells[$]=t||!this.looping?Qh($):Zx($,h),this.positions[$].set((this.cells[$].lane-2)*Wr,-4.6,(this.cells[$].row-15.5)*Xr);this.pulses=this.pulses.filter($=>e-$.time<3.2);const u=this.outgoing.some($=>$.returnY!==null),d=!t&&!this.reduced&&this.targetReveal>0&&!this.targetDetail&&this.detail<.01&&this.returnY===null&&!u&&e-this.lastInteraction>2.5;this.idleGain=t?0:je.lerp(this.idleGain,d?1:0,1-Math.exp(-n*(d?.8:4))),this.pulseGain=je.lerp(this.pulseGain,this.targetDetail||this.returnY!==null||u?0:1,1-Math.exp(-n*8));const f=($,ce)=>{if(t)return sM($,ce,r,this.shoulder.value,this.laneFocus.value);let Re=ed($+this.coordinateOrigin.row,ce+this.coordinateOrigin.lane,this.scanTime)*this.scanBlend+iM($+this.coordinateOrigin.row,ce+this.coordinateOrigin.lane,e)*this.idleGain;if(!t&&!this.reduced){let Z=0;for(const ee of this.pulses){const we=Math.hypot($-ee.row,(ce-ee.lane)*2.2),ve=e-ee.time;Z+=this.selectionPulse(we,ve)*(this.deferSelectionPulse?nM(we,ve):1)}Re+=je.clamp(Z,-.6,.6)*this.pulseGain}const G=$-this.shoulder.value;return Re+td(G,26.56)*nd(ce,this.laneFocus.value)},g=a.y+f(o,l);t||(this.returnY!==null&&this.rotation!==0?(this.lift.value=this.returnY-g,this.lift.velocity=0):(this.returnY=null,Ri(this.lift,this.targetDetail?tu:this.outgoing.some($=>$.returnY!==null&&$.cell.lane===l&&Math.abs($.cell.row-o)<5)?0:.4*this.targetReveal,this.reduced?35:this.deferSelectionPulse&&!this.targetDetail&&this.lift.value<.4?7.6:4.2,n)));const x=this.targetDetail?St((this.lift.value-.8)/2.4):this.returnY!==null?this.detail:St((this.lift.value-.4)/(tu-.4));this.detail=t?t.zoom:je.lerp(this.detail,x,i);const p=this.detail;this.appearance.apply(this.model,St(this.lift.value/.4));const m=t?St((r-21.9)/.86):this.reveal,S=je.clamp((r-21.92)/.75,0,1),T=t?-23*(1-S)**2:-28*(1-m);for(let $=this.outgoing.length-1;$>=0;$--){const ce=this.outgoing[$],Re=this.cellPosition(ce.cell),G=Re.y+f(ce.cell.row,ce.cell.lane);ce.group.rotation.y=nu(ce.group.rotation.y,n,this.reduced),ce.returnY!==null?(ce.lift.value=ce.returnY-G,ce.lift.velocity=0,ce.group.rotation.y===0&&(ce.returnY=null)):Ri(ce.lift,0,this.reduced?35:4.5,n),ce.group.position.set(Re.x-c,G+ce.lift.value,Re.z+T+this.rail.value);const Z=St(ce.lift.value/.4);this.appearance.apply(ce.group,Z);const{row:ee,lane:we}=ce.cell;ce.group.rotation.x=(f(ee+.5,we)-f(ee-.5,we))*.024*(1-p)*(1-Z),ce.lift.value<1e-4&&Math.abs(ce.group.rotation.y)<1e-4&&(this.scene.remove(ce.group),this.appearance.dispose(ce.group),this.outgoing.splice($,1))}if(this.pendingPulse&&!t&&!this.targetDetail&&this.targetReveal){const $=g+this.lift.value,ce=this.outgoing.every(Re=>Re.cell.lane!==l||Math.abs(Re.cell.row-o)>4||Re.group.position.y+.015<$);this.lift.value>=.35&&this.returnY===null&&ce&&(this.reduced||this.emitPulse(this.pendingPulse),this.pendingPulse=null)}const M=new Set(this.outgoing.map($=>yo($.cell)));M.add(yo(this.selectedCell));for(let $=0;$<this.positions.length;$++){const ce=this.positions[$],{row:Re,lane:G}=this.cells[$],Z=f(Re+.5,G)-f(Re-.5,G);this.dummy.position.set(ce.x-c,ce.y+f(Re,G),ce.z+T+this.rail.value),this.dummy.rotation.set(Z*.024*(1-p),0,0),this.dummy.scale.setScalar(M.has(yo(this.cells[$]))||(t||!this.looping)&&$>=160?0:1),this.dummy.updateMatrix();for(const ee of this.instances)ee.setMatrixAt($,this.dummy.matrix)}for(const $ of this.instances)$.instanceMatrix.needsUpdate=!0;this.model.position.set(a.x-c,a.y+f(o,l)+this.lift.value,a.z+T+this.rail.value),this.model.rotation.set((f(o+.5,l)-f(o-.5,l))*.024*(1-p)*(1-St(this.lift.value/.4)),t?0:this.rotation,0);const E=St((r-22.6)/1.6),w=St((r-24.25)/2.25),C=je.degToRad(89-22*E-8*w),v=je.degToRad(3+40*St((r-21.96)/.22)-8*E-16*w),b=je.lerp(je.lerp(10.8,10.3,E),7.33,w),D=je.lerp(je.lerp(28+7*E,140,w),72,p),F=new L(-1.091,je.lerp(-2.55+.4*E,-.045,w),je.lerp(2.48,.481,w)).clone(),O=new L(-Math.sin(C)*Math.cos(v),Math.sin(v),Math.cos(C)*Math.cos(v));if(t){const $=St((r-27.3)/1.3),ce=St((r-28.6)/5.4),Re=C-je.degToRad(9*$+32*ce),G=v-je.degToRad(1.5*$+3.7*ce);O.set(-Math.sin(Re)*Math.cos(G),Math.sin(G),Math.cos(Re)*Math.cos(G))}else O.lerp(new L(-.277,.238,.931),p).normalize();if(t){const $=St((r-25.4)/.95),ce=new L().crossVectors(new L(0,1,0),O).normalize();F.addScaledVector(ce,-2.05*(1-$)*St((r-24.2)/.8))}if(t&&r>=25.05&&r<=27.3){const $=St((r-25.4)/1.05),ce=new L().crossVectors(new L(0,1,0),O).normalize(),Re=new L().crossVectors(O,ce).normalize(),G=1080/b,Z=this.model.position.clone().add(new L(-2.5,3.7,0));Z.addScaledVector(ce,-(je.lerp(840,518,$)-960)/G),Z.addScaledVector(Re,-(540-je.lerp(340,288,$))/G),F.lerp(Z,St((r-25.05)/.35))}if(t&&r>27.3){const $=St((r-27.3)/6.7),ce=St((r-27.3)/1.25),Re=je.lerp(518-98*ce,618,$),G=je.lerp(296+34*ce,287,$),Z=1080/je.lerp(b,5.9,p),ee=new L().crossVectors(new L(0,1,0),O).normalize(),we=new L().crossVectors(O,ee).normalize(),ve=this.model.position.clone().add(new L(-2.5,3.7,0));ve.addScaledVector(ee,-(Re-960)/Z),ve.addScaledVector(we,-(540-G)/Z),F.lerp(ve,St((r-27.3)/.5))}if(!t){const $=new L().crossVectors(new L(0,1,0),O).normalize(),ce=new L().crossVectors(O,$).normalize(),Re=1080/je.lerp(b,5.9,p),G=this.model.position.clone().add(new L(0,1.85,0));G.addScaledVector($,410/Re),G.addScaledVector(ce,20/Re),F.lerp(G,p)}const X=F.clone().addScaledVector(O,D);!t&&!this.reduced&&(X.x+=this.pointer.x*.12,X.y-=this.pointer.y*.12);const V=t?1:1-Math.exp(-n*5);this.camera.position.lerp(X,V),this.cameraAim.lerp(F,V),this.camera.lookAt(this.cameraAim),this.camera.fov=je.lerp(this.camera.fov,je.radToDeg(2*Math.atan(je.lerp(b,5.9,p)/(2*D))),V);const k=this.scene.fog,U=this.camera.position.distanceTo(this.cameraAim);k.near=U+je.lerp(5,-1,p),k.far=U+je.lerp(25,12,p),this.camera.updateProjectionMatrix(),this.camera.updateMatrixWorld();let Q=-1/0;const K=l,se=o;for(let $=se-5;$<=se+5;$++)$!==se&&(Q=Math.max(Q,-4.6+f($,K)+3.76));for(const $ of this.outgoing)$.cell.lane===K&&Math.abs($.cell.row-se)<=5&&(Q=Math.max(Q,$.group.position.y+3.76));this.clearance=this.model.position.y-Q,this.canInspect=!t&&!!this.targetDetail&&p>.9&&this.pulseGain<.01&&this.clearance>.3,this.container.dataset.inspection=this.returnY!==null?"aligning":this.canInspect?"ready":this.targetDetail?"lifting":"preview";const he=this.model.position.clone().add(new L(0,2,0)).applyMatrix4(this.camera.matrixWorldInverse),le=this.bokeh.uniforms;le.focus.value=-he.z,le.aperture.value=je.lerp(3e-4,8e-4,p),this.renderer.info.reset(),this.composer.render()}projectCard(e,t){this.model.updateMatrixWorld(!0);const n=this.model.localToWorld(new L(e,t,.255)).project(this.camera);return[(n.x+1)*960,(1-n.y)*540]}get detailVisibility(){return St((this.detail-.25)/.55)}getStats(){this.model.updateMatrixWorld(!0);const e=(t,n,i)=>{const r=this.model.localToWorld(new L(t,n,i)).project(this.camera);return[Math.round((r.x+1)*960),Math.round((1-r.y)*540)]};return{topLeft:e(-2.5,3.7,0),topRight:e(2.5,3.7,0),labelTopLeft:e(-1.855,3.27,.255),labelBottomLeft:e(-1.855,2.81,.255),modelPosition:this.model.position.toArray().map(t=>Math.round(t*1e4)/1e4),cameraPosition:this.camera.position.toArray().map(t=>Math.round(t*1e4)/1e4),fieldOfView:this.camera.fov,loaded:this.loaded,drawCalls:this.renderer.info.render.calls,triangles:this.renderer.info.render.triangles,archiveCount:this.positions.length,returningFiles:this.outgoing.length,selectionPhase:this.pendingPulse?"lifting":this.pulses.length?"wave":"settled",pendingPulse:this.pendingPulse?{...this.pendingPulse}:null,pulses:this.pulses.map(t=>({...t})),referenceTime:Math.round((this.scanTime+5)*100)/100,selectedSlot:this.selectedSlot,selectedLane:Math.floor(this.selectedSlot/32),selectedCell:{...this.selectedCell},coordinateOrigin:{...this.coordinateOrigin},poolBounds:{minLane:Math.min(...this.cells.map(t=>t.lane)),maxLane:Math.max(...this.cells.map(t=>t.lane)),minRow:Math.min(...this.cells.map(t=>t.row)),maxRow:Math.max(...this.cells.map(t=>t.row))},laneFocus:this.laneFocus.value,columnCamera:this.columnCamera.value,rotation:this.rotation,clearance:this.clearance,canInspect:this.canInspect,returnPhase:this.returnY!==null?"aligning":"lowering",extraction:Math.round(this.lift.value*1e3)/1e3,appearance:Math.round(St(this.lift.value/.4)*1e3)/1e3,cameraDetail:Math.round(this.detail*1e3)/1e3,idleGain:this.idleGain,cameraDistance:this.camera.position.distanceTo(this.cameraAim),fogNear:this.scene.fog.near,fogFar:this.scene.fog.far,returningAppearance:this.outgoing.map(t=>({slot:t.slot,cell:{...t.cell},lift:t.lift.value,quality:St(t.lift.value/.4),rotation:t.group.rotation.y,worldY:t.group.position.y,phase:t.returnY!==null?"aligning":"lowering"})),rail:Math.round(this.rail.value*1e3)/1e3}}}const iu={type:"change"},ac={type:"start"},id={type:"end"},Yr=new Rs,su=new ui,oM=Math.cos(70*je.DEG2RAD),Rt=new L,$t=2*Math.PI,ot={NONE:-1,ROTATE:0,DOLLY:1,PAN:2,TOUCH_ROTATE:3,TOUCH_PAN:4,TOUCH_DOLLY_PAN:5,TOUCH_DOLLY_ROTATE:6},bo=1e-6;class lM extends cm{constructor(e,t=null){super(e,t),this.state=ot.NONE,this.target=new L,this.cursor=new L,this.minDistance=0,this.maxDistance=1/0,this.minZoom=0,this.maxZoom=1/0,this.minTargetRadius=0,this.maxTargetRadius=1/0,this.minPolarAngle=0,this.maxPolarAngle=Math.PI,this.minAzimuthAngle=-1/0,this.maxAzimuthAngle=1/0,this.enableDamping=!1,this.dampingFactor=.05,this.enableZoom=!0,this.zoomSpeed=1,this.enableRotate=!0,this.rotateSpeed=1,this.keyRotateSpeed=1,this.enablePan=!0,this.panSpeed=1,this.screenSpacePanning=!0,this.keyPanSpeed=7,this.zoomToCursor=!1,this.autoRotate=!1,this.autoRotateSpeed=2,this.keys={LEFT:"ArrowLeft",UP:"ArrowUp",RIGHT:"ArrowRight",BOTTOM:"ArrowDown"},this.mouseButtons={LEFT:ls.ROTATE,MIDDLE:ls.DOLLY,RIGHT:ls.PAN},this.touches={ONE:os.ROTATE,TWO:os.DOLLY_PAN},this.target0=this.target.clone(),this.position0=this.object.position.clone(),this.zoom0=this.object.zoom,this._cursorStyle="auto",this._domElementKeyEvents=null,this._lastPosition=new L,this._lastQuaternion=new yn,this._lastTargetPosition=new L,this._quat=new yn().setFromUnitVectors(e.up,new L(0,1,0)),this._quatInverse=this._quat.clone().invert(),this._spherical=new Mh,this._sphericalDelta=new Mh,this._scale=1,this._panOffset=new L,this._rotateStart=new Le,this._rotateEnd=new Le,this._rotateDelta=new Le,this._panStart=new Le,this._panEnd=new Le,this._panDelta=new Le,this._dollyStart=new Le,this._dollyEnd=new Le,this._dollyDelta=new Le,this._dollyDirection=new L,this._mouse=new Le,this._performCursorZoom=!1,this._pointers=[],this._pointerPositions={},this._controlActive=!1,this._onPointerMove=hM.bind(this),this._onPointerDown=cM.bind(this),this._onPointerUp=uM.bind(this),this._onContextMenu=vM.bind(this),this._onMouseWheel=pM.bind(this),this._onKeyDown=mM.bind(this),this._onTouchStart=gM.bind(this),this._onTouchMove=_M.bind(this),this._onMouseDown=dM.bind(this),this._onMouseMove=fM.bind(this),this._interceptControlDown=xM.bind(this),this._interceptControlUp=MM.bind(this),this.domElement!==null&&this.connect(this.domElement),this.update()}set cursorStyle(e){this._cursorStyle=e,e==="grab"?this.domElement.style.cursor="grab":this.domElement.style.cursor="auto"}get cursorStyle(){return this._cursorStyle}connect(e){super.connect(e),this.domElement.addEventListener("pointerdown",this._onPointerDown),this.domElement.addEventListener("pointercancel",this._onPointerUp),this.domElement.addEventListener("contextmenu",this._onContextMenu),this.domElement.addEventListener("wheel",this._onMouseWheel,{passive:!1}),this.domElement.getRootNode().addEventListener("keydown",this._interceptControlDown,{passive:!0,capture:!0}),this.domElement.style.touchAction="none"}disconnect(){this.domElement.removeEventListener("pointerdown",this._onPointerDown),this.domElement.ownerDocument.removeEventListener("pointermove",this._onPointerMove),this.domElement.ownerDocument.removeEventListener("pointerup",this._onPointerUp),this.domElement.removeEventListener("pointercancel",this._onPointerUp),this.domElement.removeEventListener("wheel",this._onMouseWheel),this.domElement.removeEventListener("contextmenu",this._onContextMenu),this.stopListenToKeyEvents(),this.domElement.getRootNode().removeEventListener("keydown",this._interceptControlDown,{capture:!0}),this.domElement.style.touchAction="auto"}dispose(){this.disconnect()}getPolarAngle(){return this._spherical.phi}getAzimuthalAngle(){return this._spherical.theta}getDistance(){return this.object.position.distanceTo(this.target)}listenToKeyEvents(e){e.addEventListener("keydown",this._onKeyDown),this._domElementKeyEvents=e}stopListenToKeyEvents(){this._domElementKeyEvents!==null&&(this._domElementKeyEvents.removeEventListener("keydown",this._onKeyDown),this._domElementKeyEvents=null)}saveState(){this.target0.copy(this.target),this.position0.copy(this.object.position),this.zoom0=this.object.zoom}reset(){this.target.copy(this.target0),this.object.position.copy(this.position0),this.object.zoom=this.zoom0,this.object.updateProjectionMatrix(),this.dispatchEvent(iu),this.update(),this.state=ot.NONE}pan(e,t){this._pan(e,t),this.update()}dollyIn(e){this._dollyIn(e),this.update()}dollyOut(e){this._dollyOut(e),this.update()}rotateLeft(e){this._rotateLeft(e),this.update()}rotateUp(e){this._rotateUp(e),this.update()}update(e=null){const t=this.object.position;Rt.copy(t).sub(this.target),Rt.applyQuaternion(this._quat),this._spherical.setFromVector3(Rt),this.autoRotate&&this.state===ot.NONE&&this._rotateLeft(this._getAutoRotationAngle(e)),this.enableDamping?(this._spherical.theta+=this._sphericalDelta.theta*this.dampingFactor,this._spherical.phi+=this._sphericalDelta.phi*this.dampingFactor):(this._spherical.theta+=this._sphericalDelta.theta,this._spherical.phi+=this._sphericalDelta.phi);let n=this.minAzimuthAngle,i=this.maxAzimuthAngle;isFinite(n)&&isFinite(i)&&(n<-Math.PI?n+=$t:n>Math.PI&&(n-=$t),i<-Math.PI?i+=$t:i>Math.PI&&(i-=$t),n<=i?this._spherical.theta=Math.max(n,Math.min(i,this._spherical.theta)):this._spherical.theta=this._spherical.theta>(n+i)/2?Math.max(n,this._spherical.theta):Math.min(i,this._spherical.theta)),this._spherical.phi=Math.max(this.minPolarAngle,Math.min(this.maxPolarAngle,this._spherical.phi)),this._spherical.makeSafe(),this.enableDamping===!0?this.target.addScaledVector(this._panOffset,this.dampingFactor):this.target.add(this._panOffset),this.target.sub(this.cursor),this.target.clampLength(this.minTargetRadius,this.maxTargetRadius),this.target.add(this.cursor);let r=!1;if(this.zoomToCursor&&this._performCursorZoom||this.object.isOrthographicCamera)this._spherical.radius=this._clampDistance(this._spherical.radius);else{const a=this._spherical.radius;this._spherical.radius=this._clampDistance(this._spherical.radius*this._scale),r=a!=this._spherical.radius}if(Rt.setFromSpherical(this._spherical),Rt.applyQuaternion(this._quatInverse),t.copy(this.target).add(Rt),this.object.lookAt(this.target),this.enableDamping===!0?(this._sphericalDelta.theta*=1-this.dampingFactor,this._sphericalDelta.phi*=1-this.dampingFactor,this._panOffset.multiplyScalar(1-this.dampingFactor)):(this._sphericalDelta.set(0,0,0),this._panOffset.set(0,0,0)),this.zoomToCursor&&this._performCursorZoom){let a=null;if(this.object.isPerspectiveCamera){const o=Rt.length();a=this._clampDistance(o*this._scale);const l=o-a;this.object.position.addScaledVector(this._dollyDirection,l),this.object.updateMatrixWorld(),r=!!l}else if(this.object.isOrthographicCamera){const o=new L(this._mouse.x,this._mouse.y,0);o.unproject(this.object);const l=this.object.zoom;this.object.zoom=Math.max(this.minZoom,Math.min(this.maxZoom,this.object.zoom/this._scale)),this.object.updateProjectionMatrix(),r=l!==this.object.zoom;const c=new L(this._mouse.x,this._mouse.y,0);c.unproject(this.object),this.object.position.sub(c).add(o),this.object.updateMatrixWorld(),a=Rt.length()}else console.warn("WARNING: OrbitControls.js encountered an unknown camera type - zoom to cursor disabled."),this.zoomToCursor=!1;a!==null&&(this.screenSpacePanning?this.target.set(0,0,-1).transformDirection(this.object.matrix).multiplyScalar(a).add(this.object.position):(Yr.origin.copy(this.object.position),Yr.direction.set(0,0,-1).transformDirection(this.object.matrix),Math.abs(this.object.up.dot(Yr.direction))<oM?this.object.lookAt(this.target):(su.setFromNormalAndCoplanarPoint(this.object.up,this.target),Yr.intersectPlane(su,this.target))))}else if(this.object.isOrthographicCamera){const a=this.object.zoom;this.object.zoom=Math.max(this.minZoom,Math.min(this.maxZoom,this.object.zoom/this._scale)),a!==this.object.zoom&&(this.object.updateProjectionMatrix(),r=!0)}return this._scale=1,this._performCursorZoom=!1,r||this._lastPosition.distanceToSquared(this.object.position)>bo||8*(1-this._lastQuaternion.dot(this.object.quaternion))>bo||this._lastTargetPosition.distanceToSquared(this.target)>bo?(this.dispatchEvent(iu),this._lastPosition.copy(this.object.position),this._lastQuaternion.copy(this.object.quaternion),this._lastTargetPosition.copy(this.target),!0):!1}_getAutoRotationAngle(e){return e!==null?$t/60*this.autoRotateSpeed*e:$t/60/60*this.autoRotateSpeed}_getZoomScale(e){const t=Math.abs(e*.01);return Math.pow(.95,this.zoomSpeed*t)}_rotateLeft(e){this._sphericalDelta.theta-=e}_rotateUp(e){this._sphericalDelta.phi-=e}_panLeft(e,t){Rt.setFromMatrixColumn(t,0),Rt.multiplyScalar(-e),this._panOffset.add(Rt)}_panUp(e,t){this.screenSpacePanning===!0?Rt.setFromMatrixColumn(t,1):(Rt.setFromMatrixColumn(t,0),Rt.crossVectors(this.object.up,Rt)),Rt.multiplyScalar(e),this._panOffset.add(Rt)}_pan(e,t){const n=this.domElement;if(this.object.isPerspectiveCamera){const i=this.object.position;Rt.copy(i).sub(this.target);let r=Rt.length();r*=Math.tan(this.object.fov/2*Math.PI/180),this._panLeft(2*e*r/n.clientHeight,this.object.matrix),this._panUp(2*t*r/n.clientHeight,this.object.matrix)}else this.object.isOrthographicCamera?(this._panLeft(e*(this.object.right-this.object.left)/this.object.zoom/n.clientWidth,this.object.matrix),this._panUp(t*(this.object.top-this.object.bottom)/this.object.zoom/n.clientHeight,this.object.matrix)):(console.warn("WARNING: OrbitControls.js encountered an unknown camera type - pan disabled."),this.enablePan=!1)}_dollyOut(e){this.object.isPerspectiveCamera||this.object.isOrthographicCamera?this._scale/=e:(console.warn("WARNING: OrbitControls.js encountered an unknown camera type - dolly/zoom disabled."),this.enableZoom=!1)}_dollyIn(e){this.object.isPerspectiveCamera||this.object.isOrthographicCamera?this._scale*=e:(console.warn("WARNING: OrbitControls.js encountered an unknown camera type - dolly/zoom disabled."),this.enableZoom=!1)}_updateZoomParameters(e,t){if(!this.zoomToCursor)return;this._performCursorZoom=!0;const n=this.domElement.getBoundingClientRect(),i=e-n.left,r=t-n.top,a=n.width,o=n.height;this._mouse.x=i/a*2-1,this._mouse.y=-(r/o)*2+1,this._dollyDirection.set(this._mouse.x,this._mouse.y,1).unproject(this.object).sub(this.object.position).normalize()}_clampDistance(e){return Math.max(this.minDistance,Math.min(this.maxDistance,e))}_handleMouseDownRotate(e){this._rotateStart.set(e.clientX,e.clientY)}_handleMouseDownDolly(e){this._updateZoomParameters(e.clientX,e.clientX),this._dollyStart.set(e.clientX,e.clientY)}_handleMouseDownPan(e){this._panStart.set(e.clientX,e.clientY)}_handleMouseMoveRotate(e){this._rotateEnd.set(e.clientX,e.clientY),this._rotateDelta.subVectors(this._rotateEnd,this._rotateStart).multiplyScalar(this.rotateSpeed);const t=this.domElement;this._rotateLeft($t*this._rotateDelta.x/t.clientHeight),this._rotateUp($t*this._rotateDelta.y/t.clientHeight),this._rotateStart.copy(this._rotateEnd),this.update()}_handleMouseMoveDolly(e){this._dollyEnd.set(e.clientX,e.clientY),this._dollyDelta.subVectors(this._dollyEnd,this._dollyStart),this._dollyDelta.y>0?this._dollyOut(this._getZoomScale(this._dollyDelta.y)):this._dollyDelta.y<0&&this._dollyIn(this._getZoomScale(this._dollyDelta.y)),this._dollyStart.copy(this._dollyEnd),this.update()}_handleMouseMovePan(e){this._panEnd.set(e.clientX,e.clientY),this._panDelta.subVectors(this._panEnd,this._panStart).multiplyScalar(this.panSpeed),this._pan(this._panDelta.x,this._panDelta.y),this._panStart.copy(this._panEnd),this.update()}_handleMouseWheel(e){this._updateZoomParameters(e.clientX,e.clientY),e.deltaY<0?this._dollyIn(this._getZoomScale(e.deltaY)):e.deltaY>0&&this._dollyOut(this._getZoomScale(e.deltaY)),this.update()}_handleKeyDown(e){let t=!1;switch(e.code){case this.keys.UP:e.ctrlKey||e.metaKey||e.shiftKey?this.enableRotate&&this._rotateUp($t*this.keyRotateSpeed/this.domElement.clientHeight):this.enablePan&&this._pan(0,this.keyPanSpeed),t=!0;break;case this.keys.BOTTOM:e.ctrlKey||e.metaKey||e.shiftKey?this.enableRotate&&this._rotateUp(-$t*this.keyRotateSpeed/this.domElement.clientHeight):this.enablePan&&this._pan(0,-this.keyPanSpeed),t=!0;break;case this.keys.LEFT:e.ctrlKey||e.metaKey||e.shiftKey?this.enableRotate&&this._rotateLeft($t*this.keyRotateSpeed/this.domElement.clientHeight):this.enablePan&&this._pan(this.keyPanSpeed,0),t=!0;break;case this.keys.RIGHT:e.ctrlKey||e.metaKey||e.shiftKey?this.enableRotate&&this._rotateLeft(-$t*this.keyRotateSpeed/this.domElement.clientHeight):this.enablePan&&this._pan(-this.keyPanSpeed,0),t=!0;break}t&&(e.preventDefault(),this.update())}_handleTouchStartRotate(e){if(this._pointers.length===1)this._rotateStart.set(e.pageX,e.pageY);else{const t=this._getSecondPointerPosition(e),n=.5*(e.pageX+t.x),i=.5*(e.pageY+t.y);this._rotateStart.set(n,i)}}_handleTouchStartPan(e){if(this._pointers.length===1)this._panStart.set(e.pageX,e.pageY);else{const t=this._getSecondPointerPosition(e),n=.5*(e.pageX+t.x),i=.5*(e.pageY+t.y);this._panStart.set(n,i)}}_handleTouchStartDolly(e){const t=this._getSecondPointerPosition(e),n=e.pageX-t.x,i=e.pageY-t.y,r=Math.sqrt(n*n+i*i);this._dollyStart.set(0,r)}_handleTouchStartDollyPan(e){this.enableZoom&&this._handleTouchStartDolly(e),this.enablePan&&this._handleTouchStartPan(e)}_handleTouchStartDollyRotate(e){this.enableZoom&&this._handleTouchStartDolly(e),this.enableRotate&&this._handleTouchStartRotate(e)}_handleTouchMoveRotate(e){if(this._pointers.length==1)this._rotateEnd.set(e.pageX,e.pageY);else{const n=this._getSecondPointerPosition(e),i=.5*(e.pageX+n.x),r=.5*(e.pageY+n.y);this._rotateEnd.set(i,r)}this._rotateDelta.subVectors(this._rotateEnd,this._rotateStart).multiplyScalar(this.rotateSpeed);const t=this.domElement;this._rotateLeft($t*this._rotateDelta.x/t.clientHeight),this._rotateUp($t*this._rotateDelta.y/t.clientHeight),this._rotateStart.copy(this._rotateEnd)}_handleTouchMovePan(e){if(this._pointers.length===1)this._panEnd.set(e.pageX,e.pageY);else{const t=this._getSecondPointerPosition(e),n=.5*(e.pageX+t.x),i=.5*(e.pageY+t.y);this._panEnd.set(n,i)}this._panDelta.subVectors(this._panEnd,this._panStart).multiplyScalar(this.panSpeed),this._pan(this._panDelta.x,this._panDelta.y),this._panStart.copy(this._panEnd)}_handleTouchMoveDolly(e){const t=this._getSecondPointerPosition(e),n=e.pageX-t.x,i=e.pageY-t.y,r=Math.sqrt(n*n+i*i);this._dollyEnd.set(0,r),this._dollyDelta.set(0,Math.pow(this._dollyEnd.y/this._dollyStart.y,this.zoomSpeed)),this._dollyOut(this._dollyDelta.y),this._dollyStart.copy(this._dollyEnd);const a=(e.pageX+t.x)*.5,o=(e.pageY+t.y)*.5;this._updateZoomParameters(a,o)}_handleTouchMoveDollyPan(e){this.enableZoom&&this._handleTouchMoveDolly(e),this.enablePan&&this._handleTouchMovePan(e)}_handleTouchMoveDollyRotate(e){this.enableZoom&&this._handleTouchMoveDolly(e),this.enableRotate&&this._handleTouchMoveRotate(e)}_addPointer(e){this._pointers.push(e.pointerId)}_removePointer(e){delete this._pointerPositions[e.pointerId];for(let t=0;t<this._pointers.length;t++)if(this._pointers[t]==e.pointerId){this._pointers.splice(t,1);return}}_isTrackingPointer(e){for(let t=0;t<this._pointers.length;t++)if(this._pointers[t]==e.pointerId)return!0;return!1}_trackPointer(e){let t=this._pointerPositions[e.pointerId];t===void 0&&(t=new Le,this._pointerPositions[e.pointerId]=t),t.set(e.pageX,e.pageY)}_getSecondPointerPosition(e){const t=e.pointerId===this._pointers[0]?this._pointers[1]:this._pointers[0];return this._pointerPositions[t]}_customWheelEvent(e){const t=e.deltaMode,n={clientX:e.clientX,clientY:e.clientY,deltaY:e.deltaY};switch(t){case 1:n.deltaY*=16;break;case 2:n.deltaY*=100;break}return e.ctrlKey&&!this._controlActive&&(n.deltaY*=10),n}}function cM(s){this.enabled!==!1&&(this._pointers.length===0&&(this.domElement.setPointerCapture(s.pointerId),this.domElement.ownerDocument.addEventListener("pointermove",this._onPointerMove),this.domElement.ownerDocument.addEventListener("pointerup",this._onPointerUp)),!this._isTrackingPointer(s)&&(this._addPointer(s),s.pointerType==="touch"?this._onTouchStart(s):this._onMouseDown(s),this._cursorStyle==="grab"&&(this.domElement.style.cursor="grabbing")))}function hM(s){this.enabled!==!1&&(s.pointerType==="touch"?this._onTouchMove(s):this._onMouseMove(s))}function uM(s){switch(this._removePointer(s),this._pointers.length){case 0:this.domElement.releasePointerCapture(s.pointerId),this.domElement.ownerDocument.removeEventListener("pointermove",this._onPointerMove),this.domElement.ownerDocument.removeEventListener("pointerup",this._onPointerUp),this.dispatchEvent(id),this.state=ot.NONE,this._cursorStyle==="grab"&&(this.domElement.style.cursor="grab");break;case 1:const e=this._pointers[0],t=this._pointerPositions[e];this._onTouchStart({pointerId:e,pageX:t.x,pageY:t.y});break}}function dM(s){let e;switch(s.button){case 0:e=this.mouseButtons.LEFT;break;case 1:e=this.mouseButtons.MIDDLE;break;case 2:e=this.mouseButtons.RIGHT;break;default:e=-1}switch(e){case ls.DOLLY:if(this.enableZoom===!1)return;this._handleMouseDownDolly(s),this.state=ot.DOLLY;break;case ls.ROTATE:if(s.ctrlKey||s.metaKey||s.shiftKey){if(this.enablePan===!1)return;this._handleMouseDownPan(s),this.state=ot.PAN}else{if(this.enableRotate===!1)return;this._handleMouseDownRotate(s),this.state=ot.ROTATE}break;case ls.PAN:if(s.ctrlKey||s.metaKey||s.shiftKey){if(this.enableRotate===!1)return;this._handleMouseDownRotate(s),this.state=ot.ROTATE}else{if(this.enablePan===!1)return;this._handleMouseDownPan(s),this.state=ot.PAN}break;default:this.state=ot.NONE}this.state!==ot.NONE&&this.dispatchEvent(ac)}function fM(s){switch(this.state){case ot.ROTATE:if(this.enableRotate===!1)return;this._handleMouseMoveRotate(s);break;case ot.DOLLY:if(this.enableZoom===!1)return;this._handleMouseMoveDolly(s);break;case ot.PAN:if(this.enablePan===!1)return;this._handleMouseMovePan(s);break}}function pM(s){this.enabled===!1||this.enableZoom===!1||this.state!==ot.NONE||(s.preventDefault(),this.dispatchEvent(ac),this._handleMouseWheel(this._customWheelEvent(s)),this.dispatchEvent(id))}function mM(s){this.enabled!==!1&&this._handleKeyDown(s)}function gM(s){switch(this._trackPointer(s),this._pointers.length){case 1:switch(this.touches.ONE){case os.ROTATE:if(this.enableRotate===!1)return;this._handleTouchStartRotate(s),this.state=ot.TOUCH_ROTATE;break;case os.PAN:if(this.enablePan===!1)return;this._handleTouchStartPan(s),this.state=ot.TOUCH_PAN;break;default:this.state=ot.NONE}break;case 2:switch(this.touches.TWO){case os.DOLLY_PAN:if(this.enableZoom===!1&&this.enablePan===!1)return;this._handleTouchStartDollyPan(s),this.state=ot.TOUCH_DOLLY_PAN;break;case os.DOLLY_ROTATE:if(this.enableZoom===!1&&this.enableRotate===!1)return;this._handleTouchStartDollyRotate(s),this.state=ot.TOUCH_DOLLY_ROTATE;break;default:this.state=ot.NONE}break;default:this.state=ot.NONE}this.state!==ot.NONE&&this.dispatchEvent(ac)}function _M(s){switch(this._trackPointer(s),this.state){case ot.TOUCH_ROTATE:if(this.enableRotate===!1)return;this._handleTouchMoveRotate(s),this.update();break;case ot.TOUCH_PAN:if(this.enablePan===!1)return;this._handleTouchMovePan(s),this.update();break;case ot.TOUCH_DOLLY_PAN:if(this.enableZoom===!1&&this.enablePan===!1)return;this._handleTouchMoveDollyPan(s),this.update();break;case ot.TOUCH_DOLLY_ROTATE:if(this.enableZoom===!1&&this.enableRotate===!1)return;this._handleTouchMoveDollyRotate(s),this.update();break;default:this.state=ot.NONE}}function vM(s){this.enabled!==!1&&s.preventDefault()}function xM(s){s.key==="Control"&&(this._controlActive=!0,this.domElement.getRootNode().addEventListener("keyup",this._interceptControlUp,{passive:!0,capture:!0}))}function MM(s){s.key==="Control"&&(this._controlActive=!1,this.domElement.getRootNode().removeEventListener("keyup",this._interceptControlUp,{passive:!0,capture:!0}))}const Eo=[{id:"fasteners",label:"紧固件",en:"FASTENERS",depth:2.75},{id:"cover",label:"透明盖板",en:"OPTICAL COVER",depth:1.85},{id:"optical-lenses",label:"折射环组",en:"REFRACTIVE RINGS",depth:.75},{id:"optical-core",label:"光学核心",en:"OPTICAL CORE",depth:-.15},{id:"substrate",label:"信息基板",en:"SUBSTRATE",depth:-1.1},{id:"carrier",label:"背板与框架",en:"CARRIER",depth:-2.05}];class yM{root;canvasHost;renderer;scene=new Zl;camera=new Wt(34,16/9,.3,120);controls;source;groups=new Map;spread={value:0,velocity:0};targetSpread=0;lastTime=0;request=0;reduced=!1;loading=!1;closing=!1;transitions=[];transitionId=0;status="";opener=null;siblings=[];initialCamera=new L(7.2,3.8,12);onClose;provider;isOpen=!1;constructor(e,t){this.onClose=t,this.root=document.createElement("section"),this.root.className="model-viewer",this.root.hidden=!0,this.root.setAttribute("role","dialog"),this.root.setAttribute("aria-modal","true"),this.root.setAttribute("aria-labelledby","viewer-title"),this.root.innerHTML=`
      <div class="viewer-canvas"></div>
      <div class="scene-atmosphere viewer-atmosphere" aria-hidden="true"></div>
      <header class="viewer-header">
        <button class="viewer-back" data-viewer="close">← <span>返回档案</span><kbd>ESC</kbd></button>
        <div class="viewer-heading"><span>RHINE LAB / OBJECT STUDY</span><h2 id="viewer-title">档案模型</h2><p id="viewer-file"></p></div>
        <span class="viewer-index">360<span>°</span></span>
      </header>
      <aside class="viewer-parts" aria-label="模型装配结构"><div>ASSEMBLY / 装配结构</div>${Eo.map((n,i)=>`<p><span>${String(i+1).padStart(2,"0")}</span><strong>${n.label}</strong><small>${n.en}</small></p>`).join("")}</aside>
      <div class="viewer-loading" role="status"><span>正在载入模型…</span><button data-viewer="retry" hidden>重新载入 ↗</button></div>
      <footer class="viewer-footer">
        <div class="viewer-help"><span>拖动旋转</span><span>↑ ↓ ← → 平移</span><span>滚轮缩放</span></div>
        <div class="viewer-actions"><button data-viewer="explode" aria-pressed="false"><span>＋</span> 拆解档案</button><button data-viewer="assemble" aria-pressed="true"><span>−</span> 一键重组</button></div>
        <button class="viewer-reset" data-viewer="reset">复位视角 <span>↗</span></button>
      </footer>
      <div class="viewer-state" aria-live="polite">已组装</div>`,e.appendChild(this.root),this.canvasHost=this.root.querySelector(".viewer-canvas"),this.renderer=new Yu({antialias:!0,powerPreference:"high-performance"}),this.renderer.toneMapping=ar,this.renderer.toneMappingExposure=1.05,this.renderer.domElement.tabIndex=0,this.renderer.domElement.setAttribute("aria-label","档案三维模型：拖动旋转，方向键平移，滚轮或加减键缩放，Home 复位"),this.canvasHost.appendChild(this.renderer.domElement),this.scene.background=new Ie("#eae5e1"),this.scene.fog=new _a("#eae5e1",13.5,26.5),$u(this.renderer,this.scene),this.camera.position.copy(this.initialCamera),this.controls=new lM(this.camera,this.renderer.domElement),this.controls.enableDamping=!0,this.controls.dampingFactor=.085,this.controls.rotateSpeed=.65,this.controls.zoomSpeed=.7,this.controls.panSpeed=.7,this.controls.minDistance=5,this.controls.maxDistance=28,this.controls.maxTargetRadius=5,this.controls.screenSpacePanning=!0,this.controls.enabled=!1,this.controls.update(),this.root.addEventListener("click",n=>{if(this.closing)return;const i=n.target.closest("[data-viewer]")?.dataset.viewer;i==="close"&&this.close(),i==="retry"&&this.load(),!(this.loading||!this.source)&&(i==="explode"&&this.setExploded(!0),i==="assemble"&&this.setExploded(!1),i==="reset"&&this.resetView())}),this.root.addEventListener("keydown",n=>this.keydown(n))}open(e,t,n,i){this.isOpen||(this.isOpen=!0,this.closing=!1,this.reduced=i,this.provider=n,this.opener=document.activeElement,this.siblings=[...this.root.parentElement.children].filter(r=>r instanceof HTMLElement&&r!==this.root).map(r=>({node:r,inert:r.inert})),this.siblings.forEach(({node:r})=>r.inert=!0),this.root.hidden=!1,this.root.dataset.transition="opening",this.root.querySelector("#viewer-title").textContent=t,this.root.querySelector("#viewer-file").textContent="FILE "+e+" / INTERNAL DATABASE",this.spread={value:0,velocity:0},this.targetSpread=0,this.lastTime=0,this.root.dataset.exploded="false",this.resetView(),this.resize(),this.renderer.domElement.focus({preventScroll:!0}),this.enter(),this.load())}async load(){if(!this.provider||this.loading)return;const e=++this.request;this.loading=!0,this.controls.enabled=!1;const t=this.root.querySelector(".viewer-loading");t.hidden=!1,t.querySelector("span").textContent="正在载入模型…",t.querySelector("button").hidden=!0,this.setButtonsDisabled(!0);try{const n=await this.provider();if(!this.isOpen||this.closing||e!==this.request){n.dispose();return}this.source=n;for(const i of Eo){const r=new In;r.name=i.id,this.groups.set(i.id,r)}for(const i of[...n.model.children])this.groups.get(i.userData.assemblyPart??"cover")?.add(i);for(const i of this.groups.values())n.model.add(i);n.model.position.set(0,-1.85,0),this.scene.add(n.model),this.loading=!1,t.hidden=!0,this.controls.enabled=!0,this.setButtonsDisabled(!1),this.setExploded(!1),this.setStatus("已组装"),this.update(this.lastTime),this.reduced||this.transitions.push(this.canvasHost.animate([{opacity:0,transform:"scale(0.97)"},{opacity:1,transform:"scale(1)"}],{duration:380,easing:"cubic-bezier(0.22, 1, 0.36, 1)"}))}catch(n){if(!this.isOpen||this.closing||e!==this.request)return;this.loading=!1,t.querySelector("span").textContent="模型载入失败，请重试",t.querySelector("button").hidden=!1,console.error("Model viewer failed to load",n)}}enter(){const e=++this.transitionId;if(this.transitions.forEach(n=>n.cancel()),this.transitions=[],this.reduced){this.root.dataset.transition="open";return}const t=this.root.animate([{opacity:0},{opacity:1}],{duration:320,easing:"cubic-bezier(0.22, 1, 0.36, 1)"});this.transitions.push(t);for(const n of[".viewer-header",".viewer-footer",".viewer-state"]){const i=this.root.querySelector(n);this.transitions.push(i.animate([{opacity:0,translate:"0 10px"},{opacity:1,translate:"0 0"}],{duration:300,delay:60,fill:"backwards",easing:"cubic-bezier(0.22, 1, 0.36, 1)"}))}t.finished.then(()=>{e===this.transitionId&&(this.root.dataset.transition="open")}).catch(()=>{})}close(){if(!this.isOpen||this.closing)return;this.closing=!0,this.request++,this.loading=!1,this.controls.enabled=!1,this.setButtonsDisabled(!0);const e=++this.transitionId,t=getComputedStyle(this.root).opacity,n=getComputedStyle(this.canvasHost),i=n.opacity,r=n.transform;if(this.transitions.forEach(o=>o.cancel()),this.transitions=[],this.root.dataset.transition="closing",this.reduced){this.finishClose();return}const a=this.root.animate([{opacity:t},{opacity:0}],{duration:220,easing:"cubic-bezier(0.4, 0, 1, 1)",fill:"forwards"});this.transitions.push(a,this.canvasHost.animate([{transform:r,opacity:i},{transform:"scale(0.97)",opacity:0}],{duration:220,easing:"cubic-bezier(0.4, 0, 1, 1)",fill:"forwards"})),a.finished.then(()=>{e===this.transitionId&&this.finishClose()}).catch(()=>{})}finishClose(){this.isOpen=!1,this.closing=!1,this.root.hidden=!0,this.transitions.forEach(e=>e.cancel()),this.transitions=[],this.source&&(this.scene.remove(this.source.model),this.source.dispose(),this.source=void 0),this.groups.clear(),this.siblings.forEach(({node:e,inert:t})=>e.inert=t),this.siblings=[],this.opener?.focus({preventScroll:!0}),this.onClose()}setButtonsDisabled(e){for(const t of["explode","assemble","reset"])this.root.querySelector(`[data-viewer="${t}"]`).disabled=e}setExploded(e){this.targetSpread=e?1:0,this.root.dataset.exploded=String(e),this.root.querySelector('[data-viewer="explode"]').setAttribute("aria-pressed",String(e)),this.root.querySelector('[data-viewer="assemble"]').setAttribute("aria-pressed",String(!e)),this.setStatus(e?"正在拆解":this.spread.value>.001?"正在重组":"已组装"),this.reduced&&(this.spread={value:this.targetSpread,velocity:0})}setStatus(e){e!==this.status&&(this.status=e,this.root.querySelector(".viewer-state").textContent=e)}resetView(){this.controls.enabled=!1,this.controls.enableDamping=!1,this.controls.update(),this.controls.target.set(0,0,0),this.camera.position.copy(this.initialCamera),this.controls.enableDamping=!1,this.controls.update(),this.controls.enableDamping=!this.reduced,this.controls.enabled=this.isOpen&&!this.loading&&!!this.source}keydown(e){if(e.stopPropagation(),e.key==="Escape"){e.preventDefault(),this.close();return}if(this.closing){e.preventDefault();return}if(e.key==="Tab"){const t=[...this.root.querySelectorAll('button:not([disabled]):not([hidden]),canvas[tabindex="0"]')],n=t[0],i=t.at(-1);e.shiftKey&&document.activeElement===n&&(e.preventDefault(),i?.focus()),!e.shiftKey&&document.activeElement===i&&(e.preventDefault(),n?.focus());return}if(!(!this.source||this.loading)){if(e.key==="Home"){e.preventDefault(),this.resetView();return}if(["+","=","-"].includes(e.key)){e.preventDefault();const t=this.camera.position.distanceTo(this.controls.target),n=je.clamp(t*(e.key==="-"?1.12:1/1.12),5,28);this.camera.position.sub(this.controls.target).multiplyScalar(n/t).add(this.controls.target),this.controls.update();return}if(["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(e.key)){e.preventDefault();const t=new L().setFromMatrixColumn(this.camera.matrix,0),n=new L().setFromMatrixColumn(this.camera.matrix,1),i=new L,r=this.camera.position.distanceTo(this.controls.target)*.025;e.key==="ArrowLeft"&&i.addScaledVector(t,-r),e.key==="ArrowRight"&&i.addScaledVector(t,r),e.key==="ArrowUp"&&i.addScaledVector(n,r),e.key==="ArrowDown"&&i.addScaledVector(n,-r),this.camera.position.add(i),this.controls.target.add(i),this.controls.update()}}}resize(){if(!this.isOpen)return;const e=this.canvasHost.clientWidth,t=this.canvasHost.clientHeight;this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.5)*Math.min(innerWidth/1920,innerHeight/1080)),this.renderer.setSize(e,t),this.camera.aspect=e/t,this.camera.updateProjectionMatrix()}update(e){if(!this.isOpen)return;const t=Math.min(this.lastTime?e-this.lastTime:1/60,.05);if(this.lastTime=e,this.source){Ri(this.spread,this.targetSpread,this.reduced?45:5.5,t),Math.abs(this.spread.value-this.targetSpread)<1e-4&&Math.abs(this.spread.velocity)<.001&&(this.spread={value:this.targetSpread,velocity:0},this.setStatus(this.targetSpread?"已拆解":"已组装"));for(const r of Eo)this.groups.get(r.id).position.z=r.depth*this.spread.value}this.controls.update();const n=this.scene.fog,i=this.camera.position.length();n.near=Math.max(0,i-1),n.far=i+12,this.renderer.render(this.scene,this.camera),this.root.dataset.stats=JSON.stringify({ready:!!this.source,spread:this.spread.value,target:this.targetSpread,distance:this.camera.position.distanceTo(this.controls.target),targetPosition:this.controls.target.toArray(),azimuth:this.controls.getAzimuthalAngle(),polar:this.controls.getPolarAngle(),parts:[...this.groups].map(([r,a])=>({id:r,z:a.position.z,meshes:a.children.length}))})}}class SM{constructor(e){this.host=e,this.value=e.textContent??"",this.text=document.createElement("span"),this.text.textContent=this.value,e.replaceChildren(this.text),e.classList.add("scrub-title")}host;text;value;lastChange=-1/0;timer;animation;obscured=!1;update(e,t){if(!t){this.reset(),this.value=this.text.textContent=e,this.lastChange=-1/0;return}if(e===this.value)return;const n=performance.now(),i=n-this.lastChange<240;if(this.lastChange=n,this.value=e,clearTimeout(this.timer),!this.obscured&&!i){this.text.textContent=e;return}this.obscured||(this.host.style.width=`${Math.max(88,this.host.offsetWidth)}px`,this.obscured=!0,this.host.dataset.scrubbing="true",this.text.style.opacity="0",this.animation?.cancel(),this.animation=this.text.animate([{opacity:1},{opacity:.28,offset:.35},{opacity:1,offset:.7},{opacity:0}],{duration:140,easing:"steps(1, end)"})),this.text.textContent=e,this.timer=setTimeout(()=>this.reveal(),260)}reveal(){this.animation?.cancel(),this.obscured=!1,delete this.host.dataset.scrubbing,this.host.style.width="",this.text.style.opacity="",this.animation=this.host.animate([{opacity:.2},{opacity:1,offset:.35},{opacity:.5,offset:.6},{opacity:1}],{duration:180,easing:"steps(1, end)"})}reset(){clearTimeout(this.timer),this.animation?.cancel(),this.animation=void 0,this.obscured=!1,delete this.host.dataset.scrubbing,this.host.style.width="",this.text.style.opacity="",this.lastChange=-1/0}}const Ot=(s,e,t)=>Math.max(0,Math.min(1,(s-e)/(t-e))),Ks=s=>s*s*(3-2*s),is=(s,e,t,n)=>s.slice(0,e<t?0:Math.min(s.length,1+Math.floor((e-t)*(s.length-1)/(n-t)))),hi=(s,e)=>e.includes(s),bM=[1,1,3,4,5,6,9,11,12,14,17,18,19,20,22,23,25,26];function EM(s){const e=s+5,t=Math.floor(e*25+1e-5),n=e<9.12?"access":e<11.12?"logo":e<19.48?"auth":e<22.76?"scan":"welcome";let i="";t<363?(i=is("ID CONFIRMED",t,282,295),t>=320&&(i+=" : "+is("JOYCE MOORE",t,321,339))):t<421?i=is("REQUEST RECEIVED",t,367,389):(i=is("START PROCESSING",t,423,440),t>=449&&(i+=".".repeat(Math.min(3,1+Math.floor((t-449)/4)))),hi(t,[479,485,486])&&(i="              SING..."));const r=248+652*Math.exp(-Math.max(0,e-20)*2.8),a=hi(t,[525,526,528,529]),o=[1,0,.28,0,1,0,0],l=t-569,c=Ks(Ot(e,26.56,26.92));return{t:e,f:t,step:n,auth:i,access:"ACCESS PERMISSION REQUIRED".slice(0,t<170?0:bM[Math.min(17,t-170)]),accessOpacity:t>=170&&t<227?t===226?.25:1:0,logoOpacity:e>=9.16&&e<19.48?hi(t,[461,471,475])?.55:1:0,logoLeft:1-Math.pow(1-Ot(e,10.6,11.84),3),drawTop:Ks(Ot(e,9.16,9.4)),drawLeft:Ot(e,9.36,9.64),drawRight:Ot(e,9.58,10.04),logoLetters:is("RHINE·LAB",t,232,255),plus:Ot(e,9.88,10),minus:Ot(e,10.08,10.24),plusAngle:90*Ks(Ot(e,10.24,10.72)),authOpacity:t>=281&&t<487?1:0,brand:[11.12,11.2,11.28].map(h=>Ot(e,h,h+.2)),brandX:205*Math.pow(1-Ot(e,11.12,11.84),3),poweredLetters:is("POWERED BY RHINE LAB",t,279,295).length,scanVisible:e>=19.48&&e<22.76,scanRadius:r,ringScale:a?1.94:1,ringOpacity:a?.32:Ot(e,19.68,19.96),scanTracking:31*(1-Ot(e,19.48,20.44)),scanFont:22+14*(1-Ot(e,19.48,20.44)),permissionOpacity:e<21.84?Ot(e,19.48,19.88):hi(t,[547,550])?.05:0,ornament:e>=21.84,coreRadius:hi(t,[546,547,549,550])?42:5,welcomeVisible:e>=22.76&&e<26.92,welcomePanel:l>=0&&l<7?o[l]:0,welcomeInk:l>=0&&l<7?[0,0,.2,1,0,0,.25][l]:1,companyVisible:t>=588&&!hi(t,[590,591]),companyMask:hi(t,[594,595]),highlight:Ot(e,23.52,24.04),databaseOpacity:t<626||hi(t,[628,629,631,634])?0:1,welcomeLogo:t>=588,welcomeScale:1-.46*c,welcomeOpacity:1-Math.pow(c,3),exitBlur:8*c,exit:c,backgroundOpacity:e<26.92?1:0,white:Ks(Ot(e,26.16,26.88))}}const ru="http://www.w3.org/2000/svg",ss=(s,e,t,n=960,i=540)=>{const r=a=>`${n+Math.cos(a)*s},${i+Math.sin(a)*s}`;return`M${r(e)}A${s},${s} 0 ${t>Math.PI?1:0} 1 ${r(e+Math.min(t,Math.PI*1.999))}`};class TM{constructor(e){this.stage=e,[".access-text",".boot-logo",".auth-status","#auth-message",".scan",".scan > span",".welcome",".welcome-heading",".welcome-panel",".welcome-company",".welcome-highlight",".welcome-database",".welcome-logo",".brand",".powered","#boot-background",".boot-background svg",".boot-white"].forEach(r=>this.nodes.set(r,e.querySelector(r)));const t=e.querySelector(".boot-logo svg"),n=t.querySelector("path");this.strokes=Qx.map(r=>{const a=n.cloneNode();return a.setAttribute("d",r),a.setAttribute("pathLength","1"),a.style.strokeDasharray="1",t.insertBefore(a,n),a}),n.remove();const i=t.querySelector("path:not([pathLength])");this.plus=document.createElementNS(ru,"path"),this.plus.setAttribute("d","M44 70h50M69 45v50"),this.minus=document.createElementNS(ru,"path"),this.minus.setAttribute("d","M219 70h44"),[this.plus,this.minus].forEach(r=>{r.setAttribute("stroke","currentColor"),r.setAttribute("stroke-width","15"),t.insertBefore(r,i)}),i.remove(),this.letters=t.querySelector("text"),this.letters.setAttribute("text-anchor","start"),this.letters.setAttribute("x","20"),this.brandLines=Array.from(e.querySelector(".brand").children),this.scanPaths=Array.from(e.querySelectorAll(".scan path")),this.orbitDots=Array.from(e.querySelectorAll(".scan .orbit-dot")),this.core=e.querySelector(".scan .scan-core"),this.poweredHTML=this.el(".powered").innerHTML}stage;nodes=new Map;strokes;letters;plus;minus;brandLines;scanPaths;orbitDots;core;poweredHTML;el(e){return this.nodes.get(e)}opacity(e,t){this.el(e).style.opacity=String(Number(t))}update(e){const t=EM(e),n=t.t;return this.stage.dataset.bootFrame=String(t.f),this.el(".access-text").textContent=t.access,this.opacity(".access-text",t.accessOpacity),this.opacity(".boot-logo",t.logoOpacity),this.el(".boot-logo").style.transform=`translateX(${294*(1-t.logoLeft)}px)`,this.strokes.forEach((i,r)=>i.style.strokeDashoffset=String(1-[t.drawTop,t.drawLeft,t.drawRight][r])),this.letters.textContent=t.logoLetters,this.plus.style.opacity=String(t.plus),this.minus.style.opacity=String(t.minus),this.plus.setAttribute("transform",`rotate(${t.plusAngle} 69 70)`),this.opacity(".auth-status",t.authOpacity),this.el("#auth-message").textContent=t.auth,this.opacity(".brand",1),this.el(".brand").style.transform=`translateX(${t.brandX}px)`,this.brandLines.forEach((i,r)=>i.style.opacity=String(t.brand[r])),this.opacity(".powered",t.poweredLetters>0),this.el(".powered").style.clipPath=`inset(0 ${100*(1-t.poweredLetters/19)}% 0 0)`,this.opacity(".scan",t.scanVisible),t.scanVisible&&this.renderScan(t),this.opacity(".welcome",t.welcomeVisible?t.welcomeOpacity:0),this.el(".welcome").style.transform=`scale(${t.welcomeScale})`,this.el(".welcome").style.filter=`blur(${t.exitBlur}px) invert(${t.exit*.22}) sepia(${t.exit}) saturate(${1+t.exit*5}) hue-rotate(${t.exit*115}deg)`,this.opacity(".welcome-panel",t.welcomePanel),this.opacity(".welcome-heading",1),this.el(".welcome-heading").style.color=`rgb(${255*(1-t.welcomeInk)} ${255*(1-t.welcomeInk)} ${255*(1-t.welcomeInk)})`,this.opacity(".welcome-company",t.companyVisible),this.el(".welcome-company").style.visibility=t.companyMask?"hidden":"visible",this.el(".welcome-highlight").style.clipPath=`inset(0 ${100*(1-t.highlight)}% 0 0)`,this.opacity(".welcome-database",t.databaseOpacity),this.opacity(".welcome-logo",t.welcomeLogo),this.opacity("#boot-background",t.backgroundOpacity),this.opacity(".boot-white",t.white),this.el(".boot-background svg").style.transform=`translate(${Math.sin(n*.16)*18}px, ${-(n-6)*5}px) scale(1.08)`,t}renderScan(e){const t=e.t,n=Ks(Ot(t,19.76,21.8)),i=e.scanRadius,r=this.scanPaths[0].parentElement;r.setAttribute("transform",`translate(960 540) scale(${e.ringScale}) translate(-960 -540)`),r.style.opacity=String(e.ringOpacity);const a=-Math.PI/2+(1-n)*5;this.scanPaths[0].setAttribute("d",ss(i,a,Math.PI*(1.35+.64*n))),this.scanPaths[0].setAttribute("stroke-width",String(2.4*i/256)),this.scanPaths[1].setAttribute("d",ss(i*(.68+.23*n),-Math.PI/2-(1-n)*6,Math.PI*(1.15+.84*n))),this.scanPaths[1].setAttribute("stroke-width",String(3.6*i/256));const o=(t-19.64)*4;this.scanPaths[2].setAttribute("d",ss(92+28*(1-n),o,2.9)),this.scanPaths[3].setAttribute("d",ss(92+28*(1-n),o+Math.PI,1.8)),this.scanPaths[4].setAttribute("d",ss(38,-o,4.2,830,552)),this.scanPaths[5].setAttribute("d",ss(38,Math.PI-o,4.2,1090,528)),this.scanPaths.slice(4).forEach(c=>c.style.opacity=e.ornament?"1":"0"),this.core.style.opacity=e.ornament?"1":"0",this.core.setAttribute("r",String(e.coreRadius));const l=-Math.PI/2+(1-n)*7+.1*Math.sin(t*2);this.orbitDots.forEach((c,h)=>{c.setAttribute("cx",String(960+Math.cos(l+h*Math.PI)*(175+50*(1-n)))),c.setAttribute("cy",String(540+Math.sin(l+h*Math.PI)*(175+50*(1-n))))}),this.opacity(".scan > span",e.permissionOpacity),this.el(".scan > span").style.letterSpacing=`${e.scanTracking}px`,this.el(".scan > span").style.fontSize=`${e.scanFont}px`}reset(){[".brand",".powered"].forEach(e=>this.el(e).removeAttribute("style")),this.brandLines.forEach(e=>e.removeAttribute("style")),this.el(".powered").innerHTML=this.poweredHTML,this.opacity("#boot-background",0)}}class AM{enabled=!1;context;play(e="tick"){if(this.enabled)try{this.context??=new AudioContext;const t=this.context;t.state==="suspended"&&t.resume();const n=t.createOscillator(),i=t.createGain();n.type="sine";const r={tick:760,open:420,confirm:960,back:320}[e];n.frequency.setValueAtTime(r,t.currentTime),n.frequency.exponentialRampToValueAtTime(r*(e==="open"?1.8:.7),t.currentTime+.13),i.gain.setValueAtTime(1e-4,t.currentTime),i.gain.exponentialRampToValueAtTime(.035,t.currentTime+.008),i.gain.exponentialRampToValueAtTime(1e-4,t.currentTime+.18),n.connect(i),i.connect(t.destination),n.start(),n.stop(t.currentTime+.2)}catch{}}}const de=s=>document.querySelector(s);de("#stage").innerHTML=`
  <div id="three-scene" class="three-scene"></div>
  <div class="scene-atmosphere"></div>
  <div id="boot-background" class="boot-background"><svg viewBox="0 0 1920 1080" preserveAspectRatio="none"><g fill="none" stroke="#fff" stroke-width="3"><path d="M-210 705C-45 705 182 704 247 567C337 377 99 306 4 435S27 680 169 631C309 584 227 314 279 111S568-113 568-113"/><path d="M1560-80C1374 114 1671 168 1601 323S1371 367 1431 480S1692 666 1559 787S1329 886 1498 1130"/><circle cx="1450" cy="648" r="346"/><circle cx="1450" cy="648" r="348"/></g></svg></div>
  <header class="brand"><h1>RHINE LAB</h1><div>SYNTHESIZE INFORMATION</div><p>ANALYSIS <b>OS</b></p></header>
  <nav class="system-nav" aria-label="系统导航">
    <button data-action="search"><span class="nav-glyph">⌕</span> ARCHIVE INDEX <span class="key">/</span></button>
    <button data-action="saved" aria-label="查看收藏档案" title="收藏档案">＋ SAVED <span id="saved-count">00</span></button>
    <button data-action="settings" aria-label="系统设置" title="系统设置"><span class="settings-glyph">◷</span></button>
  </nav>
  <button id="skip" class="skip" data-action="skip">ENTER SYSTEM <span>↗</span></button>
  <section id="boot" class="boot" aria-label="系统启动">
    <div class="access-text">ACCESS</div>
    <div class="boot-logo">${So}</div>
    <div class="auth-status"><span>▪</span> <span id="auth-message"></span><i></i></div>
    <div class="scan"><svg viewBox="0 0 1920 1080" aria-hidden="true"><g fill="none" stroke="#080a08" stroke-width="2" stroke-linecap="round"><path/><path stroke="#fff"/><path/><path/><path/><path/><circle class="orbit-dot" r="8" fill="#ed821b" stroke="none"/><circle class="orbit-dot" r="8" fill="#ed821b" stroke="none"/><circle class="scan-core" cx="960" cy="540" r="5" fill="#080a08" stroke="none"/></g></svg><span>PERMISSION AUTHORIZED</span></div>
    <div class="welcome"><div class="welcome-panel"></div><div class="welcome-heading">WELCOME TO</div><div class="welcome-company"><strong>RHINE LAB.LLC.</strong><strong class="welcome-highlight" aria-hidden="true">RHINE LAB.LLC.</strong></div><div class="welcome-database">INTERNAL DATABASE</div><div class="welcome-logo">${So}</div></div>
  </section>
  <div id="cinema-caption" class="cinema-caption"></div>
  <svg id="inspection-marks" viewBox="0 0 1920 1080" aria-hidden="true"><path id="inspection-lines"/><g id="inspection-corners"></g></svg>
  <div id="inspection-text" aria-hidden="true">CONFIDENTIALITY:<strong>GENERAL BUSINESS USE</strong></div>
  <section id="archive-ui" class="archive-ui" aria-label="档案选择">
    <div class="archive-callout"><div class="eyebrow">INTERNAL DATABASE <span>／</span> <span id="archive-category">机构档案</span></div><button class="file-title" data-action="open">FILE NUMBER: <span id="selected-id">X-<span id="selected-code">001</span></span><span class="file-open">↗</span></button><div class="callout-rule"><i></i></div><div class="file-summary"><span id="selected-title">莱茵生命</span><span id="selected-clearance">BUSINESS AREA</span></div><button class="read-file" data-action="open">ACCESS FILE <span>→</span></button></div>
    <div id="hover-label" class="hover-label" hidden>X-<span id="hover-code">001</span><span id="hover-title"></span></div>
    <div class="archive-counter"><span class="tiny-label">ARCHIVE / SELECT</span><div><span id="selected-number">01</span><i>/</i><span class="count-total">12</span></div></div>
    <div class="archive-navigation"><button data-action="prev" aria-label="上一个档案">↑</button><div id="file-ticks" class="file-ticks"></div><button data-action="next" aria-label="下一个档案">↓</button></div>
    <div class="column-navigation"><button data-action="column-prev" aria-label="上一列">←</button><div><span id="column-number">COLUMN <span id="column-index">03</span> / 05</span><strong id="column-name">机构档案</strong></div><button data-action="column-next" aria-label="下一列">→</button></div>
    <div class="archive-hint"><kbd>←</kbd> <kbd>→</kbd> 切换列 <span>／</span> <kbd>↑</kbd> <kbd>↓</kbd> 前后档案 <span>／</span> <kbd>ENTER</kbd> 读取</div>
  </section>
  <section id="detail-ui" class="detail-ui" aria-label="档案内容" hidden>
    <button class="back-button" data-action="back">← <span>ARCHIVE OVERVIEW</span><small>ESC</small></button>
    <div class="object-caption"><span id="object-id">NO.001</span><div>INTERNAL DATABASE</div><small>DRAG TO INSPECT <span>↔</span></small><button class="viewer-open" data-action="model-viewer">360° 查看文档模型 <span>↗</span></button></div>
    <article id="detail-content" class="detail-content"></article>
  </section>
  <div class="powered">POWERED BY <b>RHINE LAB</b><i></i></div>
  <footer class="system-footer"><span><i class="status-light"></i> SESSION AUTHORIZED</span><span>JOYCE MOORE <i>／</i> <span id="clock">00:00:00</span></span><button data-action="replay" title="重播启动流程">REINITIALIZE ↗</button></footer>
  <div id="modal-root"></div><div id="toast" class="toast" role="status"></div>
  <div id="loading" class="loading"><div class="loading-mark">${So}</div><span>CONNECTING TO INTERNAL DATABASE</span><i></i></div>
`;de("#boot-background").insertAdjacentHTML("beforeend",'<div class="boot-white"></div>');const sd=new TM(de("#stage"));let ut="boot",vt=0,fs=0,ha="",Li=!1,At=null,ps="",ms="全部档案",sr="overview";const Rl=new URLSearchParams(location.search);let oc=Rl.get("freeze")==="1"?Number(Rl.get("time")??0):null;Rl.get("review")==="1"&&(de("#stage").dataset.review="true",window.addEventListener("message",s=>{if(s.origin!==location.origin||s.source!==window.parent||s.data?.type!=="rhine-review-frame")return;const e=Number(s.data.time);!Number.isFinite(e)||e<0||e>=35||(oc=e,Li&&ut!=="boot"&&Vt("boot"))}));let au,rd=null;function ad(s,e){try{return JSON.parse(localStorage.getItem(s)??"null")??e}catch{return e}}const xn=new Set(ad("rhine-saved",[])),_t=ad("rhine-settings",{sound:!1,reduced:matchMedia("(prefers-reduced-motion: reduce)").matches,quality:!0}),lc={locales:"en-US",format:{minimumIntegerDigits:2,useGrouping:!1},duration:460,motionBlur:!0,animated:!_t.reduced},od=fa(de("#selected-number"),{...lc,value:1}),ld=fa(de("#column-index"),{...lc,value:3}),cd={...lc,format:{minimumIntegerDigits:3,useGrouping:!1},value:1},cc=new SM(de("#selected-title")),hd=fa(de("#selected-code"),cd),ud=fa(de("#hover-code"),cd),Zt=new AM;Zt.enabled=_t.sound;let ht,ws;const dd=[],fd=Fi.map((s,e)=>Oi(e)[0]);function wM(){dd.unshift({id:Ut[vt].id,time:new Date().toLocaleTimeString("en-GB")})}function pd(){try{localStorage.setItem("rhine-settings",JSON.stringify(_t))}catch{}Zt.enabled=_t.sound,_t.reduced&&cc.reset(),ht?.setReduced(_t.reduced),ht?.setQuality(_t.quality),od.update({animated:!_t.reduced&&ut==="archive"}),ld.update({animated:!_t.reduced&&ut==="archive"}),hd.update({animated:!_t.reduced&&ut==="archive"}),ud.update({animated:!_t.reduced&&ut==="archive"}),de("#stage").classList.toggle("reduce-motion",_t.reduced)}function md(){const s=Math.min(innerWidth/1920,innerHeight/1080);de("#stage").style.transform=`translate(-50%, -50%) scale(${s})`,de("#viewport").style.setProperty("--scale",String(s)),ht?.resize(),ws?.resize()}window.addEventListener("resize",md);md();de("#file-ticks").innerHTML=Ut.map((s,e)=>`<button data-select="${e}" aria-label="选择档案 ${s.id} ${s.title}" title="${s.id} · ${s.title}"></button>`).join("");function Vt(s){s!=="archive"&&cc.reset(),s==="detail"&&ut!=="detail"&&wM(),ut=s,de("#stage").dataset.mode=s,de("#boot").inert=s!=="boot",de("#boot").setAttribute("aria-hidden",String(s!=="boot")),de("#archive-ui").inert=s!=="archive",de("#archive-ui").setAttribute("aria-hidden",String(s!=="archive")),de(".system-nav").inert=s==="boot",de(".system-footer").inert=s==="boot",de("#detail-ui").hidden=s!=="detail",ht?.setMode(s==="boot"?"hidden":s),s!=="boot"&&(sd.reset(),de(".file-title").firstChild.textContent="FILE NUMBER: ",de("#stage").dataset.boot="done",de("#cinema-caption").textContent=""),s==="detail"&&gd()}function Ii(s,e){vt=(s+Ut.length)%Ut.length,fd[_i(vt).lane]=vt,ut==="detail"&&Vt("archive"),sr="overview",ht?.select(vt,e),ba(e),Zt.play("tick")}function Cl(s){const e=Oi(_i(vt).lane);e.length<2||Ii(e[(e.indexOf(vt)+s+e.length)%e.length],{axis:"row",direction:s})}function ua(s){const e=_i(vt).lane,t=wl(e+s,Fi.length);Ii(fd[t],{axis:"lane",direction:s})}function ba(s){const e=Ut[vt],{lane:t}=_i(vt),n=Oi(t);cc.update(e.title,!_t.reduced&&ut==="archive"),de("#selected-clearance").textContent=e.clearance,de("#archive-category").textContent=e.category;const i=s&&"axis"in s?s.direction>0?"up":"down":"auto";hd.update({value:Number(e.id.slice(2)),animated:!_t.reduced&&ut==="archive",direction:i}),od.update({value:n.indexOf(vt)+1,animated:!_t.reduced&&ut==="archive",direction:s&&"axis"in s&&s.axis==="row"?i:"auto"}),de(".count-total").textContent=String(n.length).padStart(2,"0"),ld.update({value:t+1,animated:!_t.reduced&&ut==="archive",direction:s&&"axis"in s&&s.axis==="lane"?i:"auto"}),de("#column-name").textContent=Fi[t],de('[data-action="column-prev"]').disabled=!1,de('[data-action="column-next"]').disabled=!1,document.querySelectorAll("[data-select]").forEach(r=>{r.hidden=!n.includes(Number(r.dataset.select)),r.classList.toggle("selected",Number(r.dataset.select)===vt),r.setAttribute("aria-pressed",String(Number(r.dataset.select)===vt))}),de("#saved-count").textContent=String(xn.size).padStart(2,"0"),ut==="detail"&&gd()}function da(){Li&&(rr(),Vt("detail"),Zt.play("open"),de("#detail-content").focus({preventScroll:!0}))}function RM(){const s=Ut[vt].id;xn.has(s)?xn.delete(s):xn.add(s);try{localStorage.setItem("rhine-saved",JSON.stringify([...xn]))}catch{}ba(),de('[data-action="bookmark"]').focus({preventScroll:!0}),Zt.play("confirm"),vd(xn.has(s)?"档案已加入收藏":"已取消收藏")}function gd(){const s=Ut[vt];de("#object-id").textContent="NO."+String(vt+1).padStart(3,"0"),de("#detail-content").innerHTML=`
  <div class="detail-kicker"><span>FILE ${s.id}</span><span>${s.clearance}</span></div>
  <h2>${s.en}</h2><div class="detail-title-cn">${s.title}<span>${s.category}</span></div>
  <div class="detail-rule"></div>
  <dl class="metadata"><div><dt>DEPARTMENT / 科室</dt><dd>${s.department}</dd></div><div><dt>COLLECTION / 编目范围</dt><dd>${s.date}</dd></div><div><dt>RELATED / 相关人物</dt><dd>${s.lead}</dd></div><div><dt>STATUS / 状态</dt><dd><i></i>${s.clearance==="RESTRICTED"?"目录访问":"已归档 · 可读取"}</dd></div></dl>
  <div class="detail-tabs" role="tablist"><button class="active" role="tab" aria-selected="true" data-tab="overview">01 <span>概述</span></button><button role="tab" aria-selected="false" data-tab="notes">02 <span>研究记录</span></button><button role="tab" aria-selected="false" data-tab="history">03 <span>访问日志</span></button></div>
  <div id="tab-panel" class="tab-panel" role="tabpanel">${_d()}</div>
  <div class="detail-actions"><button class="solid-button" data-action="bookmark">${xn.has(s.id)?"− REMOVE FROM SAVED":"＋ SAVE ARCHIVE"}<span>${xn.has(s.id)?"已收藏":"收藏档案"}</span></button><a class="export-button" href="/archives/RHINE-LAB-${s.id}.txt" download="RHINE-LAB-${s.id}.txt" aria-label="导出 ${s.id} 档案">EXPORT <span>↓</span></a></div>
  <div class="detail-footnote"><a href="${s.source}" target="_blank" rel="noopener">设定参考 ↗</a><span>${String(vt+1).padStart(3,"0")} / ${String(Ut.length).padStart(3,"0")}</span></div>`,de("#detail-content").setAttribute("tabindex","-1"),hc(sr,!1)}function _d(){return`<div class="panel-label">ABSTRACT / 摘要</div><p>${Ut[vt].abstract}</p>`}function hc(s,e=!0){sr=s,document.querySelectorAll("[data-tab]").forEach(n=>{const i=n.dataset.tab===s;n.classList.toggle("active",i),n.setAttribute("aria-selected",String(i)),n.setAttribute("tabindex",i?"0":"-1")});const t=Ut[vt];de("#tab-panel").innerHTML=s==="overview"?_d():s==="notes"?`<div class="panel-label">RESEARCH NOTES / 研究记录</div><ol class="research-notes">${t.findings.map((n,i)=>`<li><span>${String(i+1).padStart(2,"0")}</span>${n}</li>`).join("")}</ol>`:`<div class="panel-label">ACCESS LOG / 本次访问</div>${dd.filter(n=>n.id===t.id).slice(0,4).map(n=>`<div class="log-row"><span>${n.time}</span><span>JOYCE MOORE</span><b>READ AUTHORIZED</b></div>`).join("")}<p class="log-note">本次会话已通过身份验证。档案内容以当前终端可访问范围展示。</p>`,e&&Zt.play("tick")}function vd(s){clearTimeout(au),de("#toast").textContent=s,de("#toast").classList.add("visible"),au=setTimeout(()=>de("#toast").classList.remove("visible"),2600)}function xd(s){Li&&(rd=document.activeElement,At=s,ps="",ms="全部档案",Zt.play("open"),Md())}function rr(){At&&(At=null,de("#modal-root").innerHTML="",rd?.focus({preventScroll:!0}))}function Md(){At&&(de("#modal-root").innerHTML=`<div class="modal-backdrop"><section class="terminal-modal ${At==="settings"?"settings-modal":""}" role="dialog" aria-modal="true" aria-label="${At==="settings"?"系统设置":At==="saved"?"收藏档案":"档案检索"}"><div class="modal-top"><span>RHINE LAB / ${At==="settings"?"SYSTEM PREFERENCES":"ARCHIVE DIRECTORY"}</span><button data-action="close-modal" aria-label="关闭窗口">CLOSE <span>×</span></button></div>${At==="settings"?CM():`<h2>${At==="saved"?"SAVED ARCHIVES":"ARCHIVE INDEX"}<small>${At==="saved"?"收藏档案":"内部档案检索"}</small></h2><div class="search-field"><span>⌕</span><input id="archive-search" type="search" autocomplete="off" placeholder="输入档案编号、名称或科室" aria-label="检索档案"/><span class="key">ESC</span></div><div class="category-filters">${Kx.map((s,e)=>`<button data-filter="${s}" class="${e===0?"active":""}">${s}</button>`).join("")}</div><div class="result-header"><span>FILE / 档案</span><span>DEPARTMENT / 科室</span><span>ACCESS</span></div><div id="search-results" class="search-results"></div><div class="modal-bottom"><span id="result-count"></span><span>INTERNAL DATABASE <i>●</i> CONNECTED</span></div>`}</section></div>`,At!=="settings"?(uc(),requestAnimationFrame(()=>de("#archive-search").focus())):requestAnimationFrame(()=>de('[data-action="close-modal"]').focus()),de("#modal-root").querySelector(".modal-backdrop")?.addEventListener("click",s=>{s.target===s.currentTarget&&rr()}))}function uc(){const s=Ut.map((e,t)=>({r:e,i:t})).filter(({r:e})=>(At!=="saved"||xn.has(e.id))&&(ms==="全部档案"||e.category===ms)&&`${e.id} ${e.title} ${e.en} ${e.department} ${e.lead}`.toLowerCase().includes(ps.toLowerCase()));de("#search-results").innerHTML=s.length?s.map(({r:e,i:t})=>`<button class="result-row" data-result="${t}"><span class="result-name"><b>${e.id}</b><span>${e.title}<small>${e.en}</small></span>${xn.has(e.id)?"<i>＋</i>":""}</span><span>${e.department}</span><span>${e.clearance==="RESTRICTED"?"CATALOG ONLY":"AUTHORIZED"} <i>↗</i></span></button>`).join(""):`<div class="empty-results"><span>∅</span><strong>${At==="saved"&&!ps?"尚无收藏档案":"没有匹配的档案"}</strong><p>${At==="saved"&&!ps?"读取档案时，选择 SAVE ARCHIVE 将其保存在此处。":"尝试其他名称、档案编号，或切换科室分类。"}</p><button data-action="reset-search">${At==="saved"?"查看全部档案 →":"重置检索 →"}</button></div>`,de("#result-count").textContent=`${String(s.length).padStart(2,"0")} RECORDS FOUND`}function CM(){return`<h2>SYSTEM SETTINGS<small>终端偏好设置</small></h2><p class="settings-intro">JOYCE MOORE <span>·</span> SESSION AUTHORIZED</p><div class="settings-list"><label><div><strong>INTERFACE SOUND</strong><span>界面反馈音</span></div><input type="checkbox" data-pref="sound" ${_t.sound?"checked":""}/><i class="toggle"></i></label><label><div><strong>REDUCED MOTION</strong><span>减少镜头移动和过渡动效</span></div><input type="checkbox" data-pref="reduced" ${_t.reduced?"checked":""}/><i class="toggle"></i></label><label><div><strong>HIGH QUALITY RENDERING</strong><span>环境遮蔽与高分辨率渲染</span></div><input type="checkbox" data-pref="quality" ${_t.quality?"checked":""}/><i class="toggle"></i></label></div><div class="settings-shortcuts"><span>KEYBOARD CONTROLS</span><p><kbd>←</kbd><kbd>→</kbd> 切列 <kbd>↑</kbd><kbd>↓</kbd> 选档 <kbd>ENTER</kbd> 读取 <kbd>/</kbd> 检索 <kbd>ESC</kbd> 返回</p></div><div class="settings-bottom"><button data-action="fullscreen">FULLSCREEN <span>↗</span></button><button data-action="restart">REINITIALIZE SYSTEM <span>↻</span></button></div><div class="modal-bottom"><span>ANALYSIS OS / 1.0 · 使用 MiSans 字体（小米） <a href="/fonts/MiSans-license.pdf" target="_blank" rel="noopener">字体许可</a></span><span>POWERED BY RHINE LAB</span></div>`}document.addEventListener("input",s=>{s.target.id==="archive-search"&&(ps=s.target.value,uc())});document.addEventListener("change",s=>{const e=s.target;e.dataset.pref&&(_t[e.dataset.pref]=e.checked,pd(),Zt.play("confirm"))});document.addEventListener("click",s=>{const e=s.target.closest("button");if(!e)return;if(e.dataset.select){Ii(Number(e.dataset.select));return}if(e.dataset.result){Ii(Number(e.dataset.result)),da();return}if(e.dataset.filter){ms=e.dataset.filter,document.querySelectorAll("[data-filter]").forEach(n=>n.classList.toggle("active",n.dataset.filter===ms)),uc();return}if(e.dataset.tab){hc(e.dataset.tab);return}const t=e.dataset.action;t==="skip"&&(Vt("archive"),Zt.play("confirm")),t==="prev"&&Cl(-1),t==="next"&&Cl(1),t==="column-prev"&&ua(-1),t==="column-next"&&ua(1),t==="open"&&da(),t==="model-viewer"&&ut==="detail"&&(ws??=new yM(de("#stage"),()=>Zt.play("back")),ws.open(Ut[vt].id,Ut[vt].title,()=>ht.createAssemblyModel(),_t.reduced),Zt.play("open")),t==="back"&&(Vt("archive"),Zt.play("back")),(t==="search"||t==="saved"||t==="settings")&&xd(t),t==="close-modal"&&rr(),t==="bookmark"&&RM(),t==="reset-search"&&(At="search",ps="",ms="全部档案",Md()),(t==="replay"||t==="restart")&&(rr(),fs=performance.now()/1e3-1.76,oc=null,ha="",Vt(_t.reduced?"archive":"boot"),ht.select(0),vt=0,ba(),Zt.play("back")),t==="fullscreen"&&(document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen().catch(()=>vd("请使用浏览器的全屏快捷键 F11")))});document.addEventListener("keydown",s=>{if(ws?.isOpen)return;const e=s.target instanceof HTMLInputElement;if(s.key==="Escape"){At?rr():(ut==="detail"||ut==="boot"&&Li)&&Vt("archive");return}if(At&&s.key==="Tab"){const t=[...de("#modal-root").querySelectorAll('button,input,[tabindex="0"]')],n=t[0],i=t.at(-1);s.shiftKey&&document.activeElement===n?(s.preventDefault(),i?.focus()):!s.shiftKey&&document.activeElement===i&&(s.preventDefault(),n?.focus());return}if(!(e||At||!Li)){if(s.target.dataset.tab&&["ArrowLeft","ArrowRight"].includes(s.key)){s.preventDefault();const t=["overview","notes","history"];hc(t[(t.indexOf(sr)+(s.key==="ArrowRight"?1:2))%3]),de(`[data-tab="${sr}"]`).focus();return}s.key==="/"&&(s.preventDefault(),ut==="boot"&&Vt("archive"),xd("search")),s.key==="ArrowLeft"&&ut!=="boot"&&(s.preventDefault(),ua(-1)),s.key==="ArrowRight"&&ut!=="boot"&&(s.preventDefault(),ua(1)),["ArrowUp","ArrowDown"].includes(s.key)&&ut!=="boot"&&(s.preventDefault(),Cl(s.key==="ArrowUp"?-1:1)),s.key==="Enter"&&(document.activeElement===document.body||document.activeElement?.id==="detail-content"||["prev","next","column-prev","column-next"].includes(document.activeElement?.dataset.action??"")||document.activeElement?.dataset.select)&&(s.preventDefault(),ut==="boot"?Vt("archive"):ut==="archive"&&da())}});const Cn=s=>(s=Math.max(0,Math.min(1,s)),s*s*(3-2*s));function PM(s){const e=sd.update(s);let t=e.step,n=e.step==="auth"?s<9.52?"身份信息确认：JOYCE MOORE":s<11.84?"请求已接收":"开始处理":e.step==="scan"?"权限验证通过":e.step==="welcome"?"欢迎访问莱茵生命内部资料档案":"";s>=22&&(t="array",n="选择档案"),s>=25.68&&(t="select",n="编号：X-001"),s>=28.3&&(t="inspect",n=s>=29.3?"保密级别：商业区":"编号：X-001"),t!==ha&&(de("#stage").dataset.boot=t,ha=t,["auth","scan","select"].includes(t)&&Zt.play(t==="scan"?"confirm":"tick")),de("#cinema-caption").textContent=n,de(".file-title").firstChild.textContent=t==="array"?"SELECTING FILES...".slice(0,Math.max(0,Math.floor((s-21.94)*18))):"FILE NUMBER: ",de("#stage").style.setProperty("--entry-opacity",String(Cn((s-21.9)/.13))),de(".callout-rule").style.transform=`scaleX(${Cn((s-22.08)/.9)})`;const i=Cn((s-22)/.4),r=Cn((s-26)/1.8),a=.55*Cn((s-27.3)/1.65)+.45*Cn((s-29)/5);if(s>=35){Vt("detail");return}return{reveal:i,lift:r,zoom:a,time:s}}let ou=0,To=0,Ao=performance.now(),Pl=0;function yd(s){const e=s/1e3,t=ut==="boot"&&Li?PM(oc??e-fs):void 0;ws?.isOpen||ht?.update(e,t),ws?.update(e),ht&&ut==="detail"&&(de("#detail-content").style.opacity=String(ht.detailVisibility),de("#detail-content").style.transform=`translateY(${(1-ht.detailVisibility)*18}px)`,de("#detail-content").inert=ht.detailVisibility<.1);const n=t?.time??-1,i=Cn((n-29.15)/.35)*(1-Cn((n-31.4)/.5));if(de("#inspection-marks").style.opacity=String(i),de("#inspection-text").style.opacity=String(i),de("#inspection-text strong").style.opacity=String(Cn((n-30.25)/.5)),ht&&i>0){const r=[[-2.05,3.04],[2.05,3.04],[-2.05,.35],[2.05,.35]].map(([h,u])=>ht.projectCard(h,u));de("#inspection-corners").innerHTML=r.map(([h,u])=>`<rect x="${h-4}" y="${u-4}" width="8" height="8"/>`).join("");const a=ht.projectCard(-1.88,.5),o=ht.projectCard(-.36,1.7),l=ht.projectCard(.36,2.04),c=ht.projectCard(1.9,2.9);de("#inspection-lines").setAttribute("d",`M${a}L${o}M${l}L${c}`)}if(ht&&n>32.5){const[r,a]=ht.projectCard(.15,1.9);de("#inspection-marks").style.opacity=String(Cn((n-32.5)/.5)),de("#inspection-corners").innerHTML="",de("#inspection-lines").setAttribute("d",`M${r-2},${a}h4M${r},${a-2}v4`)}Math.floor(e)!==ou&&(ou=Math.floor(e),de("#clock").textContent=new Date().toLocaleTimeString("en-GB")),To++,s-Ao>1e3&&(Pl=To*1e3/(s-Ao),Ao=s,To=0,de("#three-scene").dataset.fps=String(Math.round(Pl)),de("#three-scene").dataset.renderStats=JSON.stringify(ht?.getStats())),requestAnimationFrame(yd)}async function DM(){try{ht=new aM(de("#three-scene")),await Promise.all([ht.load(),document.fonts.load("400 20px MiSans"),document.fonts.load("700 20px MiSans")]),ht.select(vt),ht.onSelect=(e,t)=>{ut!=="boot"&&Ii(e,t?{cell:t}:void 0)},ht.onHover=e=>{const t=de("#hover-label");if(e===null){t.hidden=!0;return}ud.update({value:Number(Ut[e].id.slice(2)),animated:!t.hidden&&!_t.reduced&&ut==="archive"}),de("#hover-title").textContent=" / "+Ut[e].title,t.hidden=!1},pd(),Li=!0,fs=performance.now()/1e3,Vt("boot"),Ii(0),de("#loading").classList.add("loaded"),setTimeout(()=>de("#loading").remove(),600);const s=new URLSearchParams(location.search);s.get("scene")==="archive"&&Vt("archive"),s.get("scene")==="detail"&&Vt("detail"),fs-=s.has("time")?Number(s.get("time")):1.76,s.has("time")||(fs+=.6),_t.reduced&&!s.has("time")&&Vt("archive"),requestAnimationFrame(yd)}catch(s){console.error(s),de("#loading").innerHTML='<div class="error-state"><strong>CONNECTION INTERRUPTED</strong><p>三维档案资源未能载入。请确认浏览器已启用硬件加速，然后重新连接。</p><button onclick="location.reload()">RECONNECT →</button></div>'}}ba();DM();Object.assign(window,{rhine:{seek:s=>{Vt("boot"),fs=performance.now()/1e3-s,ha=""},archive:()=>Vt("archive"),detail:()=>da(),select:s=>Ii(s),stats:()=>({...ht?.getStats(),fps:Math.round(Pl),mode:ut,selected:Ut[vt].id,saved:[...xn]})}});
