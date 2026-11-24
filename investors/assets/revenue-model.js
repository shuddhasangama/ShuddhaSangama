/* Planning assumptions, INR, 24 Nov 2026. Mirrors the downloadable workbook. */
const RevenueModel=(()=>{
 const cases={Conservative:{factor:.5,operations:150000,conversion:.05},Base:{factor:1,operations:250000,conversion:.1},Aggressive:{factor:1.5,operations:400000,conversion:.15}};
 const base=[150,250,400,600,800,1000,1100,1200,1350,1500,1700,1950];
 const cities=[['Bengaluru',1],['Delhi NCR',1],['Mumbai',1],['Pune',2],['Hyderabad',3],['Chennai',4],['Kolkata',5],['Ahmedabad',6],['Jaipur',7],['Chandigarh',8],['Kochi',9]];
 function calculate(name){
  const c=cases[name];if(!c)throw Error('Unknown scenario');
  let cash=500000,paidTotal=0,collections=0,costs=0,providerTotal=0,metaTotal=0,bgvTotal=0,gatewayTotal=0,minCash=500000,reserveGap=0;
  return base.map((n,i)=>{
   const paid=n*c.factor,provider=Math.max(80000,paid*200),meta=paid<=400?100000:paid<=1500?100000+(paid-400)*50000/1100:paid*100;
   const revenue=paid*1999,bgv=paid*150,gateway=paid*46,setup=i===0?100000:0,recurring=provider+meta+bgv+gateway+c.operations,cost=recurring+setup;
   cash+=revenue-cost;paidTotal+=paid;collections+=revenue;costs+=cost;providerTotal+=provider;metaTotal+=meta;bgvTotal+=bgv;gatewayTotal+=gateway;
   const reserve=recurring*3,headroom=Math.max(0,cash-reserve);minCash=Math.min(minCash,cash);reserveGap=Math.max(reserveGap,reserve-cash,0);
   return {month:i+1,paid,paidTotal,freeSignups:Math.ceil(paid/c.conversion),revenue,collections,provider,meta,providerTotal,metaTotal,bgvTotal,gatewayTotal,operationsTotal:c.operations*(i+1),cost,costs,cash,reserve,headroom,minCash,reserveGap,productAllocation:headroom*.4,marketingAllocation:headroom*.35,regionAllocation:headroom*.25,cities:cities.filter(x=>x[1]<=i+1).length};
  });
 }
 return {cases,cities,calculate};
})();
if(typeof module!=='undefined')module.exports=RevenueModel;
