// ============================================================
// TEA DETERMINISTIC ENGINE
// ============================================================
const TEAEngine = {
  calcDepreciation(capexMn, capMT) { return +((capexMn*1e6*0.70/10 + capexMn*1e6*0.30/25) / Math.max(capMT,1)).toFixed(1); },
  calcLabor(hc, costPer, capMT, fx=1280) { return +(hc * costPer * 1e8 / Math.max(capMT,1) / fx).toFixed(1); },
  calcMaintenance(capexMn, capMT, fx=1280) { return +(capexMn * fx * 10000 * 0.0065 / Math.max(capMT,1) / fx).toFixed(1); },
  calcNPV(cfs, r) { return +cfs.reduce((s,cf,t) => s + cf/Math.pow(1+r,t), 0).toFixed(0); },
  calcIRR(cfs, guess=0.1) {
    let rate = guess;
    for(let i=0;i<1000;i++){
      let npv=0, dnpv=0;
      for(let t=0;t<cfs.length;t++){
        const f=Math.pow(1+rate,t); npv += cfs[t]/f;
        if(t>0) dnpv -= t*cfs[t]/Math.pow(1+rate,t+1);
      }
      if(Math.abs(npv)<1e-6) return +(rate*100).toFixed(1);
      if(Math.abs(dnpv)<1e-12) break;
      rate -= npv/dnpv;
      if(rate<-0.99) rate=-0.5; if(rate>10) rate=5;
    }
    return null;
  },
  calcBCRatio(revs, costs, r) {
    const pvB=revs.reduce((s,b,t)=>s+b/Math.pow(1+r,t),0), pvC=costs.reduce((s,c,t)=>s+c/Math.pow(1+r,t),0);
    return pvC>0 ? +(pvB/pvC).toFixed(2) : 0;
  },
  calcPayback(cfs) {
    let cum=0;
    for(let t=0;t<cfs.length;t++){
      cum+=cfs[t];
      if(cum>=0&&t>0){const prev=cum-cfs[t]; return +(t-1+(prev<0?-prev/cfs[t]:0)).toFixed(1);}
    }
    return null;
  },
  analyze(sc, proj) {
    const fx=proj.exchangeRate||1280, cap=sc.capacity||0, capexMn=sc.capex||0;
    const rm=sc.rawMaterial||0, sm=sc.subMaterial||0, st=sc.steam||0, el=sc.electricity||0, co=sc.cooling||0, wa=sc.waste||0;
    const varTotal=+(rm+sm+st+el+co+wa).toFixed(1);
    const labor=this.calcLabor(sc.headcount||60,sc.laborCost||1.2,cap,fx);
    const dep=this.calcDepreciation(capexMn,cap), maint=this.calcMaintenance(capexMn,cap,fx), other=sc.otherFixed||25;
    const fixTotal=+(labor+dep+maint+other).toFixed(1), mfgCost=+(varTotal+fixTotal).toFixed(1);
    const sp=sc.sellingPrice||0, disc=(proj.discountRate||9)/100, tax=(proj.taxRate||22)/100;
    const nYrs=proj.analysisYears||15, constr=proj.constructionYears||2, ramp=[0.5,0.8,1.0];
    const cfs=[],yrs=[],revArr=[],costArr=[];
    for(let y=0;y<constr;y++){cfs.push(-(capexMn*1e6/constr));yrs.push(-constr+y);revArr.push(0);costArr.push(capexMn*1e6/constr);}
    for(let y=1;y<=nYrs;y++){
      const u=y<=ramp.length?ramp[y-1]:1.0, rev=sp*cap*u, opex=mfgCost*cap*u, ebit=rev-opex, tx=Math.max(0,ebit*tax);
      cfs.push(ebit-tx);yrs.push(y);revArr.push(rev);costArr.push(opex);
    }
    return {
      name:sc.name||'',fermParam:sc.fermentation||'',capacityMT:cap,capexMnUsd:capexMn,
      totalInvestKRW:Math.round(capexMn*fx/100),glucosePrice:sc.glucosePrice||0,glucoseUnit:sc.glucoseUnit||0,
      rawMaterial:rm,subMaterial:sm,steam:st,electricity:el,cooling:co,waste:wa,variableTotal:varTotal,
      labor,depreciation:dep,maintenance:maint,otherFixed:other,fixedTotal:fixTotal,manufacturingCost:mfgCost,sellingPrice:sp,
      npv:+(this.calcNPV(cfs,disc)/1e6).toFixed(1),irr:this.calcIRR(cfs),
      bcRatio:this.calcBCRatio(revArr,costArr,disc),payback:this.calcPayback(cfs),
      cashflows:cfs,yearLabels:yrs,
      variableRatio:+(varTotal/Math.max(mfgCost,1)*100).toFixed(1),
      fixedRatio:+(fixTotal/Math.max(mfgCost,1)*100).toFixed(1),
      fermResult:sc._fermResult||null,fermEnabled:!!(sc.fermConfig&&sc.fermConfig.enabled),
    };
  }
};

// ============================================================
// FERMENTATION ENGINE (based on ferm_sys.py / tmp_reactor2.py)
// Calculates from solution usage -> fermenter sizing -> utilities -> CAPEX/OPEX
// ============================================================
const FermEngine = {
  K: 1.4,
  R_AIR: 0.287,
  DT_COOL: 5,
  STAGE: 2,
  LANG: 3.14285714285,
  CE: 806.7,

  calcBatchTime(fc){
    return (fc.fermTime||48)+(fc.sipTime||2)+(fc.cipTime||2)+(fc.transferTime||2);
  },

  calcRawMaterialCost(fc, capacity_MT, opHrs){
    if(!fc.solutions||!fc.solutions.length||capacity_MT<=0)return{total:0,breakdown:[],totalMassKg:0};
    const target_kg=capacity_MT*1000;
    const batchTime=this.calcBatchTime(fc);
    const wvL=(fc.vesselM3||100)*1000*((fc.wvPct||70)/100);
    const prodPerBatch=(fc.titer||10)*wvL/1000;
    if(prodPerBatch<=0)return{total:0,breakdown:[],totalMassKg:0};
    const batchesPerYear=Math.floor(opHrs/batchTime);
    const nFerm=Math.max(1,Math.ceil(target_kg/(prodPerBatch*batchesPerYear)));
    const totalBatchesYr=batchesPerYear*nFerm;
    let totalCostYr=0; const bd=[];
    fc.solutions.forEach(sol=>{
      const vol=sol.volume_L||0;
      (sol.components||[]).forEach(comp=>{
        const massKgPerBatch=(comp.conc_g_per_L||0)*vol/1000;
        const price=comp.price_usd_per_kg||0;
        const costYr=massKgPerBatch*price*totalBatchesYr;
        totalCostYr+=costYr;
        if(massKgPerBatch>0)bd.push({chemical:comp.chemical||'',solution:sol.name||'',massPerBatch:+massKgPerBatch.toFixed(3),price,costPerMT:+(costYr/target_kg*1000).toFixed(1)});
      });
    });
    return{total:+(totalCostYr/target_kg*1000).toFixed(1),breakdown:bd,totalMassKg:totalCostYr};
  },

  calcFermenter(fc, capacity_MT, opHrs){
    const batchTime=this.calcBatchTime(fc);
    const tau=fc.fermTime||48;
    const batchTime2=batchTime;
    const V_max=fc.vesselM3||100;
    const V_wf=(fc.wvPct||70)/100;
    const vvm=fc.vvm||1;
    const sipRate=fc.sipStreamRate||0.5;
    const agitEff=fc.agitationEff||3;
    const tauCip=fc.cipTime||2;
    const tauSip=fc.sipTime||2;
    const cipAcidRatio=0.8;
    const P=101325, P_drop=200000;

    const wvL=V_max*1000*V_wf;
    const prodPerBatch=(fc.titer||10)*wvL/1000;
    if(prodPerBatch<=0)return null;

    const target_kg=capacity_MT*1000;
    const batchesPerYear=Math.floor(opHrs/batchTime);
    const nFerm=Math.max(1,Math.ceil(target_kg/(prodPerBatch*batchesPerYear)));
    const totalBatchesYr=batchesPerYear*nFerm;

    const outVolM3=wvL/1000;
    const V_T=outVolM3*batchTime/V_wf*(batchTime2/batchTime);
    const N_per_ferm=Math.max(1,Math.ceil(V_T/V_max));
    const V_i=V_T/N_per_ferm;
    const N_total=N_per_ferm*nFerm;
    const V_Working=V_i*V_wf*N_total;

    const p_agit_kw=agitEff*V_Working;
    const air_flow=V_Working*vvm/60*101325/(this.R_AIR*1000*298.15);
    const P_ratio=(P_drop+P)/P;
    const r_stage=Math.pow(P_ratio,1/this.STAGE);
    const exp_factor=(this.K-1)/this.K;
    const comp_work=this.STAGE/exp_factor*this.R_AIR*298.15*(Math.pow(r_stage,exp_factor)-1);
    const p_comp_kw=air_flow*comp_work;
    const total_kw=(p_agit_kw*batchTime+p_comp_kw*tau)*N_total/batchTime2;

    const steamFlow=V_i*sipRate*N_total*tauSip/batchTime;
    const steamPrice=fc.steamPrice||0.019;
    const steamCostHr=steamFlow*steamPrice;
    const steamCostYr=steamCostHr*opHrs;
    const steamPerMT=+(steamCostYr/target_kg*1000).toFixed(1);

    const elecPrice=fc.elecPrice||0.128;
    const elecCostYr=total_kw*opHrs*elecPrice;
    const elecPerMT=+(elecCostYr/target_kg*1000).toFixed(1);

    const heatKW=total_kw;
    const coolWaterFlow=heatKW/4.186/this.DT_COOL*3.6;
    const coolPrice=fc.coolPrice||5.33e-5;
    const coolCostYr=coolWaterFlow*opHrs*coolPrice;
    const coolPerMT=+(coolCostYr/target_kg*1000).toFixed(1);

    const cipMassPerBatch=V_i*N_total*1000*2;
    const cipFlow=cipMassPerBatch/batchTime2;
    const cipAcidPrice=0.02, cipBasePrice=0.024, cipWaterPrice=0.001, wastewaterPrice=0.00033;
    const cipCostYr=(cipFlow*cipAcidPrice+cipFlow*cipBasePrice+cipFlow*cipWaterPrice)*opHrs;
    const wasteCostYr=cipFlow*3*wastewaterPrice*opHrs;
    const wastePerMT=+((cipCostYr+wasteCostYr)/target_kg*1000).toFixed(1);

    const D_ft=(4*V_i/Math.PI/2.5)**(1/3)*3.28084;
    const L_ft=D_ft*2.5;
    const tankCostEach=Math.exp(7.0132+0.18255*Math.log(Math.max(1,D_ft*L_ft))+0.02297*Math.pow(Math.log(Math.max(1,D_ft*L_ft)),2));
    const totalTankCost=tankCostEach*N_total*(this.CE/567)*2.5;
    const compPower=Math.max(450,p_comp_kw*1.341);
    const compCost=Math.exp(7.58+0.8*Math.log(compPower))*N_total*(this.CE/567)*2.5;
    const pumpCost=N_total*2*5000*(this.CE/567)*2.2;
    const hxArea=Math.max(1,(p_agit_kw+p_comp_kw)/(0.6*15));
    const hxCost=3000*Math.pow(hxArea,0.6)*2.5;

    const installedCost=totalTankCost+compCost+pumpCost+hxCost;
    let capex=installedCost*this.LANG*1.15;
    if(fc.gmp)capex*=5;
    const capexMn=+(capex/1e6).toFixed(2);

    const depreciation=+(capex*0.082/target_kg*1000).toFixed(1);
    const repair=+(capex*0.05/target_kg*1000).toFixed(1);
    let labor=+(1440000000/target_kg/1500*1000).toFixed(1);
    if(fc.gmp)labor=+(labor*5).toFixed(1);

    return{
      batchTime,tau,nFerm,N_total,V_i:+V_i.toFixed(1),V_T:+V_T.toFixed(1),V_Working:+V_Working.toFixed(1),
      prodPerBatch:+prodPerBatch.toFixed(3),batchesPerYear,totalBatchesYr,
      wvL:+wvL.toFixed(0),
      p_agit_kw:+p_agit_kw.toFixed(1),p_comp_kw:+p_comp_kw.toFixed(1),total_kw:+total_kw.toFixed(1),
      steamPerMT,elecPerMT,coolPerMT,wastePerMT,
      capex,capexMn,installedCost:+installedCost.toFixed(0),
      depreciation,repair,labor,
    };
  },

  calcOutputMass(fc){
    const inMass=fc.inMass||{};
    const outMass=fc.outMass||{};
    return {inMass,outMass};
  },

  scaleUpCapex(knownCapex, knownCap, targetCap, exponent){
    if(!knownCap||!targetCap)return 0;
    return +(knownCapex*Math.pow(targetCap/knownCap, exponent||0.6)).toFixed(2);
  },

  applyToScenario(sc){
    const fc=sc.fermConfig;if(!fc||!fc.enabled)return;
    const opHrs=fc.operatingHours||7920;
    const capacity=sc.capacity||0;
    if(capacity<=0)return;

    const rawResult=this.calcRawMaterialCost(fc,capacity,opHrs);

    const ferm=this.calcFermenter(fc,capacity,opHrs);
    if(!ferm)return;

    sc.rawMaterial=rawResult.total;
    sc.subMaterial=0;
    sc.steam=ferm.steamPerMT;
    sc.electricity=ferm.elecPerMT;
    sc.cooling=ferm.coolPerMT;
    sc.waste=ferm.wastePerMT;
    sc.capex=ferm.capexMn;
    sc.fermentation=(fc.titer||'?')+' g/L, '+(fc.fermTime||'?')+'h, '+ferm.nFerm+'기 '+ferm.V_i+'m3';

    sc._fermResult={
      ...ferm,
      rawMaterial:rawResult,
      subUnit:fc.yieldPct>0?+(1/(fc.yieldPct/100)).toFixed(4):0,
    };
  },
};

// ============================================================
// BENCHMARK DATABASE
// ============================================================
const BENCHMARKS = {
  "1,3-PDO":{name:"1,3-PDO",cat:"바이오케미컬",org:"E. coli (eng.)",titer:165,yield:47,prod:2.3,
    defaults:{capacity:10000,capex:65,glucosePrice:300,glucoseUnit:2.23,rawMaterial:667.8,subMaterial:265.6,steam:44,electricity:129.3,cooling:9.6,waste:15.6,headcount:60,laborCost:1.2,otherFixed:25,sellingPrice:2500}},
  "Rh Collagen (Single)":{name:"Rh Collagen (Single)",cat:"바이오소재",org:"Pichia pastoris",titer:4.0,yield:1.99,prod:0.083,
    defaults:{capacity:1,capex:15,glucosePrice:500,glucoseUnit:100.55,rawMaterial:45000,subMaterial:12000,steam:800,electricity:3500,cooling:200,waste:500,headcount:20,laborCost:1.2,otherFixed:8,sellingPrice:500000}},
  "Rh Collagen (Triple)":{name:"Rh Collagen (Triple Helix)",cat:"바이오소재",org:"Pichia pastoris",titer:0.18,yield:0.045,prod:0.00375,
    defaults:{capacity:0.1,capex:20,glucosePrice:500,glucoseUnit:2234.4,rawMaterial:890000,subMaterial:120000,steam:5000,electricity:25000,cooling:1500,waste:3000,headcount:25,laborCost:1.2,otherFixed:12,sellingPrice:5000000}},
  "mTG":{name:"mTG (Microbial Transglutaminase)",cat:"바이오소재",org:"S. mobaraensis",titer:25,yield:35,prod:0.52,
    defaults:{capacity:100,capex:25,glucosePrice:300,glucoseUnit:0.86,rawMaterial:2500,subMaterial:800,steam:120,electricity:450,cooling:80,waste:60,headcount:30,laborCost:1.2,otherFixed:10,sellingPrice:25000}},
  "Rhamnolipid":{name:"Rhamnolipid",cat:"바이오계면활성제",org:"Pseudomonas",titer:40,yield:30,prod:0.56,
    defaults:{capacity:5000,capex:35,glucosePrice:300,glucoseUnit:3.33,rawMaterial:1200,subMaterial:350,steam:80,electricity:200,cooling:40,waste:30,headcount:40,laborCost:1.2,otherFixed:15,sellingPrice:5000}},
  "Ceramide":{name:"Ceramide",cat:"바이오소재",org:"In-vitro (CerS)",titer:8,yield:20,prod:0.11,
    defaults:{capacity:50,capex:20,glucosePrice:800,glucoseUnit:50,rawMaterial:18000,subMaterial:5000,steam:300,electricity:800,cooling:100,waste:200,headcount:25,laborCost:1.2,otherFixed:10,sellingPrice:80000}},
};

const MAX_SCENARIOS = 10;

// ============================================================
// GLOBAL STATE
// ============================================================
let STATE = {
  activeTab: 0,
  project:{name:'',product:'',analyst:'',exchangeRate:1280,discountRate:9,taxRate:22,analysisYears:15,constructionYears:2},
  scenarios:[],results:[],selectedChart:0,
  showBenchmarkModal:false,showUploadModal:false,uploadData:null,
  chartInstances:{},collapsedSections:{},nextId:1,
  chatOpen:false,chatLoading:false,
  chatMessages:[{role:'assistant',content:'안녕하세요. TEA-Agent v9.0 AI 어시스턴트입니다.\n\n질문 예시:\n- "현재 USD/KRW 환율 알려줘"\n- "1,3-PDO 시장 현황 알려줘"\n- "수율 근거 작성해줘"'}],
  chemList:[],chemEditName:null,
  solList:[],
  utilList:{},subMatList:{},utilCat:{},utilCatOptions:['resin','membrane','wastewater','filter','cip','steam','cooling','fuel','기타'],
  bfdNodes:[],bfdEdges:[],bfdNodeTypes:{},bfdSelectedNode:null,
  bioProduct:'',bioSource:'Glucose',bioTargetMT:100,
  projectList:[],
  showFlowGuide: localStorage.getItem('tea_guide_hidden')!=='1',
};

function setState(patch){
  Object.assign(STATE,typeof patch==='function'?patch(STATE):patch);
  render();
}

// ============================================================
// UTIL
// ============================================================
const fmt=(n,d=1)=>{if(n==null||isNaN(n))return'-';if(Math.abs(n)>=1e6)return(n/1e6).toFixed(d)+'M';if(Math.abs(n)>=1e3)return(n/1e3).toFixed(d)+'K';return n.toFixed(d);};
const fmtComma=n=>n!=null?n.toLocaleString():'-';
const esc=s=>{const d=document.createElement('div');d.textContent=s;return d.innerHTML;};

