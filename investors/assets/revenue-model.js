/* Founder planning assumptions; INR. Cohort dates start one month after signup. */
const RevenueModel=(()=>{
const cases={Conservative:{factor:.5,operations:150000,firstDate:.6,repeatRate:.1},Base:{factor:1,operations:250000,firstDate:.6,repeatRate:.1},Aggressive:{factor:1.5,operations:400000,firstDate:.6,repeatRate:.1}};
const base=[150,250,400,600,800,1000,1100,1200,1350,1500,1700,1950];
const cities=[['Bengaluru',1],['Delhi NCR',1],['Mumbai',1],['Pune',4],['Hyderabad',5],['Chennai',6],['Kolkata',7],['Ahmedabad',8],['Jaipur',9],['Chandigarh',10],['Kochi',12]];
function calculate(name,overrides={}){
const c={...cases[name],...overrides};if(!cases[name])throw Error('Unknown scenario');
let cash=500000,paidTotal=0,collections=0,costs=0,providerTotal=0,metaTotal=0,bgvTotal=0,gatewayTotal=0,minCash=500000,reserveGap=0,registrationTotal=0,dateTotal=0,coverTotal=0;
const cohorts=[];
return base.map((n,i)=>{
const paid=n*c.factor,provider=Math.max(80000,paid*200),meta=paid<=400?100000:paid<=1500?100000+(paid-400)*50000/1100:paid*100;
// Weeks 1–4: 25% + 20% + 10% + 5%, all of the original paid cohort.
// Repeat customers = 10% of first-date participants; 1 + 1 + 0.5 visits
// in the following three months (editable planning midpoint of 2–3).
const registration=paid*1999,first=i===0?0:base[i-1]*c.factor*c.firstDate,repeat=[1,1,.5].reduce((sum,w,j)=>sum+(cohorts[i-j-1]||0)*w,0)*c.repeatRate;
cohorts.push(first);
const date=first*499+repeat*249,cover=(first+repeat)*500,revenue=registration+date,bgv=paid*150,gateway=paid*46+(date+cover)*46/1999,setup=i===0?100000:0,recurring=provider+meta+bgv+gateway+c.operations,cost=recurring+setup;
cash+=revenue-cost;paidTotal+=paid;collections+=revenue;registrationTotal+=registration;dateTotal+=date;coverTotal+=cover;costs+=cost;providerTotal+=provider;metaTotal+=meta;bgvTotal+=bgv;gatewayTotal+=gateway;
const reserve=recurring*3,headroom=Math.max(0,cash-reserve);minCash=Math.min(minCash,cash);reserveGap=Math.max(reserveGap,reserve-cash,0);
return {month:i+1,paid,paidTotal,registration,date,first,repeat,registrationTotal,dateTotal,coverTotal,revenue,collections,provider,meta,providerTotal,metaTotal,bgvTotal,gatewayTotal,operationsTotal:c.operations*(i+1),cost,costs,cash,reserve,headroom,minCash,reserveGap,productAllocation:headroom*.4,marketingAllocation:headroom*.35,regionAllocation:headroom*.25,cities:cities.filter(x=>x[1]<=i+1).length};
});
}
return {cases,cities,calculate};
})();
if(typeof module!=='undefined')module.exports=RevenueModel;
