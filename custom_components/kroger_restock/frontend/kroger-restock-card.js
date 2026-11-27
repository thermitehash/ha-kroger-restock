var q=globalThis,H=q.ShadowRoot&&(q.ShadyCSS===void 0||q.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,K=Symbol(),le=new WeakMap,k=class{constructor(t,e,s){if(this._$cssResult$=!0,s!==K)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o,e=this.t;if(H&&t===void 0){let s=e!==void 0&&e.length===1;s&&(t=le.get(e)),t===void 0&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),s&&le.set(e,t))}return t}toString(){return this.cssText}},de=r=>new k(typeof r=="string"?r:r+"",void 0,K),x=(r,...t)=>{let e=r.length===1?r[0]:t.reduce((s,i,n)=>s+(o=>{if(o._$cssResult$===!0)return o.cssText;if(typeof o=="number")return o;throw Error("Value passed to 'css' function must be a 'css' function result: "+o+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+r[n+1],r[0]);return new k(e,r,K)},he=(r,t)=>{if(H)r.adoptedStyleSheets=t.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let e of t){let s=document.createElement("style"),i=q.litNonce;i!==void 0&&s.setAttribute("nonce",i),s.textContent=e.cssText,r.appendChild(s)}},F=H?r=>r:r=>r instanceof CSSStyleSheet?(t=>{let e="";for(let s of t.cssRules)e+=s.cssText;return de(e)})(r):r;var{is:Le,defineProperty:Oe,getOwnPropertyDescriptor:Ie,getOwnPropertyNames:Ne,getOwnPropertySymbols:Ue,getPrototypeOf:De}=Object,B=globalThis,ue=B.trustedTypes,qe=ue?ue.emptyScript:"",He=B.reactiveElementPolyfillSupport,R=(r,t)=>r,Q={toAttribute(r,t){switch(t){case Boolean:r=r?qe:null;break;case Object:case Array:r=r==null?r:JSON.stringify(r)}return r},fromAttribute(r,t){let e=r;switch(t){case Boolean:e=r!==null;break;case Number:e=r===null?null:Number(r);break;case Object:case Array:try{e=JSON.parse(r)}catch{e=null}}return e}},me=(r,t)=>!Le(r,t),pe={attribute:!0,type:String,converter:Q,reflect:!1,useDefault:!1,hasChanged:me};Symbol.metadata??=Symbol("metadata"),B.litPropertyMetadata??=new WeakMap;var v=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=pe){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(t,e),!e.noAccessor){let s=Symbol(),i=this.getPropertyDescriptor(t,s,e);i!==void 0&&Oe(this.prototype,t,i)}}static getPropertyDescriptor(t,e,s){let{get:i,set:n}=Ie(this.prototype,t)??{get(){return this[e]},set(o){this[e]=o}};return{get:i,set(o){let h=i?.call(this);n?.call(this,o),this.requestUpdate(t,h,s)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??pe}static _$Ei(){if(this.hasOwnProperty(R("elementProperties")))return;let t=De(this);t.finalize(),t.l!==void 0&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(R("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(R("properties"))){let e=this.properties,s=[...Ne(e),...Ue(e)];for(let i of s)this.createProperty(i,e[i])}let t=this[Symbol.metadata];if(t!==null){let e=litPropertyMetadata.get(t);if(e!==void 0)for(let[s,i]of e)this.elementProperties.set(s,i)}this._$Eh=new Map;for(let[e,s]of this.elementProperties){let i=this._$Eu(e,s);i!==void 0&&this._$Eh.set(i,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){let e=[];if(Array.isArray(t)){let s=new Set(t.flat(1/0).reverse());for(let i of s)e.unshift(F(i))}else t!==void 0&&e.push(F(t));return e}static _$Eu(t,e){let s=e.attribute;return s===!1?void 0:typeof s=="string"?s:typeof t=="string"?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),this.renderRoot!==void 0&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){let t=new Map,e=this.constructor.elementProperties;for(let s of e.keys())this.hasOwnProperty(s)&&(t.set(s,this[s]),delete this[s]);t.size>0&&(this._$Ep=t)}createRenderRoot(){let t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return he(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,e,s){this._$AK(t,s)}_$ET(t,e){let s=this.constructor.elementProperties.get(t),i=this.constructor._$Eu(t,s);if(i!==void 0&&s.reflect===!0){let n=(s.converter?.toAttribute!==void 0?s.converter:Q).toAttribute(e,s.type);this._$Em=t,n==null?this.removeAttribute(i):this.setAttribute(i,n),this._$Em=null}}_$AK(t,e){let s=this.constructor,i=s._$Eh.get(t);if(i!==void 0&&this._$Em!==i){let n=s.getPropertyOptions(i),o=typeof n.converter=="function"?{fromAttribute:n.converter}:n.converter?.fromAttribute!==void 0?n.converter:Q;this._$Em=i;let h=o.fromAttribute(e,n.type);this[i]=h??this._$Ej?.get(i)??h,this._$Em=null}}requestUpdate(t,e,s,i=!1,n){if(t!==void 0){let o=this.constructor;if(i===!1&&(n=this[t]),s??=o.getPropertyOptions(t),!((s.hasChanged??me)(n,e)||s.useDefault&&s.reflect&&n===this._$Ej?.get(t)&&!this.hasAttribute(o._$Eu(t,s))))return;this.C(t,e,s)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(t,e,{useDefault:s,reflect:i,wrapped:n},o){s&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,o??e??this[t]),n!==!0||o!==void 0)||(this._$AL.has(t)||(this.hasUpdated||s||(e=void 0),this._$AL.set(t,e)),i===!0&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let t=this.scheduleUpdate();return t!=null&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[i,n]of this._$Ep)this[i]=n;this._$Ep=void 0}let s=this.constructor.elementProperties;if(s.size>0)for(let[i,n]of s){let{wrapped:o}=n,h=this[i];o!==!0||this._$AL.has(i)||h===void 0||this.C(i,void 0,n,h)}}let t=!1,e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach(s=>s.hostUpdate?.()),this.update(e)):this._$EM()}catch(s){throw t=!1,this._$EM(),s}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(t){}firstUpdated(t){}};v.elementStyles=[],v.shadowRootOptions={mode:"open"},v[R("elementProperties")]=new Map,v[R("finalized")]=new Map,He?.({ReactiveElement:v}),(B.reactiveElementVersions??=[]).push("2.1.2");var te=globalThis,fe=r=>r,z=te.trustedTypes,ge=z?z.createPolicy("lit-html",{createHTML:r=>r}):void 0,$e="$lit$",y=`lit$${Math.random().toFixed(9).slice(2)}$`,we="?"+y,Be=`<${we}>`,w=document,T=()=>w.createComment(""),M=r=>r===null||typeof r!="object"&&typeof r!="function",se=Array.isArray,ze=r=>se(r)||typeof r?.[Symbol.iterator]=="function",J=`[ 	
\f\r]`,P=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,ve=/-->/g,be=/>/g,_=RegExp(`>|${J}(?:([^\\s"'>=/]+)(${J}*=${J}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),ye=/'/g,xe=/"/g,Se=/^(?:script|style|textarea|title)$/i,ie=r=>(t,...e)=>({_$litType$:r,strings:t,values:e}),c=ie(1),at=ie(2),ct=ie(3),S=Symbol.for("lit-noChange"),a=Symbol.for("lit-nothing"),_e=new WeakMap,$=w.createTreeWalker(w,129);function Ae(r,t){if(!se(r)||!r.hasOwnProperty("raw"))throw Error("invalid template strings array");return ge!==void 0?ge.createHTML(t):t}var je=(r,t)=>{let e=r.length-1,s=[],i,n=t===2?"<svg>":t===3?"<math>":"",o=P;for(let h=0;h<e;h++){let l=r[h],u,p,d=-1,g=0;for(;g<l.length&&(o.lastIndex=g,p=o.exec(l),p!==null);)g=o.lastIndex,o===P?p[1]==="!--"?o=ve:p[1]!==void 0?o=be:p[2]!==void 0?(Se.test(p[2])&&(i=RegExp("</"+p[2],"g")),o=_):p[3]!==void 0&&(o=_):o===_?p[0]===">"?(o=i??P,d=-1):p[1]===void 0?d=-2:(d=o.lastIndex-p[2].length,u=p[1],o=p[3]===void 0?_:p[3]==='"'?xe:ye):o===xe||o===ye?o=_:o===ve||o===be?o=P:(o=_,i=void 0);let b=o===_&&r[h+1].startsWith("/>")?" ":"";n+=o===P?l+Be:d>=0?(s.push(u),l.slice(0,d)+$e+l.slice(d)+y+b):l+y+(d===-2?h:b)}return[Ae(r,n+(r[e]||"<?>")+(t===2?"</svg>":t===3?"</math>":"")),s]},L=class r{constructor({strings:t,_$litType$:e},s){let i;this.parts=[];let n=0,o=0,h=t.length-1,l=this.parts,[u,p]=je(t,e);if(this.el=r.createElement(u,s),$.currentNode=this.el.content,e===2||e===3){let d=this.el.content.firstChild;d.replaceWith(...d.childNodes)}for(;(i=$.nextNode())!==null&&l.length<h;){if(i.nodeType===1){if(i.hasAttributes())for(let d of i.getAttributeNames())if(d.endsWith($e)){let g=p[o++],b=i.getAttribute(d).split(y),D=/([.?@])?(.*)/.exec(g);l.push({type:1,index:n,name:D[2],strings:b,ctor:D[1]==="."?G:D[1]==="?"?X:D[1]==="@"?Z:C}),i.removeAttribute(d)}else d.startsWith(y)&&(l.push({type:6,index:n}),i.removeAttribute(d));if(Se.test(i.tagName)){let d=i.textContent.split(y),g=d.length-1;if(g>0){i.textContent=z?z.emptyScript:"";for(let b=0;b<g;b++)i.append(d[b],T()),$.nextNode(),l.push({type:2,index:++n});i.append(d[g],T())}}}else if(i.nodeType===8)if(i.data===we)l.push({type:2,index:n});else{let d=-1;for(;(d=i.data.indexOf(y,d+1))!==-1;)l.push({type:7,index:n}),d+=y.length-1}n++}}static createElement(t,e){let s=w.createElement("template");return s.innerHTML=t,s}};function A(r,t,e=r,s){if(t===S)return t;let i=s!==void 0?e._$Co?.[s]:e._$Cl,n=M(t)?void 0:t._$litDirective$;return i?.constructor!==n&&(i?._$AO?.(!1),n===void 0?i=void 0:(i=new n(r),i._$AT(r,e,s)),s!==void 0?(e._$Co??=[])[s]=i:e._$Cl=i),i!==void 0&&(t=A(r,i._$AS(r,t.values),i,s)),t}var Y=class{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){let{el:{content:e},parts:s}=this._$AD,i=(t?.creationScope??w).importNode(e,!0);$.currentNode=i;let n=$.nextNode(),o=0,h=0,l=s[0];for(;l!==void 0;){if(o===l.index){let u;l.type===2?u=new O(n,n.nextSibling,this,t):l.type===1?u=new l.ctor(n,l.name,l.strings,this,t):l.type===6&&(u=new ee(n,this,t)),this._$AV.push(u),l=s[++h]}o!==l?.index&&(n=$.nextNode(),o++)}return $.currentNode=w,i}p(t){let e=0;for(let s of this._$AV)s!==void 0&&(s.strings!==void 0?(s._$AI(t,s,e),e+=s.strings.length-2):s._$AI(t[e])),e++}},O=class r{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,s,i){this.type=2,this._$AH=a,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=s,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode,e=this._$AM;return e!==void 0&&t?.nodeType===11&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=A(this,t,e),M(t)?t===a||t==null||t===""?(this._$AH!==a&&this._$AR(),this._$AH=a):t!==this._$AH&&t!==S&&this._(t):t._$litType$!==void 0?this.$(t):t.nodeType!==void 0?this.T(t):ze(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==a&&M(this._$AH)?this._$AA.nextSibling.data=t:this.T(w.createTextNode(t)),this._$AH=t}$(t){let{values:e,_$litType$:s}=t,i=typeof s=="number"?this._$AC(t):(s.el===void 0&&(s.el=L.createElement(Ae(s.h,s.h[0]),this.options)),s);if(this._$AH?._$AD===i)this._$AH.p(e);else{let n=new Y(i,this),o=n.u(this.options);n.p(e),this.T(o),this._$AH=n}}_$AC(t){let e=_e.get(t.strings);return e===void 0&&_e.set(t.strings,e=new L(t)),e}k(t){se(this._$AH)||(this._$AH=[],this._$AR());let e=this._$AH,s,i=0;for(let n of t)i===e.length?e.push(s=new r(this.O(T()),this.O(T()),this,this.options)):s=e[i],s._$AI(n),i++;i<e.length&&(this._$AR(s&&s._$AB.nextSibling,i),e.length=i)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t!==this._$AB;){let s=fe(t).nextSibling;fe(t).remove(),t=s}}setConnected(t){this._$AM===void 0&&(this._$Cv=t,this._$AP?.(t))}},C=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,s,i,n){this.type=1,this._$AH=a,this._$AN=void 0,this.element=t,this.name=e,this._$AM=i,this.options=n,s.length>2||s[0]!==""||s[1]!==""?(this._$AH=Array(s.length-1).fill(new String),this.strings=s):this._$AH=a}_$AI(t,e=this,s,i){let n=this.strings,o=!1;if(n===void 0)t=A(this,t,e,0),o=!M(t)||t!==this._$AH&&t!==S,o&&(this._$AH=t);else{let h=t,l,u;for(t=n[0],l=0;l<n.length-1;l++)u=A(this,h[s+l],e,l),u===S&&(u=this._$AH[l]),o||=!M(u)||u!==this._$AH[l],u===a?t=a:t!==a&&(t+=(u??"")+n[l+1]),this._$AH[l]=u}o&&!i&&this.j(t)}j(t){t===a?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}},G=class extends C{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===a?void 0:t}},X=class extends C{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==a)}},Z=class extends C{constructor(t,e,s,i,n){super(t,e,s,i,n),this.type=5}_$AI(t,e=this){if((t=A(this,t,e,0)??a)===S)return;let s=this._$AH,i=t===a&&s!==a||t.capture!==s.capture||t.once!==s.once||t.passive!==s.passive,n=t!==a&&(s===a||i);i&&this.element.removeEventListener(this.name,this,s),n&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}},ee=class{constructor(t,e,s){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=s}get _$AU(){return this._$AM._$AU}_$AI(t){A(this,t)}};var Ve=te.litHtmlPolyfillSupport;Ve?.(L,O),(te.litHtmlVersions??=[]).push("3.3.3");var Ce=(r,t,e)=>{let s=e?.renderBefore??t,i=s._$litPart$;if(i===void 0){let n=e?.renderBefore??null;s._$litPart$=i=new O(t.insertBefore(T(),n),n,void 0,e??{})}return i._$AI(r),i};var re=globalThis,m=class extends v{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){let e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=Ce(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return S}};m._$litElement$=!0,m.finalized=!0,re.litElementHydrateSupport?.({LitElement:m});var We=re.litElementPolyfillSupport;We?.({LitElement:m});(re.litElementVersions??=[]).push("4.2.2");var ne=["ean_13","ean_8","upc_a","upc_e"];async function Ee(r){let t=globalThis.BarcodeDetector;if(t?.getSupportedFormats)try{let s=await t.getSupportedFormats();if(ne.every(i=>s.includes(i)))return new t({formats:[...ne]})}catch{}let e=await import("./chunks/ponyfill-H3WXH5GU.js");return e.prepareZXingModule({overrides:{locateFile:(s,i)=>s.endsWith(".wasm")?r:i+s}}),new e.BarcodeDetector({formats:[...ne]})}var Ke=200,Fe=3e3,I=class extends m{constructor(){super(...arguments);this.wasmUrl="";this.error="";this.cameras=[];this.cameraId="";this.busy=!1;this.lastCode="";this.lastAt=0}connectedCallback(){super.connectedCallback(),this.start()}disconnectedCallback(){super.disconnectedCallback(),this.stop()}async start(e){if(this.stopStream(),this.error="",!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){this.error="The camera needs a secure (https) connection, for example Home Assistant Cloud. Type the barcode instead.";return}try{this.stream=await navigator.mediaDevices.getUserMedia({audio:!1,video:e?{deviceId:{exact:e}}:{facingMode:{ideal:"environment"},width:{ideal:1280}}})}catch(n){this.error=`Can't open the camera: ${n.message||n}. Check the camera permission.`;return}await this.updateComplete;let s=this.renderRoot.querySelector("video");if(!s)return;s.srcObject=this.stream,await s.play().catch(()=>{});let i=this.stream.getVideoTracks()[0];this.cameraId=i?.getSettings().deviceId??"";try{let n=await navigator.mediaDevices.enumerateDevices();this.cameras=n.filter(o=>o.kind==="videoinput")}catch{this.cameras=[]}try{this.detector??=await Ee(this.wasmUrl)}catch(n){this.error=`Barcode reader failed to load: ${n.message||n}`;return}this.timer=window.setInterval(()=>{this.tick(s)},Ke)}async tick(e){if(!(this.busy||!this.detector||e.readyState<2)){this.busy=!0;try{let i=(await this.detector.detect(e))[0]?.rawValue,n=Date.now();i&&(i!==this.lastCode||n-this.lastAt>Fe)&&(this.lastCode=i,this.lastAt=n,navigator.vibrate?.(60),this.onCode?.(i))}catch{}finally{this.busy=!1}}}stopStream(){this.timer!==void 0&&window.clearInterval(this.timer),this.timer=void 0,this.stream?.getTracks().forEach(e=>e.stop()),this.stream=void 0}stop(){this.stopStream()}close(){this.stop(),this.onClose?.()}render(){return c`
      <video playsinline muted></video>
      ${this.error?a:c`<div class="frame"></div>`}
      <div class="top">
        <button @click=${this.close} aria-label="Close scanner">✕ Done</button>
        ${this.cameras.length>1?c`<select
              aria-label="Camera"
              .value=${this.cameraId}
              @change=${e=>this.start(e.target.value)}
            >
              ${this.cameras.map((e,s)=>c`<option value=${e.deviceId} ?selected=${e.deviceId===this.cameraId}>
                    ${e.label||`Camera ${s+1}`}
                  </option>`)}
            </select>`:a}
      </div>
      <div class="bottom">
        ${this.error?c`<div class="msg error" role="alert">${this.error}</div>`:this.message?c`<div class="msg ${this.message.tone}" role="status">${this.message.text}</div>`:c`<div class="hint">Aim at the barcode. Keep scanning; tap Done when finished.</div>`}
      </div>
    `}};I.properties={message:{attribute:!1},error:{state:!0},cameras:{state:!0},cameraId:{state:!0}},I.styles=x`
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
  `;customElements.get("kroger-restock-camera")||customElements.define("kroger-restock-camera",I);var oe=5,Qe=4e3;function Je(r){return typeof r=="number"?`$${r.toFixed(2)}`:""}var N=class extends m{constructor(){super(...arguments);this.results=[];this.query="";this.busy=!1;this.error="";this.searched=!1;this.confirmRemove=!1;this.keyHandler=e=>{e.key==="Escape"&&this.close()}}connectedCallback(){super.connectedCallback(),this.results=(this.item.candidates??[]).slice(0,oe),this.query=this.item.status==="unmatched"&&/^\d+$/.test(this.item.name)?"":this.item.name,document.addEventListener("keydown",this.keyHandler)}disconnectedCallback(){super.disconnectedCallback(),document.removeEventListener("keydown",this.keyHandler),window.clearTimeout(this.confirmTimer)}firstUpdated(){this.results.length||this.renderRoot.querySelector("input")?.focus()}close(){this.remove(),this.onClose?.()}async search(){let e=this.query.trim();if(!(!e||this.busy)){this.busy=!0,this.error="";try{let s=await this.callService("search_products",{query:e,limit:oe});this.results=(s.products??[]).slice(0,oe),this.searched=!0}catch(s){this.error=s?.message||String(s)}finally{this.busy=!1}}}async pick(e){if(!this.busy){this.busy=!0,this.error="";try{let s=await this.callService("resolve_item",{item_id:this.item.item_id,product_id:e.product_id});this.onDone?.(s,"resolve"),this.close()}catch(s){this.error=s?.message||String(s)}finally{this.busy=!1}}}async removeItem(){if(!this.confirmRemove){this.confirmRemove=!0,window.clearTimeout(this.confirmTimer),this.confirmTimer=window.setTimeout(()=>this.confirmRemove=!1,Qe);return}this.busy=!0;try{let e=await this.callService("set_quantity",{item_id:this.item.item_id,quantity:0});this.onDone?.(e,"remove"),this.close()}catch(e){this.error=e?.message||String(e)}finally{this.busy=!1}}render(){let e=this.item;return c`
      <div class="backdrop" @click=${this.close}></div>
      <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="title">
        <header>
          <div>
            <h2 id="title">Pick the right product</h2>
            <div class="for">
              for “${e.name}”${e.quantity>1?c` ×${e.quantity}`:a}
            </div>
          </div>
          <button class="close" @click=${this.close} aria-label="Close">✕</button>
        </header>
        <form
          class="search"
          @submit=${s=>{s.preventDefault(),this.search()}}
        >
          <input
            type="search"
            enterkeyhint="search"
            autocomplete="off"
            .value=${this.query}
            @input=${s=>this.query=s.target.value}
            placeholder="Search by name, e.g. 2% milk"
            aria-label="Search products"
          />
          <button type="submit" ?disabled=${!this.query.trim()||this.busy}>Search</button>
        </form>
        ${this.error?c`<div class="error" role="alert">${this.error}</div>`:a}
        <div class="list" aria-busy=${this.busy?"true":"false"}>
          ${this.results.length?this.results.map(s=>this.renderMatch(s)):c`<div class="empty">
                ${this.searched?"No products found. Try other words.":e.status==="unmatched"?"This barcode isn't in the Kroger catalog. Search by name to pick the product.":"No matches yet. Search by name."}
              </div>`}
        </div>
        <footer>
          <button class="remove ${this.confirmRemove?"confirm":""}" @click=${this.removeItem} ?disabled=${this.busy}>
            ${this.confirmRemove?"Tap again to remove":"Remove item"}
          </button>
          <button class="cancel" @click=${this.close}>Cancel</button>
        </footer>
      </div>
    `}renderMatch(e){let s=[e.brand&&!e.name.toLowerCase().includes(e.brand.toLowerCase())?e.brand:"",e.size].filter(Boolean).join(" \xB7 "),i=[Je(e.price),e.aisle].filter(Boolean).join(" \xB7 ");return c`<button class="match" @click=${()=>this.pick(e)} ?disabled=${this.busy}>
      ${e.image_url?c`<img src=${e.image_url} alt="" loading="lazy" referrerpolicy="no-referrer" />`:c`<span class="noimg" aria-hidden="true"></span>`}
      <span class="text">
        <span class="name">${e.name}</span>
        ${s?c`<span class="details">${s}</span>`:a}
        <span class="meta">
          ${i}${e.in_stock===!1?c`<span class="oos">Out of stock</span>`:a}
        </span>
      </span>
      <span class="pick">Pick</span>
    </button>`}};N.properties={item:{attribute:!1},results:{state:!0},query:{state:!0},busy:{state:!0},error:{state:!0},searched:{state:!0},confirmRemove:{state:!0}},N.styles=x`
    :host {
      position: fixed;
      inset: 0;
      z-index: 9000;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: var(--ha-font-family-body, Roboto, sans-serif);
      color: var(--primary-text-color, #212121);
    }
    .backdrop {
      position: absolute;
      inset: 0;
      background: rgba(0, 0, 0, 0.45);
    }
    .sheet {
      position: relative;
      width: min(520px, 100% - 32px);
      max-height: min(720px, 100% - 48px);
      display: flex;
      flex-direction: column;
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-dialog-border-radius, 24px);
      box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3);
      overflow: hidden;
    }
    @media (max-width: 600px) {
      :host {
        align-items: flex-end;
      }
      .sheet {
        width: 100%;
        max-height: 88%;
        border-radius: 20px 20px 0 0;
        padding-bottom: env(safe-area-inset-bottom);
      }
    }
    header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
      padding: 18px 16px 8px 20px;
    }
    h2 {
      margin: 0;
      font-size: 20px;
      font-weight: 500;
    }
    .for {
      color: var(--secondary-text-color, #727272);
      font-size: 14px;
      margin-top: 2px;
      overflow-wrap: anywhere;
    }
    button {
      font: inherit;
      color: inherit;
      cursor: pointer;
    }
    .close {
      border: none;
      background: transparent;
      font-size: 18px;
      width: 40px;
      height: 40px;
      border-radius: 20px;
      color: var(--secondary-text-color, #727272);
    }
    form.search {
      display: flex;
      gap: 8px;
      padding: 4px 16px 8px;
    }
    form.search input {
      flex: 1;
      min-width: 0;
      min-height: 42px;
      padding: 0 14px;
      font-size: 16px;
      color: inherit;
      background: var(--secondary-background-color, #f5f5f5);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      border-radius: 21px;
      outline: none;
    }
    form.search button {
      border: none;
      border-radius: 21px;
      padding: 0 16px;
      background: var(--primary-color, #03a9f4);
      color: var(--text-primary-color, #fff);
      font-weight: 500;
    }
    form.search button:disabled {
      opacity: 0.5;
    }
    .error {
      margin: 0 16px 8px;
      padding: 8px 12px;
      border-radius: 8px;
      border-left: 4px solid var(--error-color, #db4437);
      background: var(--secondary-background-color, #f5f5f5);
      font-size: 14px;
    }
    .list {
      overflow-y: auto;
      padding: 0 8px;
      flex: 1;
    }
    .list[aria-busy="true"] {
      opacity: 0.6;
    }
    .empty {
      padding: 20px 12px;
      color: var(--secondary-text-color, #727272);
    }
    button.match {
      display: flex;
      align-items: center;
      gap: 12px;
      width: 100%;
      text-align: left;
      padding: 10px 8px;
      border: none;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      background: transparent;
      border-radius: 0;
    }
    button.match:last-child {
      border-bottom: none;
    }
    button.match:hover,
    button.match:focus-visible {
      background: var(--secondary-background-color, #f5f5f5);
      outline: none;
    }
    img,
    .noimg {
      flex: none;
      width: 52px;
      height: 52px;
      border-radius: 8px;
      object-fit: contain;
      background: #fff;
    }
    .noimg {
      background: var(--secondary-background-color, #f5f5f5);
    }
    .text {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 1px;
    }
    .name {
      font-size: 15px;
      line-height: 1.3;
    }
    .details,
    .meta {
      font-size: 13px;
      color: var(--secondary-text-color, #727272);
    }
    .oos {
      margin-left: 6px;
      color: var(--warning-color, #ffa600);
      font-weight: 500;
    }
    .pick {
      flex: none;
      color: var(--primary-color, #03a9f4);
      font-weight: 500;
      padding: 0 6px;
    }
    footer {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 16px 14px;
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }
    footer button {
      border: none;
      background: transparent;
      min-height: 40px;
      padding: 0 12px;
      border-radius: 20px;
      font-weight: 500;
    }
    .remove {
      color: var(--error-color, #db4437);
    }
    .remove.confirm {
      background: var(--error-color, #db4437);
      color: #fff;
    }
    .cancel {
      color: var(--primary-color, #03a9f4);
    }
  `;customElements.get("kroger-restock-fix")||customElements.define("kroger-restock-fix",N);function ae(r){return r?.auth?.external}function ke(r,t=window){let e=ae(r);return!!(e?.config?.hasBarCodeScanner&&typeof e.fireMessage=="function"&&typeof t.externalBus=="function")}var j=class{constructor(t,e=window){this.bus=t;this.win=e}get open(){return this.wrapper!==void 0}start(t){this.open&&this.restore(),this.options=t,this.original=this.win.externalBus;let e=this.original;this.wrapper=s=>{try{this.inspect(typeof s=="string"?JSON.parse(s):s)}catch{}return e(s)},this.win.externalBus=this.wrapper,this.bus.fireMessage({type:"bar_code/scan",payload:{title:t.title,description:t.description,...t.alternativeLabel?{alternative_option_label:t.alternativeLabel}:{}}})}notify(t){this.open&&this.bus.fireMessage({type:"bar_code/notify",payload:{message:t}})}close(){this.open&&(this.bus.fireMessage({type:"bar_code/close"}),this.restore())}inspect(t){if(!(!t||t.type!=="command")){if(t.command==="bar_code/scan_result"){let e=t.payload??{};typeof e.rawValue=="string"&&this.options?.onCode(e.rawValue,String(e.format??"unknown"))}else if(t.command==="bar_code/aborted"){let e=String(t.payload?.reason??"canceled"),s=this.options;this.restore(),s?.onClose(e)}}}restore(){this.wrapper&&this.win.externalBus===this.wrapper&&this.original&&(this.win.externalBus=this.original),this.wrapper=void 0,this.original=void 0,this.options=void 0}};function V(r){let t=r.name??"";switch(r.result){case"in_cart":{let e=[t,r.size].filter(Boolean).join(" ");return r.aisle&&(e+=` \xB7 ${r.aisle}`),r.already_in_cart?{text:`\u2713 In cart (recorded): ${e}`,tone:"success"}:r.pushed===!1?{text:`\u2713 On list, cart push pending: ${e}`,tone:"warning"}:{text:`\u2713 In cart: ${e}`,tone:"success"}}case"waiting":return{text:`\u23F3 Waiting on stock: ${t}`,tone:"info"};case"unmatched":return{text:`? Unknown code ${r.upc||t} (added for you to fix)`,tone:"warning"};case"needs_review":return{text:`\u2022 Needs review: ${t}`,tone:"warning"};case"duplicate":return r.debounced?{text:"Already scanned",tone:"info"}:{text:`\u21BA Already on list (qty ${r.quantity}): ${t}`,tone:"info"};case"ignored":return{text:`\u2298 ${r.message||"Ignored"}`,tone:"warning"};default:return{text:r.error||"Done",tone:r.error?"error":"info"}}}function ce(r){return r.warning?{text:`\u26A0 ${r.warning}`,tone:"warning"}:r.result==="removed"?{text:`Removed: ${r.name}`,tone:"info"}:r.error?{text:`Quantity ${r.quantity} saved; cart push pending: ${r.name}`,tone:"warning"}:{text:`${r.name}: \xD7${r.quantity}`,tone:"success"}}function Re(r){let t=r.trim();if(!t)return null;if(/https?:\/\//i.test(t))return{kind:"url",value:t};let e=t.replace(/[\s-]/g,"");return/^\d{4,14}$/.test(e)?{kind:"upc",value:e}:{kind:"name",value:t}}function Pe(r,t=Date.now()){if(!r)return"";let e=Date.parse(r);if(Number.isNaN(e))return"";let s=Math.max(0,Math.round((t-e)/1e3));if(s<45)return"just now";let i=Math.round(s/60);if(i<60)return`${i} min ago`;let n=Math.round(i/60);return n<24?`${n} h ago`:`${Math.round(n/24)} d ago`}var f="kroger-restock-card",Ye="kroger_restock",Ge=4e3,Xe=3e3;function Ze(){try{let r=new URL(import.meta.url);return{base:r.href.slice(0,r.href.lastIndexOf("/")+1).split("?")[0],version:r.searchParams.get("v")??""}}catch{return{base:"/kroger_restock_frontend/",version:""}}}function Te(r){window.dispatchEvent(new CustomEvent("haptic",{detail:r}))}var E=class extends m{constructor(){super(...arguments);this._busy=!1;this._text="";this._scanning=!1;this.queue=Promise.resolve();this.lastCode="";this.lastCodeAt=0}static getConfigElement(){return document.createElement(`${f}-editor`)}static getStubConfig(e){return{entity:Me(e)??"",rows:10}}setConfig(e){if(!e)throw new Error("Invalid configuration");this._config={rows:10,scanner:"auto",show_input:!0,show_actions:!0,...e}}getCardSize(){return 2+Math.min(this.items.length,this._config?.rows??10)}getGridOptions(){return{columns:12,min_columns:6,rows:"auto"}}connectedCallback(){super.connectedCallback(),this.clock=window.setInterval(()=>this.requestUpdate(),3e4)}disconnectedCallback(){super.disconnectedCallback(),window.clearInterval(this.clock),window.clearTimeout(this.confirmTimer),this.native?.close(),this.closeCamera()}shouldUpdate(e){if(!e.has("hass")||e.size>1)return!0;let s=e.get("hass"),i=this.entityId;return!s||!i||s.states[i]!==this.hass.states[i]}get entityId(){return this._config?.entity||Me(this.hass)}get stateObj(){let e=this.entityId;return e?this.hass?.states?.[e]:void 0}get items(){let e=this.stateObj?.attributes?.items;return Array.isArray(e)?e:[]}get entryId(){return this.stateObj?.attributes?.config_entry_id}get scannerKind(){let e=this._config?.scanner??"auto";if(e==="off")return null;let s=ke(this.hass);return e==="app"?s?"app":null:e==="camera"?"camera":s?"app":"camera"}async callService(e,s){let i={...s};return this.entryId&&(i.config_entry_id=this.entryId),(await this.hass.connection.sendMessagePromise({type:"call_service",domain:Ye,service:e,service_data:i,return_response:!0}))?.response??{}}show(e){this._line=e,Te(e.tone==="success"?"success":e.tone==="error"?"failure":"warning")}showError(e){let s={text:e?.message||String(e),tone:"error"};return this.show(s),s}enqueue(e){let s=this.queue.then(e,e);return this.queue=s.catch(()=>{}),s}async scanCode(e){let s=Date.now();if(!(e===this.lastCode&&s-this.lastCodeAt<Xe))return this.lastCode=e,this.lastCodeAt=s,this.enqueue(async()=>{this._busy=!0;try{let i=V(await this.callService("scan_upc",{upc:e,source:"card"}));return this.show(i),i}catch(i){return this.showError(i)}finally{this._busy=!1}})}async submitText(){let e=this._text,s=Re(e);s&&(this._text="",await this.enqueue(async()=>{this._busy=!0;try{let i;s.kind==="url"?i=await this.callService("scan_upc",{url:s.value,source:"card"}):s.kind==="upc"?i=await this.callService("scan_upc",{upc:s.value,source:"card"}):i=await this.callService("add_item",{name:s.value,source:"card"}),this.show(V(i))}catch(i){this.showError(i),this._text||(this._text=e)}finally{this._busy=!1}}))}startScan(){let e=this.scannerKind;e==="app"?this.startNative():e==="camera"&&this.openCamera()}startNative(){let e=ae(this.hass);e&&(this.native??=new j(e),this._scanning=!0,this.native.start({title:"Scan groceries",description:"Aim at the barcode. Keep scanning; close when you're done.",alternativeLabel:"Type it instead",onCode:s=>{this.scanCode(s).then(i=>{i&&this.native?.notify(i.text)})},onClose:s=>{this._scanning=!1,s==="alternative_options"&&this.updateComplete.then(()=>this.renderRoot.querySelector("input")?.focus())}}))}openCamera(){if(this.camera)return;let{base:e,version:s}=Ze(),i=document.createElement("kroger-restock-camera");i.wasmUrl=`${e}zxing_reader.wasm${s?`?v=${s}`:""}`,i.onCode=n=>{this.scanCode(n).then(o=>{o&&this.camera&&(this.camera.message=o)})},i.onClose=()=>this.closeCamera(),document.body.appendChild(i),this.camera=i,this._scanning=!0}closeCamera(){this.camera?.remove(),this.camera=void 0,this._scanning=!1}async setQuantity(e,s){if(s<1&&this._confirmRemove!==e.item_id){this._confirmRemove=e.item_id,window.clearTimeout(this.confirmTimer),this.confirmTimer=window.setTimeout(()=>this._confirmRemove=void 0,Ge),Te("light");return}this._confirmRemove=void 0,await this.enqueue(async()=>{this._busy=!0;try{this.show(ce(await this.callService("set_quantity",{item_id:e.item_id,quantity:s})))}catch(i){this.showError(i)}finally{this._busy=!1}})}undo(e){return this.setQuantity(e,e.quantity-(e.added??1))}openFix(e){document.querySelector("kroger-restock-fix")?.remove();let s=document.createElement("kroger-restock-fix");s.item=e,s.callService=(i,n)=>this.callService(i,n),s.onDone=(i,n)=>this.show(n==="remove"?ce(i):V(i)),document.body.appendChild(s)}render(){if(!this._config||!this.hass)return a;let e=this._config,s=this.stateObj,i=this.scannerKind,n=this.items.slice(0,e.rows??10);return c`
      <ha-card .header=${e.title||void 0}>
        <div class="controls">
          ${i?c`<button
                class="scan"
                @click=${this.startScan}
                ?disabled=${this._scanning}
                aria-label="Scan a barcode"
              >
                <ha-icon icon="mdi:barcode-scan"></ha-icon><span>Scan</span>
              </button>`:a}
          ${e.shortcut?c`<a
                class="scan secondary"
                href=${`shortcuts://run-shortcut?name=${encodeURIComponent(e.shortcut)}`}
                aria-label="Run the iPhone Shortcut"
                ><ha-icon icon="mdi:apple-ios"></ha-icon><span>Shortcut</span></a
              >`:a}
          ${e.show_input?c`<form
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
              </form>`:a}
        </div>
        ${this._line?c`<div class="line ${this._line.tone}" role="status">${this._line.text}</div>`:a}
        ${s?n.length===0?c`<div class="empty">Nothing scanned yet.</div>`:c`<ul class="rows">
                ${n.map(o=>this.renderRow(o))}
              </ul>`:c`<div class="empty warn">
              Pick the Kroger Restock "Recently scanned" sensor in the card settings.
            </div>`}
      </ha-card>
    `}renderRow(e){let s=this._config.show_actions,i=e.status==="needs_review"||e.status==="unmatched",n=this._confirmRemove===e.item_id,o=[e.name,e.size?`(${e.size})`:""].filter(Boolean).join(" ");return c`<li class="row status-${e.status}">
      <div class="main">
        <div class="name">
          <span>${o}</span>${e.quantity>1?c`<span class="qty">×${e.quantity}</span>`:a}
        </div>
        <div class="sub">
          ${e.status_text??e.status}${e.at?c` · ${Pe(e.at)}`:a}
        </div>
      </div>
      ${s?c`<div class="actions">
            ${e.can_undo?c`<button class="text" @click=${()=>this.undo(e)} ?disabled=${this._busy}>
                  Undo +${e.added??1}
                </button>`:a}
            ${i?c`<button class="text" @click=${()=>this.openFix(e)}>Fix</button>`:a}
            <button
              class="icon ${n?"confirm":""}"
              @click=${()=>this.setQuantity(e,e.quantity-1)}
              ?disabled=${this._busy}
              aria-label=${e.quantity>1?`One less ${e.name}`:`Remove ${e.name}`}
            >
              ${n?c`<span>Remove?</span>`:c`<ha-icon icon=${e.quantity>1?"mdi:minus":"mdi:delete-outline"}></ha-icon>`}
            </button>
            <button
              class="icon"
              @click=${()=>this.setQuantity(e,e.quantity+1)}
              ?disabled=${this._busy||e.quantity>=99}
              aria-label=${`One more ${e.name}`}
            >
              <ha-icon icon="mdi:plus"></ha-icon>
            </button>
          </div>`:a}
    </li>`}};E.properties={hass:{attribute:!1},_config:{state:!0},_line:{state:!0},_busy:{state:!0},_text:{state:!0},_confirmRemove:{state:!0},_scanning:{state:!0}},E.styles=x`
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
  `;function Me(r){if(r?.states)return Object.keys(r.states).find(t=>{let e=r.states[t]?.attributes;return t.startsWith("sensor.")&&Array.isArray(e?.items)&&"todo_entity_id"in(e??{})})}var et=[{name:"entity",selector:{entity:{domain:"sensor",integration:"kroger_restock"}}},{name:"title",selector:{text:{}}},{name:"rows",selector:{number:{min:1,max:25,mode:"box"}}},{name:"scanner",selector:{select:{mode:"dropdown",options:[{value:"auto",label:"Automatic (app scanner, else camera)"},{value:"app",label:"Home Assistant app scanner only"},{value:"camera",label:"Browser camera only"},{value:"off",label:"No scan button"}]}}},{name:"show_input",selector:{boolean:{}}},{name:"show_actions",selector:{boolean:{}}},{name:"shortcut",selector:{text:{}}}],tt={entity:"Recently scanned sensor",title:"Title (optional)",rows:"Items to show",scanner:"Scan button",show_input:"Show the text field (barcode, name or link)",show_actions:"Show \u2212 / + / undo buttons",shortcut:"iPhone Shortcut to run (optional, name)"},st={shortcut:"Adds a button that runs this Shortcut, e.g. Grocery scan. Leave empty for none."},U=class extends m{setConfig(t){this._config=t}render(){if(!this.hass||!this._config)return a;let t={rows:10,scanner:"auto",show_input:!0,show_actions:!0,...this._config};return c`<ha-form
      .hass=${this.hass}
      .data=${t}
      .schema=${et}
      .computeLabel=${e=>tt[e.name]??e.name}
      .computeHelper=${e=>st[e.name]}
      @value-changed=${this.changed}
    ></ha-form>`}changed(t){t.stopPropagation();let e={...t.detail.value,type:`custom:${f}`};for(let s of["title","shortcut"])e[s]||delete e[s];this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:e},bubbles:!0,composed:!0}))}};U.properties={hass:{attribute:!1},_config:{state:!0}};customElements.get(f)||customElements.define(f,E);customElements.get(`${f}-editor`)||customElements.define(`${f}-editor`,U);var W=window;W.customCards=W.customCards||[];W.customCards.some(r=>r.type===f)||W.customCards.push({type:f,name:"Kroger Restock scanner",description:"Scan or type groceries onto the Kroger Restock list and fix recent additions.",preview:!0,documentationURL:"https://github.com/thrivestorm2/ha-kroger-restock#restock-scanner-card"});
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