function _tipIcon(tip){return tip?'<span title="'+esc(tip).replace(/"/g,'&quot;')+'" style="cursor:help;color:#9ca3af;font-size:10px">ⓘ</span>':'';}
function inputField(id,label,value,unit,type,tip){
  type=type||'text';
  return '<div class="flex-1 min-w-[100px]"><div class="text-xs text-gray-500 font-medium mb-1 flex items-center gap-1">'+esc(label)+_tipIcon(tip)+'</div><div class="flex items-center gap-1"><input id="'+id+'" type="'+type+'" value="'+esc(String(value||''))+'" class="input-field" onchange="handleInput(\''+id+'\',this.value)">'+(unit?'<span class="text-xs text-gray-400 whitespace-nowrap">'+esc(unit)+'</span>':'')+'</div></div>';
}
// Read-only display for a value derived from BioSTEAM / the chemical DB.
function derivedField(label,value,unit,badge,tip){
  const badgeHtml=badge?'<span class="ml-1 px-1 rounded" style="font-size:8px;background:#dbeafe;color:#1d4ed8">'+esc(badge)+'</span>':'';
  const disp=(value==null||value==='')?'-':(typeof value==='number'?fmtComma(value):esc(String(value)));
  return '<div class="flex-1 min-w-[100px]"><div class="text-xs text-gray-500 font-medium mb-1 flex items-center gap-1">'+esc(label)+_tipIcon(tip)+badgeHtml+'</div><div class="flex items-center gap-1"><div class="input-field" style="background:#eef2ff;color:#1e3a8a;font-weight:600">'+disp+'</div>'+(unit?'<span class="text-xs text-gray-400 whitespace-nowrap">'+esc(unit)+'</span>':'')+'</div></div>';
}

function handleInput(id,val){
  const p=id.split('__');
  if(p[0]==='proj'){
    const k=p[1],nums=['exchangeRate','discountRate','taxRate','analysisYears','constructionYears'];
    STATE.project[k]=nums.includes(k)?(parseFloat(val)||0):val;
  }else if(p[0]==='fc'){
    const sc=STATE.scenarios.find(s=>s.id===parseInt(p[1]));
    if(sc&&sc.fermConfig){const numFields=['titer','yieldPct','productivity','temp','fermTime','initOD','finalOD','vvm','wvPct','vesselM3','sipTime','cipTime','transferTime','sipTemp','steamPrice','elecPrice','coolPrice'];sc.fermConfig[p[2]]=numFields.includes(p[2])?(parseFloat(val)||0):val;}
  }else if(p[0]==='sc'){
    const sc=STATE.scenarios.find(s=>s.id===parseInt(p[1]));
    if(sc){const strs=['name','fermentation'];sc[p[2]]=strs.includes(p[2])?val:(parseFloat(val)||0);}
  }
  render();
}

function toggleSection(k){STATE.collapsedSections[k]=!STATE.collapsedSections[k];render();}
function addEmptyScenario(){
  if(STATE.scenarios.length>=MAX_SCENARIOS){alert('최대 '+MAX_SCENARIOS+'개까지 추가 가능합니다.');return;}
  setState(s=>({scenarios:[...s.scenarios,{id:s.nextId++,name:'Scenario '+(s.scenarios.length+1),fermentation:'',capacity:10000,capex:50,glucosePrice:300,glucoseUnit:2.0,rawMaterial:600,subMaterial:200,steam:80,electricity:100,cooling:10,waste:15,headcount:60,laborCost:1.2,otherFixed:25,sellingPrice:2500}]}));
}
function removeScenario(id){setState(s=>({scenarios:s.scenarios.filter(sc=>sc.id!==id)}));}
function addFromBenchmark(key){
  if(STATE.scenarios.length>=MAX_SCENARIOS){alert('최대 '+MAX_SCENARIOS+'개');setState({showBenchmarkModal:false});return;}
  const bm=BENCHMARKS[key];if(!bm)return;
  const sc={id:STATE.nextId++,name:bm.name+' - S'+(STATE.scenarios.length+1),fermentation:bm.titer+' g/L, '+bm.yield+'%, '+bm.prod+' g/L/h',benchmark:key,...bm.defaults};
  setState(s=>({scenarios:[...s.scenarios,sc],project:{...s.project,product:s.project.product||bm.name},showBenchmarkModal:false}));
}

// ============================================================
// FERMENTATION HELPERS
// ============================================================
function toggleFermCalc(scId,checked){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc){sc.fermConfig.enabled=checked;if(checked)FermEngine.applyToScenario(sc);}render();}
function runFermCalc(scId){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc){FermEngine.applyToScenario(sc);render();}}
function runFermAndApply(scId){
  const sc=STATE.scenarios.find(s=>s.id===scId);if(!sc)return;
  sc.fermConfig.enabled=true;
  FermEngine.applyToScenario(sc);
  render();
}
function applySolCostToScenario(scId){
  const sc=STATE.scenarios.find(s=>s.id===scId);if(!sc)return;
  let totalCostPerL=0;
  STATE.solList.forEach(sol=>{totalCostPerL+=parseFloat(calcSolCost(sol))||0;});
  if(sc._fermResult&&sc._fermResult.media){
    const updatedMedia=[];
    (sc.fermConfig.media||[]).forEach(m=>{
      const dbChem=STATE.chemList.find(c=>c.name===m.name);
      if(dbChem&&dbChem.price>0)m.price=dbChem.price;
    });
    FermEngine.applyToScenario(sc);
  }else{
    const mediaPerMT=totalCostPerL*10*1000;
    sc.subMaterial=+mediaPerMT.toFixed(1);
  }
  alert('용액 원가가 시나리오 부재료비에 반영되었습니다.');
  render();
}
async function runBiosteamForScenario(scId){
  const sc=STATE.scenarios.find(s=>s.id===scId);if(!sc)return;
  if(BIOSTEAM_RUNNING)return;
  BIOSTEAM_RUNNING=true;render();
  try{
    const body={
      chemicals:STATE.chemList.map(c=>({name:c.name,formula:c.formula,price:c.price,phase:c.phase})),
      solutions:STATE.solList,
      bfd:{nodes:STATE.bfdNodes.map(n=>({id:n.id,node_type:n.node_type,label:n.label,x:n.x,y:n.y,params:n.params||{},solution_flows:n.solution_flows||{}})),edges:STATE.bfdEdges.map(e=>({id:e.id,source:e.source,target:e.target}))},
      main_product:document.getElementById('bio-prod-'+scId)?.value||STATE.project.product||'',
      main_source:document.getElementById('bio-src-'+scId)?.value||'Glucose',
      target_amount:sc.capacity||STATE.bioTargetMT||100,
      operating_hours:parseFloat(document.getElementById('bio-oph-'+scId)?.value)||7920,
      electricity_price:0.128,
      gmp:document.getElementById('bio-gmp-'+scId)?.checked??true,
      od_to_dcw:0.22,
      heat_utility:combinedHeatUtility(),
    };
    const r=await fetch('/api/biosteam/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result=await r.json();
    sc._biosteamResult=result;
    if(result.success){
      sc.capex=+(result.capexMn||0).toFixed(2);
      sc.rawMaterial=+(result.rawMaterial||0).toFixed(1);
      sc.subMaterial=+(result.subMaterial||0).toFixed(1);
      sc.steam=+(result.steam||0).toFixed(1);
      sc.electricity=+(result.electricity||0).toFixed(1);
      sc.cooling=+(result.cooling||0).toFixed(1);
      sc.waste=+(result.waste||0).toFixed(1);
      sc._biosteamApplied=true;
    }
  }catch(e){sc._biosteamResult={success:false,error:e.message};}
  BIOSTEAM_RUNNING=false;render();
}
function addMediaComp(scId){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc&&sc.fermConfig){sc.fermConfig.media.push({name:'',conc:0,price:0});render();}}
function removeMedia(scId,idx){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc&&sc.fermConfig){sc.fermConfig.media.splice(idx,1);render();}}
function updateMedia(scId,idx,field,val){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc&&sc.fermConfig&&sc.fermConfig.media[idx])sc.fermConfig.media[idx][field]=val;}

function addFermSolution(scId){
  const sc=STATE.scenarios.find(s=>s.id===scId);if(!sc)return;
  if(!sc.fermConfig.solutions)sc.fermConfig.solutions=[];
  sc.fermConfig.solutions.push({name:'용액 '+(sc.fermConfig.solutions.length+1),volume_L:1,components:[{chemical:'',conc_g_per_L:0,price_usd_per_kg:0}]});
  render();
}
function removeFermSol(scId,si){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc)sc.fermConfig.solutions.splice(si,1);render();}
function updateFermSol(scId,si,field,val){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc&&sc.fermConfig.solutions[si])sc.fermConfig.solutions[si][field]=val;}
function addFermSolComp(scId,si){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc&&sc.fermConfig.solutions[si])sc.fermConfig.solutions[si].components.push({chemical:'',conc_g_per_L:0,price_usd_per_kg:0});render();}
function removeFermSolComp(scId,si,ci){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc&&sc.fermConfig.solutions[si])sc.fermConfig.solutions[si].components.splice(ci,1);render();}
function updateFermSolComp(scId,si,ci,field,val){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc&&sc.fermConfig.solutions[si]&&sc.fermConfig.solutions[si].components[ci])sc.fermConfig.solutions[si].components[ci][field]=val;}
function importSolToFerm(scId){
  const sc=STATE.scenarios.find(s=>s.id===scId);if(!sc)return;
  if(!sc.fermConfig.solutions)sc.fermConfig.solutions=[];
  STATE.solList.forEach(sol=>{
    const existing=sc.fermConfig.solutions.find(s=>s.name===sol.user_name);
    if(!existing){
      const comps=(sol.components||[]).map(c=>{
        const dbChem=STATE.chemList.find(ch=>ch.name===c.name);
        return{chemical:c.name,conc_g_per_L:c.concentration_g_per_l||0,price_usd_per_kg:dbChem?dbChem.price:(c.price||0)};
      });
      sc.fermConfig.solutions.push({name:sol.user_name,volume_L:1,components:comps});
    }
  });
  render();
}
function addFermOutput(scId){const sc=STATE.scenarios.find(s=>s.id===scId);if(!sc)return;if(!sc.fermConfig.outputs)sc.fermConfig.outputs=[];sc.fermConfig.outputs.push({chemical:'',mass_kg:0});render();}
function removeFermOutput(scId,oi){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc)sc.fermConfig.outputs.splice(oi,1);render();}
function updateFermOutput(scId,oi,field,val){const sc=STATE.scenarios.find(s=>s.id===scId);if(sc&&sc.fermConfig.outputs[oi])sc.fermConfig.outputs[oi][field]=val;}

// ============================================================
// RUN ANALYSIS
// ============================================================
function runAnalysis(){
  if(!STATE.scenarios.length){alert('시나리오를 추가해주세요.');return;}
  STATE.scenarios.forEach(sc=>{if(sc.fermConfig&&sc.fermConfig.enabled)FermEngine.applyToScenario(sc);});
  const results=STATE.scenarios.map(sc=>TEAEngine.analyze(sc,STATE.project));
  setState({results,activeTab:tabIndex('results'),selectedChart:0});
  setTimeout(renderCharts,100);
}

// ============================================================
// FILE UPLOAD
// ============================================================
async function handleFileUpload(file){
  if(!file)return;
  try{
    const formData=new FormData();formData.append('file',file);
    const resp=await fetch('/api/upload',{method:'POST',body:formData});
    if(resp.ok){const json=await resp.json();if(json.success){setState({uploadData:json.data,showUploadModal:true});return;}}
  }catch(e){}
  const ext=file.name.split('.').pop().toLowerCase();
  const reader=new FileReader();
  reader.onload=e=>{
    try{
      if(ext==='xlsx'||ext==='xls'){const wb=XLSX.read(e.target.result,{type:'binary'});const ws=wb.Sheets[wb.SheetNames[0]];parseClientData(XLSX.utils.sheet_to_json(ws,{header:1}));}
      else{const text=e.target.result;parseClientText(text);}
    }catch(err){alert('파일 파싱 오류: '+err.message);}
  };
  if(ext==='xlsx'||ext==='xls')reader.readAsBinaryString(file);else reader.readAsText(file);
}
function parseClientText(text){
  const lines=text.split('\n').filter(l=>l.trim()),parsed={project:{},scenarios:[]};
  const projMap={'프로젝트이름':'name','제품명':'product','분석자':'analyst','환율':'exchangeRate','할인율':'discountRate','법인세율':'taxRate','분석기간':'analysisYears','건설기간':'constructionYears'};
  const scMap={'시나리오이름':'name','생산량':'capacity','capacity':'capacity','투자비':'capex','capex':'capex','원재료비':'rawMaterial','부재료':'subMaterial','스팀':'steam','전기':'electricity','냉각':'cooling','폐기물':'waste','인원수':'headcount','인건비단가':'laborCost','기타고정비':'otherFixed','판매가':'sellingPrice','기질단가':'glucosePrice','기질원단위':'glucoseUnit'};
  lines.forEach(line=>{const sep=line.includes('\t')?'\t':(line.includes(',')?',':':');const parts=line.split(sep).map(s=>s.trim());if(parts.length<2)return;const key=parts[0].toLowerCase().replace(/[\s_]/g,'');const numVal=parseFloat(parts[1].replace(/[^\d.-]/g,''));if(projMap[key])parsed.project[projMap[key]]=isNaN(numVal)?parts[1]:numVal;else if(scMap[key]){if(!parsed.scenarios.length)parsed.scenarios.push({});parsed.scenarios[0][scMap[key]]=isNaN(numVal)?parts[1]:numVal;}});
  setState({uploadData:parsed,showUploadModal:true});
}
function parseClientData(rows){
  if(rows.length>0&&rows[0].length===2){parseClientText(rows.map(r=>r.join(',')).join('\n'));return;}
  const parsed={project:{},scenarios:[]};
  if(rows.length>1){const headers=rows[0].map(h=>(h||'').toString().toLowerCase().replace(/[\s_]/g,''));for(let i=1;i<rows.length;i++){const sc={};rows[i].forEach((v,j)=>{if(headers[j])sc[headers[j]]=v;});if(Object.keys(sc).length)parsed.scenarios.push(sc);}}
  setState({uploadData:parsed,showUploadModal:true});
}
function applyUploadData(){
  const data=STATE.uploadData;if(!data)return;
  const proj={...STATE.project};if(data.project)Object.assign(proj,data.project);
  const newScenarios=[...STATE.scenarios];
  if(data.scenarios){const toAdd=data.scenarios.slice(0,Math.max(0,MAX_SCENARIOS-newScenarios.length));toAdd.forEach(sc=>newScenarios.push({id:STATE.nextId++,name:sc.name||'Upload',fermentation:'',capacity:sc.capacity||0,capex:sc.capex||0,glucosePrice:sc.glucosePrice||300,glucoseUnit:sc.glucoseUnit||0,rawMaterial:sc.rawMaterial||0,subMaterial:sc.subMaterial||0,steam:sc.steam||0,electricity:sc.electricity||0,cooling:sc.cooling||0,waste:sc.waste||0,headcount:sc.headcount||60,laborCost:sc.laborCost||1.2,otherFixed:sc.otherFixed||25,sellingPrice:sc.sellingPrice||0}));}
  setState({project:proj,scenarios:newScenarios,showUploadModal:false,uploadData:null});
}

// ============================================================
// CHARTS
// ============================================================
function destroyCharts(){Object.values(STATE.chartInstances).forEach(c=>{try{c.destroy();}catch(e){}});STATE.chartInstances={};}
function renderCharts(){
  destroyCharts();const R=STATE.results;if(!R.length)return;const sel=R[STATE.selectedChart]||R[0];
  const cwCtx=document.getElementById('chart-waterfall');
  if(cwCtx){const items=[{l:'원재료비',v:sel.rawMaterial,c:'#2563eb'},{l:'부재료',v:sel.subMaterial,c:'#3b82f6'},{l:'스팀',v:sel.steam,c:'#60a5fa'},{l:'전기',v:sel.electricity,c:'#93c5fd'},{l:'냉각',v:sel.cooling,c:'#bfdbfe'},{l:'폐기물',v:sel.waste,c:'#dbeafe'},{l:'인무비',v:sel.labor,c:'#c2410c'},{l:'감가상각',v:sel.depreciation,c:'#ea580c'},{l:'수선비',v:sel.maintenance,c:'#f97316'},{l:'기타',v:sel.otherFixed,c:'#fdba74'}];let cum=0;const bases=[],vals=[];items.forEach(i=>{bases.push(cum);vals.push(i.v);cum+=i.v;});bases.push(0);vals.push(cum);
  STATE.chartInstances.waterfall=new Chart(cwCtx,{type:'bar',data:{labels:[...items.map(i=>i.l),'합계'],datasets:[{data:bases,backgroundColor:'transparent',borderWidth:0,barPercentage:0.7},{data:vals,backgroundColor:[...items.map(i=>i.c),'#006600'],barPercentage:0.7}]},options:{responsive:true,plugins:{legend:{display:false},title:{display:true,text:'제조원가 구성 - '+sel.name+' ($'+sel.manufacturingCost+'/MT)',font:{size:13,weight:'bold'},color:'#006600'}},scales:{x:{stacked:true,ticks:{font:{size:10}}},y:{stacked:true,ticks:{font:{size:10}}}}}});}
  const scCtx=document.getElementById('chart-comparison');
  if(scCtx)STATE.chartInstances.comparison=new Chart(scCtx,{type:'bar',data:{labels:R.map(r=>r.name.substring(0,15)),datasets:[{label:'변동비',data:R.map(r=>r.variableTotal),backgroundColor:'#3b82f6'},{label:'고정비',data:R.map(r=>r.fixedTotal),backgroundColor:'#ea580c'}]},options:{responsive:true,plugins:{title:{display:true,text:'시나리오별 제조원가 ($/MT)',font:{size:13,weight:'bold'},color:'#006600'}},scales:{x:{stacked:true},y:{stacked:true}}}});
  const npvCtx=document.getElementById('chart-npv');
  if(npvCtx)STATE.chartInstances.npv=new Chart(npvCtx,{type:'bar',data:{labels:R.map(r=>r.name.substring(0,15)),datasets:[{label:'NPV (Mn$)',data:R.map(r=>r.npv),backgroundColor:R.map(r=>r.npv>=0?'#006600':'#dc2626')}]},options:{responsive:true,plugins:{title:{display:true,text:'NPV 비교 (Mn$)',font:{size:13,weight:'bold'},color:'#006600'},legend:{display:false}}}});
  const cfCtx=document.getElementById('chart-cashflow');
  if(cfCtx){let cum=0;const cumData=sel.cashflows.map(cf=>{cum+=cf;return+(cum/1e6).toFixed(1);});STATE.chartInstances.cashflow=new Chart(cfCtx,{type:'line',data:{labels:sel.yearLabels,datasets:[{label:'현금흐름 (Mn$)',data:sel.cashflows.map(cf=>+(cf/1e6).toFixed(1)),borderColor:'#3b82f6',tension:0.3,pointRadius:3},{label:'누적현금흐름 (Mn$)',data:cumData,borderColor:'#006600',borderWidth:2,tension:0.3,pointRadius:3}]},options:{responsive:true,plugins:{title:{display:true,text:'현금흐름 - '+sel.name,font:{size:13,weight:'bold'},color:'#006600'}}}});}
}

// ============================================================
// EXPORT
// ============================================================
function exportCSV(){
  const R=STATE.results;if(!R.length)return;
  let csv='﻿항목,'+R.map(r=>r.name).join(',')+'\n';
  [['Capacity (MT)',r=>r.capacityMT],['CAPEX (Mn$)',r=>r.capexMnUsd],['제조원가 ($/MT)',r=>r.manufacturingCost],['NPV (Mn$)',r=>r.npv],['IRR (%)',r=>r.irr],['BC Ratio',r=>r.bcRatio],['Payback (년)',r=>r.payback]].forEach(([l,fn])=>{csv+=l+','+R.map(fn).join(',')+'\n';});
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='TEA_결과.csv';a.click();
}
function exportExcel(){
  const R=STATE.results;if(!R.length)return;
  const headers=['항목',...R.map(r=>r.name)];
  const rows=[['환율(원/$)',...R.map(()=>STATE.project.exchangeRate)],['Capacity(MT)',...R.map(r=>r.capacityMT)],['CAPEX(Mn$)',...R.map(r=>r.capexMnUsd)],['원재료비',...R.map(r=>r.rawMaterial)],['부재료',...R.map(r=>r.subMaterial)],['스팀',...R.map(r=>r.steam)],['전기',...R.map(r=>r.electricity)],['냉각',...R.map(r=>r.cooling)],['폐기물',...R.map(r=>r.waste)],['변동비합계',...R.map(r=>r.variableTotal)],['인무비',...R.map(r=>r.labor)],['감가상각',...R.map(r=>r.depreciation)],['수선비',...R.map(r=>r.maintenance)],['기타고정비',...R.map(r=>r.otherFixed)],['고정비합계',...R.map(r=>r.fixedTotal)],['제조원가($/MT)',...R.map(r=>r.manufacturingCost)],['판매가($/MT)',...R.map(r=>r.sellingPrice)],['NPV(Mn$)',...R.map(r=>r.npv)],['IRR(%)',...R.map(r=>r.irr)],['BC Ratio',...R.map(r=>r.bcRatio)],['Payback(년)',...R.map(r=>r.payback)]];
  const wb=XLSX.utils.book_new();const ws=XLSX.utils.aoa_to_sheet([headers,...rows]);XLSX.utils.book_append_sheet(wb,ws,'경제성분석');XLSX.writeFile(wb,'TEA_결과.xlsx');
}

