var D=globalThis,H=D.ShadowRoot&&(D.ShadyCSS===void 0||D.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,V=Symbol(),ot=new WeakMap,E=class{constructor(t,e,s){if(this._$cssResult$=!0,s!==V)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o,e=this.t;if(H&&t===void 0){let s=e!==void 0&&e.length===1;s&&(t=ot.get(e)),t===void 0&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),s&&ot.set(e,t))}return t}toString(){return this.cssText}},at=n=>new E(typeof n=="string"?n:n+"",void 0,V),k=(n,...t)=>{let e=n.length===1?n[0]:t.reduce((s,i,r)=>s+(o=>{if(o._$cssResult$===!0)return o.cssText;if(typeof o=="number")return o;throw Error("Value passed to 'css' function must be a 'css' function result: "+o+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+n[r+1],n[0]);return new E(e,n,V)},ct=(n,t)=>{if(H)n.adoptedStyleSheets=t.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let e of t){let s=document.createElement("style"),i=D.litNonce;i!==void 0&&s.setAttribute("nonce",i),s.textContent=e.cssText,n.appendChild(s)}},W=H?n=>n:n=>n instanceof CSSStyleSheet?(t=>{let e="";for(let s of t.cssRules)e+=s.cssText;return at(e)})(n):n;var{is:Mt,defineProperty:Tt,getOwnPropertyDescriptor:Ot,getOwnPropertyNames:Lt,getOwnPropertySymbols:Ut,getPrototypeOf:It}=Object,B=globalThis,lt=B.trustedTypes,Nt=lt?lt.emptyScript:"",Dt=B.reactiveElementPolyfillSupport,R=(n,t)=>n,K={toAttribute(n,t){switch(t){case Boolean:n=n?Nt:null;break;case Object:case Array:n=n==null?n:JSON.stringify(n)}return n},fromAttribute(n,t){let e=n;switch(t){case Boolean:e=n!==null;break;case Number:e=n===null?null:Number(n);break;case Object:case Array:try{e=JSON.parse(n)}catch{e=null}}return e}},ht=(n,t)=>!Mt(n,t),dt={attribute:!0,type:String,converter:K,reflect:!1,useDefault:!1,hasChanged:ht};Symbol.metadata??=Symbol("metadata"),B.litPropertyMetadata??=new WeakMap;var v=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=dt){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(t,e),!e.noAccessor){let s=Symbol(),i=this.getPropertyDescriptor(t,s,e);i!==void 0&&Tt(this.prototype,t,i)}}static getPropertyDescriptor(t,e,s){let{get:i,set:r}=Ot(this.prototype,t)??{get(){return this[e]},set(o){this[e]=o}};return{get:i,set(o){let h=i?.call(this);r?.call(this,o),this.requestUpdate(t,h,s)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??dt}static _$Ei(){if(this.hasOwnProperty(R("elementProperties")))return;let t=It(this);t.finalize(),t.l!==void 0&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(R("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(R("properties"))){let e=this.properties,s=[...Lt(e),...Ut(e)];for(let i of s)this.createProperty(i,e[i])}let t=this[Symbol.metadata];if(t!==null){let e=litPropertyMetadata.get(t);if(e!==void 0)for(let[s,i]of e)this.elementProperties.set(s,i)}this._$Eh=new Map;for(let[e,s]of this.elementProperties){let i=this._$Eu(e,s);i!==void 0&&this._$Eh.set(i,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){let e=[];if(Array.isArray(t)){let s=new Set(t.flat(1/0).reverse());for(let i of s)e.unshift(W(i))}else t!==void 0&&e.push(W(t));return e}static _$Eu(t,e){let s=e.attribute;return s===!1?void 0:typeof s=="string"?s:typeof t=="string"?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),this.renderRoot!==void 0&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){let t=new Map,e=this.constructor.elementProperties;for(let s of e.keys())this.hasOwnProperty(s)&&(t.set(s,this[s]),delete this[s]);t.size>0&&(this._$Ep=t)}createRenderRoot(){let t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return ct(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,e,s){this._$AK(t,s)}_$ET(t,e){let s=this.constructor.elementProperties.get(t),i=this.constructor._$Eu(t,s);if(i!==void 0&&s.reflect===!0){let r=(s.converter?.toAttribute!==void 0?s.converter:K).toAttribute(e,s.type);this._$Em=t,r==null?this.removeAttribute(i):this.setAttribute(i,r),this._$Em=null}}_$AK(t,e){let s=this.constructor,i=s._$Eh.get(t);if(i!==void 0&&this._$Em!==i){let r=s.getPropertyOptions(i),o=typeof r.converter=="function"?{fromAttribute:r.converter}:r.converter?.fromAttribute!==void 0?r.converter:K;this._$Em=i;let h=o.fromAttribute(e,r.type);this[i]=h??this._$Ej?.get(i)??h,this._$Em=null}}requestUpdate(t,e,s,i=!1,r){if(t!==void 0){let o=this.constructor;if(i===!1&&(r=this[t]),s??=o.getPropertyOptions(t),!((s.hasChanged??ht)(r,e)||s.useDefault&&s.reflect&&r===this._$Ej?.get(t)&&!this.hasAttribute(o._$Eu(t,s))))return;this.C(t,e,s)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(t,e,{useDefault:s,reflect:i,wrapped:r},o){s&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,o??e??this[t]),r!==!0||o!==void 0)||(this._$AL.has(t)||(this.hasUpdated||s||(e=void 0),this._$AL.set(t,e)),i===!0&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let t=this.scheduleUpdate();return t!=null&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[i,r]of this._$Ep)this[i]=r;this._$Ep=void 0}let s=this.constructor.elementProperties;if(s.size>0)for(let[i,r]of s){let{wrapped:o}=r,h=this[i];o!==!0||this._$AL.has(i)||h===void 0||this.C(i,void 0,r,h)}}let t=!1,e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach(s=>s.hostUpdate?.()),this.update(e)):this._$EM()}catch(s){throw t=!1,this._$EM(),s}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(t){}firstUpdated(t){}};v.elementStyles=[],v.shadowRootOptions={mode:"open"},v[R("elementProperties")]=new Map,v[R("finalized")]=new Map,Dt?.({ReactiveElement:v}),(B.reactiveElementVersions??=[]).push("2.1.2");var X=globalThis,ut=n=>n,q=X.trustedTypes,pt=q?q.createPolicy("lit-html",{createHTML:n=>n}):void 0,_t="$lit$",_=`lit$${Math.random().toFixed(9).slice(2)}$`,bt="?"+_,Ht=`<${bt}>`,w=document,M=()=>w.createComment(""),T=n=>n===null||typeof n!="object"&&typeof n!="function",tt=Array.isArray,Bt=n=>tt(n)||typeof n?.[Symbol.iterator]=="function",F=`[ 	
\f\r]`,P=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,mt=/-->/g,ft=/>/g,b=RegExp(`>|${F}(?:([^\\s"'>=/]+)(${F}*=${F}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),gt=/'/g,vt=/"/g,$t=/^(?:script|style|textarea|title)$/i,et=n=>(t,...e)=>({_$litType$:n,strings:t,values:e}),l=et(1),ie=et(2),ne=et(3),x=Symbol.for("lit-noChange"),c=Symbol.for("lit-nothing"),yt=new WeakMap,$=w.createTreeWalker(w,129);function wt(n,t){if(!tt(n)||!n.hasOwnProperty("raw"))throw Error("invalid template strings array");return pt!==void 0?pt.createHTML(t):t}var qt=(n,t)=>{let e=n.length-1,s=[],i,r=t===2?"<svg>":t===3?"<math>":"",o=P;for(let h=0;h<e;h++){let a=n[h],u,p,d=-1,g=0;for(;g<a.length&&(o.lastIndex=g,p=o.exec(a),p!==null);)g=o.lastIndex,o===P?p[1]==="!--"?o=mt:p[1]!==void 0?o=ft:p[2]!==void 0?($t.test(p[2])&&(i=RegExp("</"+p[2],"g")),o=b):p[3]!==void 0&&(o=b):o===b?p[0]===">"?(o=i??P,d=-1):p[1]===void 0?d=-2:(d=o.lastIndex-p[2].length,u=p[1],o=p[3]===void 0?b:p[3]==='"'?vt:gt):o===vt||o===gt?o=b:o===mt||o===ft?o=P:(o=b,i=void 0);let y=o===b&&n[h+1].startsWith("/>")?" ":"";r+=o===P?a+Ht:d>=0?(s.push(u),a.slice(0,d)+_t+a.slice(d)+_+y):a+_+(d===-2?h:y)}return[wt(n,r+(n[e]||"<?>")+(t===2?"</svg>":t===3?"</math>":"")),s]},O=class n{constructor({strings:t,_$litType$:e},s){let i;this.parts=[];let r=0,o=0,h=t.length-1,a=this.parts,[u,p]=qt(t,e);if(this.el=n.createElement(u,s),$.currentNode=this.el.content,e===2||e===3){let d=this.el.content.firstChild;d.replaceWith(...d.childNodes)}for(;(i=$.nextNode())!==null&&a.length<h;){if(i.nodeType===1){if(i.hasAttributes())for(let d of i.getAttributeNames())if(d.endsWith(_t)){let g=p[o++],y=i.getAttribute(d).split(_),N=/([.?@])?(.*)/.exec(g);a.push({type:1,index:r,name:N[2],strings:y,ctor:N[1]==="."?J:N[1]==="?"?Y:N[1]==="@"?G:S}),i.removeAttribute(d)}else d.startsWith(_)&&(a.push({type:6,index:r}),i.removeAttribute(d));if($t.test(i.tagName)){let d=i.textContent.split(_),g=d.length-1;if(g>0){i.textContent=q?q.emptyScript:"";for(let y=0;y<g;y++)i.append(d[y],M()),$.nextNode(),a.push({type:2,index:++r});i.append(d[g],M())}}}else if(i.nodeType===8)if(i.data===bt)a.push({type:2,index:r});else{let d=-1;for(;(d=i.data.indexOf(_,d+1))!==-1;)a.push({type:7,index:r}),d+=_.length-1}r++}}static createElement(t,e){let s=w.createElement("template");return s.innerHTML=t,s}};function A(n,t,e=n,s){if(t===x)return t;let i=s!==void 0?e._$Co?.[s]:e._$Cl,r=T(t)?void 0:t._$litDirective$;return i?.constructor!==r&&(i?._$AO?.(!1),r===void 0?i=void 0:(i=new r(n),i._$AT(n,e,s)),s!==void 0?(e._$Co??=[])[s]=i:e._$Cl=i),i!==void 0&&(t=A(n,i._$AS(n,t.values),i,s)),t}var Q=class{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){let{el:{content:e},parts:s}=this._$AD,i=(t?.creationScope??w).importNode(e,!0);$.currentNode=i;let r=$.nextNode(),o=0,h=0,a=s[0];for(;a!==void 0;){if(o===a.index){let u;a.type===2?u=new L(r,r.nextSibling,this,t):a.type===1?u=new a.ctor(r,a.name,a.strings,this,t):a.type===6&&(u=new Z(r,this,t)),this._$AV.push(u),a=s[++h]}o!==a?.index&&(r=$.nextNode(),o++)}return $.currentNode=w,i}p(t){let e=0;for(let s of this._$AV)s!==void 0&&(s.strings!==void 0?(s._$AI(t,s,e),e+=s.strings.length-2):s._$AI(t[e])),e++}},L=class n{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,s,i){this.type=2,this._$AH=c,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=s,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode,e=this._$AM;return e!==void 0&&t?.nodeType===11&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=A(this,t,e),T(t)?t===c||t==null||t===""?(this._$AH!==c&&this._$AR(),this._$AH=c):t!==this._$AH&&t!==x&&this._(t):t._$litType$!==void 0?this.$(t):t.nodeType!==void 0?this.T(t):Bt(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==c&&T(this._$AH)?this._$AA.nextSibling.data=t:this.T(w.createTextNode(t)),this._$AH=t}$(t){let{values:e,_$litType$:s}=t,i=typeof s=="number"?this._$AC(t):(s.el===void 0&&(s.el=O.createElement(wt(s.h,s.h[0]),this.options)),s);if(this._$AH?._$AD===i)this._$AH.p(e);else{let r=new Q(i,this),o=r.u(this.options);r.p(e),this.T(o),this._$AH=r}}_$AC(t){let e=yt.get(t.strings);return e===void 0&&yt.set(t.strings,e=new O(t)),e}k(t){tt(this._$AH)||(this._$AH=[],this._$AR());let e=this._$AH,s,i=0;for(let r of t)i===e.length?e.push(s=new n(this.O(M()),this.O(M()),this,this.options)):s=e[i],s._$AI(r),i++;i<e.length&&(this._$AR(s&&s._$AB.nextSibling,i),e.length=i)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t!==this._$AB;){let s=ut(t).nextSibling;ut(t).remove(),t=s}}setConnected(t){this._$AM===void 0&&(this._$Cv=t,this._$AP?.(t))}},S=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,s,i,r){this.type=1,this._$AH=c,this._$AN=void 0,this.element=t,this.name=e,this._$AM=i,this.options=r,s.length>2||s[0]!==""||s[1]!==""?(this._$AH=Array(s.length-1).fill(new String),this.strings=s):this._$AH=c}_$AI(t,e=this,s,i){let r=this.strings,o=!1;if(r===void 0)t=A(this,t,e,0),o=!T(t)||t!==this._$AH&&t!==x,o&&(this._$AH=t);else{let h=t,a,u;for(t=r[0],a=0;a<r.length-1;a++)u=A(this,h[s+a],e,a),u===x&&(u=this._$AH[a]),o||=!T(u)||u!==this._$AH[a],u===c?t=c:t!==c&&(t+=(u??"")+r[a+1]),this._$AH[a]=u}o&&!i&&this.j(t)}j(t){t===c?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}},J=class extends S{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===c?void 0:t}},Y=class extends S{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==c)}},G=class extends S{constructor(t,e,s,i,r){super(t,e,s,i,r),this.type=5}_$AI(t,e=this){if((t=A(this,t,e,0)??c)===x)return;let s=this._$AH,i=t===c&&s!==c||t.capture!==s.capture||t.once!==s.once||t.passive!==s.passive,r=t!==c&&(s===c||i);i&&this.element.removeEventListener(this.name,this,s),r&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}},Z=class{constructor(t,e,s){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=s}get _$AU(){return this._$AM._$AU}_$AI(t){A(this,t)}};var zt=X.litHtmlPolyfillSupport;zt?.(O,L),(X.litHtmlVersions??=[]).push("3.3.3");var xt=(n,t,e)=>{let s=e?.renderBefore??t,i=s._$litPart$;if(i===void 0){let r=e?.renderBefore??null;s._$litPart$=i=new L(t.insertBefore(M(),r),r,void 0,e??{})}return i._$AI(n),i};var st=globalThis,m=class extends v{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){let e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=xt(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return x}};m._$litElement$=!0,m.finalized=!0,st.litElementHydrateSupport?.({LitElement:m});var jt=st.litElementPolyfillSupport;jt?.({LitElement:m});(st.litElementVersions??=[]).push("4.2.2");var it=["ean_13","ean_8","upc_a","upc_e"];async function At(n){let t=globalThis.BarcodeDetector;if(t?.getSupportedFormats)try{let s=await t.getSupportedFormats();if(it.every(i=>s.includes(i)))return new t({formats:[...it]})}catch{}let e=await import("./chunks/ponyfill-H3WXH5GU.js");return e.prepareZXingModule({overrides:{locateFile:(s,i)=>s.endsWith(".wasm")?n:i+s}}),new e.BarcodeDetector({formats:[...it]})}var Vt=200,Wt=3e3,U=class extends m{constructor(){super(...arguments);this.wasmUrl="";this.error="";this.cameras=[];this.cameraId="";this.busy=!1;this.lastCode="";this.lastAt=0}connectedCallback(){super.connectedCallback(),this.start()}disconnectedCallback(){super.disconnectedCallback(),this.stop()}async start(e){if(this.stopStream(),this.error="",!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){this.error="The camera needs a secure (https) connection, for example Home Assistant Cloud. Type the barcode instead.";return}try{this.stream=await navigator.mediaDevices.getUserMedia({audio:!1,video:e?{deviceId:{exact:e}}:{facingMode:{ideal:"environment"},width:{ideal:1280}}})}catch(r){this.error=`Can't open the camera: ${r.message||r}. Check the camera permission.`;return}await this.updateComplete;let s=this.renderRoot.querySelector("video");if(!s)return;s.srcObject=this.stream,await s.play().catch(()=>{});let i=this.stream.getVideoTracks()[0];this.cameraId=i?.getSettings().deviceId??"";try{let r=await navigator.mediaDevices.enumerateDevices();this.cameras=r.filter(o=>o.kind==="videoinput")}catch{this.cameras=[]}try{this.detector??=await At(this.wasmUrl)}catch(r){this.error=`Barcode reader failed to load: ${r.message||r}`;return}this.timer=window.setInterval(()=>{this.tick(s)},Vt)}async tick(e){if(!(this.busy||!this.detector||e.readyState<2)){this.busy=!0;try{let i=(await this.detector.detect(e))[0]?.rawValue,r=Date.now();i&&(i!==this.lastCode||r-this.lastAt>Wt)&&(this.lastCode=i,this.lastAt=r,navigator.vibrate?.(60),this.onCode?.(i))}catch{}finally{this.busy=!1}}}stopStream(){this.timer!==void 0&&window.clearInterval(this.timer),this.timer=void 0,this.stream?.getTracks().forEach(e=>e.stop()),this.stream=void 0}stop(){this.stopStream()}close(){this.stop(),this.onClose?.()}render(){return l`
      <video playsinline muted></video>
      ${this.error?c:l`<div class="frame"></div>`}
      <div class="top">
        <button @click=${this.close} aria-label="Close scanner">✕ Done</button>
        ${this.cameras.length>1?l`<select
              aria-label="Camera"
              .value=${this.cameraId}
              @change=${e=>this.start(e.target.value)}
            >
              ${this.cameras.map((e,s)=>l`<option value=${e.deviceId} ?selected=${e.deviceId===this.cameraId}>
                    ${e.label||`Camera ${s+1}`}
                  </option>`)}
            </select>`:c}
      </div>
      <div class="bottom">
        ${this.error?l`<div class="msg error" role="alert">${this.error}</div>`:this.message?l`<div class="msg ${this.message.tone}" role="status">${this.message.text}</div>`:l`<div class="hint">Aim at the barcode. Keep scanning; tap Done when finished.</div>`}
      </div>
    `}};U.properties={message:{attribute:!1},error:{state:!0},cameras:{state:!0},cameraId:{state:!0}},U.styles=k`
    :host {
      position: fixed;
      inset: 0;
      z-index: 10000;
      background: #000;
      color: #fff;
      display: flex;
      flex-direction: column;
      font-family: var(--ha-font-family-body, Roboto, sans-serif);
    }
    video {
      flex: 1;
      width: 100%;
      min-height: 0;
      object-fit: cover;
    }
    .frame {
      position: absolute;
      left: 10%;
      right: 10%;
      top: 35%;
      height: 22%;
      border: 2px solid rgba(255, 255, 255, 0.85);
      border-radius: 12px;
      pointer-events: none;
      box-shadow: 0 0 0 100vmax rgba(0, 0, 0, 0.35);
    }
    .top,
    .bottom {
      position: absolute;
      left: 0;
      right: 0;
      padding: 12px 16px;
      padding-top: max(12px, env(safe-area-inset-top));
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .top {
      top: 0;
      justify-content: space-between;
    }
    .bottom {
      bottom: 0;
      padding-bottom: max(16px, env(safe-area-inset-bottom));
      flex-direction: column;
      align-items: stretch;
    }
    button,
    select {
      font: inherit;
      color: #fff;
      background: rgba(0, 0, 0, 0.55);
      border: 1px solid rgba(255, 255, 255, 0.5);
      border-radius: 20px;
      padding: 8px 14px;
      min-height: 40px;
    }
    .msg {
      background: rgba(0, 0, 0, 0.7);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 15px;
      line-height: 1.35;
    }
    .msg.success {
      border-left: 4px solid #43a047;
    }
    .msg.info {
      border-left: 4px solid #1e88e5;
    }
    .msg.warning {
      border-left: 4px solid #fb8c00;
    }
    .msg.error {
      border-left: 4px solid #e53935;
    }
    .hint {
      opacity: 0.8;
      font-size: 13px;
      text-align: center;
    }
  `;customElements.get("kroger-restock-camera")||customElements.define("kroger-restock-camera",U);function nt(n){return n?.auth?.external}function St(n,t=window){let e=nt(n);return!!(e?.config?.hasBarCodeScanner&&typeof e.fireMessage=="function"&&typeof t.externalBus=="function")}var z=class{constructor(t,e=window){this.bus=t;this.win=e}get open(){return this.wrapper!==void 0}start(t){this.open&&this.restore(),this.options=t,this.original=this.win.externalBus;let e=this.original;this.wrapper=s=>{try{this.inspect(typeof s=="string"?JSON.parse(s):s)}catch{}return e(s)},this.win.externalBus=this.wrapper,this.bus.fireMessage({type:"bar_code/scan",payload:{title:t.title,description:t.description,...t.alternativeLabel?{alternative_option_label:t.alternativeLabel}:{}}})}notify(t){this.open&&this.bus.fireMessage({type:"bar_code/notify",payload:{message:t}})}close(){this.open&&(this.bus.fireMessage({type:"bar_code/close"}),this.restore())}inspect(t){if(!(!t||t.type!=="command")){if(t.command==="bar_code/scan_result"){let e=t.payload??{};typeof e.rawValue=="string"&&this.options?.onCode(e.rawValue,String(e.format??"unknown"))}else if(t.command==="bar_code/aborted"){let e=String(t.payload?.reason??"canceled"),s=this.options;this.restore(),s?.onClose(e)}}}restore(){this.wrapper&&this.win.externalBus===this.wrapper&&this.original&&(this.win.externalBus=this.original),this.wrapper=void 0,this.original=void 0,this.options=void 0}};function rt(n){let t=n.name??"";switch(n.result){case"in_cart":{let e=[t,n.size].filter(Boolean).join(" ");return n.aisle&&(e+=` \xB7 ${n.aisle}`),n.already_in_cart?{text:`\u2713 In cart (recorded): ${e}`,tone:"success"}:n.pushed===!1?{text:`\u2713 On list, cart push pending: ${e}`,tone:"warning"}:{text:`\u2713 In cart: ${e}`,tone:"success"}}case"waiting":return{text:`\u23F3 Waiting on stock: ${t}`,tone:"info"};case"unmatched":return{text:`? Unknown code ${n.upc||t} (added for you to fix)`,tone:"warning"};case"needs_review":return{text:`\u2022 Needs review: ${t}`,tone:"warning"};case"duplicate":return n.debounced?{text:"Already scanned",tone:"info"}:{text:`\u21BA Already on list (qty ${n.quantity}): ${t}`,tone:"info"};case"ignored":return{text:`\u2298 ${n.message||"Ignored"}`,tone:"warning"};default:return{text:n.error||"Done",tone:n.error?"error":"info"}}}function Ct(n){return n.warning?{text:`\u26A0 ${n.warning}`,tone:"warning"}:n.result==="removed"?{text:`Removed: ${n.name}`,tone:"info"}:n.error?{text:`Quantity ${n.quantity} saved; cart push pending: ${n.name}`,tone:"warning"}:{text:`${n.name}: \xD7${n.quantity}`,tone:"success"}}function Et(n){let t=n.trim();if(!t)return null;if(/https?:\/\//i.test(t))return{kind:"url",value:t};let e=t.replace(/[\s-]/g,"");return/^\d{4,14}$/.test(e)?{kind:"upc",value:e}:{kind:"name",value:t}}function kt(n,t=Date.now()){if(!n)return"";let e=Date.parse(n);if(Number.isNaN(e))return"";let s=Math.max(0,Math.round((t-e)/1e3));if(s<45)return"just now";let i=Math.round(s/60);if(i<60)return`${i} min ago`;let r=Math.round(i/60);return r<24?`${r} h ago`:`${Math.round(r/24)} d ago`}var f="kroger-restock-card",Kt="kroger_restock",Ft=4e3,Qt=3e3;function Jt(){try{let n=new URL(import.meta.url);return{base:n.href.slice(0,n.href.lastIndexOf("/")+1).split("?")[0],version:n.searchParams.get("v")??""}}catch{return{base:"/kroger_restock_frontend/",version:""}}}function Rt(n){window.dispatchEvent(new CustomEvent("haptic",{detail:n}))}var C=class extends m{constructor(){super(...arguments);this._busy=!1;this._text="";this._scanning=!1;this.queue=Promise.resolve();this.lastCode="";this.lastCodeAt=0}static getConfigElement(){return document.createElement(`${f}-editor`)}static getStubConfig(e){return{entity:Pt(e)??"",rows:10}}setConfig(e){if(!e)throw new Error("Invalid configuration");this._config={rows:10,scanner:"auto",show_input:!0,show_actions:!0,...e}}getCardSize(){return 2+Math.min(this.items.length,this._config?.rows??10)}getGridOptions(){return{columns:12,min_columns:6,rows:"auto"}}connectedCallback(){super.connectedCallback(),this.clock=window.setInterval(()=>this.requestUpdate(),3e4)}disconnectedCallback(){super.disconnectedCallback(),window.clearInterval(this.clock),window.clearTimeout(this.confirmTimer),this.native?.close(),this.closeCamera()}shouldUpdate(e){if(!e.has("hass")||e.size>1)return!0;let s=e.get("hass"),i=this.entityId;return!s||!i||s.states[i]!==this.hass.states[i]}get entityId(){return this._config?.entity||Pt(this.hass)}get stateObj(){let e=this.entityId;return e?this.hass?.states?.[e]:void 0}get items(){let e=this.stateObj?.attributes?.items;return Array.isArray(e)?e:[]}get entryId(){return this.stateObj?.attributes?.config_entry_id}get scannerKind(){let e=this._config?.scanner??"auto";if(e==="off")return null;let s=St(this.hass);return e==="app"?s?"app":null:e==="camera"?"camera":s?"app":"camera"}async callService(e,s){let i={...s};return this.entryId&&(i.config_entry_id=this.entryId),(await this.hass.connection.sendMessagePromise({type:"call_service",domain:Kt,service:e,service_data:i,return_response:!0}))?.response??{}}show(e){this._line=e,Rt(e.tone==="success"?"success":e.tone==="error"?"failure":"warning")}showError(e){let s={text:e?.message||String(e),tone:"error"};return this.show(s),s}enqueue(e){let s=this.queue.then(e,e);return this.queue=s.catch(()=>{}),s}async scanCode(e){let s=Date.now();if(!(e===this.lastCode&&s-this.lastCodeAt<Qt))return this.lastCode=e,this.lastCodeAt=s,this.enqueue(async()=>{this._busy=!0;try{let i=rt(await this.callService("scan_upc",{upc:e,source:"card"}));return this.show(i),i}catch(i){return this.showError(i)}finally{this._busy=!1}})}async submitText(){let e=this._text,s=Et(e);s&&(this._text="",await this.enqueue(async()=>{this._busy=!0;try{let i;s.kind==="url"?i=await this.callService("scan_upc",{url:s.value,source:"card"}):s.kind==="upc"?i=await this.callService("scan_upc",{upc:s.value,source:"card"}):i=await this.callService("add_item",{name:s.value,source:"card"}),this.show(rt(i))}catch(i){this.showError(i),this._text||(this._text=e)}finally{this._busy=!1}}))}startScan(){let e=this.scannerKind;e==="app"?this.startNative():e==="camera"&&this.openCamera()}startNative(){let e=nt(this.hass);e&&(this.native??=new z(e),this._scanning=!0,this.native.start({title:"Scan groceries",description:"Aim at the barcode. Keep scanning; close when you're done.",alternativeLabel:"Type it instead",onCode:s=>{this.scanCode(s).then(i=>{i&&this.native?.notify(i.text)})},onClose:s=>{this._scanning=!1,s==="alternative_options"&&this.updateComplete.then(()=>this.renderRoot.querySelector("input")?.focus())}}))}openCamera(){if(this.camera)return;let{base:e,version:s}=Jt(),i=document.createElement("kroger-restock-camera");i.wasmUrl=`${e}zxing_reader.wasm${s?`?v=${s}`:""}`,i.onCode=r=>{this.scanCode(r).then(o=>{o&&this.camera&&(this.camera.message=o)})},i.onClose=()=>this.closeCamera(),document.body.appendChild(i),this.camera=i,this._scanning=!0}closeCamera(){this.camera?.remove(),this.camera=void 0,this._scanning=!1}async setQuantity(e,s){if(s<1&&this._confirmRemove!==e.item_id){this._confirmRemove=e.item_id,window.clearTimeout(this.confirmTimer),this.confirmTimer=window.setTimeout(()=>this._confirmRemove=void 0,Ft),Rt("light");return}this._confirmRemove=void 0,await this.enqueue(async()=>{this._busy=!0;try{this.show(Ct(await this.callService("set_quantity",{item_id:e.item_id,quantity:s})))}catch(i){this.showError(i)}finally{this._busy=!1}})}undo(e){return this.setQuantity(e,e.quantity-(e.added??1))}openList(){let e=this.stateObj?.attributes?.todo_entity_id,s=e?`/todo?entity_id=${encodeURIComponent(e)}`:"/todo";history.pushState(null,"",s),window.dispatchEvent(new CustomEvent("location-changed",{detail:{replace:!1}}))}render(){if(!this._config||!this.hass)return c;let e=this._config,s=this.stateObj,i=this.scannerKind,r=this.items.slice(0,e.rows??10);return l`
      <ha-card .header=${e.title||void 0}>
        <div class="controls">
          ${i?l`<button
                class="scan"
                @click=${this.startScan}
                ?disabled=${this._scanning}
                aria-label="Scan a barcode"
              >
                <ha-icon icon="mdi:barcode-scan"></ha-icon><span>Scan</span>
              </button>`:c}
          ${e.shortcut?l`<a
                class="scan secondary"
                href=${`shortcuts://run-shortcut?name=${encodeURIComponent(e.shortcut)}`}
                aria-label="Run the iPhone Shortcut"
                ><ha-icon icon="mdi:apple-ios"></ha-icon><span>Shortcut</span></a
              >`:c}
          ${e.show_input?l`<form
                class="add"
                @submit=${o=>{o.preventDefault(),this.submitText()}}
              >
                <input
                  type="text"
                  enterkeyhint="send"
                  autocomplete="off"
                  .value=${this._text}
                  @input=${o=>this._text=o.target.value}
                  placeholder="Barcode, name or link"
                  aria-label="Barcode, item name or Kroger link"
                />
                <button type="submit" ?disabled=${!this._text.trim()||this._busy} aria-label="Add">
                  <ha-icon icon="mdi:plus"></ha-icon>
                </button>
              </form>`:c}
        </div>
        ${this._line?l`<div class="line ${this._line.tone}" role="status">${this._line.text}</div>`:c}
        ${s?r.length===0?l`<div class="empty">Nothing scanned yet.</div>`:l`<ul class="rows">
                ${r.map(o=>this.renderRow(o))}
              </ul>`:l`<div class="empty warn">
              Pick the Kroger Restock "Recently scanned" sensor in the card settings.
            </div>`}
      </ha-card>
    `}renderRow(e){let s=this._config.show_actions,i=e.status==="needs_review"||e.status==="unmatched",r=this._confirmRemove===e.item_id,o=[e.name,e.size?`(${e.size})`:""].filter(Boolean).join(" ");return l`<li class="row status-${e.status}">
      <div class="main">
        <div class="name">
          <span>${o}</span>${e.quantity>1?l`<span class="qty">×${e.quantity}</span>`:c}
        </div>
        <div class="sub">
          ${e.status_text??e.status}${e.at?l` · ${kt(e.at)}`:c}
        </div>
      </div>
      ${s?l`<div class="actions">
            ${e.can_undo?l`<button class="text" @click=${()=>this.undo(e)} ?disabled=${this._busy}>
                  Undo +${e.added??1}
                </button>`:c}
            ${i?l`<button class="text" @click=${()=>this.openList()}>Fix</button>`:c}
            <button
              class="icon ${r?"confirm":""}"
              @click=${()=>this.setQuantity(e,e.quantity-1)}
              ?disabled=${this._busy}
              aria-label=${e.quantity>1?`One less ${e.name}`:`Remove ${e.name}`}
            >
              ${r?l`<span>Remove?</span>`:l`<ha-icon icon=${e.quantity>1?"mdi:minus":"mdi:delete-outline"}></ha-icon>`}
            </button>
            <button
              class="icon"
              @click=${()=>this.setQuantity(e,e.quantity+1)}
              ?disabled=${this._busy||e.quantity>=99}
              aria-label=${`One more ${e.name}`}
            >
              <ha-icon icon="mdi:plus"></ha-icon>
            </button>
          </div>`:c}
    </li>`}};C.properties={hass:{attribute:!1},_config:{state:!0},_line:{state:!0},_busy:{state:!0},_text:{state:!0},_confirmRemove:{state:!0},_scanning:{state:!0}},C.styles=k`
    ha-card {
      overflow: hidden;
    }
    .controls {
      display: flex;
      gap: 8px;
      padding: 12px 12px 4px;
      flex-wrap: wrap;
    }
    button,
    input,
    a.scan {
      font: inherit;
      color: inherit;
    }
    .scan {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 44px;
      padding: 0 16px;
      border: none;
      border-radius: 22px;
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
      font-weight: 500;
      cursor: pointer;
      text-decoration: none;
    }
    .scan.secondary {
      background: transparent;
      color: var(--primary-color);
      border: 1px solid var(--primary-color);
    }
    .scan:disabled {
      opacity: 0.6;
    }
    form.add {
      flex: 1 1 200px;
      display: flex;
      min-width: 0;
      border: 1px solid var(--divider-color);
      border-radius: 22px;
      overflow: hidden;
      background: var(--card-background-color);
    }
    form.add input {
      flex: 1;
      min-width: 0;
      border: none;
      background: transparent;
      padding: 0 14px;
      min-height: 42px;
      font-size: 16px; /* no zoom on iOS */
      outline: none;
    }
    form.add button {
      border: none;
      background: transparent;
      color: var(--primary-color);
      width: 44px;
      cursor: pointer;
    }
    form.add button:disabled {
      color: var(--disabled-text-color);
    }
    .line {
      margin: 8px 12px 0;
      padding: 8px 12px;
      border-radius: 8px;
      border-left: 4px solid var(--info-color, #039be5);
      background: var(--secondary-background-color);
      font-size: 14px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .line.success {
      border-left-color: var(--success-color, #43a047);
    }
    .line.warning {
      border-left-color: var(--warning-color, #ffa600);
    }
    .line.error {
      border-left-color: var(--error-color, #db4437);
    }
    .empty {
      padding: 16px 12px 20px;
      color: var(--secondary-text-color);
    }
    .empty.warn {
      color: var(--warning-color, #ffa600);
    }
    ul.rows {
      list-style: none;
      margin: 8px 0 4px;
      padding: 0;
    }
    li.row {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-top: 1px solid var(--divider-color);
    }
    li.row:first-child {
      border-top: none;
    }
    .main {
      flex: 1;
      min-width: 0;
    }
    .name {
      display: flex;
      gap: 6px;
      align-items: baseline;
      font-size: 15px;
      line-height: 1.3;
    }
    .name span:first-child {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .qty {
      flex: none;
      font-weight: 600;
      color: var(--primary-color);
    }
    .sub {
      font-size: 12.5px;
      color: var(--secondary-text-color);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .status-needs_review .sub,
    .status-unmatched .sub,
    .status-check_cart .sub {
      color: var(--warning-color, #ffa600);
    }
    .actions {
      flex: none;
      display: flex;
      align-items: center;
      gap: 2px;
    }
    .actions button {
      border: none;
      background: transparent;
      cursor: pointer;
      min-height: 40px;
      border-radius: 20px;
      color: var(--secondary-text-color);
    }
    .actions button.icon {
      min-width: 40px;
    }
    .actions button.text {
      color: var(--primary-color);
      font-weight: 500;
      padding: 0 8px;
    }
    .actions button.confirm {
      color: var(--error-color, #db4437);
      font-weight: 600;
      padding: 0 8px;
    }
    .actions button:disabled {
      opacity: 0.5;
    }
  `;function Pt(n){if(n?.states)return Object.keys(n.states).find(t=>{let e=n.states[t]?.attributes;return t.startsWith("sensor.")&&Array.isArray(e?.items)&&"todo_entity_id"in(e??{})})}var Yt=[{name:"entity",selector:{entity:{domain:"sensor",integration:"kroger_restock"}}},{name:"title",selector:{text:{}}},{name:"rows",selector:{number:{min:1,max:25,mode:"box"}}},{name:"scanner",selector:{select:{mode:"dropdown",options:[{value:"auto",label:"Automatic (app scanner, else camera)"},{value:"app",label:"Home Assistant app scanner only"},{value:"camera",label:"Browser camera only"},{value:"off",label:"No scan button"}]}}},{name:"show_input",selector:{boolean:{}}},{name:"show_actions",selector:{boolean:{}}},{name:"shortcut",selector:{text:{}}}],Gt={entity:"Recently scanned sensor",title:"Title (optional)",rows:"Items to show",scanner:"Scan button",show_input:"Show the text field (barcode, name or link)",show_actions:"Show \u2212 / + / undo buttons",shortcut:"iPhone Shortcut to run (optional, name)"},Zt={shortcut:"Adds a button that runs this Shortcut, e.g. Grocery scan. Leave empty for none."},I=class extends m{setConfig(t){this._config=t}render(){if(!this.hass||!this._config)return c;let t={rows:10,scanner:"auto",show_input:!0,show_actions:!0,...this._config};return l`<ha-form
      .hass=${this.hass}
      .data=${t}
      .schema=${Yt}
      .computeLabel=${e=>Gt[e.name]??e.name}
      .computeHelper=${e=>Zt[e.name]}
      @value-changed=${this.changed}
    ></ha-form>`}changed(t){t.stopPropagation();let e={...t.detail.value,type:`custom:${f}`};for(let s of["title","shortcut"])e[s]||delete e[s];this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:e},bubbles:!0,composed:!0}))}};I.properties={hass:{attribute:!1},_config:{state:!0}};customElements.get(f)||customElements.define(f,C);customElements.get(`${f}-editor`)||customElements.define(`${f}-editor`,I);var j=window;j.customCards=j.customCards||[];j.customCards.some(n=>n.type===f)||j.customCards.push({type:f,name:"Kroger Restock scanner",description:"Scan or type groceries onto the Kroger Restock list and fix recent additions.",preview:!0,documentationURL:"https://github.com/thrivestorm2/ha-kroger-restock#restock-scanner-card"});
/*! Bundled license information:

@lit/reactive-element/css-tag.js:
  (**
   * @license
   * Copyright 2019 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/reactive-element.js:
lit-html/lit-html.js:
lit-element/lit-element.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/is-server.js:
  (**
   * @license
   * Copyright 2022 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)
*/