// ============================================================
// CHEMICAL DB
// ============================================================
async function loadChemicals(){
  try{const r=await fetch('/api/chemicals');const d=await r.json();STATE.chemList=d.chemicals||[];render();}catch(e){}
}
async function addChemical(){
  const n=document.getElementById('chem-name')?.value?.trim();
  const f=document.getElementById('chem-formula')?.value?.trim()||'';
  const p=parseFloat(document.getElementById('chem-price')?.value)||0;
  const ph=document.getElementById('chem-phase')?.value||'l';
  if(!n){alert('물질명을 입력하세요.');return;}
  await fetch('/api/chemicals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,formula:f,price:p,phase:ph})});
  await loadChemicals();
}
async function deleteChemical(name){
  if(!confirm(name+' 삭제?'))return;
  await fetch('/api/chemicals/'+encodeURIComponent(name),{method:'DELETE'});
  await loadChemicals();
}
async function updateChemicalPrice(name,price){
  const chem=STATE.chemList.find(c=>c.name===name);if(!chem)return;
  await fetch('/api/chemicals/'+encodeURIComponent(name),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,formula:chem.formula,price:parseFloat(price)||0,phase:chem.phase})});
  await loadChemicals();
}

// ============================================================
// SOLUTION MANAGEMENT
// ============================================================
async function loadSolutions(){
  try{const r=await fetch('/api/solutions');const d=await r.json();STATE.solList=d.solutions||[];render();}catch(e){}
}
function addSolution(){
  const id='sol_'+Date.now()+'_'+STATE.solList.length;
  STATE.solList.push({id,user_name:'용액 '+(STATE.solList.length+1),components:[{name:'Water',concentration_g_per_l:1000}],autoclave:true});
  render();
}
function removeSolution(id){STATE.solList=STATE.solList.filter(s=>s.id!==id);render();}
function addSolComponent(id){const s=STATE.solList.find(x=>x.id===id);if(s){s.components.push({name:'',concentration_g_per_l:0});render();}}
function removeSolComponent(id,idx){const s=STATE.solList.find(x=>x.id===id);if(s){s.components.splice(idx,1);render();}}
function updateSolComponent(id,idx,field,val){
  const s=STATE.solList.find(x=>x.id===id);if(!s||!s.components[idx])return;
  if(field==='concentration_g_per_l'){let n=parseFloat(val)||0;if(n<0)n=0;s.components[idx][field]=n;}  // no negatives (#5)
  else s.components[idx][field]=val;
}
async function saveSolutions(){
  const r=await fetch('/api/solutions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({solutions:STATE.solList})});
  const d=await r.json();
  if(d.solutions){
    // Server dropped incomplete rows (#6) and ran fill_water3 (#8); reflect it.
    STATE.solList=d.solutions.map((s,i)=>({id:s.id||('sol_'+Date.now()+'_'+i),autoclave:s.autoclave!==false,...s}));
  }
  render();
  alert('용액 저장 완료!\n· 물질/농도가 비어있는 행은 삭제되었습니다.\n· 나머지는 물로 채워 1L 기준 조성으로 정규화했습니다.');
}
async function importSolutionsFromProject(name){
  if(!name)return;
  try{
    const r=await fetch('/api/project/load/'+encodeURIComponent(name));
    const d=await r.json();if(d.error){alert(d.error);return;}
    const sols=(d.data&&d.data.solutions)||[];
    if(!sols.length){alert('"'+name+'" 프로젝트에 용액이 없습니다.');return;}
    let added=0;
    sols.forEach(s=>{
      const nm=s.user_name||s.name;if(!nm)return;
      if(STATE.solList.some(x=>x.user_name===nm))return;   // skip duplicates by name
      STATE.solList.push({id:'sol_'+Date.now()+'_'+STATE.solList.length,user_name:nm,components:(s.components||[]).map(c=>({name:c.name,concentration_g_per_l:c.concentration_g_per_l||0})),autoclave:s.autoclave!==false});
      added++;
    });
    render();
    alert('"'+name+'"에서 용액 '+added+'개를 불러왔습니다.');
  }catch(e){alert('불러오기 실패: '+(e.message||e));}
}
function calcSolCost(sol){
  let total=0;
  sol.components.forEach(comp=>{
    const chem=STATE.chemList.find(c=>c.name===comp.name);
    if(chem)total+=(comp.concentration_g_per_l/1000)*chem.price;
  });
  return total.toFixed(4);
}

// ============================================================
// BFD - SVG + 드래그 방식
// ============================================================
const BFD_COLORS={'연속 피드':'#3b82f6','배치 피드':'#6366f1','발효기':'#22c55e','증발기':'#f59e0b','동결건조기':'#8b5cf6','원심분리기':'#ec4899','믹싱 탱크':'#14b8a6','Product Stream':'#a16207','폐기물':'#6b7280','MVR':'#0ea5e9','Chromatography':'#d946ef','발효/정제 분리선':'#64748b'};
function bfdNodeColor(type){return BFD_COLORS[type]||'#94a3b8';}

let BFD_DRAG=null;
let BFD_LINK=null;
let BFD_LINK_EL=null;
// Terminal sinks: nothing flows out, so they have no outgoing connection port.
const BFD_SINK_TYPES=['Product Stream','폐기물'];
let BFD_CONNECT=false;      // click-to-connect mode
let BFD_CONNECT_SRC=null;   // first node clicked in connect mode

async function createEdge(source,target){
  if(!source||!target||source===target)return;
  if(STATE.bfdEdges.some(e=>e.source===source&&e.target===target))return;
  const res=await fetch('/api/bfd/edge',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source,target})});
  const d=await res.json();if(d.edge)STATE.bfdEdges.push(d.edge);
  await fetch('/api/bfd/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nodes:STATE.bfdNodes,edges:STATE.bfdEdges})});
  initBFD();
}
function toggleConnectMode(){
  BFD_CONNECT=!BFD_CONNECT;BFD_CONNECT_SRC=null;
  const b=document.getElementById('bfd-connect-btn');
  if(b){b.style.background=BFD_CONNECT?'#15803d':'#e0e7ff';b.style.color=BFD_CONNECT?'#fff':'#3730a3';b.textContent=BFD_CONNECT?'🔗 연결 모드: ON (노드 두 개 클릭)':'🔗 연결 모드';}
  const c=document.getElementById('bfd-container');if(c)c.style.cursor=BFD_CONNECT?'crosshair':'default';
  initBFD();
}
let CHAT_W=420, CHAT_H=560;
let _chatRz=null;
function startChatResize(ev,dir){
  ev.preventDefault();ev.stopPropagation();
  _chatRz={dir,x0:ev.clientX,y0:ev.clientY,w0:CHAT_W,h0:CHAT_H};
  document.body.style.userSelect='none';
  document.body.style.cursor=dir==='w'?'ew-resize':dir==='n'?'ns-resize':'nw-resize';
}
document.addEventListener('mousemove',ev=>{
  if(!_chatRz)return;
  const dx=_chatRz.x0-ev.clientX;
  const dy=_chatRz.y0-ev.clientY;
  if(_chatRz.dir==='w'||_chatRz.dir==='nw')
    CHAT_W=Math.max(300,Math.min(900,_chatRz.w0+dx));
  if(_chatRz.dir==='n'||_chatRz.dir==='nw')
    CHAT_H=Math.max(280,Math.min(window.innerHeight-120,_chatRz.h0+dy));
  const p=document.getElementById('chat-panel-el');
  if(p){p.style.width=CHAT_W+'px';p.style.height=CHAT_H+'px';}
});
document.addEventListener('mouseup',()=>{
  if(_chatRz){_chatRz=null;document.body.style.userSelect='';document.body.style.cursor='';}
});

async function loadBFD(){
  try{
    const[ntR,bfdR]=await Promise.all([fetch('/api/bfd/node-types'),fetch('/api/bfd')]);
    const nt=await ntR.json(),bfd=await bfdR.json();
    STATE.bfdNodeTypes=nt.nodeTypes||{};STATE.bfdNodes=bfd.nodes||[];STATE.bfdEdges=bfd.edges||[];
    render();setTimeout(initBFD,50);
  }catch(e){}
}
async function addBFDNode(type){
  const cont=document.getElementById('bfd-container');
  const r=cont?cont.getBoundingClientRect():{width:700,height:500};
  const x=80+Math.random()*Math.max(200,r.width-200),y=60+Math.random()*Math.max(200,r.height-150);
  const res=await fetch('/api/bfd/node',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({node_type:type,label:type,x,y})});
  const d=await res.json();if(d.node){STATE.bfdNodes.push(d.node);initBFD();}
}
async function deleteBFDNode(id){
  const res=await fetch('/api/bfd/node/'+id,{method:'DELETE'});const d=await res.json();
  STATE.bfdNodes=d.nodes||[];STATE.bfdEdges=d.edges||[];STATE.bfdSelectedNode=null;initBFD();renderNodePropsPanel(null);
}
async function clearBFD(){
  if(!confirm('흐름도를 초기화하시겠습니까?'))return;
  await fetch('/api/bfd/clear',{method:'POST'});
  STATE.bfdNodes=[];STATE.bfdEdges=[];STATE.bfdSelectedNode=null;initBFD();renderNodePropsPanel(null);
}
async function saveBFD(){
  await fetch('/api/bfd/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nodes:STATE.bfdNodes,edges:STATE.bfdEdges})});
  alert('흐름도 저장 완료!');
}
async function deleteBFDEdgeById(eid){
  const res=await fetch('/api/bfd/edge/'+eid,{method:'DELETE'});const d=await res.json();
  STATE.bfdEdges=d.edges||[];initBFD();
}

function initBFD(){
  const cont=document.getElementById('bfd-container');
  const svg=document.getElementById('bfd-svg');
  if(!cont||!svg)return;
  Array.from(cont.children).forEach(el=>{if(el!==svg)el.remove();});
  let edgesHtml=`<defs><marker id="bfd-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b"/></marker></defs>`;
  STATE.bfdEdges.forEach(e=>{
    const sn=STATE.bfdNodes.find(n=>n.id===e.source),tn=STATE.bfdNodes.find(n=>n.id===e.target);
    if(!sn||!tn)return;
    // Flow goes downward: source bottom-center → target top-center.
    const x1=sn.x+60,y1=sn.y+44,x2=tn.x+60,y2=tn.y-2;
    // Wide transparent hit-band (clickable to delete) + the visible arrow.
    edgesHtml+=`<path d="M ${x1} ${y1} L ${x2} ${y2}" stroke="transparent" stroke-width="14" fill="none" style="pointer-events:stroke;cursor:pointer" onclick="deleteBFDEdgeById('${e.id}')"><title>클릭으로 삭제</title></path>`;
    edgesHtml+=`<path d="M ${x1} ${y1} L ${x2} ${y2}" stroke="#64748b" stroke-width="2" fill="none" marker-end="url(#bfd-arrow)" style="pointer-events:none"/>`;
  });
  svg.innerHTML=edgesHtml;
  STATE.bfdNodes.forEach(node=>{
    const div=document.createElement('div');
    const color=bfdNodeColor(node.node_type);
    const nt=STATE.bfdNodeTypes[node.node_type]||{icon:'⚙'};
    const isSep=node.node_type==='발효/정제 분리선';
    div.className='bfd-node'+(STATE.bfdSelectedNode===node.id?' selected':'')+(BFD_CONNECT_SRC===node.id?' selected':'');
    div.dataset.nodeId=node.id;
    div.style.cssText=`left:${node.x}px;top:${node.y}px;background:${color}18;border-color:${color};position:absolute;`;
    if(BFD_CONNECT)div.style.cssText+='outline:2px dashed '+(BFD_CONNECT_SRC===node.id?'#15803d':'#c7d2fe')+';';
    if(isSep){
      div.style.cssText+=`min-width:120px;padding:6px 16px;font-size:13px;font-weight:700;color:${color};`;
      div.innerHTML=`<div style="text-align:center">발효<hr style="margin:5px 0;border-color:${color};border-width:2px"/>정제</div>`;
    }else{
      div.innerHTML=`<div style="font-size:22px;line-height:1.2">${nt.icon}</div><div style="color:${color};font-size:11px;white-space:nowrap;overflow:hidden;max-width:100px;text-overflow:ellipsis">${node.label}</div>`;
    }
    div.title='본체 드래그: 이동 | 오른쪽 파란 점 드래그: 다른 노드에 연결';
    div.onmousedown=ev=>{
      ev.stopPropagation();
      // Connect mode: first click = source, second click on another node = edge.
      if(BFD_CONNECT){
        if(!BFD_CONNECT_SRC){BFD_CONNECT_SRC=node.id;initBFD();return;}
        if(BFD_CONNECT_SRC!==node.id){const src=BFD_CONNECT_SRC;BFD_CONNECT_SRC=null;createEdge(src,node.id);}
        else{BFD_CONNECT_SRC=null;initBFD();}
        return;
      }
      STATE.bfdSelectedNode=node.id;
      document.querySelectorAll('#bfd-container .bfd-node').forEach(el=>el.classList.remove('selected'));
      div.classList.add('selected');
      renderNodePropsPanel(node.id);
      if(ev.shiftKey){BFD_LINK=node;return;}
      BFD_DRAG={node,offsetX:ev.clientX-node.x,offsetY:ev.clientY-node.y};
    };
    // Connection port at the BOTTOM: drag from this dot down to another node to
    // draw an edge. Terminal sinks (Product Stream / 폐기물) get no outgoing port.
    if(!BFD_SINK_TYPES.includes(node.node_type)){
      const port=document.createElement('div');
      port.className='bfd-port';
      port.title='이 점을 아래 노드로 드래그해서 연결';
      port.style.cssText='position:absolute;left:50%;bottom:-9px;transform:translateX(-50%);width:15px;height:15px;border-radius:50%;background:#3b82f6;border:2px solid #fff;cursor:crosshair;box-shadow:0 1px 3px rgba(0,0,0,0.35);z-index:6';
      port.onmousedown=ev=>{ev.stopPropagation();ev.preventDefault();BFD_LINK=node;};
      div.appendChild(port);
    }
    cont.appendChild(div);
  });
  cont.onmousedown=ev=>{
    if(ev.target===cont||ev.target===svg){
      STATE.bfdSelectedNode=null;
      document.querySelectorAll('#bfd-container .bfd-node').forEach(el=>el.classList.remove('selected'));
      renderNodePropsPanel(null);
    }
  };
}

// --- Node property editor: uses the v1 rich schema (render) + process endpoint ---
let _NODEEDIT=null;   // {nodeId}
let _NETABLES={};     // tableKey -> {columns, tid}

async function renderNodePropsPanel(nodeId){
  const panel=document.getElementById('bfd-props-panel');if(!panel)return;
  if(!nodeId){panel.innerHTML='<div class="text-xs text-gray-400">노드를 선택하세요<br><br>노드 <b>오른쪽 파란 점</b>을 드래그해 다른 노드에 놓으면 연결선이 생깁니다.<br>노드 클릭: 선택·편집</div>';_NODEEDIT=null;return;}
  const node=STATE.bfdNodes.find(n=>n.id===nodeId);if(!node)return;
  panel.innerHTML='<div class="text-xs text-gray-400">불러오는 중…</div>';
  let schema;
  try{const r=await fetch('/api/bfd/node/'+encodeURIComponent(nodeId)+'/schema');schema=await r.json();if(schema.detail)throw new Error(schema.detail);}
  catch(e){panel.innerHTML='<div class="text-xs" style="color:#dc2626">스키마 로드 실패: '+esc(e.message||e)+'</div>';return;}
  _NODEEDIT={nodeId};_NETABLES={};
  const color=bfdNodeColor(node.node_type);
  let h=`<div class="font-bold text-sm mb-2" style="color:${color}">⬢ ${esc(schema.node_type||node.node_type)}</div>`;
  h+=`<div class="text-xs text-gray-500 mb-1">Name</div><input id="ne-name" class="input-field mb-2" value="${esc(schema.name||node.label||'')}">`;
  h+='<div style="max-height:440px;overflow-y:auto">';
  (schema.groups||[]).forEach((g,gi)=>{h+=neGroup(g,'g'+gi);});
  h+='</div>';
  h+=`<div class="flex gap-2 mt-3"><button class="btn-primary text-xs flex-1" onclick="saveNodeEdit()">💾 저장 (처리)</button><button class="btn-danger" onclick="deleteBFDNode('${nodeId}')">삭제</button></div>`;
  panel.innerHTML=h;
}

function neGroup(g,gid){
  const open=g.advanced?'':' open';
  let h=`<details${open} style="border:1px solid #e2e8f0;border-radius:6px;padding:6px 8px;margin:6px 0"><summary class="text-xs font-bold" style="color:#15803d;cursor:pointer">${esc(g.title)}</summary>`;
  (g.fields||[]).forEach((f,fi)=>{h+= f.fields ? neGroup(f,gid+'_'+fi) : neField(f,gid+'_'+fi);});
  h+='</details>';
  return h;
}

// Node-editor id→price field links: picking a utility id fills the price field.
const NE_PRICE_LINK={resin_id:'resin_price',membrane_id:'membrane_cost'};
function neSyncLinkedPrice(idKey,val){
  const priceKey=NE_PRICE_LINK[idKey];if(!priceKey)return;
  const price=combinedHeatUtility()[val];
  if(price==null)return;
  const el=document.querySelector('#bfd-props-panel [data-nekey="'+priceKey+'"]');
  if(el){el.value=price;el.style.background='#ecfdf5';}
}
function neField(f,fid){
  if(f.kind==='table')return neTable(f,fid);
  const id='ne_'+fid;
  if(f.kind==='bool'){
    return '<div class="my-1"><label class="flex items-center gap-1 text-xs"><input id="'+id+'" data-nekey="'+esc(f.key)+'" data-nekind="bool" type="checkbox"'+(f.value?' checked':'')+'> '+esc(f.label)+'</label></div>';
  }
  let inner;
  if(f.kind==='select'){
    // When a utility-id dropdown changes, pull its price from the utilities DB
    // into the linked price field so the coupling is visible immediately.
    const onc=NE_PRICE_LINK[f.key]?' onchange="neSyncLinkedPrice(\''+esc(f.key)+'\',this.value)"':'';
    inner='<select id="'+id+'" data-nekey="'+esc(f.key)+'" data-nekind="select" class="input-field text-xs"'+onc+'>';
    (f.options||[]).forEach(o=>{inner+='<option'+(String(o)===String(f.value)?' selected':'')+'>'+esc(o)+'</option>';});
    inner+='</select>';
  }else{
    const t=(f.kind==='number'||f.kind==='int')?'number':'text';
    inner='<input id="'+id+'" data-nekey="'+esc(f.key)+'" data-nekind="'+f.kind+'" type="'+t+'" step="any" value="'+esc(f.value==null?'':String(f.value))+'" class="input-field text-xs">';
  }
  return '<div class="my-1"><div class="text-gray-500" style="font-size:10px">'+esc(f.label)+'</div>'+inner+'</div>';
}

function neTable(f,fid){
  const tid='netbl_'+fid;
  _NETABLES[f.key]={columns:f.columns,tid:tid};
  let h='<div class="my-1"><div class="font-bold" style="font-size:10px;color:#6d28d9">'+esc(f.label)+'</div>';
  h+='<table class="w-full text-xs" style="border-collapse:collapse"><thead><tr>';
  (f.columns||[]).forEach(c=>{h+='<th style="border:1px solid #e5e7eb;padding:1px 3px;font-size:9px">'+esc(c.name)+'</th>';});
  h+='<th></th></tr></thead><tbody id="'+tid+'">';
  (f.rows||[]).forEach(r=>{h+=neRow(f.key,r);});
  h+='</tbody></table>';
  h+='<button class="text-xs px-2 rounded mt-1" style="background:#e5e7eb;border:none;cursor:pointer" onclick="neAddRow(\''+esc(f.key)+'\')">+ 행</button></div>';
  return h;
}

function neRow(key,row){
  const cols=_NETABLES[key].columns; row=row||{};
  let h='<tr>';
  cols.forEach(c=>{
    h+='<td style="border:1px solid #e5e7eb;padding:1px">';
    if(c.type==='select'){
      const opts=(c.options&&c.options.length)?c.options:STATE.chemList.map(x=>x.name);
      h+='<select class="input-field text-xs" data-necol="'+esc(c.name)+'" style="padding:1px;font-size:10px"><option value=""></option>';
      opts.forEach(o=>{h+='<option'+(String(row[c.name])===String(o)?' selected':'')+'>'+esc(o)+'</option>';});
      h+='</select>';
    }else{
      const t=c.type==='number'?'number':'text';
      h+='<input class="input-field text-xs" data-necol="'+esc(c.name)+'" type="'+t+'" step="any" value="'+esc(row[c.name]==null?'':String(row[c.name]))+'" style="padding:1px;font-size:10px;width:64px">';
    }
    h+='</td>';
  });
  h+='<td><button style="color:#dc2626;border:none;background:none;cursor:pointer;font-size:10px" onclick="this.closest(\'tr\').remove()">×</button></td></tr>';
  return h;
}

function neAddRow(key){
  const t=document.getElementById(_NETABLES[key].tid);if(t)t.insertAdjacentHTML('beforeend',neRow(key,{}));
}

async function saveNodeEdit(){
  if(!_NODEEDIT)return;
  const nodeId=_NODEEDIT.nodeId, value={};
  document.querySelectorAll('#bfd-props-panel [data-nekey]').forEach(el=>{
    const key=el.getAttribute('data-nekey'), kind=el.getAttribute('data-nekind');
    if(kind==='bool')value[key]=el.checked;
    else if(kind==='number')value[key]=parseFloat(el.value)||0;
    else if(kind==='int')value[key]=parseInt(el.value||'0',10)||0;
    else value[key]=el.value;
  });
  Object.keys(_NETABLES).forEach(key=>{
    const t=document.getElementById(_NETABLES[key].tid);if(!t)return;
    const cols=_NETABLES[key].columns, rows=[];
    t.querySelectorAll('tr').forEach(tr=>{
      const row={}; let has=false;
      tr.querySelectorAll('[data-necol]').forEach(el=>{
        const cn=el.getAttribute('data-necol'), col=cols.find(c=>c.name===cn);
        let v=el.value; if(col&&col.type==='number')v=parseFloat(v)||0;
        row[cn]=v; if(cn===cols[0].name && v!=='' && v!=null)has=true;
      });
      if(has)rows.push(row);
    });
    value[key]=rows;
  });
  const name=document.getElementById('ne-name').value;
  try{
    const r=await fetch('/api/bfd/node/'+encodeURIComponent(nodeId),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,value})});
    const d=await r.json(); if(d.detail)throw new Error(d.detail);
    const n=STATE.bfdNodes.find(x=>x.id===nodeId); if(n&&d.node){n.params=d.node.params;n.label=d.node.label;}
    await fetch('/api/bfd/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nodes:STATE.bfdNodes,edges:STATE.bfdEdges})});
    initBFD(); renderNodePropsPanel(nodeId);
    alert('노드 저장 및 처리 완료');
  }catch(e){alert('저장 실패: '+(e.message||e));}
}

document.addEventListener('mousemove',ev=>{
  const cont=document.getElementById('bfd-container');
  const svg=document.getElementById('bfd-svg');
  if(!cont||!svg)return;
  if(BFD_DRAG){
    const rect=cont.getBoundingClientRect();
    BFD_DRAG.node.x=Math.max(0,Math.min(ev.clientX-BFD_DRAG.offsetX,rect.width-130));
    BFD_DRAG.node.y=Math.max(0,Math.min(ev.clientY-BFD_DRAG.offsetY,rect.height-60));
    initBFD();
  }
  if(BFD_LINK){
    if(!BFD_LINK_EL){
      BFD_LINK_EL=document.createElementNS('http://www.w3.org/2000/svg','path');
      BFD_LINK_EL.setAttribute('stroke','#3b82f6');BFD_LINK_EL.setAttribute('stroke-width','2');
      BFD_LINK_EL.setAttribute('stroke-dasharray','5,3');BFD_LINK_EL.setAttribute('fill','none');
      svg.appendChild(BFD_LINK_EL);
    }
    const rect=svg.getBoundingClientRect();
    BFD_LINK_EL.setAttribute('d',`M ${BFD_LINK.x+60} ${BFD_LINK.y+44} L ${ev.clientX-rect.left} ${ev.clientY-rect.top}`);
  }
});
document.addEventListener('mouseup',async ev=>{
  if(BFD_DRAG){
    await fetch('/api/bfd/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nodes:STATE.bfdNodes,edges:STATE.bfdEdges})});
    BFD_DRAG=null;
  }
  if(BFD_LINK){
    const targetDiv=ev.target.closest('#bfd-container .bfd-node');
    if(targetDiv&&targetDiv.dataset.nodeId&&targetDiv.dataset.nodeId!==BFD_LINK.id){
      await createEdge(BFD_LINK.id,targetDiv.dataset.nodeId);
    }
    BFD_LINK=null;if(BFD_LINK_EL){BFD_LINK_EL.remove();BFD_LINK_EL=null;}
  }
});

// ============================================================
// PROJECT MANAGEMENT
// ============================================================
async function loadProjectList(){
  try{const r=await fetch('/api/project/list');const d=await r.json();STATE.projectList=d.projects||[];render();}catch(e){}
}
async function saveProject(){
  const name=document.getElementById('proj-save-name')?.value?.trim()||STATE.project.name||'프로젝트';
  if(!name){alert('프로젝트 이름을 입력하세요.');return;}
  const body={name,chemicals:STATE.chemList,solutions:STATE.solList,bfd:{nodes:STATE.bfdNodes,edges:STATE.bfdEdges},project:STATE.project,scenarios:STATE.scenarios,utilities:{}};
  await fetch('/api/project/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  alert('프로젝트 "'+name+'" 저장 완료!');
  await loadProjectList();
}
async function loadProject(name){
  const r=await fetch('/api/project/load/'+encodeURIComponent(name));
  const d=await r.json();if(d.error){alert(d.error);return;}
  const data=d.data;
  STATE.project=data.project||STATE.project;
  STATE.scenarios=(data.scenarios||[]).map((sc,i)=>({id:i+1,...sc}));
  STATE.nextId=(STATE.scenarios.length)+1;
  STATE.chemList=data.chemicals||[];STATE.solList=data.solutions||[];
  STATE.bfdNodes=(data.bfd||{}).nodes||[];STATE.bfdEdges=(data.bfd||{}).edges||[];
  STATE.results=[];
  render();setTimeout(initBFD,100);
  alert('프로젝트 "'+name+'" 로드 완료!');
}
async function deleteProject(name){
  if(!confirm('"'+name+'" 프로젝트를 삭제하시겠습니까?'))return;
  await fetch('/api/project/'+encodeURIComponent(name),{method:'DELETE'});
  await loadProjectList();
}

// ============================================================
// SCALE UP
// ============================================================
function runScaleUp(){
  const g=id=>parseFloat(document.getElementById(id)?.value||0);
  const r=FermEngine.scaleUpCapex(g('su__knownCapex'),g('su__knownCap'),g('su__targetCap'),g('su__exponent'));
  const el=document.getElementById('scaleup-result');
  if(el)el.innerHTML='<div class="p-3 rounded" style="background:var(--green-light)"><span class="font-bold" style="color:var(--green)">결과: '+r+' Mn$ </span><span class="text-gray-500">(Scale Factor: '+(g('su__targetCap')/g('su__knownCap')).toFixed(2)+'x)</span></div>';
}

// ============================================================
// TAB RENDERERS
// ============================================================
function renderInputTab(){
  const P=STATE.project,S=STATE.scenarios;
  let h='<div class="card p-5 mb-4"><div class="flex justify-between items-center mb-4"><div class="section-title">프로젝트 기본 정보</div><div class="flex gap-2"><label class="btn-secondary text-xs flex items-center gap-1 cursor-pointer" style="padding:6px 14px"><input type="file" accept=".csv,.tsv,.txt,.md,.xlsx,.xls" class="hidden" onchange="handleFileUpload(this.files[0])">파일 업로드</label></div></div>';
  h+='<div class="grid grid-cols-5 gap-3 mb-3">'+inputField('proj__name','프로젝트 이름',P.name)+inputField('proj__product','제품명',P.product)+inputField('proj__analyst','분석자',P.analyst)+inputField('proj__exchangeRate','환율',P.exchangeRate,'원/$','number')+inputField('proj__discountRate','할인율',P.discountRate,'%','number')+'</div>';
  h+='<div class="grid grid-cols-5 gap-3">'+inputField('proj__taxRate','법인세율',P.taxRate,'%','number')+inputField('proj__analysisYears','분석 기간',P.analysisYears,'년','number')+inputField('proj__constructionYears','건설 기간',P.constructionYears,'년','number')+'<div class="col-span-2 flex items-end gap-2"><button class="btn-primary text-xs" onclick="setState({showBenchmarkModal:true})"'+(S.length>=MAX_SCENARIOS?' disabled':'')+'> + 벤치마크 추가</button><button class="btn-secondary text-xs" onclick="addEmptyScenario()"'+(S.length>=MAX_SCENARIOS?' disabled':'')+'> + 빈 시나리오</button><span class="text-xs ml-2 '+(S.length>=MAX_SCENARIOS?'text-red-500 font-bold':'text-gray-400')+'">'+S.length+'/'+MAX_SCENARIOS+'</span></div></div></div>';

  if(!S.length){
    h+='<div class="drop-zone" ondragover="event.preventDefault();this.classList.add(\'dragover\')" ondragleave="this.classList.remove(\'dragover\')" ondrop="event.preventDefault();this.classList.remove(\'dragover\');handleFileUpload(event.dataTransfer.files[0])"><div class="text-4xl mb-2">📄</div><div class="text-gray-500 mb-3">시나리오를 추가하여 경제성 분석을 시작하세요</div><button class="btn-primary" onclick="setState({showBenchmarkModal:true})">벤치마크 라이브러리에서 추가</button></div>';
  }

  S.forEach((sc,i)=>{
    if(!sc.fermConfig)sc.fermConfig={enabled:false,titer:10,yieldPct:30,productivity:0.5,temp:30,fermTime:48,initOD:0.5,finalOD:100,vvm:1,wvPct:70,vesselM3:100,sipTime:2,cipTime:2,transferTime:2,sipTemp:130,steamPrice:0.019,elecPrice:0.128,coolPrice:5.33e-5,sipStreamRate:0.5,agitationEff:3,gmp:true,operatingHours:7920,solutions:[],inMass:{},outMass:{},media:[]};
    const cs=STATE.collapsedSections,vo=!cs['var_'+sc.id],fo=!cs['fix_'+sc.id],fmo=!cs['ferm_'+sc.id],dso=!cs['ds_'+sc.id];
    h+='<div class="card mb-3 overflow-hidden"><div class="flex justify-between items-center px-4 py-3" style="background:var(--green-light)"><span class="font-bold text-sm" style="color:var(--green)">시나리오 '+(i+1)+'</span><button class="btn-danger" onclick="removeScenario('+sc.id+')">삭제</button></div><div class="p-4">';
    h+='<div class="grid grid-cols-2 gap-3 mb-3">'+inputField('sc__'+sc.id+'__name','시나리오 이름',sc.name)+inputField('sc__'+sc.id+'__fermentation','발효 파라미터',sc.fermentation||'')+'</div>';
    const bio=sc._biosteamResult&&sc._biosteamResult.success?sc._biosteamResult:null;
    const subChem=bio&&bio.substrate?bio.substrate.chemical:'탄소원';
    const 원단위Tip='기질 원단위 = 제품 1 MT(1000kg) 생산에 필요한 기질(탄소원) 소비량 (kg/MT). BioSTEAM 물질수지에서 도출됩니다.';
    h+='<div class="grid grid-cols-4 gap-3 mb-3">';
    h+=inputField('sc__'+sc.id+'__capacity','Capacity',sc.capacity,'MT/yr','number');
    h+= bio ? derivedField('CAPEX',sc.capex,'Mn$','BioSTEAM','BioSTEAM 시뮬레이션에서 도출된 설비투자비')
            : inputField('sc__'+sc.id+'__capex','CAPEX',sc.capex,'Mn$','number','BioSTEAM 실행 후 자동 도출됩니다. 미실행 시 수동 입력.');
    h+= bio ? derivedField('기질 단가',sc.glucosePrice,'$/MT','화학물질 DB',subChem+' 단가(화학물질 DB) × 1000')
            : inputField('sc__'+sc.id+'__glucosePrice','기질 단가',sc.glucosePrice,'$/MT','number','탄소원 단가. BioSTEAM 실행 시 화학물질 DB 값으로 자동 반영됩니다.');
    h+= bio ? derivedField('기질 원단위',sc.glucoseUnit,'kg/MT','BioSTEAM',원단위Tip)
            : inputField('sc__'+sc.id+'__glucoseUnit','기질 원단위',sc.glucoseUnit,'kg/MT','number',원단위Tip);
    h+='</div>';

    h+='<div class="collapsible-header mb-2" onclick="toggleSection(\'ds_'+sc.id+'\')"><span class="arrow '+(dso?'open':'')+'">▶</span><span class="text-xs font-bold" style="color:#7c3aed">🔗 데이터 연동 (화학물질DB · 용액관리 · BioSTEAM)</span></div>';
    if(dso){
      h+='<div class="ml-2 mb-3 p-3 rounded-lg" style="background:#faf5ff;border:1px solid #e9d5ff">';

      h+='<div class="grid grid-cols-2 gap-3 mb-3">';
      h+='<div class="p-2 rounded" style="background:#fff;border:1px solid #e2e8f0">';
      h+='<div class="flex justify-between items-center mb-1"><span class="text-xs font-bold" style="color:#92400e">⚗ 화학물질 DB</span><button class="text-xs px-2 py-0.5 rounded" style="background:#fef3c7;color:#92400e;border:1px solid #fde68a;cursor:pointer" onclick="goTab(\'chem\')">편집 →</button></div>';
      const nChem=STATE.chemList.length;
      h+='<div class="text-xs text-gray-500">등록된 화학물질: <b>'+nChem+'종</b></div>';
      if(nChem>0)h+='<div class="text-xs text-gray-400 mt-1">'+STATE.chemList.slice(0,5).map(c=>esc(c.name)+'($'+c.price+')').join(', ')+(nChem>5?' ...':'')+'</div>';
      h+='</div>';

      h+='<div class="p-2 rounded" style="background:#fff;border:1px solid #e2e8f0">';
      h+='<div class="flex justify-between items-center mb-1"><span class="text-xs font-bold" style="color:#92400e">⚗ 용액 관리</span><button class="text-xs px-2 py-0.5 rounded" style="background:#fef3c7;color:#92400e;border:1px solid #fde68a;cursor:pointer" onclick="goTab(\'sol\')">편집 →</button></div>';
      const nSol=STATE.solList.length;
      h+='<div class="text-xs text-gray-500">등록된 용액: <b>'+nSol+'개</b></div>';
      if(nSol>0){
        let totalSolCost=0;
        STATE.solList.forEach(sol=>{totalSolCost+=parseFloat(calcSolCost(sol))||0;});
        h+='<div class="text-xs text-gray-400 mt-1">'+STATE.solList.map(s=>esc(s.user_name)+' ($'+calcSolCost(s)+'/L)').join(', ')+'</div>';
        h+='<div class="text-xs text-gray-400 mt-1">💡 용액 사용량·부재료비는 BFD의 발효기 solution flow에서 BioSTEAM이 실제 소비량으로 계산합니다.</div>';
      }
      h+='</div>';
      h+='</div>';


      h+='<div class="p-2 rounded" style="background:#fff;border:1px solid #e2e8f0">';
      h+='<div class="flex justify-between items-center mb-1"><span class="text-xs font-bold" style="color:#1d4ed8">⚗ BioSTEAM 공정 시뮬레이션</span>';
      if(BIOSTEAM_OK)h+='<span class="badge" style="background:#dcfce7;color:#15803d">Ready</span>';
      else h+='<span class="badge" style="background:#f1f5f9;color:#9ca3af">미설치</span>';
      h+='</div>';
      if(BIOSTEAM_OK){
        h+='<div class="text-xs text-gray-500 mb-2">공정 흐름도(BFD) 기반 물질수지 → CAPEX·OPEX 자동 계산</div>';
        h+='<div class="grid grid-cols-4 gap-2 mb-2">';
        h+='<div><label class="text-xs text-gray-500">Target Product</label><select id="bio-prod-'+sc.id+'" class="input-field text-xs" onchange="STATE.bioProduct=this.value">';
        STATE.chemList.forEach(c=>h+='<option value="'+esc(c.name)+'"'+((STATE.bioProduct||STATE.project.product)===c.name?' selected':'')+'>'+esc(c.name)+'</option>');
        h+='</select></div>';
        h+='<div><label class="text-xs text-gray-500">Carbon Source</label><select id="bio-src-'+sc.id+'" class="input-field text-xs" onchange="STATE.bioSource=this.value">';
        STATE.chemList.forEach(c=>h+='<option value="'+esc(c.name)+'"'+(STATE.bioSource===c.name?' selected':'')+'>'+esc(c.name)+'</option>');
        h+='</select></div>';
        h+='<div><label class="text-xs text-gray-500 flex items-center gap-1"><input id="bio-gmp-'+sc.id+'" type="checkbox" checked> GMP</label></div>';
        h+='<div><label class="text-xs text-gray-500">운영시간(h/yr)</label><input id="bio-oph-'+sc.id+'" class="input-field text-xs" type="number" value="7920"></div>';
        h+='</div>';
        h+='<div class="flex items-center gap-2"><button class="text-xs px-3 py-1 rounded font-bold" style="background:#1d4ed8;color:#fff;border:none;cursor:pointer" onclick="runBiosteamForScenario('+sc.id+')" '+(BIOSTEAM_RUNNING?'disabled':'')+'>🔮 BioSTEAM 시뮬레이션 → 시나리오에 반영</button>';
        if(sc._biosteamApplied)h+='<span class="text-xs" style="color:#15803d">✓ BioSTEAM 결과 적용됨</span>';
        h+='</div>';
        if(sc._biosteamResult&&sc._biosteamResult.success){
          const c=sc._biosteamResult;
          h+='<div class="mt-2 p-2 rounded text-xs" style="background:#dbeafe"><div class="grid grid-cols-4 gap-1">';
          h+='<span>CAPEX: <b>$'+fmt(c.capexMn,1)+'M</b></span>';
          h+='<span>원재료: <b>$'+fmt(c.rawMaterial)+'/MT</b></span>';
          h+='<span>부재료: <b>$'+fmt(c.subMaterial)+'/MT</b></span>';
          h+='<span>스팀: <b>$'+fmt(c.steam)+'/MT</b></span>';
          h+='<span>전기: <b>$'+fmt(c.electricity)+'/MT</b></span>';
          h+='<span>냉각: <b>$'+fmt(c.cooling)+'/MT</b></span>';
          h+='<span>폐기물: <b>$'+fmt(c.waste)+'/MT</b></span>';
          h+='</div></div>';
        }else if(sc._biosteamResult&&!sc._biosteamResult.success){
          h+='<div class="mt-2 p-2 rounded text-xs" style="background:#fef2f2">';
          h+='<div style="color:#dc2626"><b>✗ Error:</b> '+esc(sc._biosteamResult.error||'오류')+'</div>';
          if(sc._biosteamResult.unit_hint)h+='<div style="color:#ea580c"><b>Unit:</b> '+esc(sc._biosteamResult.unit_hint)+'</div>';
          if(sc._biosteamResult.detail)h+='<details><summary style="color:#9ca3af;cursor:pointer">상세</summary><pre style="white-space:pre-wrap;font-size:9px;max-height:150px;overflow:auto;background:#fff;padding:4px;border-radius:4px;margin-top:4px">'+esc(sc._biosteamResult.detail)+'</pre></details>';
          h+='</div>';
        }
      }else{
        h+='<div class="text-xs text-gray-400">biosteam 패키지를 설치하면 공정 물질수지 기반 CAPEX·OPEX 자동 계산이 가능합니다.</div>';
      }
      h+='</div>';

      h+='</div>';
    }

    h+='<div class="collapsible-header mb-2" onclick="toggleSection(\'fix_'+sc.id+'\')"><span class="arrow '+(fo?'open':'')+'">▶</span><span class="section-title mb-0">고정비</span></div>';
    if(fo)h+='<div class="grid grid-cols-4 gap-2 mb-3 ml-4">'+inputField('sc__'+sc.id+'__headcount','인원수',sc.headcount,'명','number')+inputField('sc__'+sc.id+'__laborCost','인건비 단가',sc.laborCost,'억원/년','number')+inputField('sc__'+sc.id+'__otherFixed','기타 고정비',sc.otherFixed,'$/MT','number')+inputField('sc__'+sc.id+'__sellingPrice','판매가',sc.sellingPrice,'$/MT','number')+'</div>';
    h+='</div></div>';
  });

  if(S.length){
    h+='<div class="flex justify-center items-center gap-2 mt-4 mb-1">';
    h+='<button class="btn-secondary text-sm" onclick="addEmptyScenario()"'+(S.length>=MAX_SCENARIOS?' disabled':'')+'>+ 시나리오 추가</button>';
    h+='<button class="btn-secondary text-sm" onclick="setState({showBenchmarkModal:true})"'+(S.length>=MAX_SCENARIOS?' disabled':'')+'>+ 벤치마크에서 추가</button>';
    h+='<span class="text-xs '+(S.length>=MAX_SCENARIOS?'text-red-500 font-bold':'text-gray-400')+'">'+S.length+'/'+MAX_SCENARIOS+' 시나리오 (여러 개를 추가하면 분석 결과에서 나란히 비교됩니다)</span>';
    h+='</div>';
    h+='<div class="flex justify-center mt-2"><button class="btn-primary px-10 py-3 text-base" onclick="runAnalysis()">🔍 경제성 분석 실행</button></div>';
  }
  return h;
}

function renderResultsTab(){
  if(!STATE.results.length)return'<div class="card p-10 text-center text-gray-400"><div class="text-4xl mb-3">📊</div><div>시나리오 입력 탭에서 분석을 실행하세요</div></div>';
  const R=STATE.results;
  // BioSTEAM linkage banner: analysis uses BioSTEAM-derived costs only for
  // scenarios that have been applied.  Surface the state and offer a one-click.
  const appliedN=STATE.scenarios.filter(s=>s._biosteamApplied).length;
  const bioReady=BIOSTEAM_RESULT&&BIOSTEAM_RESULT.success;
  let h='';
  if(appliedN===STATE.scenarios.length&&appliedN>0){
    h+='<div class="mb-3 p-2 rounded text-xs" style="background:#f0fdf4;border:1px solid #bbf7d0;color:#15803d">✓ 아래 결과는 <b>BioSTEAM 시뮬레이션</b>에서 도출된 CAPEX·원부재료·유틸리티 원가를 기반으로 합니다.</div>';
  }else if(bioReady){
    h+='<div class="mb-3 p-2 rounded text-xs flex items-center justify-between" style="background:#fffbeb;border:1px solid #fde68a;color:#92400e"><span>⚠ BioSTEAM 결과가 일부 시나리오('+appliedN+'/'+STATE.scenarios.length+')에만 반영되었습니다. 결과를 BioSTEAM 기반으로 통일하려면 적용하세요.</span><button class="btn-sm" style="background:#92400e;color:#fff;border:none" onclick="applyBiosteamToAllScenarios();runAnalysis()">전체에 적용 후 재분석</button></div>';
  }else{
    h+='<div class="mb-3 p-2 rounded text-xs" style="background:#f8fafc;border:1px solid #e2e8f0;color:#64748b">ℹ 현재 결과는 시나리오 입력값 기반입니다. <b>공정 흐름도</b> 탭에서 BioSTEAM을 실행하면 물질수지 기반 원가로 분석할 수 있습니다. <button class="text-xs underline" style="border:none;background:none;color:#1d4ed8;cursor:pointer" onclick="goTab(\'bfd\')">→ 공정 흐름도</button></div>';
  }
  h+='<div class="flex gap-2 mb-4 flex-wrap">';
  h+='<button class="btn-secondary text-xs" onclick="exportCSV()">CSV 내보내기</button>';
  h+='<button class="btn-secondary text-xs" onclick="exportExcel()">Excel 내보내기</button>';
  h+='</div>';
  h+='<div class="grid grid-cols-'+Math.min(R.length,4)+' gap-3 mb-4">';
  R.forEach(r=>{
    const npvColor=r.npv>=0?'var(--green)':'#dc2626',decision=r.npv>0&&r.irr>15&&r.bcRatio>1.2?'투자 권고':'검토 필요';
    h+='<div class="card p-4"><div class="font-bold text-sm mb-3 truncate" style="color:var(--green)">'+esc(r.name)+'</div>';
    h+='<div class="grid grid-cols-2 gap-2 text-xs">';
    h+='<div><div class="text-gray-400">NPV</div><div class="font-bold text-base" style="color:'+npvColor+'">'+r.npv+' Mn$</div></div>';
    h+='<div><div class="text-gray-400">IRR</div><div class="font-bold text-base">'+(r.irr!=null?r.irr+'%':'-')+'</div></div>';
    h+='<div><div class="text-gray-400">BC Ratio</div><div class="font-bold">'+r.bcRatio+'</div></div>';
    h+='<div><div class="text-gray-400">Payback</div><div class="font-bold">'+(r.payback!=null?r.payback+'년':'-')+'</div></div>';
    h+='<div><div class="text-gray-400">제조원가</div><div class="font-bold">$'+r.manufacturingCost+'/MT</div></div>';
    h+='<div><div class="text-gray-400">판단</div><div class="font-bold text-xs" style="color:'+(decision==='투자 권고'?'var(--green)':'#f59e0b')+'">'+decision+'</div></div>';
    h+='</div></div>';
  });
  h+='</div>';
  h+='<div class="card overflow-hidden"><div class="overflow-x-auto"><table class="tea-table"><thead><tr><th style="text-align:left">항목</th>'+R.map(r=>'<th>'+esc(r.name)+'</th>').join('')+'</tr></thead><tbody>';
  const rows=[['Capacity (MT/yr)',r=>r.capacityMT.toLocaleString()],['CAPEX (Mn$)',r=>r.capexMnUsd],['총투자비 (억원)',r=>r.totalInvestKRW.toLocaleString()],[' --- 변동비 ($/MT) ---',()=>''],['원재료비',r=>r.rawMaterial],['부재료',r=>r.subMaterial],['스팀',r=>r.steam],['전기',r=>r.electricity],['냉각',r=>r.cooling],['폐기물',r=>r.waste],['변동비 합계',r=>r.variableTotal],[' --- 고정비 ($/MT) ---',()=>''],['인무비',r=>r.labor],['감가상각',r=>r.depreciation],['수선비',r=>r.maintenance],['기타 고정비',r=>r.otherFixed],['고정비 합계',r=>r.fixedTotal],['제조원가 ($/MT)',r=>r.manufacturingCost],['판매가 ($/MT)',r=>r.sellingPrice],[' --- 경제성 지표 ---',()=>''],['NPV (Mn$)',r=>r.npv],['IRR (%)',r=>r.irr!=null?r.irr:'N/A'],['BC Ratio',r=>r.bcRatio],['Payback (년)',r=>r.payback!=null?r.payback:'N/A']];
  rows.forEach(([l,fn])=>{const isSec=l.startsWith(' ---');h+='<tr class="'+(isSec?'section-header':'')+'"><td>'+esc(l.replace(/ --- /g,''))+'</td>'+(isSec?R.map(()=>'<td></td>').join(''):R.map(r=>'<td>'+fn(r)+'</td>').join(''))+'</tr>';});
  h+='</tbody></table></div></div>';
  return h;
}

function renderChartsTab(){
  if(!STATE.results.length)return'<div class="card p-10 text-center text-gray-400"><div class="text-4xl mb-3">📈</div><div>먼저 분석을 실행하세요</div></div>';
  const R=STATE.results;
  let h='<div class="flex gap-2 mb-4 flex-wrap">';
  R.forEach((r,i)=>h+='<button class="btn-sm '+(STATE.selectedChart===i?'btn-primary':'btn-secondary')+'" onclick="setState({selectedChart:'+i+'});setTimeout(renderCharts,50)">'+esc(r.name.substring(0,12))+'</button>');
  h+='</div>';
  h+='<div class="grid grid-cols-2 gap-4"><div class="card p-4"><canvas id="chart-waterfall"></canvas></div><div class="card p-4"><canvas id="chart-comparison"></canvas></div><div class="card p-4"><canvas id="chart-npv"></canvas></div><div class="card p-4"><canvas id="chart-cashflow"></canvas></div></div>';
  return h;
}

function renderFermTab(){
  // BioSTEAM-based: show the base CAPEX, current target, and back-calculated
  // titer from the most recent successful BioSTEAM run.
  const c=BIOSTEAM_RESULT&&BIOSTEAM_RESULT.success?BIOSTEAM_RESULT:null;
  let h='<div style="max-width:900px">';
  h+='<div class="section-title text-base mb-3">🧫 발효 공정 (BioSTEAM 기반)</div>';
  if(!BIOSTEAM_OK){
    h+='<div class="card p-6 text-center text-gray-400">BioSTEAM이 설치되어야 발효 공정 계산이 가능합니다. (유틸리티/부재료 탭·공정 흐름도 탭 참고)</div></div>';
    return h;
  }
  if(!c){
    h+='<div class="card p-6"><div class="text-sm text-gray-600 mb-3">아직 BioSTEAM 결과가 없습니다. <b>공정 흐름도</b> 탭에서 BFD를 구성하고 <b>BioSTEAM 시뮬레이션</b>을 실행하면 여기에 기준 CAPEX·목표 생산량·Titer가 표시됩니다.</div>';
    h+='<button class="btn-primary text-sm" onclick="goTab(\'bfd\')">→ 공정 흐름도로 이동</button></div>';
  }else{
    h+='<div class="card p-5 mb-4"><div class="font-bold text-sm mb-3" style="color:var(--green)">📊 BioSTEAM 기준 결과</div>';
    h+='<div class="grid grid-cols-3 gap-3">';
    h+='<div class="p-3 rounded" style="background:#f0fdf4;border:1px solid #bbf7d0"><div class="text-xs text-gray-500">기준 CAPEX</div><div class="font-bold text-lg" style="color:#15803d">$'+fmt(c.capexMn,2)+' M</div></div>';
    h+='<div class="p-3 rounded" style="background:#eff6ff;border:1px solid #bfdbfe"><div class="text-xs text-gray-500">현재 기준 Target 생산량</div><div class="font-bold text-lg" style="color:#1d4ed8">'+fmtComma(c.target_MT_per_yr)+' MT/yr</div></div>';
    h+='<div class="p-3 rounded" style="background:#faf5ff;border:1px solid #e9d5ff"><div class="text-xs text-gray-500">Titer (BioSTEAM 역산)</div><div class="font-bold text-lg" style="color:#6d28d9">'+fmt(c.titer_g_per_L,2)+' g/L</div></div>';
    h+='</div>';
    if(c.logic){
      h+='<div class="grid grid-cols-3 gap-2 mt-3 text-xs text-gray-600">';
      h+='<div>배치 시간: <b>'+fmt(c.logic.batch_time_h,1)+' h</b></div>';
      h+='<div>운영시간: <b>'+fmtComma(c.logic.operating_hours)+' h/yr</b></div>';
      h+='<div>주 제품 / 탄소원: <b>'+esc(c.logic.main_product||'')+' / '+esc(c.logic.main_source||'')+'</b></div>';
      h+='</div>';
    }
    h+='<div class="text-xs text-gray-400 mt-2">* Titer = 발효기 최종 broth 부피 기준 제품 농도(BioSTEAM 물질수지에서 역산). 목표 생산량은 공정 흐름도 탭의 Target(MT/yr) 값입니다.</div>';
    h+='</div>';
    h+='<div class="card p-4 mb-4"><div class="font-bold text-sm mb-2" style="color:var(--green)">유틸리티 / 원부재료 (BioSTEAM $/MT)</div>';
    h+='<div class="grid grid-cols-4 gap-2 text-xs">';
    [['원재료',c.rawMaterial],['부재료',c.subMaterial],['스팀',c.steam],['전기',c.electricity],['냉각',c.cooling],['폐기물',c.waste],['감가상각',c.depreciation],['인건비',c.labor]].forEach(([l,v])=>{h+='<div class="p-2 rounded" style="background:#f8fafc;border:1px solid #e2e8f0"><div class="text-gray-500">'+l+'</div><div class="font-bold">$'+fmt(v)+'/MT</div></div>';});
    h+='</div></div>';
  }
  h+='<div class="card p-4"><div class="font-bold text-sm mb-3" style="color:var(--green)">📐 CAPEX Scale-up 계산기 (0.6 Power Law)</div>';
  h+='<div class="text-xs text-gray-400 mb-2">기준 CAPEX/생산량은 위 BioSTEAM 결과를 사용할 수 있습니다.</div>';
  h+='<div class="grid grid-cols-4 gap-3 mb-3">'+inputField('su__knownCapex','기준 CAPEX',c?+(c.capexMn||0).toFixed(2):50,'Mn$','number')+inputField('su__knownCap','기준 생산량',c?c.target_MT_per_yr:1000,'MT/yr','number')+inputField('su__targetCap','목표 생산량',5000,'MT/yr','number')+inputField('su__exponent','Scale 지수',0.6,'','number')+'</div>';
  h+='<button class="btn-primary text-xs" onclick="runScaleUp()">계산</button><div id="scaleup-result" class="mt-3 text-xs"></div></div>';
  h+='</div>';
  return h;
}

function renderBenchmarkTab(){
  let h='<div class="section-title text-base mb-4">📚 벤치마크 제품 라이브러리</div><div class="grid grid-cols-2 gap-4">';
  Object.entries(BENCHMARKS).forEach(([key,bm])=>{
    h+='<div class="card p-4"><div class="flex justify-between items-start mb-2"><div><div class="font-bold text-sm" style="color:var(--green)">'+esc(bm.name)+'</div><span class="badge" style="background:var(--green-light);color:var(--green)">'+esc(bm.cat)+'</span></div><button class="btn-primary text-xs" onclick="addFromBenchmark(\''+key.replace(/'/g,"\\'")+'\')" '+(STATE.scenarios.length>=MAX_SCENARIOS?'disabled':'')+'> + 추가</button></div>';
    h+='<div class="grid grid-cols-3 gap-2 text-xs mt-2"><div class="text-gray-400">Titer<br><b>'+bm.titer+' g/L</b></div><div class="text-gray-400">Yield<br><b>'+bm.yield+'%</b></div><div class="text-gray-400">Productivity<br><b>'+bm.prod+' g/L/h</b></div><div class="text-gray-400">생산량<br><b>'+bm.defaults.capacity+' MT/yr</b></div><div class="text-gray-400">CAPEX<br><b>'+bm.defaults.capex+' Mn$</b></div><div class="text-gray-400">판매가<br><b>$'+bm.defaults.sellingPrice.toLocaleString()+'/MT</b></div></div>';
    h+='</div>';
  });
  h+='</div>';
  return h;
}

function renderChemTab(){
  const chems=STATE.chemList;
  let h='<div class="card p-5 mb-4"><div class="section-title text-base mb-3">⚗ 화학물질 데이터베이스</div>';
  h+='<div class="border rounded-lg p-4 mb-4" style="background:#f8fafc"><div class="font-bold text-sm mb-3" style="color:var(--green)">신규 화학물질 등록</div>';
  h+='<div class="grid grid-cols-5 gap-3 mb-3"><div class="flex-1"><div class="text-xs text-gray-500 mb-1">물질명</div><input id="chem-name" class="input-field" placeholder="Glucose"></div>';
  h+='<div class="flex-1"><div class="text-xs text-gray-500 mb-1">화학식</div><input id="chem-formula" class="input-field" placeholder="C6H12O6"></div>';
  h+='<div class="flex-1"><div class="text-xs text-gray-500 mb-1">단가 ($/kg)</div><input id="chem-price" class="input-field" type="number" placeholder="0.4"></div>';
  h+='<div class="flex-1"><div class="text-xs text-gray-500 mb-1">상태</div><select id="chem-phase" class="input-field"><option value="l">액체 (l)</option><option value="s">고체 (s)</option><option value="g">기체 (g)</option></select></div>';
  h+='<div class="flex items-end"><button class="btn-primary text-xs w-full" onclick="addChemical()">+ 등록</button></div></div>';
  h+='<div class="flex gap-2"><label class="btn-secondary text-xs cursor-pointer"><input type="file" accept=".csv" class="hidden" onchange="uploadChemCSV(this.files[0])">CSV 일괄 업로드</label><button class="btn-secondary text-xs" onclick="loadChemicals()">🔄 새로고침</button></div></div>';
  h+='<div class="overflow-x-auto"><table class="tea-table"><thead><tr><th style="text-align:left">물질명</th><th style="text-align:left">화학식</th><th>단가 ($/kg)</th><th>상태</th><th>관리</th></tr></thead><tbody>';
  if(!chems.length)h+='<tr><td colspan="5" class="text-center text-gray-400 py-4">화학물질 데이터가 없습니다. 새로고침을 눌러 기본 DB를 로드하세요.</td></tr>';
  else chems.forEach(c=>{
    const phaseLabel={'l':'액체','s':'고체','g':'기체'}[c.phase]||c.phase;
    h+='<tr><td class="font-semibold">'+esc(c.name)+'</td><td class="text-gray-500">'+esc(c.formula)+'</td>';
    h+='<td><input type="number" value="'+c.price+'" class="input-field text-right" style="width:100px" onblur="updateChemicalPrice(\''+esc(c.name)+'\',this.value)"></td>';
    h+='<td><span class="badge" style="background:#f1f5f9;color:#475569">'+phaseLabel+'</span></td>';
    h+='<td><button class="btn-danger" onclick="deleteChemical(\''+esc(c.name)+'\')">삭제</button></td></tr>';
  });
  h+='</tbody></table></div></div>';
  return h;
}

async function uploadChemCSV(file){
  if(!file)return;
  const formData=new FormData();formData.append('file',file);
  await fetch('/api/chemicals/upload',{method:'POST',body:formData});
  await loadChemicals();
}

function renderSolutionTab(){
  const sols=STATE.solList;
  let h='<div class="section-title text-base mb-3">⚗ 용액 관리</div>';
  h+='<div class="text-xs text-gray-500 mb-2">용액은 <b>현재 프로젝트</b>에 속합니다(프로젝트 저장 시 함께 저장). 다른 프로젝트의 용액을 가져올 수 있습니다.</div>';
  h+='<div class="flex gap-2 mb-4 flex-wrap items-center"><button class="btn-primary text-sm" onclick="addSolution()">+ 용액 추가</button><button class="btn-secondary text-sm" onclick="saveSolutions()">💾 저장(정규화)</button><button class="btn-secondary text-sm" onclick="loadSolutions()">🔄 새로고침</button>';
  h+='<span class="text-gray-300 mx-1">|</span><select id="sol-import-proj" class="input-field text-xs" style="width:190px"><option value="">다른 프로젝트에서 불러오기…</option>';
  STATE.projectList.forEach(n=>h+='<option value="'+esc(n)+'">'+esc(n)+'</option>');
  h+='</select><button class="btn-secondary text-xs" onclick="importSolutionsFromProject(document.getElementById(\'sol-import-proj\').value)">가져오기</button></div>';
  if(!sols.length)return h+'<div class="card p-10 text-center text-gray-400">용액을 추가해주세요.</div>';
  sols.forEach(sol=>{
    const cost=calcSolCost(sol);
    h+='<div class="card p-4 mb-3"><div class="flex justify-between items-center mb-3"><input class="input-field font-bold" style="max-width:200px" value="'+esc(sol.user_name)+'" onchange="sol=STATE.solList.find(x=>x.id===\''+sol.id+'\');if(sol)sol.user_name=this.value"><div class="flex items-center gap-3"><span class="text-xs text-gray-400">원가: <b>$'+cost+'/L</b></span><label class="flex items-center gap-1 text-xs"><input type="checkbox" '+(sol.autoclave?'checked':'')+' onchange="STATE.solList.find(x=>x.id===\''+sol.id+'\').autoclave=this.checked"> 오토클레이브</label><button class="btn-danger" onclick="removeSolution(\''+sol.id+'\')">삭제</button></div></div>';
    h+='<div class="text-xs font-bold mb-2" style="color:var(--green)">성분 구성 <button class="ml-2 px-2 py-0.5 rounded text-white text-xs" style="background:var(--green)" onclick="addSolComponent(\''+sol.id+'\')">+ 추가</button></div>';
    h+='<div class="grid gap-1">';
    sol.components.forEach((comp,idx)=>{
      h+='<div class="flex gap-2 items-center text-xs">';
      h+='<select class="input-field" style="width:130px" onchange="updateSolComponent(\''+sol.id+'\','+idx+',\'name\',this.value)"><option value="">선택</option>';
      STATE.chemList.forEach(c=>h+='<option value="'+esc(c.name)+'" '+(comp.name===c.name?'selected':'')+'>'+esc(c.name)+'</option>');
      h+='</select>';
      h+='<input class="input-field" style="width:90px" type="number" min="0" step="any" value="'+comp.concentration_g_per_l+'" placeholder="g/L" onchange="updateSolComponent(\''+sol.id+'\','+idx+',\'concentration_g_per_l\',this.value)"> g/L';
      h+='<button class="btn-danger" style="padding:2px 6px" onclick="removeSolComponent(\''+sol.id+'\','+idx+')">×</button></div>';
    });
    h+='</div></div>';
  });
  return h;
}

// ============================================================
// UTILITIES / SUB-MATERIALS  (heat_utility split into two tables)
// ============================================================
async function loadUtilities(){
  try{
    const r=await fetch('/api/utilities');const d=await r.json();
    STATE.utilList=d.utilities||{};STATE.subMatList=d.submaterials||{};
    STATE.utilCat=d.categories||{};
    if(d.category_options)STATE.utilCatOptions=d.category_options;
    render();
  }catch(e){}
}
function _defaultCat(key){
  const u=(key||'').toLowerCase();
  if(u.includes('resin'))return 'resin';
  if(u.includes('membrane'))return 'membrane';
  if(u.includes('waste')||u.includes('sludge'))return 'wastewater';
  if(u.includes('filter'))return 'filter';
  if(u.includes('cip'))return 'cip';
  if(u.includes('gas')||u.includes('propane')||u.includes('propylene')||u.includes('ethylene'))return 'fuel';
  if(u.includes('steam'))return 'steam';
  if(u.includes('cool')||u.includes('chill')||u.includes('water'))return 'cooling';
  return '기타';
}
function updateUtilPrice(kind,key,val){
  let p=parseFloat(val);if(isNaN(p)||p<0)p=0;   // no negative prices
  (kind==='util'?STATE.utilList:STATE.subMatList)[key]=p;
}
function updateUtilCat(key,val){STATE.utilCat[key]=val;}
function renameUtil(kind,oldKey,newKey){
  newKey=(newKey||'').trim();if(!newKey||newKey===oldKey)return;
  const tbl=kind==='util'?STATE.utilList:STATE.subMatList;
  tbl[newKey]=tbl[oldKey];delete tbl[oldKey];
  if(oldKey in STATE.utilCat){STATE.utilCat[newKey]=STATE.utilCat[oldKey];delete STATE.utilCat[oldKey];}
  render();
}
function addUtilRow(kind){
  const tbl=kind==='util'?STATE.utilList:STATE.subMatList;
  let i=1,name;do{name=(kind==='util'?'new_utility_':'new_submaterial_')+i;i++;}while(name in tbl);
  tbl[name]=0;STATE.utilCat[name]=kind==='util'?'기타':'resin';render();
}
function removeUtilRow(kind,key){
  delete (kind==='util'?STATE.utilList:STATE.subMatList)[key];delete STATE.utilCat[key];render();
}
async function saveUtilities(){
  const r=await fetch('/api/utilities',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({utilities:STATE.utilList,submaterials:STATE.subMatList,categories:STATE.utilCat})});
  const d=await r.json();
  STATE.utilList=d.utilities||STATE.utilList;STATE.subMatList=d.submaterials||STATE.subMatList;STATE.utilCat=d.categories||STATE.utilCat;
  alert('유틸리티/부재료 단가·구분 저장 완료!\n노드(HIC/IEX resin 등) 드롭다운에 반영됩니다.');render();
}
function combinedHeatUtility(){
  // Recombine both tables into the single heat_utility dict BioSTEAM consumes.
  return Object.assign({}, STATE.utilList, STATE.subMatList);
}
function _utilTable(kind,title,desc,color,tbl){
  const keys=Object.keys(tbl);
  let h='<div class="card p-4 mb-4"><div class="flex justify-between items-center mb-1"><div class="font-bold text-sm" style="color:'+color+'">'+title+'</div>';
  h+='<button class="btn-sm text-xs" style="background:'+color+';color:#fff;border:none" onclick="addUtilRow(\''+kind+'\')">+ 항목 추가</button></div>';
  h+='<div class="text-xs text-gray-400 mb-2">'+desc+'</div>';
  h+='<div class="overflow-x-auto"><table class="tea-table"><thead><tr><th style="text-align:left">항목(ID)</th><th>구분</th><th>단가</th><th>관리</th></tr></thead><tbody>';
  if(!keys.length)h+='<tr><td colspan="4" class="text-center text-gray-400 py-3">항목이 없습니다. "+ 항목 추가"로 등록하세요.</td></tr>';
  keys.forEach(k=>{
    const cat=STATE.utilCat[k]||_defaultCat(k);
    h+='<tr><td><input class="input-field" style="width:200px" value="'+esc(k)+'" onchange="renameUtil(\''+kind+'\',\''+esc(k)+'\',this.value)"></td>';
    h+='<td><select class="input-field text-xs" style="width:120px" onchange="updateUtilCat(\''+esc(k)+'\',this.value)">';
    STATE.utilCatOptions.forEach(o=>{h+='<option'+(o===cat?' selected':'')+'>'+esc(o)+'</option>';});
    h+='</select></td>';
    h+='<td><input type="number" min="0" step="any" value="'+tbl[k]+'" class="input-field text-right" style="width:120px" onchange="updateUtilPrice(\''+kind+'\',\''+esc(k)+'\',this.value)"></td>';
    h+='<td><button class="btn-danger" onclick="removeUtilRow(\''+kind+'\',\''+esc(k)+'\')">삭제</button></td></tr>';
  });
  h+='</tbody></table></div></div>';
  return h;
}
function renderUtilTab(){
  let h='<div class="section-title text-base mb-2">⚡ 유틸리티 / 부재료 단가 관리</div>';
  h+='<div class="text-xs text-gray-500 mb-3">진짜 유틸리티(스팀·냉각수·연료 등)와 부재료(resin·filter·membrane·CIP 약품 등)를 분리해 관리합니다. 각 항목의 <b>구분</b>(resin/membrane/wastewater…)을 지정하면, 노드(HIC/IEX column의 Resin 종류, Diafiltration의 Membrane, Wastewater 종류 등) 드롭다운이 그 구분에 맞는 항목만 보여줍니다. 이름은 자유롭게 지정 가능합니다. <b>저장 후 노드를 다시 열면 반영됩니다.</b></div>';
  h+='<div class="flex gap-2 mb-4"><button class="btn-primary text-sm" onclick="saveUtilities()">💾 서버에 저장</button><button class="btn-secondary text-sm" onclick="loadUtilities()">🔄 새로고침</button></div>';
  h+=_utilTable('util','⚡ 유틸리티 (steam, cooling water, fuel, waste)','단위 소비량당 단가($/kg 또는 $/kmol 등, 초기값 기준)','#0f766e',STATE.utilList);
  h+=_utilTable('sub','🧫 부재료 (resin, filter, membrane, CIP)','HIC/IEX resin, diafiltration membrane, HEPA/air filter, CIP 약품 등. 구분을 resin/membrane 등으로 지정하세요.','#92400e',STATE.subMatList);
  return h;
}

function renderBFDTab(){
  const types=Object.keys(STATE.bfdNodeTypes);
  let h='<div class="section-title text-base mb-2">🔗 공정 흐름도 (Block Flow Diagram)</div>';
  h+='<div class="flex gap-2 mb-2 flex-wrap items-center">';
  if(!types.length){
    h+='<div class="text-xs text-gray-400 mr-2">노드 종류</div>';
    h+='<select id="node-type-sel" class="input-field text-xs" style="width:200px"><option>로드를 눌러주세요</option></select>';
  }else{
    h+='<div class="text-xs text-gray-400 mr-1">노드 종류</div>';
    h+='<select id="node-type-sel" class="input-field text-xs" style="width:200px">';
    types.forEach(t=>{const nt=STATE.bfdNodeTypes[t];h+=`<option value="${esc(t)}">${nt.icon} ${esc(t)}</option>`;});
    h+='</select>';
    h+='<button class="btn-sm text-xs" style="background:var(--green);color:#fff" onclick="addBFDNodeFromSel()">+ 노드 추가</button>';
  }
  h+='<button class="btn-sm btn-danger" style="background:#fee2e2;color:#dc2626" onclick="deleteBFDSelNode()">🗑 노드 삭제</button>';
  h+='<button class="btn-sm" style="background:#fef2f2;color:#dc2626;border:1px solid #fecaca" onclick="deleteBFDLastEdge()">↩ 마지막 잇선 삭제</button>';
  h+='<button class="btn-secondary text-xs ml-auto" onclick="clearBFD()" style="padding:4px 10px">↺ 초기화</button>';
  h+='</div>';
  if(types.length){
    h+='<div class="flex flex-wrap gap-1 mb-3 p-2 rounded" style="background:#f8fafc;border:1px solid #e2e8f0">';
    types.forEach(type=>{
      const nt=STATE.bfdNodeTypes[type];
      h+=`<button class="text-xs px-2 py-1 rounded font-semibold" style="background:${nt.color};color:#fff;border:none;cursor:pointer" onclick="addBFDNode('${esc(type)}')" title="${esc(type)} 노드 추가">${nt.icon} ${esc(type)}</button>`;
    });
    h+='</div>';
  }else{
    h+='<div class="text-xs text-gray-400 mb-3 p-2 rounded" style="background:#f8fafc;border:1px dashed #e2e8f0">🔄 <b>로드</b>를 눌러 노드 타입을 불러오세요.</div>';
  }
  h+='<div style="display:flex;gap:16px;align-items:flex-start">';
  h+='<div id="bfd-container" style="flex:1;position:relative;height:520px;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc;overflow:hidden;cursor:default">';
  h+='<svg id="bfd-svg" style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:visible"></svg>';
  h+='<div style="position:absolute;bottom:8px;left:8px;font-size:10px;color:#94a3b8">💡 노드 본체 드래그: 이동 &nbsp;|&nbsp; <b>오른쪽 파란 점(포트)을 드래그</b>해서 다른 노드에 놓으면 연결 &nbsp;|&nbsp; 잇선 클릭: 삭제</div>';
  h+='</div>';
  h+='<div style="width:340px;flex-shrink:0"><div class="card p-3"><div id="bfd-props-panel" class="text-xs text-gray-400">노드를 선택하세요<br><br>노드 <b>오른쪽 파란 점</b>을<br>드래그해 연결선을 그립니다.</div></div>';
  h+='<div class="flex gap-2 mt-2"><button class="btn-primary text-xs flex-1" onclick="saveBFD()">💾 저장</button><button class="btn-secondary text-xs flex-1" onclick="loadBFD()">🔄 로드</button></div>';
  h+='</div>';
  h+='</div>';
  h+=renderBiosteamPanel();
  return h;
}

function addBFDNodeFromSel(){
  const sel=document.getElementById('node-type-sel');if(sel&&sel.value)addBFDNode(sel.value);
}
function deleteBFDSelNode(){
  if(STATE.bfdSelectedNode)deleteBFDNode(STATE.bfdSelectedNode);
  else alert('삭제할 노드를 먼저 선택하세요.');
}
async function deleteBFDLastEdge(){
  if(!STATE.bfdEdges.length){alert('삭제할 잇선이 없습니다.');return;}
  const last=STATE.bfdEdges[STATE.bfdEdges.length-1];
  if(confirm('잇선 삭제: '+last.source+' → '+last.target+'?'))await deleteBFDEdgeById(last.id);
}

function renderProjectTab(){
  let h='<div class="section-title text-base mb-4">💾 프로젝트 관리</div>';
  h+='<div class="card p-5 mb-4"><div class="font-bold text-sm mb-3" style="color:var(--green)">프로젝트 저장</div>';
  h+='<div class="text-xs text-gray-500 mb-3">현재 프로젝트(시나리오, 화학물질 DB, 용액, BFD 흐름도)를 서버에 저장합니다.</div>';
  h+='<div class="flex gap-3 items-end"><div style="flex:1"><div class="text-xs text-gray-500 mb-1">프로젝트 이름</div><input id="proj-save-name" class="input-field" placeholder="'+esc(STATE.project.name||'프로젝트 이름')+'" value="'+esc(STATE.project.name||'')+'"></div><button class="btn-primary" onclick="saveProject()">💾 저장</button></div></div>';
  h+='<div class="card p-5"><div class="flex justify-between items-center mb-3"><div class="font-bold text-sm" style="color:var(--green)">저장된 프로젝트</div><button class="btn-secondary text-xs" onclick="loadProjectList()">🔄 새로고침</button></div>';
  if(!STATE.projectList.length){
    h+='<div class="text-center py-6 text-gray-400 text-sm">저장된 프로젝트가 없습니다.</div>';
  }else{
    h+='<div class="grid gap-2">';
    STATE.projectList.forEach(name=>{
      h+='<div class="flex justify-between items-center p-3 rounded-lg border border-gray-100 hover:bg-gray-50">';
      h+='<div class="flex items-center gap-2"><span class="text-2xl">📁</span><span class="font-semibold text-sm">'+esc(name)+'</span></div>';
      h+='<div class="flex gap-2"><button class="btn-primary text-xs" onclick="loadProject(\''+esc(name)+'\')">불러오기</button><button class="btn-danger" onclick="deleteProject(\''+esc(name)+'\')">삭제</button></div>';
      h+='</div>';
    });
    h+='</div>';
  }
  h+='</div>';
  return h;
}

function renderGuideTab(){
  return `<div style="max-width:900px">
  <div class="card p-5 mb-5">
    <div class="section-title text-base mb-4">🗺 전체 분석 워크플로우</div>
    <div style="display:flex;align-items:center;gap:0;flex-wrap:wrap;justify-content:center">
      <div style="text-align:center;padding:8px 0">
        <div style="font-size:10px;font-weight:800;color:#b91c1c;margin-bottom:4px">데이터 준비 (필수)</div>
        <div style="display:flex;flex-direction:column;gap:6px">
          <div onclick="goTab('chem')" style="background:#fef3c7;border:1px solid #fde68a;border-radius:8px;padding:6px 14px;font-size:11px;font-weight:700;color:#92400e;cursor:pointer;text-align:center">⚗ 화학물질 DB</div>
          <div style="color:#d1d5db;text-align:center;font-size:11px">↓</div>
          <div onclick="goTab('sol')" style="background:#fef3c7;border:1px solid #fde68a;border-radius:8px;padding:6px 14px;font-size:11px;font-weight:700;color:#92400e;cursor:pointer;text-align:center">⚗ 용액 관리</div>
          <div style="color:#d1d5db;text-align:center;font-size:11px">↓</div>
          <div onclick="goTab('util')" style="background:#fef3c7;border:1px solid #fde68a;border-radius:8px;padding:6px 14px;font-size:11px;font-weight:700;color:#92400e;cursor:pointer;text-align:center">⚗ 유틸리티/부재료</div>
        </div>
      </div>
      <div style="font-size:22px;color:#d1d5db;padding:0 12px;margin-top:20px">→</div>
      <div style="text-align:center;padding:8px 0">
        <div style="font-size:10px;font-weight:700;color:#15803d;margin-bottom:4px">핵심 단계</div>
        <div onclick="goTab('input')" style="background:#dcfce7;border:2px solid #15803d;border-radius:8px;padding:10px 18px;font-size:13px;font-weight:800;color:#15803d;cursor:pointer;text-align:center;box-shadow:0 2px 8px rgba(21,128,61,0.2)">① 시나리오 입력<div style="font-size:10px;font-weight:400;margin-top:3px;color:#4ade80">CAPEX·생산량·판매가</div></div>
        <div style="color:#d1d5db;text-align:center;font-size:18px;margin:6px 0">↓</div>
        <div onclick="goTab('bfd')" style="background:#dbeafe;border:2px solid #1d4ed8;border-radius:8px;padding:10px 18px;font-size:13px;font-weight:800;color:#1d4ed8;cursor:pointer;text-align:center;box-shadow:0 2px 8px rgba(29,78,216,0.2)">② 공정 흐름도<div style="font-size:10px;font-weight:400;margin-top:3px;color:#60a5fa">BFD → BioSTEAM</div></div>
        <div style="color:#d1d5db;text-align:center;font-size:18px;margin:6px 0">↓</div>
        <div onclick="goTab('results')" style="background:#dcfce7;border:2px solid #15803d;border-radius:8px;padding:10px 18px;font-size:13px;font-weight:800;color:#15803d;cursor:pointer;text-align:center;box-shadow:0 2px 8px rgba(21,128,61,0.2)">③ 분석 결과<div style="font-size:10px;font-weight:400;margin-top:3px;color:#4ade80">NPV·IRR·회수기간·BC비율</div></div>
      </div>
      <div style="font-size:22px;color:#d1d5db;padding:0 12px;margin-top:20px">→</div>
      <div style="text-align:center;padding:8px 0">
        <div style="font-size:10px;font-weight:700;color:#9ca3af;margin-bottom:4px">보완 도구 (선택)</div>
        <div style="display:flex;flex-direction:column;gap:6px">
          <div onclick="goTab('charts')" style="background:#dbeafe;border:1px solid #93c5fd;border-radius:8px;padding:6px 14px;font-size:11px;font-weight:700;color:#1d4ed8;cursor:pointer;text-align:center">⚗ 차트 분석</div>
          <div onclick="goTab('bench')" style="background:#fef3c7;border:1px solid #fde68a;border-radius:8px;padding:6px 14px;font-size:11px;font-weight:700;color:#92400e;cursor:pointer;text-align:center">⚗ 벤치마크 DB</div>
          <div onclick="goTab('project')" style="background:#f1f5f9;border:1px solid #cbd5e1;border-radius:8px;padding:6px 14px;font-size:11px;font-weight:700;color:#475569;cursor:pointer;text-align:center">⚗ 프로젝트 저장</div>
        </div>
      </div>
    </div>
  </div>
  <div class="card p-4">
    <div class="font-bold text-sm mb-3" style="color:var(--green)">📊 경제성 지표 판단 기준</div>
    <table class="tea-table text-xs">
      <thead><tr><th style="text-align:left">지표</th><th>의미</th><th style="background:#15803d">✓ 투자 권고</th><th style="background:#b45309">⚠ 추가 검토</th><th style="background:#dc2626">✗ 투자 불가</th></tr></thead>
      <tbody>
        <tr><td><b>NPV</b></td><td>순현재가치 (백만 USD)</td><td>&gt; 0</td><td>≈ 0</td><td>&lt; 0</td></tr>
        <tr><td><b>IRR</b></td><td>내부수익률</td><td>&gt; 15%</td><td>10~15%</td><td>&lt; 10%</td></tr>
        <tr><td><b>BC Ratio</b></td><td>편익비용비율</td><td>&gt; 1.2</td><td>1.0~1.2</td><td>&lt; 1.0</td></tr>
        <tr><td><b>회수기간</b></td><td>투자금 회수 연수</td><td>&lt; 5년</td><td>5~8년</td><td>&gt; 8년</td></tr>
      </tbody>
    </table>
    <div class="mt-3 text-xs text-gray-500">* 할인율 기본값 9% (LG Chem WACC 기준). 프로젝트 설정에서 조정 가능.</div>
  </div>
  </div>`;
}

// ============================================================
// MODALS
// ============================================================
function renderModals(){
  let h='';
  if(STATE.showBenchmarkModal){
    h+='<div class="modal-overlay" onclick="setState({showBenchmarkModal:false})"><div class="modal-content p-5" style="width:700px" onclick="event.stopPropagation()"><div class="font-bold text-base mb-4" style="color:var(--green)">벤치마크 라이브러리</div><div class="grid grid-cols-2 gap-3">';
    Object.entries(BENCHMARKS).forEach(([key,bm])=>{
      h+='<div class="border rounded-lg p-3 cursor-pointer hover:border-green-500" onclick="addFromBenchmark(\''+key.replace(/'/g,"\\'")+'\')"><div class="font-bold text-sm" style="color:var(--green)">'+esc(bm.name)+'</div><div class="text-xs text-gray-400 mt-1">Titer: '+bm.titer+' g/L | Yield: '+bm.yield+'% | Prod: '+bm.prod+' g/L/h</div></div>';
    });
    h+='</div><div class="flex justify-end mt-4"><button class="btn-secondary text-xs" onclick="setState({showBenchmarkModal:false})">닫기</button></div></div></div>';
  }
  if(STATE.showUploadModal&&STATE.uploadData){
    const ud=STATE.uploadData;
    h+='<div class="modal-overlay" onclick="setState({showUploadModal:false})"><div class="modal-content" style="width:520px" onclick="event.stopPropagation()"><div class="p-4 border-b"><div class="font-bold" style="color:var(--green)">업로드 데이터 확인</div></div><div class="p-4">';
    if(ud.project&&Object.keys(ud.project).length){h+='<div class="text-xs font-bold mb-2">프로젝트 정보</div>';Object.entries(ud.project).forEach(([k,v])=>{h+='<div class="flex justify-between py-1 border-b text-xs"><span class="text-gray-500">'+esc(k)+'</span><span class="font-semibold">'+esc(String(v))+'</span></div>';});}
    if(ud.scenarios&&ud.scenarios.length){h+='<div class="text-xs font-bold mt-3 mb-2">시나리오 ('+ud.scenarios.length+'개)</div>';ud.scenarios.forEach((sc,i)=>{h+='<div class="text-xs mb-1 p-2 bg-gray-50 rounded"><b>시나리오 '+(i+1)+': '+esc(sc.name||'')+'</b></div>';});}
    h+='<div class="flex gap-2 mt-4 justify-end"><button class="btn-secondary text-xs" onclick="setState({showUploadModal:false})">취소</button><button class="btn-primary text-xs" onclick="applyUploadData()">적용</button></div></div></div></div>';
  }
  return h;
}

// ============================================================
// MAIN RENDER
// ============================================================
// Key-based tab definitions so ordering is data-driven (no hardcoded indices).
// Order = workflow: 시나리오 입력 → 데이터 준비(필수) → 흐름도/발효 → 결과 → 관리.
const TAB_DEFS=[
  {key:'input',  label:'시나리오 입력',    num:'01', cls:'c-core', render:renderInputTab,     tip:'[핵심 1단계] 제품명·CAPEX·생산량·판매가를 입력'},
  {key:'chem',   label:'화학물질 DB',      num:'02', cls:'c-db',   render:renderChemTab,      tip:'[필수 데이터 준비] 원료·제품 화학물질 단가 DB 관리'},
  {key:'sol',    label:'용액 관리',        num:'03', cls:'c-db',   render:renderSolutionTab,  tip:'[필수 데이터 준비] 프로젝트별 배지·용액 조성 관리'},
  {key:'util',   label:'유틸리티/부재료',  num:'04', cls:'c-db',   render:renderUtilTab,      tip:'[필수 데이터 준비] 유틸리티(스팀·냉각수)·부재료(resin·filter) 단가'},
  {key:'bfd',    label:'공정 흐름도',      num:'05', cls:'c-vis',  render:renderBFDTab,       tip:'[공정] BFD 작성 → 노드 추가 후 드래그로 연결'},
  {key:'ferm',   label:'발효 공정',        num:'06', cls:'c-prep', render:renderFermTab,      tip:'[공정] Scale-up·발효 공정 도구'},
  {key:'results',label:'분석 결과',        num:'07', cls:'c-core', render:renderResultsTab,   tip:'[결과] NPV·IRR·회수기간·BC비율'},
  {key:'charts', label:'차트 분석',        num:'08', cls:'c-core', render:renderChartsTab,    tip:'[결과] 현금흐름·누적NPV·민감도 차트'},
  {key:'bench',  label:'벤치마크 DB',      num:'B',  cls:'c-db',   render:renderBenchmarkTab, tip:'[보조] 경쟁 기술 벤치마크 등록·비교'},
  {key:'project',label:'프로젝트 관리',    num:'M',  cls:'c-mgmt', render:renderProjectTab,   tip:'[관리] 프로젝트 저장·불러오기·비교'},
  {key:'guide',  label:'사용 가이드',      num:'G',  cls:'c-mgmt', render:renderGuideTab,     tip:'[안내] 사용 방법·분석 방법론·판단 기준'},
];
function tabIndex(key){return TAB_DEFS.findIndex(t=>t.key===key);}
function goTab(key){
  const i=tabIndex(key);if(i<0)return;
  setState({activeTab:i});
  if(key==='charts')setTimeout(renderCharts,100);
  if(key==='bfd')setTimeout(initBFD,100);
}

function renderQuickSaveBar(){
  let opts='<option value="">📂 불러오기…</option>';
  STATE.projectList.forEach(n=>opts+='<option value="'+esc(n)+'">'+esc(n)+'</option>');
  return '<div class="flex items-center gap-1" style="background:rgba(255,255,255,0.14);padding:4px 8px;border-radius:8px">'
    +'<input id="quick-proj-name" placeholder="프로젝트/시나리오 이름" value="'+esc(STATE.project.name||'')+'" style="font-size:11px;padding:4px 8px;border-radius:5px;border:none;width:160px;color:#111">'
    +'<button onclick="quickSaveProject()" style="font-size:11px;font-weight:700;background:#fff;color:#15803d;border:none;border-radius:5px;padding:4px 10px;cursor:pointer" title="현재 시나리오·화학물질·용액·흐름도를 저장">💾 저장</button>'
    +'<select id="quick-proj-load" onchange="if(this.value){loadProject(this.value);this.value=\'\';}" style="font-size:11px;padding:4px 6px;border-radius:5px;border:none;color:#111;max-width:150px">'+opts+'</select>'
    +'<button onclick="loadProjectList()" title="저장 목록 새로고침" style="font-size:12px;background:rgba(255,255,255,0.2);color:#fff;border:none;border-radius:5px;padding:4px 8px;cursor:pointer">🔄</button>'
    +'</div>';
}
async function quickSaveProject(){
  const name=document.getElementById('quick-proj-name')?.value?.trim()||STATE.project.name||'프로젝트';
  if(!name){alert('저장할 이름을 입력하세요.');return;}
  STATE.project.name=name;
  const body={name,chemicals:STATE.chemList,solutions:STATE.solList,bfd:{nodes:STATE.bfdNodes,edges:STATE.bfdEdges},project:STATE.project,scenarios:STATE.scenarios,utilities:{}};
  await fetch('/api/project/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  await loadProjectList();
  alert('저장 완료: "'+name+'"');
}

function showTabTip(el){
  const tip=el.getAttribute('data-tip');if(!tip)return;
  const t=document.getElementById('g-tooltip');if(!t)return;
  const r=el.getBoundingClientRect();
  t.textContent=tip;t.style.display='block';
  t.style.top=(r.bottom+8)+'px';
  t.style.left=Math.max(10,Math.min(window.innerWidth-290,r.left+r.width/2-140))+'px';
}
function hideTabTip(){const t=document.getElementById('g-tooltip');if(t)t.style.display='none';}

function render(){
  const R=STATE.results;
  const scMap={'c-core':'#15803d','c-prep':'#6d28d9','c-db':'#92400e','c-vis':'#1d4ed8','c-mgmt':'#475569'};
  const resultsIdx=tabIndex('results');
  const tabsHtml=TAB_DEFS.map((m,i)=>{
    const active=STATE.activeTab===i;const nc=scMap[m.cls];
    return '<button class="px-3 py-2 text-xs whitespace-nowrap '+(active?'tab-active':'tab-inactive')+'" style="display:flex;flex-direction:column;align-items:center;gap:1px;min-width:72px" onclick="goTab(\''+m.key+'\')" data-tip="'+m.tip.replace(/"/g,'&quot;')+'" onmouseenter="showTabTip(this)" onmouseleave="hideTabTip()">'
      +'<span class="tab-num" style="color:'+nc+'">'+m.num+'</span>'
      +'<span>'+m.label+(i===resultsIdx&&R.length?'<span class="ml-1 text-white rounded-full px-1" style="background:var(--green);font-size:9px">'+R.length+'</span>':'')+'</span>'
      +'</button>';
  }).join('');
  const showGuide=STATE.showFlowGuide;
  const flowBanner=showGuide
    ?'<div class="flow-banner">'
      +'<span style="font-size:11px;font-weight:800;color:#166534;white-space:nowrap;margin-right:2px">📋 분석 순서:</span>'
      +'<span class="flow-chip c-core" onclick="goTab(\'input\')">① 시나리오 입력</span>'
      +'<span style="color:#9ca3af">→</span>'
      +'<span style="font-size:11px;font-weight:800;color:#b91c1c;white-space:nowrap;margin:0 2px">데이터 준비 (필수):</span>'
      +'<span class="flow-chip c-db" onclick="goTab(\'chem\')">② 화학물질 DB</span>'
      +'<span style="color:#9ca3af">→</span>'
      +'<span class="flow-chip c-db" onclick="goTab(\'sol\')">③ 용액 관리</span>'
      +'<span style="color:#9ca3af">→</span>'
      +'<span class="flow-chip c-db" onclick="goTab(\'util\')">④ 유틸/부재료</span>'
      +'<span style="color:#d1d5db;margin:0 6px;font-size:16px">|</span>'
      +'<span class="flow-chip c-vis" onclick="goTab(\'bfd\')">⑤ 공정 흐름도</span>'
      +'<span style="color:#9ca3af">→</span>'
      +'<span class="flow-chip c-core" onclick="goTab(\'results\')">⑥ 분석 결과</span>'
      +'<span style="color:#9ca3af">→</span>'
      +'<span class="flow-chip c-core" onclick="goTab(\'charts\')">⑦ 차트 분석</span>'
      +'<div style="flex:1"></div>'
      +'<span style="font-size:10px;color:#9ca3af;margin-right:8px;white-space:nowrap">탭 위에 마우스를 올리면 설명이 표시됩니다</span>'
      +'<button onclick="localStorage.setItem(\'tea_guide_hidden\',\'1\');STATE.showFlowGuide=false;render()" style="background:none;border:1px solid #d1fae5;border-radius:6px;color:#9ca3af;cursor:pointer;font-size:13px;padding:2px 8px;line-height:1" title="안내 닫기">×</button>'
      +'</div>'
    :'<div style="text-align:right;padding:2px 20px;background:#f0fdf4;border-bottom:1px solid #bbf7d0"><button onclick="STATE.showFlowGuide=true;localStorage.removeItem(\'tea_guide_hidden\');render()" style="background:none;border:none;color:#15803d;cursor:pointer;font-size:11px;font-weight:600">📋 분석 순서 안내 보기</button></div>';
  document.getElementById('app').innerHTML=
    '<div style="background:linear-gradient(135deg,#006600,#004d00);color:#fff;padding:14px 24px"><div class="flex justify-between items-center gap-3 flex-wrap"><div class="flex items-center gap-3"><div class="w-9 h-9 rounded-lg flex items-center justify-center font-extrabold text-sm" style="background:rgba(255,255,255,0.15)">T</div><div><div class="font-extrabold text-base">TEA-Agent Platform</div><div class="text-xs" style="opacity:0.7">R&D 바이오 반도체 소재 기술경제성 분석 시스템</div></div></div>'+renderQuickSaveBar()+'<div class="text-right text-xs" style="opacity:0.7"><div class="font-semibold">LG Chem CTO Bio Materials Technology TFT</div><div>v9.0 · Deterministic Engine + LLM Assistant + 고급 공정 분석</div></div></div></div>'+
    '<div class="bg-white border-b px-2 flex gap-0 overflow-x-auto">'+tabsHtml+'</div>'+
    flowBanner+
    '<div style="padding:20px 24px;max-width:1400px;margin:0 auto">'+(TAB_DEFS[STATE.activeTab]||TAB_DEFS[0]).render()+'</div>'+
    '<div class="text-center py-4 text-xs text-gray-400 border-t">TEA-Agent Platform v9.0 · LG Chem CTO · Deterministic Engine + Chem DB + Solution Mgmt + BFD + LLM</div>'+
    renderModals();
  if((TAB_DEFS[STATE.activeTab]||{}).key==='bfd')setTimeout(initBFD,50);
}

// ============================================================
// LLM CHAT
// ============================================================
let _chatTimer=null,_chatElapsed=0;
function toggleChat(){STATE.chatOpen=!STATE.chatOpen;renderChatPanel();if(STATE.chatOpen)setTimeout(()=>{const el=document.getElementById('chat-scroll');if(el)el.scrollTop=el.scrollHeight;},50);}
async function sendChat(msg){
  if(!msg||!msg.trim()||STATE.chatLoading)return;
  STATE._lastUserMsg=msg.trim();
  STATE.chatMessages.push({role:'user',content:msg.trim()});
  STATE.chatLoading=true;_chatElapsed=0;renderChatPanel();
  setTimeout(()=>{const el=document.getElementById('chat-scroll');if(el)el.scrollTop=el.scrollHeight;},50);
  _chatTimer=setInterval(()=>{_chatElapsed++;const el=document.getElementById('chat-thinking-time');if(el)el.textContent=_chatElapsed+'초';},1000);
  const ctx={project:STATE.project,scenarioCount:STATE.scenarios.length,scenarioNames:STATE.scenarios.map(s=>s.name),chemCount:STATE.chemList.length};
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),30000);
  try{
    const resp=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages:STATE.chatMessages.filter(m=>m.role!=='system').slice(-10),context:ctx}),signal:controller.signal});
    clearTimeout(timeout);const result=await resp.json();
    STATE.chatMessages.push({role:'assistant',content:result.content,data:result.data});
  }catch(e){
    clearTimeout(timeout);
    if(e.name==='AbortError')STATE.chatMessages.push({role:'assistant',content:'⏱ 응답 시간 초과 (30초)',_retry:true});
    else STATE.chatMessages.push({role:'assistant',content:'✗ 서버 연결 오류: '+(e.message||e),_retry:true});
  }
  clearInterval(_chatTimer);_chatTimer=null;STATE.chatLoading=false;renderChatPanel();
  setTimeout(()=>{const el=document.getElementById('chat-scroll');if(el)el.scrollTop=el.scrollHeight;},50);
}
function retryLastChat(){if(STATE._lastUserMsg){if(STATE.chatMessages.length&&STATE.chatMessages[STATE.chatMessages.length-1]._retry)STATE.chatMessages.pop();if(STATE.chatMessages.length&&STATE.chatMessages[STATE.chatMessages.length-1].role==='user')STATE.chatMessages.pop();sendChat(STATE._lastUserMsg);}}
function resetChat(){STATE.chatMessages=[{role:'assistant',content:'안녕하세요. TEA-Agent v9.0 AI 어시스턴트입니다.'}];STATE.chatLoading=false;if(_chatTimer){clearInterval(_chatTimer);_chatTimer=null;}renderChatPanel();}
function applyChatData(data){
  if(!data)return;
  const projFields=['exchangeRate','discountRate','taxRate','analysisYears','constructionYears','name','product','analyst'];
  if(data.action==='fill'&&data.field){if(projFields.includes(data.field))STATE.project[data.field]=data.value;else if(STATE.scenarios.length>0)STATE.scenarios[0][data.field]=data.value;STATE.chatMessages.push({role:'assistant',content:'적용: '+data.field+'='+data.value});render();renderChatPanel();}
  else if(data.action==='fill_multiple'&&data.fields){Object.entries(data.fields).forEach(([k,v])=>{if(projFields.includes(k))STATE.project[k]=v;else if(STATE.scenarios.length>0)STATE.scenarios[0][k]=v;});STATE.chatMessages.push({role:'assistant',content:'적용 완료'});render();renderChatPanel();}
  else if(data.action==='add_scenario'&&data.scenario){if(STATE.scenarios.length<MAX_SCENARIOS){STATE.scenarios.push({id:STATE.nextId++,...data.scenario});STATE.chatMessages.push({role:'assistant',content:'시나리오 추가 완료!'});render();renderChatPanel();}}
}
async function fetchExchangeRate(){
  try{const resp=await fetch('/api/exchange-rate');const data=await resp.json();if(data.rate){STATE.project.exchangeRate=Math.round(data.rate);STATE.chatMessages.push({role:'assistant',content:'환율: **1 USD = '+data.rate+' KRW**\n출처: '+data.source+'\n자동 적용 완료!'});render();renderChatPanel();}}catch(e){}
}
function escChat(s){if(!s)return'';const d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function formatMd(s){if(!s)return'';return escChat(s).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code style="background:#f1f5f9;padding:1px 4px;border-radius:3px;font-size:12px">$1</code>').replace(/\n/g,'<br>');}
function renderChatPanel(){
  let existing=document.getElementById('chat-container');if(existing)existing.remove();
  const container=document.createElement('div');container.id='chat-container';
  container.innerHTML='<button class="chat-toggle" onclick="toggleChat()">AI</button>';
  if(!STATE.chatOpen){document.body.appendChild(container);return;}
  let msgs='';
  STATE.chatMessages.forEach((m,i)=>{
    if(m.role==='user')msgs+='<div class="chat-msg user">'+escChat(m.content)+'</div>';
    else{
      let actionBtn='';
      if(m.data&&(m.data.action==='fill'||m.data.action==='fill_multiple'||m.data.action==='add_scenario'))actionBtn='<br><button class="action-btn" onclick="applyChatData(STATE.chatMessages['+i+'].data)">입력값에 적용</button>';
      let retryBtn=m._retry?'<br><button onclick="retryLastChat()" style="margin-top:6px;font-size:11px;padding:4px 12px;border-radius:6px;border:1px solid #2563eb;background:#eff6ff;color:#2563eb;cursor:pointer">🔄 재시도</button>':'';
      const src=m.data&&m.data.source?'<br><span class="source-tag">출처: '+escChat(m.data.source)+'</span>':'';
      msgs+='<div class="chat-msg assistant">'+formatMd(m.content)+actionBtn+retryBtn+src+'</div>';
    }
  });
  if(STATE.chatLoading)msgs+='<div class="chat-typing"><span>.</span><span>.</span><span>.</span> AI 생각 중... <span id="chat-thinking-time" style="color:#2563eb;font-weight:700">'+_chatElapsed+'초</span></div>';
  container.innerHTML+=`<div class="chat-panel" id="chat-panel-el" style="width:${CHAT_W}px;height:${CHAT_H}px">
    <div class="chat-rz chat-rz-nw" onmousedown="startChatResize(event,'nw')"></div>
    <div class="chat-rz chat-rz-w"  onmousedown="startChatResize(event,'w')"></div>
    <div class="chat-rz chat-rz-n"  onmousedown="startChatResize(event,'n')"></div>
    <div class="chat-header">
    <div class="chat-grip" onmousedown="startChatResize(event,'nw')" title="드래그하여 크기 조절"><span></span><span></span><span></span></div>
    <div><div style="font-weight:700;font-size:14px">AI 어시스턴트</div><div style="font-size:10px;opacity:0.7">실시간 데이터 검색 & 수율 근거</div></div>
    <div style="display:flex;gap:6px;margin-left:auto"><button onclick="resetChat()" style="background:rgba(255,255,255,0.2);border:none;color:#fff;font-size:14px;cursor:pointer;border-radius:4px;padding:2px 8px">🔄</button><button onclick="toggleChat()" style="background:none;border:none;color:#fff;font-size:20px;cursor:pointer">&times;</button></div></div>
    <div class="chat-messages" id="chat-scroll">${msgs}</div>
    <div class="chat-quick-btns">
      <button onclick="fetchExchangeRate()">현재 환율</button>
      <button onclick="sendChat('1,3-PDO 시장 현황 알려줘')">PDO 시장</button>
      <button onclick="sendChat('Glucose 최신 시세 알려줘')">Glucose 시세</button>
      <button onclick="sendChat('현재 시나리오 수율 근거 작성해줘')">수율 근거</button>
    </div>
    <div class="chat-input-area">
      <input id="chat-input" placeholder="질문을 입력하세요.." onkeydown="if(event.key==='Enter'){sendChat(this.value);this.value='';}"/>
      <button onclick="const i=document.getElementById('chat-input');sendChat(i.value);i.value='';">전송</button>
    </div></div>`;
  document.body.appendChild(container);
}

// ============================================================
// BioSTEAM INTEGRATION
// ============================================================
let BIOSTEAM_OK=false;
let BIOSTEAM_INSTALLED=false;
let BIOSTEAM_ERR=null;
let BIOSTEAM_DEFAULTS=null;
let BIOSTEAM_RESULT=null;
let BIOSTEAM_RUNNING=false;

async function checkBiosteam(){
  try{
    const r=await fetch('/api/biosteam/status');const d=await r.json();
    BIOSTEAM_OK=d.available===true;
    BIOSTEAM_INSTALLED=d.installed===true;
    BIOSTEAM_ERR=d.error||null;
    if(BIOSTEAM_OK){
      const r2=await fetch('/api/biosteam/defaults');BIOSTEAM_DEFAULTS=await r2.json();
    }
    render();if((TAB_DEFS[STATE.activeTab]||{}).key==='bfd')setTimeout(initBFD,50);
  }catch(e){BIOSTEAM_OK=false;}
}

function renderConsumptionDetail(c){
  // Shows HOW MUCH raw/sub material is required (kg per MT of product) and
  // every utility the process consumes — the detail the Streamlit version had.
  const raw=c.raw_material_detail||[], sub=c.sub_material_detail||[], util=c.utilities_detail||[];
  if(!raw.length&&!sub.length&&!util.length)return'';
  const matTable=(title,rows,color)=>{
    if(!rows.length)return'';
    let t='<div class="text-xs font-bold mt-2 mb-1" style="color:'+color+'">'+title+'</div>';
    t+='<table class="w-full text-xs" style="border-collapse:collapse"><thead><tr style="color:#94a3b8">'
      +'<th style="text-align:left;font-weight:600">물질</th><th style="text-align:right;font-weight:600">소요량 (kg/MT)</th>'
      +'<th style="text-align:right;font-weight:600">단가 ($/kg)</th><th style="text-align:right;font-weight:600">원가 ($/MT)</th></tr></thead><tbody>';
    rows.forEach(r=>{
      t+='<tr style="border-top:1px solid #eef2f7"><td>'+esc(r.chemical)+'</td>'
        +'<td class="text-right">'+fmtBio(r.kg_per_mt,3)+'</td>'
        +'<td class="text-right">'+fmtBio(r.price,3)+'</td>'
        +'<td class="text-right font-semibold">'+fmtBio(r.cost_per_mt,1)+'</td></tr>';
    });
    t+='</tbody></table>';
    return t;
  };
  let h='<details open class="mt-3"><summary class="text-xs cursor-pointer font-bold" style="color:#0369a1">📦 원재료·부재료 소요량 & 유틸리티 상세</summary>';
  h+='<div class="mt-2 p-2 rounded" style="background:#f8fafc;border:1px solid #e2e8f0">';
  h+=matTable('원재료 (Carbon Source) — 소요량',raw,'#1d4ed8');
  h+=matTable('부재료 (Other Feeds) — 소요량',sub,'#92400e');
  if(util.length){
    h+='<div class="text-xs font-bold mt-3 mb-1" style="color:#0f766e">유틸리티 (전체)</div>';
    h+='<table class="w-full text-xs" style="border-collapse:collapse"><thead><tr style="color:#94a3b8">'
      +'<th style="text-align:left;font-weight:600">유틸리티</th><th style="text-align:left;font-weight:600">구분</th>'
      +'<th style="text-align:right;font-weight:600">Duty (kJ/hr)</th><th style="text-align:right;font-weight:600">원가 ($/MT)</th></tr></thead><tbody>';
    util.forEach(u=>{
      h+='<tr style="border-top:1px solid #eef2f7"><td>'+esc(u.utility)+'</td>'
        +'<td style="color:#64748b">'+esc(u.category||'')+'</td>'
        +'<td class="text-right">'+(u.duty_kJ_per_hr==null?'-':fmtBio(u.duty_kJ_per_hr,0))+'</td>'
        +'<td class="text-right font-semibold">'+fmtBio(u.cost_per_mt,1)+'</td></tr>';
    });
    h+='</tbody></table>';
  }
  h+='</div></details>';
  return h;
}

function renderBiosteamPanel(){
  if(!BIOSTEAM_OK){
    if(BIOSTEAM_INSTALLED){
      // Package is on disk but importing it raised — show the real reason.
      let h='<div class="card p-4 mt-4" style="border-left:3px solid #dc2626">';
      h+='<div class="font-bold text-xs mb-1" style="color:#dc2626">⚙ BioSTEAM 설치됨 — 하지만 import 실패</div>';
      h+='<div class="text-xs text-gray-600 mb-2">패키지는 설치되어 있으나 불러오는 중 오류가 발생했습니다. 아래 원인을 확인하세요.</div>';
      if(BIOSTEAM_ERR)h+='<details open><summary class="text-xs cursor-pointer" style="color:#6b7280">import 오류 상세</summary><pre style="white-space:pre-wrap;font-size:9px;max-height:220px;overflow:auto;background:#fff;padding:6px;border-radius:4px;margin-top:4px;border:1px solid #fecaca">'+esc(BIOSTEAM_ERR)+'</pre></details>';
      h+='</div>';
      return h;
    }
    return '<div class="card p-4 mt-4" style="border-left:3px solid #d1d5db"><div class="text-xs text-gray-400">⚙ BioSTEAM 공정 시뮬레이션은 <b>미설치</b>. biosteam 패키지를 설치하면 공정 물질수지 기반 원가 자동 계산이 활성화됩니다.</div></div>';
  }
  const chems=STATE.chemList||[];
  let h='<div class="card p-4 mt-4" style="border-left:3px solid #15803d">';
  h+='<div class="collapsible-header" onclick="document.getElementById(\'biosim-body\').classList.toggle(\'hidden\');this.querySelector(\'.arrow\').classList.toggle(\'open\')"><span class="arrow">▶</span> <span class="font-bold text-sm" style="color:#15803d">⚙ BioSTEAM 공정 시뮬레이션</span> <span class="badge ml-2" style="background:#dcfce7;color:#15803d">Ready</span></div>';
  h+='<div id="biosim-body" class="mt-3">';
  h+='<div class="grid grid-cols-3 gap-2 mb-3">';
  h+='<div><label class="text-xs text-gray-500">Target Product</label><select id="bio-product" class="input-field text-xs" onchange="STATE.bioProduct=this.value">';
  chems.forEach(c=>h+='<option value="'+esc(c.name)+'"'+(STATE.bioProduct===c.name?' selected':'')+'>'+esc(c.name)+'</option>');
  h+='</select></div>';
  h+='<div><label class="text-xs text-gray-500">Carbon Source</label><select id="bio-source" class="input-field text-xs" onchange="STATE.bioSource=this.value">';
  chems.forEach(c=>h+='<option value="'+esc(c.name)+'"'+(STATE.bioSource===c.name?' selected':'')+'>'+esc(c.name)+'</option>');
  h+='</select></div>';
  h+='<div><label class="text-xs text-gray-500">Target (MT/yr)</label><input id="bio-target" class="input-field text-xs" type="number" value="'+STATE.bioTargetMT+'" onchange="STATE.bioTargetMT=parseFloat(this.value)||100"></div>';
  h+='</div>';
  h+='<div class="grid grid-cols-4 gap-2 mb-3">';
  h+='<div><label class="text-xs text-gray-500">운영시간(h/yr)</label><input id="bio-ophours" class="input-field text-xs" type="number" value="7920"></div>';
  h+='<div><label class="text-xs text-gray-500">전기단가($/kWh)</label><input id="bio-elecprice" class="input-field text-xs" type="number" value="0.128" step="0.001"></div>';
  h+='<div><label class="text-xs text-gray-500 flex items-center gap-1"><input id="bio-gmp" type="checkbox" checked> GMP 여부</label></div>';
  h+='<div><label class="text-xs text-gray-500">OD→DCW</label><input id="bio-od" class="input-field text-xs" type="number" value="0.22" step="0.01"></div>';
  h+='</div>';
  h+='<button class="btn-primary text-sm w-full" onclick="runBiosteamSim()" '+(BIOSTEAM_RUNNING?'disabled':'')+'>🔮 '+(BIOSTEAM_RUNNING?'시뮬레이션 실행 중...':'BioSTEAM 시뮬레이션 실행')+'</button>';
  if(BIOSTEAM_RESULT){
    if(BIOSTEAM_RESULT.success){
      const c=BIOSTEAM_RESULT;
      h+='<div class="mt-3 p-3 rounded" style="background:#f0fdf4;border:1px solid #bbf7d0">';
      h+='<div class="font-bold text-xs mb-2" style="color:#15803d">✓ 시뮬레이션 결과 ($/MT)</div>';
      h+='<table class="w-full text-xs"><tbody>';
      h+='<tr><td class="py-1">CAPEX (Total)</td><td class="text-right font-bold">$'+fmt(c.capex)+'</td></tr>';
      h+='<tr><td class="py-1">CAPEX (Mn USD)</td><td class="text-right font-bold">$'+fmt(c.capexMn,2)+' M</td></tr>';
      h+='<tr class="border-t"><td class="py-1">원재료 (Carbon Source)</td><td class="text-right">$'+fmt(c.rawMaterial)+'/MT</td></tr>';
      h+='<tr><td class="py-1">부재료 (Other+Down)</td><td class="text-right">$'+fmt(c.subMaterial)+'/MT</td></tr>';
      h+='<tr><td class="py-1">스팀</td><td class="text-right">$'+fmt(c.steam)+'/MT</td></tr>';
      h+='<tr><td class="py-1">전기</td><td class="text-right">$'+fmt(c.electricity)+'/MT</td></tr>';
      h+='<tr><td class="py-1">냉각수</td><td class="text-right">$'+fmt(c.cooling)+'/MT</td></tr>';
      h+='<tr><td class="py-1">폐수처리</td><td class="text-right">$'+fmt(c.waste)+'/MT</td></tr>';
      h+='<tr class="border-t"><td class="py-1">감가상각</td><td class="text-right">$'+fmt(c.depreciation)+'/MT</td></tr>';
      h+='<tr><td class="py-1">인건비</td><td class="text-right">$'+fmt(c.labor)+'/MT</td></tr>';
      h+='<tr><td class="py-1">수선비</td><td class="text-right">$'+fmt(c.repair)+'/MT</td></tr>';
      h+='</tbody></table>';
      // --- 원재료/부재료 소요량 (kg/MT) + 전체 유틸리티 ---
      h+=renderConsumptionDetail(c);
      if(c.mass_balance){
        h+='<details class="mt-2"><summary class="text-xs cursor-pointer" style="color:#1d4ed8">⚖ Mass Balance (단위 스트림 kg/hr)</summary><div class="mt-1 p-2 rounded text-xs" style="background:#eff6ff">';
        if(c.mass_balance.streams){
          h+='<div class="font-bold mb-1">System Inlets:</div>';
          (c.mass_balance.streams.inlets||[]).forEach(s=>{
            h+='<div style="margin-left:8px">'+esc(s.stream)+': <b>'+s.total_kg_hr.toFixed(4)+'</b> kg/hr';
            if(s.components)Object.entries(s.components).forEach(([k,v])=>{h+=' | '+esc(k)+'='+v.toFixed(4);});
            h+='</div>';
          });
          h+='<div class="font-bold mb-1 mt-1">System Outlets:</div>';
          (c.mass_balance.streams.outlets||[]).forEach(s=>{
            h+='<div style="margin-left:8px">'+esc(s.stream)+': <b>'+s.total_kg_hr.toFixed(4)+'</b> kg/hr';
            if(s.components)Object.entries(s.components).forEach(([k,v])=>{h+=' | '+esc(k)+'='+v.toFixed(4);});
            h+='</div>';
          });
        }
        if(c.mass_balance.units){
          h+='<div class="font-bold mb-1 mt-1">Unit Details:</div>';
          c.mass_balance.units.forEach(u=>{
            h+='<div style="margin-left:8px;border-bottom:1px solid #dbeafe;padding:2px 0"><b>'+esc(u.type)+' '+esc(u.name)+'</b>';
            (u.ins||[]).forEach(s=>{h+='<div style="margin-left:16px;color:#059669">IN: '+esc(s.stream)+' = '+s.total_kg_hr.toFixed(4)+' kg/hr</div>';});
            (u.outs||[]).forEach(s=>{h+='<div style="margin-left:16px;color:#dc2626">OUT: '+esc(s.stream)+' = '+s.total_kg_hr.toFixed(4)+' kg/hr';if(s.components)Object.entries(s.components).forEach(([k,v])=>{h+=' | '+esc(k)+'='+v.toFixed(4);});h+='</div>';});
            h+='</div>';
          });
        }
        h+='</div></details>';
      }
      if(c.logic){
        h+='<details class="mt-2"><summary class="text-xs cursor-pointer" style="color:#6b7280">📋 산정 근거 보기</summary><div class="mt-1 p-2 rounded text-xs" style="background:#f1f5f9;font-family:monospace">';
        Object.entries(c.logic).forEach(([k,v])=>{h+='<div><b>'+esc(k)+'</b>: '+esc(String(v))+'</div>';});
        h+='</div></details>';
      }
      h+='<div class="mt-3 flex gap-2 items-center">';
      h+='<select id="bio-apply-sc" class="input-field text-xs" style="flex:1">';
      if(STATE.scenarios.length===0)h+='<option value="">(시나리오를 먼저 추가하세요)</option>';
      STATE.scenarios.forEach(sc=>h+='<option value="'+sc.id+'">'+esc(sc.name||'시나리오 '+sc.id)+'</option>');
      h+='</select>';
      h+='<button class="btn-primary text-xs" onclick="applyBiosteamToScenario()">선택 시나리오에 적용</button>';
      h+='<button class="btn-secondary text-xs" onclick="applyBiosteamToAllScenarios()">전체에 적용</button>';
      h+='</div></div>';
    }else{
      h+='<div class="mt-3 p-3 rounded" style="background:#fef2f2;border:1px solid #fecaca">';
      h+='<div class="font-bold text-xs mb-1" style="color:#dc2626">✗ 시뮬레이션 오류</div>';
      h+='<div class="text-xs text-gray-700 mb-1"><b>Error:</b> '+esc(BIOSTEAM_RESULT.error||'Unknown error')+'</div>';
      if(BIOSTEAM_RESULT.unit_hint)h+='<div class="text-xs text-orange-600 mb-1"><b>Unit:</b> '+esc(BIOSTEAM_RESULT.unit_hint)+'</div>';
      if(BIOSTEAM_RESULT._debug_fermenters)h+='<div class="text-xs mt-1" style="color:#6b7280"><b>Fermenter params sent:</b> '+esc(JSON.stringify(BIOSTEAM_RESULT._debug_fermenters))+'</div>';
      if(BIOSTEAM_RESULT.detail)h+='<details class="text-xs text-gray-500"><summary>상세 오류 보기</summary><pre style="white-space:pre-wrap;font-size:9px;max-height:200px;overflow:auto;background:#fff;padding:4px;border-radius:4px;margin-top:4px">'+esc(BIOSTEAM_RESULT.detail)+'</pre></details>';
      h+='</div>';
    }
  }
  h+='</div></div>';
  return h;
}

function fmtBio(v,d){d=d||0;if(v===undefined||v===null)return'0';return Number(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:Math.max(d,1)});}

async function runBiosteamSim(){
  if(BIOSTEAM_RUNNING)return;
  BIOSTEAM_RUNNING=true;BIOSTEAM_RESULT=null;render();setTimeout(initBFD,50);
  try{
    const body={
      chemicals:STATE.chemList.map(c=>({name:c.name,formula:c.formula,price:c.price,phase:c.phase})),
      solutions:STATE.solList,
      bfd:{nodes:STATE.bfdNodes.map(n=>({id:n.id,node_type:n.node_type,label:n.label,x:n.x,y:n.y,params:n.params||{},solution_flows:n.solution_flows||{}})),edges:STATE.bfdEdges.map(e=>({id:e.id,source:e.source,target:e.target}))},
      main_product:document.getElementById('bio-product')?.value||STATE.bioProduct||STATE.project.product||'',
      main_source:document.getElementById('bio-source')?.value||STATE.bioSource||'Glucose',
      target_amount:parseFloat(document.getElementById('bio-target')?.value)||STATE.bioTargetMT||100,
      operating_hours:parseFloat(document.getElementById('bio-ophours')?.value)||7920,
      electricity_price:parseFloat(document.getElementById('bio-elecprice')?.value)||0.128,
      gmp:document.getElementById('bio-gmp')?.checked??true,
      od_to_dcw:parseFloat(document.getElementById('bio-od')?.value)||0.22,
      heat_utility:combinedHeatUtility(),
    };
    const r=await fetch('/api/biosteam/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    BIOSTEAM_RESULT=await r.json();
  }catch(e){BIOSTEAM_RESULT={success:false,error:e.message};}
  BIOSTEAM_RUNNING=false;render();setTimeout(initBFD,50);
}

function _applyBioToSc(sc,c,cap){
  sc.capex=+(c.capexMn||0).toFixed(2);       // CAPEX from BioSTEAM
  if(cap)sc.capacity=cap;
  if(c.substrate){                            // 기질 단가(화학물질 DB) + 기질 원단위(BioSTEAM)
    sc.glucosePrice=+(c.substrate.price_per_mt||0).toFixed(2);
    sc.glucoseUnit=+(c.substrate.kg_per_mt||0).toFixed(3);
  }
  sc.rawMaterial=+(c.rawMaterial||0).toFixed(1);
  sc.subMaterial=+(c.subMaterial||0).toFixed(1);
  sc.steam=+(c.steam||0).toFixed(1);
  sc.electricity=+(c.electricity||0).toFixed(1);
  sc.cooling=+(c.cooling||0).toFixed(1);
  sc.waste=+(c.waste||0).toFixed(1);
  sc._biosteamApplied=true;
  sc._biosteamResult=c;
}
function applyBiosteamToScenario(){
  if(!BIOSTEAM_RESULT||!BIOSTEAM_RESULT.success)return alert('먼저 시뮬레이션을 실행하세요.');
  const scId=document.getElementById('bio-apply-sc')?.value;
  if(!scId)return alert('적용할 시나리오를 선택하세요.');
  const sc=STATE.scenarios.find(s=>s.id==scId);
  if(!sc)return alert('시나리오를 찾을 수 없습니다.');
  const cap=parseFloat(document.getElementById('bio-target')?.value)||sc.capacity;
  _applyBioToSc(sc,BIOSTEAM_RESULT,cap);
  alert('✓ BioSTEAM 결과가 "'+esc(sc.name||'시나리오 '+sc.id)+'"에 적용되었습니다.');
  render();setTimeout(initBFD,50);
}
function applyBiosteamToAllScenarios(){
  if(!BIOSTEAM_RESULT||!BIOSTEAM_RESULT.success)return alert('먼저 시뮬레이션을 실행하세요.');
  if(!STATE.scenarios.length)return alert('시나리오를 먼저 추가하세요.');
  const cap=parseFloat(document.getElementById('bio-target')?.value)||0;
  STATE.scenarios.forEach(sc=>_applyBioToSc(sc,BIOSTEAM_RESULT,cap||sc.capacity));
  alert('✓ BioSTEAM 결과를 전체 '+STATE.scenarios.length+'개 시나리오에 적용했습니다.');
  render();setTimeout(initBFD,50);
}

// ============================================================
// INIT
// ============================================================
render();
renderChatPanel();
loadChemicals();
loadSolutions();
loadUtilities();
loadProjectList();
checkBiosteam();
loadBFD();
